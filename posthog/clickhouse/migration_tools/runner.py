from __future__ import annotations

import re
import time
import socket
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from posthog.clickhouse.migration_tools.manifest import ManifestStep, MigrationManifest
from posthog.clickhouse.migration_tools.tracking import MIGRATION_COMPLETE_STEP, get_applied_migrations, record_step

if TYPE_CHECKING:
    from posthog.clickhouse.client.connection import NodeRole
    from posthog.clickhouse.cluster import ClickhouseCluster

logger = logging.getLogger("migrations")

MIGRATIONS_DIR = Path("posthog/clickhouse/migrations")

# Concurrent execution guard: sentinel values for the advisory lock row
LOCK_STEP_INDEX = -999
LOCK_MIGRATION_NUMBER = 0
LOCK_RETRY_ATTEMPTS = 3
LOCK_RETRY_DELAY_SECONDS = 10

# Map manifest uppercase role strings to NodeRole enum value strings (lowercase).
# We resolve to actual NodeRole at call time to avoid importing Django at module load.
_ROLE_MAP: dict[str, str] = {
    "DATA": "data",
    "COORDINATOR": "coordinator",
    "INGESTION_EVENTS": "events",
    "INGESTION_SMALL": "small",
    "INGESTION_MEDIUM": "medium",
    "SHUFFLEHOG": "shufflehog",
    "ENDPOINTS": "endpoints",
    "LOGS": "logs",
    "ALL": "all",
}

# Matches migration filenames like 0001_initial.py or directories like 0220_name
_MIGRATION_PY_RE = re.compile(r"^([0-9]+)_([a-zA-Z_0-9]+)\.py$")
_MIGRATION_DIR_RE = re.compile(r"^([0-9]+)_([a-zA-Z_0-9]+)$")


def _get_node_role_enum() -> type:
    """Deferred import of NodeRole to avoid Django dependency at module load."""
    from posthog.clickhouse.client.connection import NodeRole

    return NodeRole


def _make_query(sql: str) -> Any:
    """Deferred import of Query to avoid Django dependency at module load."""
    from posthog.clickhouse.cluster import Query

    return Query(sql)


def _map_node_roles(manifest_roles: list[str]) -> list[NodeRole]:
    """Convert manifest uppercase role strings to NodeRole enum values."""
    NodeRole = _get_node_role_enum()
    result = []
    for role in manifest_roles:
        role_value = _ROLE_MAP.get(role)
        if role_value is None:
            raise ValueError(f"Unknown node role '{role}'. Valid roles: {sorted(_ROLE_MAP.keys())}")
        result.append(NodeRole(role_value))
    return result


def resolve_step_clusters(step: ManifestStep, manifest: MigrationManifest) -> list[str] | None:
    """Determine the effective cluster list for a step.

    Priority: step.clusters > manifest.clusters > manifest.cluster (as single-element list).
    Returns None when no cluster targeting is configured.
    """
    if step.clusters is not None:
        return step.clusters
    if manifest.clusters is not None:
        return manifest.clusters
    if manifest.cluster is not None:
        return [manifest.cluster]
    return None


def check_cross_cluster_ordering(
    cluster_clients: dict[str, Any],
    migration_number: int,
    database: str,
) -> bool:
    """Verify migration N-1 has completed on all target clusters before applying N.

    Args:
        cluster_clients: mapping of cluster name to a ClickHouse client.
        migration_number: the migration about to be applied.
        database: the ClickHouse database name.

    Returns True if all clusters have applied the predecessor, or if this is
    the first migration (number <= 1).
    """
    predecessor = migration_number - 1
    if predecessor < 1:
        return True

    for cluster_name, client in cluster_clients.items():
        applied = get_applied_migrations(client, database)
        applied_numbers: set[int] = {row["migration_number"] for row in applied}
        if predecessor not in applied_numbers:
            logger.warning(
                "Cross-cluster ordering check failed: cluster %s has not applied migration %d",
                cluster_name,
                predecessor,
            )
            return False

    return True


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[dict[str, Any]]:
    """Discover all migrations (both .py and directory-based). Returns sorted list."""
    migrations: list[dict[str, Any]] = []

    for entry in migrations_dir.iterdir():
        if entry.name.startswith("_"):
            continue

        if entry.is_file():
            match = _MIGRATION_PY_RE.match(entry.name)
            if match:
                number = int(match.group(1))
                name = f"{match.group(1)}_{match.group(2)}"
                migrations.append(
                    {
                        "number": number,
                        "name": name,
                        "style": "py",
                        "path": entry,
                    }
                )
        elif entry.is_dir():
            match = _MIGRATION_DIR_RE.match(entry.name)
            if match and (entry / "manifest.yaml").exists():
                number = int(match.group(1))
                name = f"{match.group(1)}_{match.group(2)}"
                migrations.append(
                    {
                        "number": number,
                        "name": name,
                        "style": "new",
                        "path": entry,
                    }
                )

    migrations.sort(key=lambda m: m["number"])
    return migrations


def is_new_style(migration_dir: Path) -> bool:
    """Check if a path corresponds to a directory with manifest.yaml."""
    return migration_dir.is_dir() and (migration_dir / "manifest.yaml").exists()


def get_pending_migrations(
    client: Any,
    database: str,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[dict[str, Any]]:
    """Compare discovered migrations against tracking table, return unapplied."""
    all_migrations = discover_migrations(migrations_dir)
    applied = get_applied_migrations(client, database)

    applied_numbers: set[int] = {row["migration_number"] for row in applied}

    return [m for m in all_migrations if m["number"] not in applied_numbers]


def execute_migration_step(
    cluster: ClickhouseCluster,
    step: ManifestStep,
    rendered_sql: str,
) -> dict[Any, Any]:
    """Execute a single step using the correct ClickhouseCluster method.

    Returns dict with per-host results.

    Routing logic:
    - sharded + is_alter_on_replicated_table -> map_one_host_per_shard
    - is_alter_on_replicated_table only -> any_host_by_roles
    - neither -> map_hosts_by_roles
    """
    query = _make_query(rendered_sql)
    node_roles = _map_node_roles(step.node_roles)

    if step.sharded and step.is_alter_on_replicated_table:
        futures_map = cluster.map_one_host_per_shard(query)
        return futures_map.result()
    elif step.is_alter_on_replicated_table:
        future = cluster.any_host_by_roles(query, node_roles=node_roles)
        result = future.result()
        return {"single_host": result}
    else:
        futures_map = cluster.map_hosts_by_roles(query, node_roles=node_roles)
        return futures_map.result()


def _should_execute_step(
    step: ManifestStep,
    manifest: MigrationManifest,
    current_cluster: str | None,
) -> bool:
    """Decide whether a step should run on the current cluster.

    When *current_cluster* is None (single-cluster mode), every step runs.
    Otherwise, the step runs only when the resolved cluster list includes
    *current_cluster*, or when no cluster targeting is configured.
    """
    if current_cluster is None:
        return True
    effective = resolve_step_clusters(step, manifest)
    if effective is None:
        return True
    return current_cluster in effective


def acquire_migration_lock(client: Any, database: str) -> bool:
    """Attempt to acquire an advisory lock by inserting a sentinel row.

    Uses step_index=-999 and migration_number=0 as a well-known lock row.
    If the INSERT succeeds, this runner holds the lock. If a row already
    exists, another runner is active.

    Returns True if the lock was acquired, False otherwise.
    """
    hostname = socket.gethostname()
    sql = f"""
        INSERT INTO {database}.clickhouse_schema_migrations
        (migration_number, migration_name, step_index, host, node_role,
         direction, checksum, applied_at, success)
        VALUES
    """
    from datetime import UTC, datetime

    params = [
        (
            LOCK_MIGRATION_NUMBER,
            "__migration_lock__",
            LOCK_STEP_INDEX,
            hostname,
            "*",
            "up",
            "lock",
            datetime.now(tz=UTC),
            False,
        )
    ]
    try:
        client.execute(sql, params)
        return True
    except Exception:
        return False


def release_migration_lock(client: Any, database: str) -> None:
    """Delete the advisory lock row, allowing other runners to proceed."""
    sql = (
        f"DELETE FROM {database}.clickhouse_schema_migrations "
        f"WHERE migration_number = {LOCK_MIGRATION_NUMBER} "
        f"AND step_index = {LOCK_STEP_INDEX}"
    )
    try:
        client.execute(sql)
    except Exception as exc:
        logger.warning("Failed to release migration lock: %s", exc)


def check_migration_lock(client: Any, database: str) -> bool:
    """Check whether a lock row exists (another runner is active).

    Returns True if a lock row exists, False otherwise.
    """
    sql = (
        f"SELECT count() FROM {database}.clickhouse_schema_migrations "
        f"WHERE migration_number = {LOCK_MIGRATION_NUMBER} "
        f"AND step_index = {LOCK_STEP_INDEX}"
    )
    try:
        rows = client.execute(sql)
        if rows and rows[0]:
            count = rows[0][0] if isinstance(rows[0], (tuple, list)) else rows[0]
            return int(count) > 0
    except Exception:
        pass
    return False


def acquire_migration_lock_with_retry(
    client: Any,
    database: str,
    max_attempts: int = LOCK_RETRY_ATTEMPTS,
    retry_delay: float = LOCK_RETRY_DELAY_SECONDS,
) -> bool:
    """Try to acquire the migration lock, retrying on contention.

    If another runner holds the lock, waits *retry_delay* seconds (plus
    random jitter) between attempts. After *max_attempts* failures,
    returns False (caller should abort).
    """
    import random

    for attempt in range(1, max_attempts + 1):
        if not check_migration_lock(client, database):
            if acquire_migration_lock(client, database):
                logger.info("Migration lock acquired (attempt %d)", attempt)
                return True
        if attempt < max_attempts:
            jitter = random.uniform(0, retry_delay * 0.5)  # noqa: S311
            wait = retry_delay + jitter
            logger.warning(
                "Migration lock held by another runner, retrying in %.1fs (attempt %d/%d)",
                wait,
                attempt,
                max_attempts,
            )
            time.sleep(wait)
    logger.error("Failed to acquire migration lock after %d attempts", max_attempts)
    return False


def run_migration_up(
    cluster: ClickhouseCluster,
    migration: Any,
    database: str,
    migration_number: int,
    migration_name: str,
    current_cluster: str | None = None,
) -> bool:
    """Run all steps in a migration. Records results in tracking table.

    Args:
        current_cluster: when set, only steps targeting this cluster are executed.
            Steps with no cluster targeting always execute.

    Returns True if all steps succeeded on all hosts.
    On partial failure: halts, tracking table shows which hosts succeeded.
    """
    steps = migration.get_steps()
    manifest: MigrationManifest = getattr(migration, "manifest", None) or MigrationManifest(
        description="", steps=[], rollback=[]
    )

    for step_index, (step, rendered_sql) in enumerate(steps):
        if not _should_execute_step(step, manifest, current_cluster):
            logger.info(
                "Migration %s step %d skipped (cluster=%s not targeted)",
                migration_name,
                step_index,
                current_cluster,
            )
            continue

        checksum = compute_checksum(rendered_sql)

        try:
            host_results = execute_migration_step(cluster, step, rendered_sql)
        except Exception as exc:
            logger.exception(
                "Migration %s step %d failed: %s",
                migration_name,
                step_index,
                exc,
            )
            _record_for_tracking(
                database=database,
                migration_number=migration_number,
                migration_name=migration_name,
                step_index=step_index,
                host="unknown",
                node_role=",".join(step.node_roles),
                direction="up",
                checksum=checksum,
                success=False,
            )
            return False

        for host_key in host_results:
            _record_for_tracking(
                database=database,
                migration_number=migration_number,
                migration_name=migration_name,
                step_index=step_index,
                host=str(host_key),
                node_role=",".join(step.node_roles),
                direction="up",
                checksum=checksum,
                success=True,
            )

    # Record a migration-complete sentinel so get_applied_migrations knows
    # all steps finished successfully. Without this, a partial failure
    # (e.g. step 0 OK, step 1 fails) would still mark the migration as
    # applied and silently skip it on the next run.
    _record_for_tracking(
        database=database,
        migration_number=migration_number,
        migration_name=migration_name,
        step_index=MIGRATION_COMPLETE_STEP,
        host="*",
        node_role="*",
        direction="up",
        checksum="complete",
        success=True,
    )

    return True


def _record_for_tracking(
    *,
    database: str,
    migration_number: int,
    migration_name: str,
    step_index: int,
    host: str,
    node_role: str,
    direction: str,
    checksum: str,
    success: bool,
) -> None:
    """Record a step result in the tracking table.

    Uses a deferred import to get a ClickHouse client for the tracking table.
    """
    from posthog.clickhouse.client.migration_tools import get_migrations_cluster

    tracking_cluster = get_migrations_cluster()

    def _do_record(client: Any) -> None:
        record_step(
            client=client,
            migration_number=migration_number,
            migration_name=migration_name,
            step_index=step_index,
            host=host,
            node_role=node_role,
            direction=direction,
            checksum=checksum,
            success=success,
        )

    tracking_cluster.any_host(_do_record).result()


def run_migration_down(
    cluster: ClickhouseCluster,
    migration: Any,
    database: str,
    migration_number: int,
    migration_name: str,
) -> bool:
    """Execute rollback steps. Records in tracking table with direction='down'.

    Returns True if all steps succeeded on all hosts.
    On partial failure: halts, tracking table shows which hosts succeeded.
    """
    steps = migration.get_rollback_steps()

    for step_index, (step, rendered_sql) in enumerate(steps):
        checksum = compute_checksum(rendered_sql)

        try:
            host_results = execute_migration_step(cluster, step, rendered_sql)
        except Exception as exc:
            logger.exception(
                "Rollback %s step %d failed: %s",
                migration_name,
                step_index,
                exc,
            )
            _record_for_tracking(
                database=database,
                migration_number=migration_number,
                migration_name=migration_name,
                step_index=step_index,
                host="unknown",
                node_role=",".join(step.node_roles),
                direction="down",
                checksum=checksum,
                success=False,
            )
            return False

        for host_key in host_results:
            _record_for_tracking(
                database=database,
                migration_number=migration_number,
                migration_name=migration_name,
                step_index=step_index,
                host=str(host_key),
                node_role=",".join(step.node_roles),
                direction="down",
                checksum=checksum,
                success=True,
            )

    return True


def compute_checksum(sql: str) -> str:
    """SHA256 of rendered SQL."""
    return hashlib.sha256(sql.encode()).hexdigest()


def check_active_mutations(
    cluster: ClickhouseCluster,
    database: str,
    tables: list[str],
) -> list[dict[str, Any]]:
    """Query system.mutations WHERE is_done = 0 on target tables.

    Returns list of active mutation dicts across all hosts.
    """
    if not tables:
        return []

    table_list = ", ".join(f"'{t}'" for t in tables)
    sql = (
        f"SELECT database, table, mutation_id, command, create_time "
        f"FROM system.mutations "
        f"WHERE is_done = 0 AND database = '{database}' AND table IN ({table_list}) "
        f"ORDER BY create_time"
    )

    query = _make_query(sql)

    NodeRole = _get_node_role_enum()
    futures_map = cluster.map_hosts_by_roles(query, node_roles=[NodeRole("data")])
    host_results = futures_map.result()

    active: list[dict[str, Any]] = []
    for _host, rows in host_results.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    active.append(row)
    return active

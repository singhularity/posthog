from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.clickhouse.cluster import ClickhouseCluster

logger = logging.getLogger("migrations")


def _query_schema(cluster: ClickhouseCluster, database: str) -> list[tuple[str, str, str]]:
    """Capture current schema from system.columns for the given database.

    Returns a sorted list of (table, name, type) tuples.
    Uses a deferred import for Query to avoid Django dependency at module load.
    """

    sql = f"""
        SELECT table, name, type
        FROM system.columns
        WHERE database = '{database}'
        ORDER BY table, name
    """

    def _get_result(client: Any) -> list[tuple[str, str, str]]:
        return client.execute(sql)

    future = cluster.any_host(_get_result)
    rows = future.result()
    return sorted(rows)


def run_trial(
    cluster: ClickhouseCluster,
    migration: Any,
    database: str,
    migration_number: int,
    migration_name: str,
) -> bool:
    """Run up -> verify -> down -> verify schema is restored.

    Returns True if both directions work and schema is restored to
    its pre-migration state.
    """
    from posthog.clickhouse.migration_tools.runner import run_migration_down, run_migration_up

    # 1. Capture pre-migration schema
    pre_schema = _query_schema(cluster, database)
    logger.info("Trial %s: captured pre-migration schema (%d columns)", migration_name, len(pre_schema))

    # 2. Run up
    logger.info("Trial %s: running UP...", migration_name)
    up_ok = run_migration_up(
        cluster=cluster,
        migration=migration,
        database=database,
        migration_number=migration_number,
        migration_name=migration_name,
    )
    if not up_ok:
        logger.error("Trial %s: UP failed", migration_name)
        return False

    # 3. Verify schema changed after UP (RFC: "verify columns exist via system.columns")
    post_up_schema = _query_schema(cluster, database)
    if post_up_schema == pre_schema:
        logger.error(
            "Trial %s: schema unchanged after UP — migration may be a no-op",
            migration_name,
        )
        return False
    logger.info(
        "Trial %s: schema changed after UP (pre=%d cols, post=%d cols)",
        migration_name,
        len(pre_schema),
        len(post_up_schema),
    )

    # 4. Run down
    logger.info("Trial %s: running DOWN...", migration_name)
    down_ok = run_migration_down(
        cluster=cluster,
        migration=migration,
        database=database,
        migration_number=migration_number,
        migration_name=migration_name,
    )
    if not down_ok:
        logger.error("Trial %s: DOWN failed", migration_name)
        return False

    # 5. Capture post-rollback schema and compare
    post_schema = _query_schema(cluster, database)

    if pre_schema != post_schema:
        logger.error(
            "Trial %s: schema not restored after rollback. Pre-migration had %d columns, post-rollback has %d columns",
            migration_name,
            len(pre_schema),
            len(post_schema),
        )
        return False

    logger.info("Trial %s: PASSED - schema restored successfully", migration_name)
    return True

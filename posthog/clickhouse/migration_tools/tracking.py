from datetime import UTC, datetime
from typing import Any

TRACKING_TABLE_NAME = "clickhouse_schema_migrations"

TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {database}.clickhouse_schema_migrations (
    migration_number UInt32,
    migration_name String,
    step_index Int32,
    host String,
    node_role String,
    direction Enum8('up' = 1, 'down' = 2),
    checksum String,
    applied_at DateTime64(3),
    success Bool
) ENGINE = MergeTree()
ORDER BY (migration_number, step_index, host, direction, applied_at)
"""

# Sentinel step_index used to mark a migration as fully applied.
MIGRATION_COMPLETE_STEP = -1


def get_tracking_ddl(database: str) -> str:
    return TRACKING_TABLE_DDL.format(database=database)


def record_step(
    client: Any,
    migration_number: int,
    migration_name: str,
    step_index: int,
    host: str,
    node_role: str,
    direction: str,
    checksum: str,
    success: bool,
) -> None:
    sql = f"""
        INSERT INTO {TRACKING_TABLE_NAME}
        (migration_number, migration_name, step_index, host, node_role, direction, checksum, applied_at, success)
        VALUES
    """
    now = datetime.now(tz=UTC)
    params = [
        (
            migration_number,
            migration_name,
            step_index,
            host,
            node_role,
            direction,
            checksum,
            now,
            success,
        )
    ]
    client.execute(sql, params)


def get_applied_migrations(client: Any, database: str) -> list[dict[str, Any]]:
    """Return migrations that have a complete sentinel record (step_index = -1, success = 1).

    Only migrations where ALL steps succeeded and a completion marker was
    recorded are considered applied. This prevents partial failures from
    being silently skipped on the next run.
    """
    sql = f"""
        SELECT
            migration_number,
            migration_name,
            step_index,
            host,
            node_role,
            direction,
            checksum,
            applied_at,
            success
        FROM {database}.{TRACKING_TABLE_NAME}
        WHERE success = 1 AND direction = 'up' AND step_index = {MIGRATION_COMPLETE_STEP}
        ORDER BY migration_number
    """
    rows = client.execute(sql)
    columns = [
        "migration_number",
        "migration_name",
        "step_index",
        "host",
        "node_role",
        "direction",
        "checksum",
        "applied_at",
        "success",
    ]
    return [dict(zip(columns, row)) for row in rows]


def get_migration_status_all_hosts(cluster: Any, database: str) -> dict[str, Any]:
    from posthog.clickhouse.cluster import Query

    sql = f"""
        SELECT
            migration_number,
            migration_name,
            max(step_index) AS last_step,
            host,
            direction,
            min(success) AS all_success
        FROM {database}.{TRACKING_TABLE_NAME}
        WHERE direction = 'up'
        GROUP BY migration_number, migration_name, host, direction
        ORDER BY migration_number
    """

    import logging

    logger = logging.getLogger(__name__)
    futures_map = cluster.map_all_hosts(Query(sql))
    results: dict[str, Any] = {}
    try:
        host_results = futures_map.result()
        for host_info, rows in host_results.items():
            host_key = str(host_info)
            results[host_key] = {
                "reachable": True,
                "migrations": rows,
            }
    except ExceptionGroup as eg:
        # Some hosts failed — extract partial results from successful ones
        logger.warning("Some hosts unreachable during status query: %s", eg)
        for exc in eg.exceptions:
            results[str(exc)] = {"reachable": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("Status query failed: %s", exc)

    return results


def get_infi_migration_status(cluster: Any, database: str) -> dict[str, Any]:
    """Query the legacy infi clickhouse_orm migrations table for applied migrations.

    Returns per-host dict similar to get_migration_status_all_hosts.
    """
    from posthog.clickhouse.cluster import Query

    sql = f"""
        SELECT name
        FROM {database}.clickhouseorm_migrations
        ORDER BY name
    """

    results: dict[str, Any] = {}
    try:
        futures_map = cluster.map_all_hosts(Query(sql))
        host_results = futures_map.result()
        for host_info, rows in host_results.items():
            host_key = str(host_info)
            # Rows are tuples like (name,)
            migration_names = [row[0] if isinstance(row, (tuple, list)) else row for row in rows]
            results[host_key] = {
                "reachable": True,
                "migrations": migration_names,
            }
    except Exception:
        pass

    return results

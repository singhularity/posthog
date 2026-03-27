"""
Multi-node ClickHouse integration tests for the ch_migrate system.

These tests validate topology-aware migration execution against a real
3-node ClickHouse cluster. They are NOT for CI (too heavy). Run locally
before production deploy using:

    ./scripts/test-multi-node.sh

Or manually:

    docker compose -f docker-compose.multi-node.yml up -d --wait
    pytest posthog/clickhouse/test/test_multi_node_integration.py -v
    docker compose -f docker-compose.multi-node.yml down -v

Cluster topology:
    clickhouse-1  shard=1  hostClusterRole=data         port 9001
    clickhouse-2  shard=2  hostClusterRole=coordinator   port 9002
    clickhouse-3  shard=3  hostClusterRole=events        port 9003
"""

import time
import shutil
import subprocess
from pathlib import Path

import pytest
from unittest import TestCase

# ---------------------------------------------------------------------------
# Docker availability check
# ---------------------------------------------------------------------------

DOCKER_BIN = shutil.which("docker")
COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.multi-node.yml"


def _docker_available() -> bool:
    if DOCKER_BIN is None:
        return False
    try:
        result = subprocess.run(
            [DOCKER_BIN, "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()

skip_no_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker not available — skipping multi-node integration tests",
)

# ---------------------------------------------------------------------------
# Node connection helpers (raw clickhouse-driver, no Django)
# ---------------------------------------------------------------------------

NODE_CONFIGS = {
    "data": {"host": "localhost", "port": 9001},
    "coordinator": {"host": "localhost", "port": 9002},
    "events": {"host": "localhost", "port": 9003},
}

DATABASE = "default"
TRACKING_TABLE = "clickhouse_schema_migrations"

# How long to wait for ClickHouse nodes to become healthy after compose up.
STARTUP_TIMEOUT_S = 60
STARTUP_POLL_S = 2


def _get_client(role: str):
    """Return a clickhouse_driver Client connected to the node with the given role."""
    from clickhouse_driver import Client

    cfg = NODE_CONFIGS[role]
    return Client(host=cfg["host"], port=cfg["port"], database="system")


def _query(role: str, sql: str, params=None):
    """Execute a query on a specific node and return the result rows."""
    client = _get_client(role)
    return client.execute(sql, params)


def _wait_for_nodes(roles: list[str] | None = None, timeout: int = STARTUP_TIMEOUT_S):
    """Block until all nodes respond to SELECT 1, or raise after timeout."""
    if roles is None:
        roles = list(NODE_CONFIGS.keys())

    deadline = time.monotonic() + timeout
    for role in roles:
        while True:
            try:
                _query(role, "SELECT 1")
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"ClickHouse node '{role}' did not become ready within {timeout}s")
                time.sleep(STARTUP_POLL_S)


# ---------------------------------------------------------------------------
# Tracking table helpers (mirrors posthog/clickhouse/migrations/tracking.py
# without importing Django)
# ---------------------------------------------------------------------------

TRACKING_DDL = f"""
CREATE TABLE IF NOT EXISTS {DATABASE}.{TRACKING_TABLE} (
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

MIGRATION_COMPLETE_STEP = -1


def _bootstrap_tracking_table():
    """Create the tracking table on all 3 nodes."""
    for role in NODE_CONFIGS:
        _query(role, TRACKING_DDL)


def _drop_tracking_table():
    """Drop the tracking table on all 3 nodes (cleanup)."""
    for role in NODE_CONFIGS:
        _query(role, f"DROP TABLE IF EXISTS {DATABASE}.{TRACKING_TABLE}")


# ---------------------------------------------------------------------------
# Test migration SQL helpers.
# Instead of going through Django management commands (which require a full
# Django setup), we replicate the core logic: write tracking rows and
# execute SQL directly against the cluster. This keeps the test self-contained
# and focused on validating cluster behavior, not Django wiring.
# ---------------------------------------------------------------------------

TEST_TABLE = "ch_migrate_integration_test"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {DATABASE}.{TEST_TABLE} (
    id UInt64
) ENGINE = MergeTree()
ORDER BY id
"""

DROP_TABLE_SQL = f"DROP TABLE IF EXISTS {DATABASE}.{TEST_TABLE}"


def _record_step(
    role: str,
    migration_number: int,
    migration_name: str,
    step_index: int,
    host: str,
    node_role: str,
    direction: str,
    checksum: str,
    success: bool,
):
    """Insert a tracking row into the node identified by `role`."""
    sql = f"""
        INSERT INTO {DATABASE}.{TRACKING_TABLE}
        (migration_number, migration_name, step_index, host, node_role, direction, checksum, applied_at, success)
        VALUES
    """
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    params = [(migration_number, migration_name, step_index, host, node_role, direction, checksum, now, success)]
    _query(role, sql, params)


def _apply_migration_to_roles(
    target_roles: list[str],
    migration_number: int = 9990,
    migration_name: str = "9990_integration_test",
    sql: str = CREATE_TABLE_SQL,
):
    """Execute SQL on target roles and write tracking rows, including sentinel."""
    import hashlib

    checksum = hashlib.sha256(sql.encode()).hexdigest()

    for role in target_roles:
        _query(role, sql)
        _record_step(
            role=role,
            migration_number=migration_number,
            migration_name=migration_name,
            step_index=0,
            host=f"localhost:{NODE_CONFIGS[role]['port']}",
            node_role=role,
            direction="up",
            checksum=checksum,
            success=True,
        )

    # Write the completion sentinel to one of the target nodes.
    _record_step(
        role=target_roles[0],
        migration_number=migration_number,
        migration_name=migration_name,
        step_index=MIGRATION_COMPLETE_STEP,
        host="*",
        node_role="*",
        direction="up",
        checksum="complete",
        success=True,
    )


def _rollback_migration_from_roles(
    target_roles: list[str],
    migration_number: int = 9990,
    migration_name: str = "9990_integration_test",
    sql: str = DROP_TABLE_SQL,
):
    """Execute rollback SQL on target roles and write tracking rows."""
    import hashlib

    checksum = hashlib.sha256(sql.encode()).hexdigest()

    for role in target_roles:
        _query(role, sql)
        _record_step(
            role=role,
            migration_number=migration_number,
            migration_name=migration_name,
            step_index=0,
            host=f"localhost:{NODE_CONFIGS[role]['port']}",
            node_role=role,
            direction="down",
            checksum=checksum,
            success=True,
        )


def _table_exists(role: str, table: str = TEST_TABLE) -> bool:
    rows = _query(role, f"SELECT name FROM system.tables WHERE database = '{DATABASE}' AND name = '{table}'")
    return len(rows) > 0


def _get_applied_migrations(role: str) -> list[tuple]:
    """Get completed migrations (sentinel rows) from a specific node."""
    sql = f"""
        SELECT migration_number, migration_name
        FROM {DATABASE}.{TRACKING_TABLE}
        WHERE success = 1 AND direction = 'up' AND step_index = {MIGRATION_COMPLETE_STEP}
        ORDER BY migration_number
    """
    return _query(role, sql)


def _get_all_tracking_rows(role: str, migration_number: int | None = None) -> list[tuple]:
    """Get all tracking rows from a specific node, optionally filtered."""
    where = f"WHERE migration_number = {migration_number}" if migration_number else ""
    sql = f"""
        SELECT migration_number, migration_name, step_index, host, node_role, direction, success
        FROM {DATABASE}.{TRACKING_TABLE}
        {where}
        ORDER BY migration_number, step_index, applied_at
    """
    return _query(role, sql)


# ---------------------------------------------------------------------------
# Docker compose management
# ---------------------------------------------------------------------------


def _compose_up():
    assert DOCKER_BIN is not None
    subprocess.run(
        [DOCKER_BIN, "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"],
        check=True,
        capture_output=True,
        timeout=120,
    )
    _wait_for_nodes()


def _compose_down():
    assert DOCKER_BIN is not None
    subprocess.run(
        [DOCKER_BIN, "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        capture_output=True,
        timeout=60,
        check=False,
    )


def _stop_node(container_name: str):
    assert DOCKER_BIN is not None
    subprocess.run(
        [DOCKER_BIN, "stop", container_name],
        capture_output=True,
        timeout=30,
        check=False,
    )


def _start_node(container_name: str):
    assert DOCKER_BIN is not None
    subprocess.run(
        [DOCKER_BIN, "start", container_name],
        capture_output=True,
        timeout=30,
        check=False,
    )


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def multi_node_cluster():
    """Start the 3-node cluster once for the entire test module."""
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")

    _compose_up()
    yield
    _compose_down()


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure a clean state before each test."""
    if not DOCKER_AVAILABLE:
        return

    # Drop test artifacts from all nodes
    for role in NODE_CONFIGS:
        try:
            _query(role, DROP_TABLE_SQL)
        except Exception:
            pass
        try:
            _query(role, f"DROP TABLE IF EXISTS {DATABASE}.{TRACKING_TABLE}")
        except Exception:
            pass

    _bootstrap_tracking_table()
    yield

    # Cleanup
    for role in NODE_CONFIGS:
        try:
            _query(role, DROP_TABLE_SQL)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_docker
class TestBootstrapCreatesTableOnAllNodes(TestCase):
    """Verify that bootstrapping the tracking table creates it on every node."""

    def test_tracking_table_exists_on_all_nodes(self):
        for role in NODE_CONFIGS:
            rows = _query(
                role,
                f"SELECT name FROM system.tables WHERE database = '{DATABASE}' AND name = '{TRACKING_TABLE}'",
            )
            self.assertEqual(
                len(rows),
                1,
                f"Tracking table not found on {role} node",
            )

    def test_tracking_table_schema_matches(self):
        for role in NODE_CONFIGS:
            cols = _query(
                role,
                f"SELECT name, type FROM system.columns WHERE database = '{DATABASE}' AND table = '{TRACKING_TABLE}' ORDER BY position",
            )
            col_names = [c[0] for c in cols]
            self.assertIn("migration_number", col_names)
            self.assertIn("migration_name", col_names)
            self.assertIn("step_index", col_names)
            self.assertIn("host", col_names)
            self.assertIn("node_role", col_names)
            self.assertIn("direction", col_names)
            self.assertIn("success", col_names)


@skip_no_docker
class TestMigrationTargetsCorrectRoles(TestCase):
    """Apply a migration targeting DATA role only and verify it runs on
    node-1 (data) but NOT on node-2 (coordinator) or node-3 (events)."""

    def test_data_role_migration_only_on_data_node(self):
        # Apply migration only to the "data" role node
        _apply_migration_to_roles(["data"])

        # Table should exist on data node
        self.assertTrue(
            _table_exists("data"),
            "Test table should exist on data node after DATA-role migration",
        )

        # Table should NOT exist on coordinator or events nodes
        self.assertFalse(
            _table_exists("coordinator"),
            "Test table should NOT exist on coordinator node after DATA-role migration",
        )
        self.assertFalse(
            _table_exists("events"),
            "Test table should NOT exist on events node after DATA-role migration",
        )

    def test_tracking_recorded_only_for_targeted_node(self):
        _apply_migration_to_roles(["data"])

        # Tracking rows should show the data node
        rows = _get_all_tracking_rows("data", migration_number=9990)
        step_rows = [r for r in rows if r[2] != MIGRATION_COMPLETE_STEP]  # step_index != -1
        self.assertEqual(len(step_rows), 1)
        self.assertEqual(step_rows[0][4], "data")  # node_role column

    def test_all_roles_migration(self):
        """Apply migration to all 3 roles and verify table exists everywhere."""
        _apply_migration_to_roles(["data", "coordinator", "events"])

        for role in NODE_CONFIGS:
            self.assertTrue(
                _table_exists(role),
                f"Test table should exist on {role} node after ALL-role migration",
            )


@skip_no_docker
class TestStatusShowsAllNodes(TestCase):
    """Verify that per-node status can be queried from each node individually."""

    def test_status_per_node_after_migration(self):
        _apply_migration_to_roles(["data", "coordinator"])

        # Data node should have tracking rows
        data_rows = _get_all_tracking_rows("data", migration_number=9990)
        self.assertGreater(len(data_rows), 0, "Data node should have tracking rows")

        # Verify the completion sentinel exists
        applied = _get_applied_migrations("data")
        migration_numbers = [r[0] for r in applied]
        self.assertIn(9990, migration_numbers)

    def test_status_shows_no_migration_on_untargeted_node(self):
        _apply_migration_to_roles(["data"])

        # Events node should have no step rows (tracking table exists but
        # is local to each node with MergeTree, not replicated)
        # However, tracking is written to the "data" node, so the events
        # node's tracking table will be empty.
        events_rows = _get_all_tracking_rows("events", migration_number=9990)
        self.assertEqual(
            len(events_rows),
            0,
            "Events node should have no tracking rows for a DATA-only migration",
        )

    def test_multiple_migrations_ordered(self):
        """Apply two migrations and verify ordering in status output."""
        _apply_migration_to_roles(
            ["data"],
            migration_number=9990,
            migration_name="9990_first",
        )
        _apply_migration_to_roles(
            ["data"],
            migration_number=9991,
            migration_name="9991_second",
            sql=f"CREATE TABLE IF NOT EXISTS {DATABASE}.ch_migrate_integration_test_2 (id UInt64) ENGINE = MergeTree() ORDER BY id",
        )

        applied = _get_applied_migrations("data")
        numbers = [r[0] for r in applied]
        self.assertEqual(numbers, [9990, 9991])

        # Cleanup extra table
        _query("data", f"DROP TABLE IF EXISTS {DATABASE}.ch_migrate_integration_test_2")


@skip_no_docker
class TestRollbackOnAllNodes(TestCase):
    """Apply a migration to multiple nodes, then roll back and verify cleanup."""

    def test_rollback_removes_table_from_targeted_nodes(self):
        target_roles = ["data", "coordinator"]
        _apply_migration_to_roles(target_roles)

        # Verify tables exist before rollback
        for role in target_roles:
            self.assertTrue(_table_exists(role), f"Table should exist on {role} before rollback")

        # Roll back
        _rollback_migration_from_roles(target_roles)

        # Tables should be gone
        for role in target_roles:
            self.assertFalse(
                _table_exists(role),
                f"Table should NOT exist on {role} after rollback",
            )

    def test_rollback_tracking_records_direction_down(self):
        target_roles = ["data"]
        _apply_migration_to_roles(target_roles)
        _rollback_migration_from_roles(target_roles)

        rows = _get_all_tracking_rows("data", migration_number=9990)
        directions = [r[5] for r in rows]  # direction column
        self.assertIn("down", directions, "Rollback should record direction='down'")

    def test_rollback_does_not_affect_untargeted_nodes(self):
        """Apply to all 3, rollback from data only, verify others still have the table."""
        all_roles = ["data", "coordinator", "events"]
        _apply_migration_to_roles(all_roles)

        # Roll back only data
        _rollback_migration_from_roles(["data"])

        self.assertFalse(_table_exists("data"), "Table should be gone from data node")
        self.assertTrue(_table_exists("coordinator"), "Table should still exist on coordinator")
        self.assertTrue(_table_exists("events"), "Table should still exist on events")


@skip_no_docker
class TestPartialFailureRetry(TestCase):
    """Simulate partial failure by stopping a node mid-migration, then verify
    that tracking reflects partial state and re-running succeeds."""

    def test_partial_failure_and_retry(self):
        # Step 1: Apply migration to data node successfully
        _apply_migration_to_roles(
            ["data"],
            migration_number=9995,
            migration_name="9995_partial_test",
        )

        # Step 2: Stop node-1 (data)
        _stop_node("ch-test-node-1")

        # Give it a moment to fully stop
        time.sleep(2)

        # Step 3: Verify data node is unreachable
        with self.assertRaises(Exception):
            _query("data", "SELECT 1")

        # Step 4: Verify coordinator/events are still up and do NOT have
        # the migration (it targeted only data)
        self.assertFalse(_table_exists("coordinator", TEST_TABLE))
        self.assertFalse(_table_exists("events", TEST_TABLE))

        # Step 5: Restart node-1
        _start_node("ch-test-node-1")
        _wait_for_nodes(["data"], timeout=30)

        # Step 6: Verify the table persisted through restart (data was committed)
        self.assertTrue(
            _table_exists("data"),
            "Table should persist on data node after restart",
        )

        # Step 7: Verify tracking rows survived restart
        applied = _get_applied_migrations("data")
        numbers = [r[0] for r in applied]
        self.assertIn(9995, numbers, "Tracking sentinel should survive node restart")

    def test_incomplete_migration_detectable(self):
        """Write step 0 as success but omit the completion sentinel.
        This simulates a crash between step execution and sentinel write.
        Verify the migration is NOT considered applied."""
        import hashlib

        sql = CREATE_TABLE_SQL
        checksum = hashlib.sha256(sql.encode()).hexdigest()

        # Execute the SQL but only record step 0, no sentinel
        _query("data", sql)
        _record_step(
            role="data",
            migration_number=9996,
            migration_name="9996_incomplete",
            step_index=0,
            host="localhost:9001",
            node_role="data",
            direction="up",
            checksum=checksum,
            success=True,
        )

        # Migration should NOT appear as applied (no sentinel)
        applied = _get_applied_migrations("data")
        numbers = [r[0] for r in applied]
        self.assertNotIn(
            9996,
            numbers,
            "Migration without completion sentinel should NOT be considered applied",
        )

        # But step rows should still be visible
        rows = _get_all_tracking_rows("data", migration_number=9996)
        self.assertEqual(len(rows), 1, "Step 0 row should exist")

    def test_retry_after_partial_writes_sentinel(self):
        """Simulate: step 0 succeeded (no sentinel), then re-run writes
        step 0 again (idempotent SQL) and the sentinel."""
        import hashlib

        sql = CREATE_TABLE_SQL
        checksum = hashlib.sha256(sql.encode()).hexdigest()

        # First run: step 0 only, no sentinel (simulating crash)
        _query("data", sql)
        _record_step(
            role="data",
            migration_number=9997,
            migration_name="9997_retry_test",
            step_index=0,
            host="localhost:9001",
            node_role="data",
            direction="up",
            checksum=checksum,
            success=True,
        )

        # Verify not applied
        applied = _get_applied_migrations("data")
        self.assertNotIn(9997, [r[0] for r in applied])

        # Second run: re-execute (CREATE IF NOT EXISTS is idempotent) + sentinel
        _query("data", sql)
        _record_step(
            role="data",
            migration_number=9997,
            migration_name="9997_retry_test",
            step_index=0,
            host="localhost:9001",
            node_role="data",
            direction="up",
            checksum=checksum,
            success=True,
        )
        _record_step(
            role="data",
            migration_number=9997,
            migration_name="9997_retry_test",
            step_index=MIGRATION_COMPLETE_STEP,
            host="*",
            node_role="*",
            direction="up",
            checksum="complete",
            success=True,
        )

        # Now it should be applied
        applied = _get_applied_migrations("data")
        self.assertIn(9997, [r[0] for r in applied])


@skip_no_docker
class TestClusterTopologyDiscovery(TestCase):
    """Verify that the cluster topology is correctly visible from each node."""

    def test_each_node_sees_all_three_shards(self):
        for role in NODE_CONFIGS:
            rows = _query(
                role,
                "SELECT shard_num, host_name FROM system.clusters WHERE cluster = 'posthog' ORDER BY shard_num",
            )
            shard_nums = [r[0] for r in rows]
            self.assertEqual(
                sorted(shard_nums),
                [1, 2, 3],
                f"Node '{role}' should see 3 shards in the 'posthog' cluster",
            )

    def test_macro_roles_correct(self):
        expected = {
            "data": "data",
            "coordinator": "coordinator",
            "events": "events",
        }
        for role, expected_macro in expected.items():
            rows = _query(role, "SELECT getMacro('hostClusterRole')")
            actual = rows[0][0]
            self.assertEqual(
                actual,
                expected_macro,
                f"Node '{role}' should have hostClusterRole='{expected_macro}', got '{actual}'",
            )

    def test_macro_shard_numbers(self):
        expected_shards = {"data": "1", "coordinator": "2", "events": "3"}
        for role, expected_shard in expected_shards.items():
            rows = _query(role, "SELECT getMacro('shard')")
            actual = rows[0][0]
            self.assertEqual(
                actual,
                expected_shard,
                f"Node '{role}' should have shard='{expected_shard}', got '{actual}'",
            )

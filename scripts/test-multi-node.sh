#!/usr/bin/env bash
# Multi-node ClickHouse integration test runner.
#
# Starts a 3-node ClickHouse cluster, runs ch_migrate integration tests,
# then tears everything down. NOT for CI — local validation only.
#
# Usage:
#   ./scripts/test-multi-node.sh              # run all multi-node tests
#   ./scripts/test-multi-node.sh -k partial   # run only tests matching "partial"
#   ./scripts/test-multi-node.sh --keep       # don't tear down after tests

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.multi-node.yml"
TEST_FILE="posthog/clickhouse/test/test_multi_node_integration.py"
DOCKER="${DOCKER:-docker}"

KEEP_RUNNING=false
PYTEST_ARGS=()

for arg in "$@"; do
    if [[ "$arg" == "--keep" ]]; then
        KEEP_RUNNING=true
    else
        PYTEST_ARGS+=("$arg")
    fi
done

cleanup() {
    if [[ "$KEEP_RUNNING" == "true" ]]; then
        echo ""
        echo "Cluster left running (--keep). Tear down manually with:"
        echo "  $DOCKER compose -f $COMPOSE_FILE down -v"
        return
    fi
    echo ""
    echo "Tearing down multi-node cluster..."
    "$DOCKER" compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}

trap cleanup EXIT

echo "Starting 3-node ClickHouse cluster..."
"$DOCKER" compose -f "$COMPOSE_FILE" up -d --wait

echo ""
echo "Waiting for all nodes to be healthy..."

wait_for_node() {
    local name="$1"
    local port="$2"
    local deadline=$((SECONDS + 60))

    while ! "$DOCKER" exec "$name" clickhouse-client --query "SELECT 1" >/dev/null 2>&1; do
        if (( SECONDS > deadline )); then
            echo "TIMEOUT: $name did not become ready"
            exit 1
        fi
        sleep 1
    done
    echo "  $name (port $port): ready"
}

wait_for_node ch-test-node-1 9001
wait_for_node ch-test-node-2 9002
wait_for_node ch-test-node-3 9003

echo ""
echo "Running integration tests..."
echo "----------------------------------------------------------------------"

cd "$REPO_ROOT"
pytest "$TEST_FILE" -v "${PYTEST_ARGS[@]}"
TEST_EXIT=$?

echo "----------------------------------------------------------------------"

if [[ $TEST_EXIT -eq 0 ]]; then
    echo "All multi-node integration tests passed."
else
    echo "Some tests failed (exit code: $TEST_EXIT)."
fi

exit $TEST_EXIT

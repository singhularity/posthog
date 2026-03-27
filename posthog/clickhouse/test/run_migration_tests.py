"""Standalone test runner for migration module tests.

These modules are designed to be Django-independent at import time,
but posthog/__init__.py imports celery/Django. This script pre-loads
mock modules for posthog.celery so the import chain never triggers.
"""

import sys
import types

# Pre-load a fake posthog.celery so posthog/__init__.py doesn't
# try to import the real one (which needs Django + Celery).
_fake_celery_app = types.SimpleNamespace()
_posthog_celery = types.ModuleType("posthog.celery")
_posthog_celery.app = _fake_celery_app  # type: ignore[attr-defined]
sys.modules["posthog.celery"] = _posthog_celery

if __name__ == "__main__":
    import pytest

    test_dir = str(sys.argv[1]) if len(sys.argv) > 1 else "posthog/clickhouse/test/"
    sys.exit(
        pytest.main(
            [
                "--noconftest",
                "-o",
                "addopts=",
                "-v",
                "posthog/clickhouse/test/test_manifest_parser.py",
                "posthog/clickhouse/test/test_sql_section_parser.py",
                "posthog/clickhouse/test/test_jinja_env.py",
                "posthog/clickhouse/test/test_tracking_table.py",
                "posthog/clickhouse/test/test_runner.py",
                "posthog/clickhouse/test/test_rollback.py",
                "posthog/clickhouse/test/test_trial.py",
                "posthog/clickhouse/test/test_status_command.py",
                "posthog/clickhouse/test/test_create_migration.py",
                "posthog/clickhouse/test/test_validator.py",
                "posthog/clickhouse/test/test_multi_cluster.py",
                "posthog/clickhouse/test/test_deprecation.py",
            ]
        )
    )

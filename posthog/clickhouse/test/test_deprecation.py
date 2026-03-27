"""Tests for deprecation warnings and ch_migrate --check flag."""

import os
import sys
import types
import warnings
from io import StringIO
from pathlib import Path

import pytest
from unittest.mock import MagicMock

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ---------------------------------------------------------------------------
# Stub heavy dependencies so migration_tools and ch_migrate can import
# without Django, ClickHouse drivers, or other infra packages.
# ---------------------------------------------------------------------------

_stubs_installed = False


def _django_is_configured() -> bool:
    """Return True if Django is already set up (e.g. running inside the full test suite).

    MagicMock objects respond to any attribute access, so we verify USE_I18N
    is an actual bool — not a mock — to avoid false positives from prior tests.
    """
    try:
        from django.conf import settings

        val = getattr(settings, "USE_I18N", None)
        return isinstance(val, bool)
    except Exception:
        return False


def _install_stubs() -> None:
    global _stubs_installed
    if _stubs_installed:
        return
    _stubs_installed = True

    # When running inside a Django test suite, real modules are already loaded.
    # Only install stubs for standalone execution (no Django).
    if _django_is_configured():
        return

    # posthog.clickhouse.client — replace the package with a hollow shell
    # that still resolves submodules from the real filesystem path
    fake_client = types.ModuleType("posthog.clickhouse.client")
    fake_client.__path__ = [os.path.join(_BASE, "posthog/clickhouse/client")]
    fake_client.__package__ = "posthog.clickhouse.client"
    sys.modules.setdefault("posthog.clickhouse.client", fake_client)

    # posthog.clickhouse.client.connection — only NodeRole is needed
    fake_conn = types.ModuleType("posthog.clickhouse.client.connection")

    class NodeRole:
        DATA = "DATA"
        COORDINATOR = "COORDINATOR"
        ALL = "ALL"

    fake_conn.NodeRole = NodeRole  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.clickhouse.client.connection", fake_conn)

    # posthog.clickhouse.cluster
    fake_cluster = types.ModuleType("posthog.clickhouse.cluster")
    fake_cluster.Query = MagicMock()  # type: ignore[attr-defined]
    fake_cluster.get_cluster = MagicMock()  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.clickhouse.cluster", fake_cluster)

    # infi.clickhouse_orm.migrations
    for mod_name in ("infi", "infi.clickhouse_orm", "infi.clickhouse_orm.migrations"):
        m = types.ModuleType(mod_name)
        m.__path__ = ["/fake"]
        sys.modules.setdefault(mod_name, m)

    if not hasattr(sys.modules.get("infi.clickhouse_orm.migrations"), "RunPython"):

        class _FakeRunPython:
            def __init__(self, fn: object) -> None:
                pass

        sys.modules["infi.clickhouse_orm.migrations"].RunPython = _FakeRunPython  # type: ignore[attr-defined]

    # posthog.settings / posthog.settings.data_stores
    fake_settings = types.ModuleType("posthog.settings")
    fake_settings.E2E_TESTING = False  # type: ignore[attr-defined]
    fake_settings.DEBUG = True  # type: ignore[attr-defined]
    fake_settings.CLOUD_DEPLOYMENT = False  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.settings", fake_settings)

    fake_ds = types.ModuleType("posthog.settings.data_stores")
    fake_ds.CLICKHOUSE_MIGRATIONS_CLUSTER = "default"  # type: ignore[attr-defined]
    fake_ds.CLICKHOUSE_MIGRATIONS_HOST = "localhost"  # type: ignore[attr-defined]
    sys.modules.setdefault("posthog.settings.data_stores", fake_ds)

    # django stubs (for ch_migrate command)
    for mod_name in ("django", "django.conf", "django.core", "django.core.management", "django.core.management.base"):
        m = types.ModuleType(mod_name)
        m.__path__ = ["/fake"]
        sys.modules.setdefault(mod_name, m)

    if not hasattr(sys.modules.get("django.conf"), "settings"):
        settings_ns = types.SimpleNamespace(CLICKHOUSE_DATABASE="default")
        sys.modules["django.conf"].settings = settings_ns  # type: ignore[attr-defined]

    class _FakeBaseCommand:
        def __init__(self) -> None:
            self.stdout = StringIO()
            self.stderr = StringIO()

        def print_help(self, *args: object) -> None:
            pass

    if not hasattr(sys.modules.get("django.core.management.base"), "BaseCommand"):
        sys.modules["django.core.management.base"].BaseCommand = _FakeBaseCommand  # type: ignore[attr-defined]

    # posthog.management.commands — make it a resolvable package
    for mod_name in ("posthog.management", "posthog.management.commands"):
        if mod_name not in sys.modules:
            m = types.ModuleType(mod_name)
            m.__path__ = [os.path.join(_BASE, mod_name.replace(".", "/"))]
            m.__package__ = mod_name
            sys.modules[mod_name] = m


_install_stubs()

# ---------------------------------------------------------------------------
# run_sql_with_exceptions deprecation warning
# ---------------------------------------------------------------------------


class TestRunSqlWithExceptionsDeprecation:
    def test_run_sql_with_exceptions_emits_deprecation(self) -> None:
        from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            run_sql_with_exceptions("SELECT 1")
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1

    def test_deprecation_message_references_readme(self) -> None:
        from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            run_sql_with_exceptions("SELECT 1")
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "manifest.yaml" in str(deprecation_warnings[0].message)


# ---------------------------------------------------------------------------
# ch_migrate check subcommand
# ---------------------------------------------------------------------------


class TestChMigrateCheck:
    def test_check_command_exits_zero_when_no_pending(self) -> None:
        from unittest.mock import patch

        from posthog.management.commands.ch_migrate import Command

        mock_cluster = MagicMock()
        mock_cluster.any_host.return_value.result.return_value = MagicMock()

        with (
            patch("posthog.clickhouse.client.migration_tools.get_migrations_cluster", return_value=mock_cluster),
            patch("posthog.clickhouse.migration_tools.runner.get_pending_migrations", return_value=[]),
        ):
            cmd = Command()
            cmd.stdout = StringIO()  # type: ignore[assignment]
            cmd.stderr = StringIO()  # type: ignore[assignment]

            cmd.handle_check({})

            output = cmd.stdout.getvalue()
            assert "All new-style migrations applied" in output

    def test_check_command_exits_nonzero_when_pending(self) -> None:
        from unittest.mock import patch

        from posthog.management.commands.ch_migrate import Command

        mock_cluster = MagicMock()
        mock_cluster.any_host.return_value.result.return_value = MagicMock()

        pending = [
            {"number": 1, "name": "0001_test", "style": "new", "path": Path("/tmp/fake")},
            {"number": 2, "name": "0002_test", "style": "new", "path": Path("/tmp/fake2")},
        ]

        with (
            patch("posthog.clickhouse.client.migration_tools.get_migrations_cluster", return_value=mock_cluster),
            patch("posthog.clickhouse.migration_tools.runner.get_pending_migrations", return_value=pending),
        ):
            cmd = Command()
            cmd.stdout = StringIO()  # type: ignore[assignment]
            cmd.stderr = StringIO()  # type: ignore[assignment]

            with pytest.raises(SystemExit) as exc_info:
                cmd.handle_check({})

            assert exc_info.value.code == 1

            error_output = cmd.stderr.getvalue()
            assert "2 unapplied new-style migration(s)" in error_output

from __future__ import annotations

from pathlib import Path

from posthog.clickhouse.migration_tools.jinja_env import render_sql
from posthog.clickhouse.migration_tools.manifest import ManifestStep, MigrationManifest, parse_manifest
from posthog.clickhouse.migration_tools.sql_parser import get_sql_for_step


def _get_template_variables() -> dict[str, str]:
    """Get template variables from Django settings.

    Deferred import to avoid requiring Django at module load time.
    """
    from django.conf import settings

    return {
        "database": settings.CLICKHOUSE_DATABASE,
        "cluster": settings.CLICKHOUSE_CLUSTER,
        "single_shard_cluster": getattr(settings, "CLICKHOUSE_SINGLE_SHARD_CLUSTER", ""),
    }


class NewStyleMigration:
    """Represents a new-style declarative ClickHouse migration.

    A new-style migration lives in a directory containing:
    - manifest.yaml: describes the migration steps and rollback
    - *.sql: SQL template files referenced by the manifest
    """

    def __init__(self, migration_dir: Path) -> None:
        self.dir = migration_dir
        self.manifest: MigrationManifest = parse_manifest(migration_dir / "manifest.yaml")

    def _resolve_steps(self, steps: list[ManifestStep]) -> list[tuple[ManifestStep, str]]:
        """Resolve a list of manifest steps into (step, rendered_sql) pairs."""
        variables = _get_template_variables()
        result: list[tuple[ManifestStep, str]] = []
        for step in steps:
            raw_sql = get_sql_for_step(self.dir, step)
            rendered = render_sql(raw_sql, variables)
            result.append((step, rendered))
        return result

    def get_steps(self) -> list[tuple[ManifestStep, str]]:
        """Returns (step, rendered_sql) pairs for the up direction."""
        return self._resolve_steps(self.manifest.steps)

    def get_rollback_steps(self) -> list[tuple[ManifestStep, str]]:
        """Returns (step, rendered_sql) pairs for the down direction."""
        return self._resolve_steps(self.manifest.rollback)

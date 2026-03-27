from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from posthog.clickhouse.migration_tools.manifest import MigrationManifest, parse_manifest


@dataclass
class ValidationResult:
    rule: str
    severity: str  # "error" or "warning"
    message: str


def validate_migration(migration_dir: Path, *, strict: bool = False) -> list[ValidationResult]:
    """Run all validation rules on a migration directory. Returns list of issues."""
    manifest = parse_manifest(migration_dir / "manifest.yaml")

    # Collect all SQL content from referenced files
    sql_content = _collect_sql_content(migration_dir, manifest)

    results: list[ValidationResult] = []
    results.extend(check_companion_tables(manifest, sql_content))
    results.extend(check_on_cluster(sql_content))
    results.extend(check_rollback_completeness(manifest))
    results.extend(check_node_role_consistency(manifest))
    results.extend(check_drop_statements(sql_content, strict=strict))
    return results


def _collect_sql_content(migration_dir: Path, manifest: MigrationManifest) -> str:
    """Read all unique SQL files referenced by manifest steps."""
    seen_files: set[str] = set()
    parts: list[str] = []

    for step in [*manifest.steps, *manifest.rollback]:
        filename = step.sql.split("#")[0]
        if filename not in seen_files:
            seen_files.add(filename)
            sql_path = migration_dir / filename
            if sql_path.exists():
                parts.append(sql_path.read_text())

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Rule: companion_tables
# ---------------------------------------------------------------------------

# Patterns for companion table types in SQL
_ALTER_TABLE_RE = re.compile(r"ALTER\s+TABLE\s+(\S+)", re.IGNORECASE)
_KAFKA_TABLE_RE = re.compile(r"(?:kafka_)", re.IGNORECASE)
_MV_TABLE_RE = re.compile(r"(?:_mv\b|materialized)", re.IGNORECASE)
_WRITABLE_TABLE_RE = re.compile(r"(?:writable_)", re.IGNORECASE)


def check_companion_tables(manifest: MigrationManifest, sql_content: str) -> list[ValidationResult]:
    """If any step ALTERs a sharded table, check for companion table steps.

    When a sharded table is altered, the migration should also include steps
    for the Kafka table, writable Distributed table, and MV on ingestion roles.
    """
    results: list[ValidationResult] = []

    has_sharded_alter = False
    for step in manifest.steps:
        if step.sharded and "DATA" in step.node_roles:
            if _ALTER_TABLE_RE.search(sql_content):
                has_sharded_alter = True
                break

    if not has_sharded_alter:
        return results

    # Check that companion tables are referenced somewhere in the SQL
    has_kafka = bool(_KAFKA_TABLE_RE.search(sql_content))
    has_mv = bool(_MV_TABLE_RE.search(sql_content))
    has_writable = bool(_WRITABLE_TABLE_RE.search(sql_content))

    missing: list[str] = []
    if not has_kafka:
        missing.append("Kafka table")
    if not has_mv:
        missing.append("materialized view")
    if not has_writable:
        missing.append("writable Distributed table")

    if missing:
        results.append(
            ValidationResult(
                rule="companion_tables",
                severity="warning",
                message=f"Sharded ALTER detected but missing companion steps for: {', '.join(missing)}. "
                "When altering a sharded table, also update the Kafka table, writable Distributed table, and MV.",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Rule: on_cluster
# ---------------------------------------------------------------------------

_ON_CLUSTER_RE = re.compile(r"\bON\s+CLUSTER\b", re.IGNORECASE)


def check_on_cluster(sql_content: str) -> list[ValidationResult]:
    """Scan all SQL for ON CLUSTER usage. Error if found.

    The new migration system handles cluster routing via manifest node_roles,
    so SQL should never contain ON CLUSTER directly.
    """
    results: list[ValidationResult] = []
    if _ON_CLUSTER_RE.search(sql_content):
        results.append(
            ValidationResult(
                rule="on_cluster",
                severity="error",
                message="SQL contains 'ON CLUSTER'. The migration system handles cluster routing via "
                "manifest node_roles. Remove ON CLUSTER from your SQL.",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Rule: rollback_completeness
# ---------------------------------------------------------------------------


def check_rollback_completeness(manifest: MigrationManifest) -> list[ValidationResult]:
    """Every step entry must have a corresponding rollback entry (matched by count)."""
    results: list[ValidationResult] = []
    n_steps = len(manifest.steps)
    n_rollback = len(manifest.rollback)

    if n_steps > 0 and n_rollback != n_steps:
        results.append(
            ValidationResult(
                rule="rollback_completeness",
                severity="error",
                message=f"Migration has {n_steps} steps but {n_rollback} rollback entries. "
                "Each step should have a corresponding rollback entry.",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Rule: node_role_consistency
# ---------------------------------------------------------------------------


def check_node_role_consistency(manifest: MigrationManifest) -> list[ValidationResult]:
    """Sharded operations should target DATA, not COORDINATOR alone."""
    results: list[ValidationResult] = []

    for i, step in enumerate(manifest.steps):
        if step.sharded and "DATA" not in step.node_roles:
            results.append(
                ValidationResult(
                    rule="node_role_consistency",
                    severity="warning",
                    message=f"Step {i} is marked sharded=True but does not target DATA role "
                    f"(targets: {step.node_roles}). Sharded operations should include DATA.",
                )
            )

    return results


# ---------------------------------------------------------------------------
# Rule: drop_statement
# ---------------------------------------------------------------------------

_DROP_STMT_RE = re.compile(r"^\s*DROP\s+", re.IGNORECASE | re.MULTILINE)
_COMMENT_LINE_RE = re.compile(r"^\s*--.*$", re.MULTILINE)


def check_drop_statements(sql_content: str, *, strict: bool = False) -> list[ValidationResult]:
    """Scan .up.sql for DROP statements. Warning by default, error in strict mode.

    Lines that are SQL comments (starting with --) are ignored.
    """
    results: list[ValidationResult] = []

    # Strip comment lines before checking
    stripped = _COMMENT_LINE_RE.sub("", sql_content)

    if _DROP_STMT_RE.search(stripped):
        results.append(
            ValidationResult(
                rule="drop_statement",
                severity="error" if strict else "warning",
                message="SQL contains DROP statement(s). Ensure this is intentional and "
                "that data loss has been considered.",
            )
        )
    return results

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_NODE_ROLES = frozenset(
    {
        "DATA",
        "COORDINATOR",
        "INGESTION_EVENTS",
        "INGESTION_SMALL",
        "INGESTION_MEDIUM",
        "SHUFFLEHOG",
        "ENDPOINTS",
        "LOGS",
        "ALL",
    }
)


@dataclass
class ManifestStep:
    sql: str  # "up.sql#section_name" or "up.sql"
    node_roles: list[str]  # ["DATA", "COORDINATOR"]
    comment: str = ""
    sharded: bool = False
    is_alter_on_replicated_table: bool = False
    clusters: list[str] | None = None


@dataclass
class MigrationManifest:
    description: str
    steps: list[ManifestStep]
    rollback: list[ManifestStep]
    cluster: str | None = None
    clusters: list[str] | None = None


def _parse_step(raw: dict) -> ManifestStep:
    """Parse a single step dict into a ManifestStep."""
    if "sql" not in raw:
        raise ValueError("Each step must have a 'sql' field")
    if "node_roles" not in raw:
        raise ValueError("Each step must have a 'node_roles' field")

    node_roles = raw["node_roles"]
    for role in node_roles:
        if role not in VALID_NODE_ROLES:
            raise ValueError(f"Invalid node_role '{role}'. Must be one of: {sorted(VALID_NODE_ROLES)}")

    return ManifestStep(
        sql=raw["sql"],
        node_roles=node_roles,
        comment=raw.get("comment", ""),
        sharded=raw.get("sharded", False),
        is_alter_on_replicated_table=raw.get("is_alter_on_replicated_table", False),
        clusters=raw.get("clusters", None),
    )


def parse_manifest(manifest_path: Path) -> MigrationManifest:
    """Parse a migration manifest YAML file into a MigrationManifest."""
    with open(manifest_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a YAML mapping, got {type(data).__name__}")

    if "description" not in data:
        raise ValueError("Manifest must have a 'description' field")

    if "steps" not in data:
        raise ValueError("Manifest must have a 'steps' field")

    raw_steps = data["steps"]
    if not isinstance(raw_steps, list):
        raise ValueError(f"Manifest 'steps' must be a list, got {type(raw_steps).__name__}")
    raw_rollback = data.get("rollback", [])
    if not isinstance(raw_rollback, list):
        raise ValueError(f"Manifest 'rollback' must be a list, got {type(raw_rollback).__name__}")

    steps = [_parse_step(s) for s in raw_steps]
    rollback = [_parse_step(s) for s in raw_rollback]

    return MigrationManifest(
        description=data["description"],
        steps=steps,
        rollback=rollback,
        cluster=data.get("cluster", None),
        clusters=data.get("clusters", None),
    )

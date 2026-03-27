# ClickHouse migrations

This directory contains ClickHouse schema migrations for PostHog.
There are two styles: legacy `.py` files and new-style directory migrations.

## New-style directory migrations

Each migration lives in a numbered directory
(e.g. `NNNN_<name>/`) containing:

```text
NNNN_<name>/
  manifest.yaml   # declares steps, rollback, and metadata
  up.sql           # SQL template(s) for the forward direction
  down.sql         # SQL template(s) for rollback
  __init__.py      # bridge for backward compatibility with the legacy runner
```

### SQL templates

SQL files are Jinja2 templates with access to these variables:

- `{{ database }}` -- the ClickHouse database name
- `{{ cluster }}` -- the ClickHouse cluster name
- `{{ single_shard_cluster }}` -- the single-shard cluster name (if configured)

A single `.sql` file can contain multiple named sections separated by
`-- @section: <name>` comments.
Steps reference a specific section with `up.sql#section_name`
or the entire file with just `up.sql`.

## Creating a new migration

Use the management command:

```bash
python manage.py create_ch_migration \
  --name add_foo_column \
  --type add-column \
  --table events
```

This scaffolds a numbered directory with `manifest.yaml`, `up.sql`, `down.sql`,
and an `__init__.py` bridge.
It also updates `max_migration.txt`.

## Manifest reference

```yaml
description: 'Human-readable summary of the migration'

# Optional: target a single ClickHouse cluster name
cluster: posthog

# Optional: target multiple clusters (overrides `cluster`)
clusters:
  - us-east
  - eu-west

steps:
  - sql: 'up.sql#create_local'
    node_roles: [DATA] # required: DATA, COORDINATOR, or both
    comment: 'Create local table'
    sharded: true # run on each shard (default: false)
    is_alter_on_replicated_table: false # ALTER that replicates (default: false)
    clusters: # per-step override of manifest-level clusters
      - us-east

rollback:
  - sql: 'down.sql'
    node_roles: [DATA, COORDINATOR]
```

### Field details

| Field                          | Scope    | Required | Description                                    |
| ------------------------------ | -------- | -------- | ---------------------------------------------- |
| `description`                  | manifest | yes      | Human-readable summary                         |
| `cluster`                      | manifest | no       | Single target cluster name                     |
| `clusters`                     | manifest | no       | List of target clusters (overrides `cluster`)  |
| `steps`                        | manifest | yes      | Ordered list of forward steps                  |
| `rollback`                     | manifest | no       | Ordered list of rollback steps                 |
| `sql`                          | step     | yes      | SQL file reference, optionally with `#section` |
| `node_roles`                   | step     | yes      | `["DATA"]`, `["COORDINATOR"]`, or both         |
| `comment`                      | step     | no       | Human-readable description of the step         |
| `sharded`                      | step     | no       | Execute on each shard separately               |
| `is_alter_on_replicated_table` | step     | no       | ALTERs that replicate across nodes             |
| `clusters`                     | step     | no       | Per-step cluster override                      |

### Multi-cluster behavior

When `clusters` is set at the manifest or step level,
the runner filters steps based on the current cluster identity.

- **Step `clusters`** takes precedence over manifest `clusters`.
- **Manifest `clusters`** takes precedence over manifest `cluster`.
- When no cluster targeting is configured, every step runs everywhere.

Before applying migration N+1 in multi-cluster mode,
`check_cross_cluster_ordering` verifies that migration N
has been recorded as complete on all target clusters.

## `ch_migrate` commands

All commands are run via Django management:

```bash
python manage.py ch_migrate <subcommand>
```

### `bootstrap`

Create the tracking table (`clickhouse_schema_migrations`) on all nodes.
Run this once when setting up a new environment.

```bash
python manage.py ch_migrate bootstrap
```

### `plan`

Show pending migrations without executing them.

```bash
python manage.py ch_migrate plan
```

### `apply`

Apply pending migrations in order. Automatically checks for active mutations
on target tables before applying (use `--skip-mutation-check` to bypass).

```bash
python manage.py ch_migrate apply [--upto N] [--skip-mutation-check] [--force]
```

- `--upto N` -- apply migrations up to number N (inclusive)
- `--skip-mutation-check` -- skip the automatic active mutation check
- `--force` -- apply even if active mutations are found

### `down`

Roll back a specific migration by number.

```bash
python manage.py ch_migrate down <migration_number>
```

### `validate`

Run static analysis on a migration (checks for `ON CLUSTER`, rollback completeness,
node role consistency, DROP statements, companion tables).

```bash
python manage.py ch_migrate validate <migration_number> [--strict]
```

### `trial`

Sandbox validation: runs up, verifies schema, rolls back, verifies schema is restored.

```bash
python manage.py ch_migrate trial <migration_number>
```

### `status`

Show per-host migration state (both legacy infi and new-style tracking tables).

```bash
python manage.py ch_migrate status [--node <hostname>]
```

## The `__init__.py` bridge

Each new-style migration directory includes an `__init__.py`
so the legacy `migrate_clickhouse` runner can discover it.
The bridge file contains an empty `operations = []` list,
which signals that the migration is handled by `ch_migrate` instead.

## SQL linting

<!-- TODO: add sqlfluff as a dev dependency (requires pyproject.toml + uv.lock changes)
     and integrate into CI. Track in a separate commit. -->

SQL linting with sqlfluff is planned but not yet integrated into CI.

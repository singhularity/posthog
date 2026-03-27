# ruff: noqa: T201 allow print statements
import re
import sys
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.clickhouse.cluster import Query, get_cluster
from posthog.clickhouse.migration_tools.tracking import (
    get_infi_migration_status,
    get_migration_status_all_hosts,
    get_tracking_ddl,
)


def _get_direct_client(cluster: Any) -> Any:
    """Return a raw ClickHouse client from a cluster any-host call."""

    def _identity(client: Any) -> Any:
        return client

    return cluster.any_host(_identity).result()


class Command(BaseCommand):
    help = "ClickHouse migration management"

    def add_arguments(self, parser: Any) -> None:
        subparsers = parser.add_subparsers(dest="subcommand")
        subparsers.add_parser("bootstrap", help="Create tracking table on all nodes")
        subparsers.add_parser("check", help="Exit non-zero if unapplied new-style migrations exist")
        subparsers.add_parser("plan", help="Show pending migrations without executing")

        apply_parser = subparsers.add_parser("apply", help="Apply pending migrations")
        apply_parser.add_argument(
            "--upto",
            type=int,
            default=99_999,
            help="Apply migrations up to this number (inclusive).",
        )
        apply_parser.add_argument(
            "--skip-mutation-check",
            action="store_true",
            default=False,
            help="Skip the automatic active mutation check before applying.",
        )
        apply_parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Force apply even if active mutations are found.",
        )

        down_parser = subparsers.add_parser("down", help="Roll back a specific migration")
        down_parser.add_argument(
            "migration_number",
            type=int,
            help="Migration number to roll back.",
        )

        status_parser = subparsers.add_parser("status", help="Show per-host migration state")
        status_parser.add_argument(
            "--node",
            type=str,
            default=None,
            help="Filter to a specific node hostname (e.g. host1:9000).",
        )

        validate_parser = subparsers.add_parser("validate", help="Static analysis validation of a migration")
        validate_parser.add_argument(
            "migration_number",
            type=int,
            help="Migration number to validate.",
        )
        validate_parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="Treat warnings as errors.",
        )

        trial_parser = subparsers.add_parser("trial", help="Sandbox validation: apply, verify, down, verify")
        trial_parser.add_argument(
            "migration_number",
            type=int,
            help="Migration number to trial.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        subcommand = options.get("subcommand")
        if subcommand == "bootstrap":
            self.handle_bootstrap()
        elif subcommand == "check":
            self.handle_check(options)
        elif subcommand == "plan":
            self.handle_plan()
        elif subcommand == "apply":
            self.handle_apply(options)
        elif subcommand == "status":
            self.handle_status(options)
        elif subcommand == "down":
            self.handle_down(options)
        elif subcommand == "validate":
            self.handle_validate(options)
        elif subcommand == "trial":
            self.handle_trial(options)
        else:
            self.print_help("manage.py", "ch_migrate")

    def handle_bootstrap(self) -> None:
        database: str = settings.CLICKHOUSE_DATABASE
        ddl = get_tracking_ddl(database)
        cluster = get_cluster()

        print(f"Creating tracking table on all nodes (database={database})...")

        futures_map = cluster.map_all_hosts(Query(ddl))
        try:
            results = futures_map.result()
            for host_info in results:
                print(f"  OK: {host_info}")
            print("Bootstrap complete.")
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                print(f"  FAILED: {exc}")
            raise

    def handle_check(self, options: dict[str, Any]) -> None:
        """Exit with non-zero status if unapplied new-style migrations exist."""
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.runner import get_pending_migrations

        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_migrations_cluster()

        pending = get_pending_migrations(
            client=_get_direct_client(cluster),
            database=database,
        )

        # Only check new-style (directory-based) migrations — legacy .py
        # migrations are tracked in the infi clickhouseorm_migrations table,
        # not in our tracking table, so they always appear as "pending".
        pending = [m for m in pending if m["style"] == "new"]

        if pending:
            self.stderr.write(f"{len(pending)} unapplied new-style migration(s)")
            sys.exit(1)

        self.stdout.write("All new-style migrations applied.")

    def handle_plan(self) -> None:
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.new_style import NewStyleMigration
        from posthog.clickhouse.migration_tools.runner import get_pending_migrations, is_new_style

        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_migrations_cluster()

        pending = get_pending_migrations(
            client=_get_direct_client(cluster),
            database=database,
        )

        if not pending:
            print("All migrations are up to date.")
            return

        print(f"Pending migrations ({len(pending)}):\n")
        for mig in pending:
            style_label = "new-style" if mig["style"] == "new" else "legacy .py"
            print(f"  [{style_label}] {mig['name']}")

            if mig["style"] == "new" and is_new_style(mig["path"]):
                try:
                    migration = NewStyleMigration(mig["path"])
                    steps = migration.get_steps()
                    for i, (step, rendered_sql) in enumerate(steps):
                        roles = ", ".join(step.node_roles)
                        flags = []
                        if step.sharded:
                            flags.append("sharded")
                        if step.is_alter_on_replicated_table:
                            flags.append("alter-replicated")
                        flag_str = f" ({', '.join(flags)})" if flags else ""
                        comment = f"  # {step.comment}" if step.comment else ""
                        print(f"    step {i}: {step.sql} -> [{roles}]{flag_str}{comment}")
                        # Show computed SQL for review (RFC success criterion #1)
                        for sql_line in rendered_sql.strip().splitlines():
                            print(f"      | {sql_line}")
                except Exception as exc:
                    print(f"    (error reading steps: {exc})")

        print(f"\nTotal: {len(pending)} pending migration(s).")

    def handle_apply(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.new_style import NewStyleMigration
        from posthog.clickhouse.migration_tools.runner import (
            check_active_mutations,
            get_pending_migrations,
            is_new_style,
            run_migration_up,
        )

        database: str = settings.CLICKHOUSE_DATABASE
        upto: int = options.get("upto", 99_999)
        skip_mutation_check: bool = options.get("skip_mutation_check", False)
        force: bool = options.get("force", False)
        cluster = get_migrations_cluster()

        pending = get_pending_migrations(
            client=_get_direct_client(cluster),
            database=database,
        )

        pending = [m for m in pending if m["number"] <= upto]

        if not pending:
            print("All migrations are up to date.")
            return

        if not skip_mutation_check:
            # Extract table names from pending new-style migrations for mutation check
            tables_to_check: list[str] = []
            for mig in pending:
                if mig["style"] == "new" and is_new_style(mig["path"]):
                    try:
                        m = NewStyleMigration(mig["path"])
                        for step, _sql in m.get_steps():
                            if step.sharded or step.is_alter_on_replicated_table:
                                match = re.search(r"ALTER\s+TABLE\s+(\S+)", _sql, re.IGNORECASE)
                                if match:
                                    tables_to_check.append(match.group(1).split(".")[-1])
                    except Exception:
                        pass

            if tables_to_check:
                active = check_active_mutations(cluster, database, tables_to_check)
                if active and not force:
                    print("Active mutations found on target tables:")
                    for mut in active:
                        print(f"  table={mut.get('table')}, mutation_id={mut.get('mutation_id')}")
                    print("\nUse --force to apply anyway.")
                    return

        print(f"Applying {len(pending)} migration(s)...\n")

        for mig in pending:
            print(f"  Applying {mig['name']}...", end=" ", flush=True)

            if mig["style"] == "new" and is_new_style(mig["path"]):
                migration = NewStyleMigration(mig["path"])
                success = run_migration_up(
                    cluster=cluster,
                    migration=migration,
                    database=database,
                    migration_number=mig["number"],
                    migration_name=mig["name"],
                )
                if success:
                    print("OK")
                else:
                    print("FAILED")
                    print(f"\nMigration {mig['name']} failed. Halting.")
                    return
            else:
                # Legacy .py migration: delegate to the existing infi runner
                print("(legacy, skipping — use migrate_clickhouse)")

        print("\nAll migrations applied successfully.")

    def handle_status(self, options: dict[str, Any]) -> None:
        """Show per-host migration state. Reads both infi and new tracking tables."""
        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_cluster()
        node_filter: str | None = options.get("node")

        new_status = get_migration_status_all_hosts(cluster, database)
        infi_status = get_infi_migration_status(cluster, database)

        all_hosts = sorted(set(list(new_status.keys()) + list(infi_status.keys())))

        if node_filter:
            all_hosts = [h for h in all_hosts if h == node_filter]

        if not all_hosts:
            self.stdout.write("No migrations found on any host.\n")
            return

        for host in all_hosts:
            self.stdout.write(f"\n== {host} ==\n")

            # Legacy (infi) migrations
            infi_data = infi_status.get(host)
            if infi_data and infi_data.get("migrations"):
                self.stdout.write("  Legacy (infi) migrations:\n")
                for mig_name in infi_data["migrations"]:
                    self.stdout.write(f"    [applied] {mig_name}\n")
            else:
                self.stdout.write("  Legacy (infi) migrations: none\n")

            # New-style migrations
            new_data = new_status.get(host)
            if new_data and new_data.get("migrations"):
                self.stdout.write("  New-style migrations:\n")
                for row in new_data["migrations"]:
                    if isinstance(row, (tuple, list)):
                        number, name, last_step, _host, direction, all_success = row
                        status_label = "applied" if all_success else "PARTIAL"
                        self.stdout.write(f"    [{status_label}] {name} (steps: {last_step + 1})\n")
                    else:
                        self.stdout.write(f"    {row}\n")
            else:
                self.stdout.write("  New-style migrations: none\n")

        self.stdout.write("\n")

    def handle_validate(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.migration_tools.runner import discover_migrations, is_new_style
        from posthog.clickhouse.migration_tools.validator import validate_migration

        target: int = options.get("migration_number")  # type: ignore[assignment]
        strict: bool = options.get("strict", False)

        all_migrations = discover_migrations()
        target_mig = next((m for m in all_migrations if m["number"] == target), None)

        if target_mig is None:
            print(f"Migration {target} not found.")
            return

        if target_mig["style"] != "new" or not is_new_style(target_mig["path"]):
            print(f"Migration {target_mig['name']} is not a new-style migration. Validation not supported.")
            return

        print(f"Validating {target_mig['name']}...")
        results = validate_migration(target_mig["path"], strict=strict)

        if not results:
            print("  No issues found.")
            return

        has_errors = False
        for r in results:
            icon = "ERROR" if r.severity == "error" else "WARN"
            print(f"  [{icon}] ({r.rule}) {r.message}")
            if r.severity == "error":
                has_errors = True

        if has_errors:
            print(f"\nValidation FAILED for {target_mig['name']}.")
            raise SystemExit(1)
        else:
            print(f"\nValidation passed with warnings for {target_mig['name']}.")

    def handle_down(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.new_style import NewStyleMigration
        from posthog.clickhouse.migration_tools.runner import discover_migrations, is_new_style, run_migration_down

        database: str = settings.CLICKHOUSE_DATABASE
        target: int = options.get("migration_number")  # type: ignore[assignment]
        cluster = get_migrations_cluster()

        all_migrations = discover_migrations()
        target_mig = next((m for m in all_migrations if m["number"] == target), None)

        if target_mig is None:
            print(f"Migration {target} not found.")
            return

        if target_mig["style"] != "new" or not is_new_style(target_mig["path"]):
            print(f"Migration {target_mig['name']} is not a new-style migration. Rollback not supported.")
            return

        migration = NewStyleMigration(target_mig["path"])

        if not migration.get_rollback_steps():
            print(f"Migration {target_mig['name']} has no rollback steps defined.")
            return

        print(f"Rolling back {target_mig['name']}...", end=" ", flush=True)

        success = run_migration_down(
            cluster=cluster,
            migration=migration,
            database=database,
            migration_number=target_mig["number"],
            migration_name=target_mig["name"],
        )

        if success:
            print("OK")
        else:
            print("FAILED")

    def handle_trial(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.new_style import NewStyleMigration
        from posthog.clickhouse.migration_tools.runner import discover_migrations, is_new_style
        from posthog.clickhouse.migration_tools.trial import run_trial

        database: str = settings.CLICKHOUSE_DATABASE
        target: int = options.get("migration_number")  # type: ignore[assignment]
        cluster = get_migrations_cluster()

        all_migrations = discover_migrations()
        target_mig = next((m for m in all_migrations if m["number"] == target), None)

        if target_mig is None:
            print(f"Migration {target} not found.")
            return

        if target_mig["style"] != "new" or not is_new_style(target_mig["path"]):
            print(f"Migration {target_mig['name']} is not a new-style migration. Trial not supported.")
            return

        migration = NewStyleMigration(target_mig["path"])

        print(f"Running trial for {target_mig['name']}...")
        print("  Phase 1: APPLY...")

        success = run_trial(
            cluster=cluster,
            migration=migration,
            database=database,
            migration_number=target_mig["number"],
            migration_name=target_mig["name"],
        )

        if success:
            print("  Phase 2: DOWN... OK")
            print(f"\nTrial PASSED for {target_mig['name']}.")
        else:
            print(f"\nTrial FAILED for {target_mig['name']}.")

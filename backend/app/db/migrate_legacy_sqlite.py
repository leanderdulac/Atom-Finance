"""One-time data migration: legacy SQLite (atom_reports.db) -> Postgres.

Only `users`, `reports`, `experiments`, and `experiment_reviews` ever existed
in the SQLite schema — `derivative_plans`, `source_snapshots`, `paper_trades`
and `paper_events` were introduced together with the Postgres migration
itself, so there is no legacy data to carry over for those.

Run once, after `alembic upgrade head` has created the target schema and
before the SQLite file is retired:

    ATOM_DATABASE_URL=postgresql+asyncpg://... \\
        python -m app.db.migrate_legacy_sqlite /path/to/atom_reports.db

Add --dry-run to see row counts and the first few rows per table without
writing anything. Refuses to run against a Postgres database that already
has rows in any of the four target tables, to avoid double-inserting on a
second run — pass --force to override (e.g. to top up after a partial
failure; conflicting primary keys / unique constraints will still raise).
"""
import argparse
import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import asyncpg

from app.db.postgres import _database_url, _init_connection

_TABLES = ("users", "reports", "experiments", "experiment_reviews")


def _rows(sqlite_conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 (fixed table names, not user input)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _existing_counts(pg: asyncpg.Connection) -> dict[str, int]:
    counts = {}
    for table in _TABLES:
        counts[table] = await pg.fetchval(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
    return counts


async def _migrate_users(sqlite_conn: sqlite3.Connection, pg: asyncpg.Connection, dry_run: bool) -> int:
    rows = _rows(sqlite_conn, "users")
    for row in rows:
        if dry_run:
            continue
        await pg.execute(
            """INSERT INTO users (id, username, email, password_hash, role, is_active, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            row["id"], row["username"], row["email"], row["password_hash"],
            row["role"], bool(row["is_active"]), _parse_ts(row["created_at"]),
        )
    if rows and not dry_run:
        await pg.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users))")
    return len(rows)


async def _migrate_reports(sqlite_conn: sqlite3.Connection, pg: asyncpg.Connection, dry_run: bool) -> int:
    rows = _rows(sqlite_conn, "reports")
    for row in rows:
        if dry_run:
            continue
        await pg.execute(
            """INSERT INTO reports
                   (id, ticker, exchange, price, currency, bull_score, action, narrative, full_report, created_at, owner)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL)""",
            row["id"], row["ticker"], row["exchange"], row["price"], row["currency"],
            row["bull_score"], row["action"], row["narrative"],
            json.loads(row["full_report"]), _parse_ts(row["created_at"]),
        )
    if rows and not dry_run:
        await pg.execute("SELECT setval(pg_get_serial_sequence('reports', 'id'), (SELECT MAX(id) FROM reports))")
    return len(rows)


async def _migrate_experiments(sqlite_conn: sqlite3.Connection, pg: asyncpg.Connection, dry_run: bool) -> int:
    rows = _rows(sqlite_conn, "experiments")
    for row in rows:
        if dry_run:
            continue
        await pg.execute(
            """INSERT INTO experiments (id, owner, created_at, status, input_hash, inputs, result, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            row["id"], row["owner"], _parse_ts(row["created_at"]), row["status"], row["input_hash"],
            json.loads(row["inputs"]), json.loads(row["result"]) if row["result"] is not None else None,
            row["error"],
        )
    return len(rows)


async def _migrate_experiment_reviews(sqlite_conn: sqlite3.Connection, pg: asyncpg.Connection, dry_run: bool) -> int:
    rows = _rows(sqlite_conn, "experiment_reviews")
    for row in rows:
        if dry_run:
            continue
        await pg.execute(
            """INSERT INTO experiment_reviews (id, experiment_id, created_at, decision, rationale)
               VALUES ($1, $2, $3, $4, $5)""",
            row["id"], row["experiment_id"], _parse_ts(row["created_at"]), row["decision"], row["rationale"],
        )
    return len(rows)


async def migrate(sqlite_path: Path, dry_run: bool, force: bool) -> None:
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    pg = await asyncpg.connect(_database_url())
    await _init_connection(pg)  # same dict<->jsonb codec the app's pool uses
    try:
        existing = await _existing_counts(pg)
        if any(existing.values()) and not force:
            raise SystemExit(
                f"Target Postgres tables are not empty ({existing}) — refusing to migrate to "
                "avoid duplicating rows. Pass --force if this is intentional (e.g. resuming "
                "after a partial run)."
            )

        # experiment_reviews has an FK into experiments, so migrate in dependency order.
        # A transaction keeps it all-or-nothing: a mid-run failure leaves Postgres exactly
        # as it was before this script ran, so a retry doesn't need manual cleanup first.
        async with pg.transaction():
            n_users = await _migrate_users(sqlite_conn, pg, dry_run)
            n_reports = await _migrate_reports(sqlite_conn, pg, dry_run)
            n_experiments = await _migrate_experiments(sqlite_conn, pg, dry_run)
            n_reviews = await _migrate_experiment_reviews(sqlite_conn, pg, dry_run)
            if dry_run:
                raise _DryRunRollback

        print(
            f"Migrated: {n_users} users, {n_reports} reports, "
            f"{n_experiments} experiments, {n_reviews} experiment_reviews."
        )
    except _DryRunRollback:
        print(
            f"[dry-run] Would migrate: {len(_rows(sqlite_conn, 'users'))} users, "
            f"{len(_rows(sqlite_conn, 'reports'))} reports, "
            f"{len(_rows(sqlite_conn, 'experiments'))} experiments, "
            f"{len(_rows(sqlite_conn, 'experiment_reviews'))} experiment_reviews. "
            "Nothing was written."
        )
    finally:
        await pg.close()
        sqlite_conn.close()


class _DryRunRollback(Exception):
    """Raised inside the transaction to force a rollback after a dry run."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_path", type=Path, help="Path to the legacy atom_reports.db file")
    parser.add_argument("--dry-run", action="store_true", help="Show row counts without writing anything")
    parser.add_argument("--force", action="store_true", help="Migrate even if target tables already have rows")
    args = parser.parse_args()

    if not args.sqlite_path.exists():
        raise SystemExit(f"{args.sqlite_path} does not exist.")

    asyncio.run(migrate(args.sqlite_path, args.dry_run, args.force))


if __name__ == "__main__":
    main()

"""Pytest configuration for ATOM backend tests."""
import os

import pytest_asyncio

# Must be set before any app imports so security.py takes the dev/test path
os.environ.setdefault("ATOM_ENV", "test")
# Use a fixed secret key in tests so JWT tokens are deterministic
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production")
# Point to a non-existent Redis so tests always use in-memory cache
os.environ.setdefault("REDIS_URL", "redis://localhost:19999/0")
# Local dev/CI Postgres — see CONTRIBUTING.md for how to run one locally.
os.environ.setdefault("ATOM_DATABASE_URL", "postgresql+asyncpg://atom:atom_dev@localhost:5432/atom_test")

_TABLES = (
    "reports", "users", "experiments", "experiment_reviews",
    "derivative_plans", "source_snapshots", "paper_trades", "paper_events",
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    """Every test starts from an empty database — tests share one real
    Postgres instance now (no more per-test SQLite file via monkeypatching
    ATOM_DB_PATH), so isolation comes from truncating between tests instead.

    Truncates over a standalone connection, not the app's shared pool: a
    sync test using `TestClient(app)` drives the ASGI app on its own
    internally-managed event loop, separate from this (async) fixture's
    loop. asyncpg pools are bound to the loop that created them, so if this
    fixture created the shared pool here, the app's first DB call from
    TestClient's loop would crash with "attached to a different loop".
    close_pool() at teardown still resets the *app's* pool (if the test
    caused one to be created) so the next test — quite possibly running on
    yet another fresh event loop — doesn't inherit a pool bound to a loop
    that no longer exists.
    """
    if os.getenv("ATOM_SKIP_DB") == "1":
        yield
        return

    import asyncpg

    from app.db.postgres import _database_url, close_pool

    conn = await asyncpg.connect(_database_url())
    try:
        await conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    yield
    await close_pool()

"""Shared asyncpg connection pool for every table in the app.

Replaces the SQLite-based `_get_conn()` in database.py. One pool per
running event loop, lazily created on first use, closed explicitly on
shutdown.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


def _database_url() -> str:
    url = os.getenv("ATOM_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "ATOM_DATABASE_URL is not set. Example: "
            "postgresql://atom:password@localhost:5432/atom_db"
        )
    # asyncpg doesn't understand the +asyncpg driver suffix SQLAlchemy/Alembic use.
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Round-trip Python dicts/lists through JSONB without manual json.dumps/loads."""
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda v: json.dumps(v, ensure_ascii=False, default=str),
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    """Returns the pool for the *current* running event loop.

    In production there is exactly one event loop for the process's whole
    life (uvicorn), so this is just a cached singleton. Test clients that
    aren't used as a context manager (plain `TestClient(app)`, no `with`)
    can start a fresh event loop per call, though — asyncpg pools are bound
    to the loop that created them, so reusing a pool from a dead loop
    raises "attached to a different loop". Detect that and transparently
    hand back a fresh pool instead of a stale, unusable one.
    """
    global _pool, _pool_loop
    current_loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is not current_loop:
        logger.warning("Event loop changed since the pool was created — discarding the stale pool.")
        _pool = None
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _database_url(),
            min_size=1,
            max_size=10,
            init=_init_connection,
        )
        _pool_loop = current_loop
        logger.info("Postgres connection pool created.")
    return _pool


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None:
        try:
            await _pool.close()
        except RuntimeError:
            pass  # pool's loop is already gone — nothing to gracefully close
        _pool = None
        _pool_loop = None
        logger.info("Postgres connection pool closed.")

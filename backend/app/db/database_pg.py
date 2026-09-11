"""SPIKE — Postgres-backed persistence, mirroring app/db/database.py's public
API but async (asyncpg, no ORM — consistent with this codebase's existing
"zero heavy ORM dependencies" stance from database.py's own docstring).

Not wired into main.py. Exists to validate the SQLite -> Postgres migration
approach: schema translation (see alembic/versions/), connection pooling,
JSONB round-tripping, and async query ergonomics under asyncpg. See
docs/POSTGRES-MIGRATION-SPIKE.md for findings and effort estimate.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_DATABASE_URL = os.getenv("ATOM_DATABASE_URL", "")
_pool: asyncpg.Pool | None = None


async def _init_jsonb_codec(conn: asyncpg.Connection) -> None:
    """asyncpg returns JSONB as raw text by default; decode/encode transparently."""
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda v: json.dumps(v, ensure_ascii=False, default=str),
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError("ATOM_DATABASE_URL is not set.")
        _pool = await asyncpg.create_pool(
            _DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=1,
            max_size=10,
            init=_init_jsonb_codec,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ── Reports ──────────────────────────────────────────────────────────────

async def save_report(ticker: str, report: dict[str, Any], *, owner: str) -> int:
    rec = report.get("recommendation", {})
    md = report.get("market_data", {})
    pool = await get_pool()
    try:
        row_id = await pool.fetchval(
            """
            INSERT INTO reports
                (ticker, exchange, price, currency, bull_score, action, narrative, full_report, created_at, owner)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            ticker.upper(),
            report.get("exchange"),
            md.get("price"),
            md.get("currency"),
            rec.get("bull_score"),
            rec.get("action"),
            report.get("narrative"),
            report,  # dict passed directly -> encoded by the jsonb codec
            datetime.now(UTC),
            owner,
        )
        logger.info("Report saved to DB: %s (id=%d)", ticker, row_id)
        return row_id
    except Exception as exc:
        logger.error("Failed to save report for %s: %s", ticker, exc)
        raise


async def list_reports(ticker: str | None = None, limit: int = 20, *, owner: str) -> list[dict]:
    pool = await get_pool()
    try:
        if ticker:
            rows = await pool.fetch(
                "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                "FROM reports WHERE owner = $1 AND ticker = $2 ORDER BY created_at DESC LIMIT $3",
                owner, ticker.upper(), limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                "FROM reports WHERE owner = $1 ORDER BY created_at DESC LIMIT $2",
                owner, limit,
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to list reports: %s", exc)
        return []


async def get_report_by_id(report_id: int, *, owner: str) -> dict | None:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT full_report FROM reports WHERE id = $1 AND owner = $2", report_id, owner
        )
        return row["full_report"] if row else None  # already decoded by the jsonb codec
    except Exception as exc:
        logger.error("Failed to get report id=%d: %s", report_id, exc)
        return None


# ── User CRUD ────────────────────────────────────────────────────────────

async def create_user(username: str, email: str, password_hash: str, role: str = "analyst") -> int | None:
    pool = await get_pool()
    try:
        row_id = await pool.fetchval(
            "INSERT INTO users (username, email, password_hash, role, created_at) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            username.lower().strip(), email.lower().strip(), password_hash, role, datetime.now(UTC),
        )
        logger.info("User created: %s (id=%d)", username, row_id)
        return row_id
    except asyncpg.UniqueViolationError:
        logger.warning("Duplicate user attempt: %s / %s", username, email)
        return None
    except Exception as exc:
        logger.error("Failed to create user %s: %s", username, exc)
        return None


async def get_user_by_username(username: str) -> dict | None:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT id, username, email, password_hash, role, is_active, created_at "
            "FROM users WHERE username = $1 AND is_active = TRUE",
            username.lower().strip(),
        )
        return dict(row) if row else None
    except Exception as exc:
        logger.error("Failed to get user %s: %s", username, exc)
        return None


async def get_user_by_email(email: str) -> dict | None:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT id, username, email, role, is_active, created_at "
            "FROM users WHERE email = $1 AND is_active = TRUE",
            email.lower().strip(),
        )
        return dict(row) if row else None
    except Exception as exc:
        logger.error("Failed to get user by email %s: %s", email, exc)
        return None


async def user_exists(username: str) -> bool:
    pool = await get_pool()
    try:
        row = await pool.fetchrow("SELECT 1 FROM users WHERE username = $1", username.lower().strip())
        return row is not None
    except Exception:
        return False


async def list_users(limit: int = 100) -> list[dict]:
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            "SELECT id, username, email, role, is_active, created_at "
            "FROM users ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to list users: %s", exc)
        return []


async def readiness() -> None:
    """Verify writable database with a rolled-back write, without external API calls.

    DDL is transactional in Postgres (unlike SQLite's autocommit-per-statement
    default): CREATE TABLE must commit on its own, in a separate transaction
    from the probe write, or rolling back the probe would undo the table too.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS health_probe (id INTEGER PRIMARY KEY)")
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                "INSERT INTO health_probe (id) VALUES (1) ON CONFLICT (id) DO UPDATE SET id = 1"
            )
        finally:
            await tx.rollback()

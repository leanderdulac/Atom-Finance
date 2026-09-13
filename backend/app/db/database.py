"""
ATOM Database — PostgreSQL-backed persistence for reports and users.
Raw asyncpg, no ORM — schema lives in alembic/versions/, not here.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.db.postgres import get_pool

logger = logging.getLogger(__name__)


# ── Reports ──────────────────────────────────────────────────────────────

async def save_report(ticker: str, report: dict[str, Any], *, owner: str) -> int:
    """Persists a full AI report. Returns the new row ID."""
    rec = report.get("recommendation", {})
    md = report.get("market_data", {})
    try:
        pool = await get_pool()
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
            report,
            datetime.now(UTC),
            owner,
        )
        logger.info("Report saved to DB: %s (id=%d)", ticker, row_id)
        return row_id
    except Exception as exc:
        logger.error("Failed to save report for %s: %s", ticker, exc)
        raise


async def list_reports(ticker: str | None = None, limit: int = 20, *, owner: str) -> list[dict]:
    """Returns recent reports, optionally filtered by ticker."""
    try:
        pool = await get_pool()
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
    """Returns the full report JSON for a given ID."""
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT full_report FROM reports WHERE id = $1 AND owner = $2", report_id, owner
        )
        return row["full_report"] if row else None
    except Exception as exc:
        logger.error("Failed to get report id=%d: %s", report_id, exc)
        return None


# ── User CRUD ────────────────────────────────────────────────────────────

async def create_user(username: str, email: str, password_hash: str, role: str = "analyst") -> int | None:
    """Creates a new user. Returns the new row ID, or None on duplicate."""
    try:
        pool = await get_pool()
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
    """Returns user dict (includes password_hash) or None."""
    try:
        pool = await get_pool()
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
    """Returns user dict by email or None."""
    try:
        pool = await get_pool()
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
    """Fast check — returns True if username is already taken."""
    try:
        pool = await get_pool()
        row = await pool.fetchrow("SELECT 1 FROM users WHERE username = $1", username.lower().strip())
        return row is not None
    except Exception:
        return False


async def list_users(limit: int = 100) -> list[dict]:
    """Admin helper — returns user list without password hashes."""
    try:
        pool = await get_pool()
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

    DDL is transactional in Postgres: CREATE TABLE must commit on its own, in
    a separate transaction from the probe write, or rolling back the probe
    would undo the table too.
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

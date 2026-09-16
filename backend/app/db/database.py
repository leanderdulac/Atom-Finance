"""
ATOM Database — PostgreSQL-backed persistence for reports and users.
Raw asyncpg, no ORM — schema lives in alembic/versions/, not here.
"""
from __future__ import annotations

import hashlib
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


# ── Refresh tokens (HttpOnly-cookie sessions) ─────────────────────────────

def hash_token(token: str) -> str:
    """sha256 of the opaque refresh token. Only this hash is ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_refresh_token(user_id: int, token_hash: str, expires_at: datetime) -> int | None:
    """Persists a new refresh-token hash. Returns the row id or None on error."""
    try:
        pool = await get_pool()
        return await pool.fetchval(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3) RETURNING id",
            user_id, token_hash, expires_at,
        )
    except Exception as exc:
        logger.error("Failed to create refresh token: %s", exc)
        return None


async def get_user_by_id(user_id: int) -> dict | None:
    """Returns a user dict by primary key, or None."""
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT id, username, email, role, is_active, created_at "
            "FROM users WHERE id = $1 AND is_active = TRUE",
            user_id,
        )
        return dict(row) if row else None
    except Exception as exc:
        logger.error("Failed to get user id=%s: %s", user_id, exc)
        return None


async def rotate_refresh_token(
    old_token_hash: str,
    new_token_hash: str,
    new_expires_at: datetime,
) -> int | None:
    """Atomically consume and replace one refresh token (rotation).

    Returns the new token's user_id on success, or None if the old token was
    invalid/expired/revoked. A replayed (already-used) token is treated as
    theft: the whole family for that user is revoked.
    """
    now = datetime.now(UTC)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id, user_id, used_at, revoked_at, expires_at "
                    "FROM refresh_tokens WHERE token_hash = $1 FOR UPDATE",
                    old_token_hash,
                )
                if row is None:
                    return None
                if row["revoked_at"] is not None or row["expires_at"] <= now:
                    return None
                if row["used_at"] is not None:
                    # Token reuse — a stolen/duplicated token; shut the family down.
                    await conn.execute(
                        "UPDATE refresh_tokens SET revoked_at = $1 "
                        "WHERE user_id = $2 AND revoked_at IS NULL",
                        now, row["user_id"],
                    )
                    return None
                await conn.execute(
                    "UPDATE refresh_tokens SET used_at = $1, replaced_by_token_hash = $2 WHERE id = $3",
                    now, new_token_hash, row["id"],
                )
                await conn.execute(
                    "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
                    row["user_id"], new_token_hash, new_expires_at,
                )
                return row["user_id"]
    except Exception as exc:
        logger.error("Failed to rotate refresh token: %s", exc)
        return None


async def revoke_refresh_token(token_hash: str) -> bool:
    """Revokes one refresh token (logout)."""
    try:
        pool = await get_pool()
        await pool.execute(
            "UPDATE refresh_tokens SET revoked_at = $1 WHERE token_hash = $2 AND revoked_at IS NULL",
            datetime.now(UTC), token_hash,
        )
        return True
    except Exception as exc:
        logger.error("Failed to revoke refresh token: %s", exc)
        return False

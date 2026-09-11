"""
ATOM Database — SQLite-backed persistence for reports and users.
Zero heavy ORM dependencies; uses Python's built-in sqlite3.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("ATOM_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "..", "atom_reports.db"))
_DB_PATH = os.path.abspath(_DB_PATH)


def _create_tables(conn: sqlite3.Connection) -> None:
    # ── Reports ───────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL,
            exchange    TEXT,
            price       REAL,
            currency    TEXT,
            bull_score  REAL,
            action      TEXT,
            narrative   TEXT,
            full_report TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_ticker ON reports(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at)")

    if "owner" not in {row[1] for row in conn.execute("PRAGMA table_info(reports)")}:
        conn.execute("ALTER TABLE reports ADD COLUMN owner TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_owner ON reports(owner, created_at)")

    # ── Users ─────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'analyst',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    conn.commit()


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        _create_tables(conn)
        yield conn
    finally:
        conn.close()


def save_report(ticker: str, report: dict[str, Any], *, owner: str) -> int:
    """Persists a full AI report. Returns the new row ID."""
    try:
        rec = report.get("recommendation", {})
        md = report.get("market_data", {})
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO reports
                    (ticker, exchange, price, currency, bull_score, action, narrative, full_report, created_at, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker.upper(),
                    report.get("exchange"),
                    md.get("price"),
                    md.get("currency"),
                    rec.get("bull_score"),
                    rec.get("action"),
                    report.get("narrative"),
                    json.dumps(report, ensure_ascii=False, default=str),
                    datetime.now(UTC).isoformat(),
                    owner,
                ),
            )
            conn.commit()
            logger.info("Report saved to DB: %s (id=%d)", ticker, cur.lastrowid)
            # lastrowid is None only when the last statement wasn't an INSERT;
            # we just ran one, so it's always populated here.
            assert cur.lastrowid is not None
            return cur.lastrowid
    except Exception as exc:
        logger.error("Failed to save report for %s: %s", ticker, exc)
        raise


def list_reports(ticker: str | None = None, limit: int = 20, *, owner: str) -> list[dict]:
    """Returns recent reports, optionally filtered by ticker."""
    try:
        with _get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                    "FROM reports WHERE owner = ? AND ticker = ? ORDER BY created_at DESC LIMIT ?",
                    (owner, ticker.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                    "FROM reports WHERE owner = ? ORDER BY created_at DESC LIMIT ?",
                    (owner, limit),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to list reports: %s", exc)
        return []


def get_report_by_id(report_id: int, *, owner: str) -> dict | None:
    """Returns the full report JSON for a given ID."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT full_report FROM reports WHERE id = ? AND owner = ?", (report_id, owner)
            ).fetchone()
            if row:
                return json.loads(row["full_report"])
            return None
    except Exception as exc:
        logger.error("Failed to get report id=%d: %s", report_id, exc)
        return None


# ── User CRUD ──────────────────────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str, role: str = "analyst") -> int | None:
    """Creates a new user. Returns the new row ID, or None on duplicate."""
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username.lower().strip(), email.lower().strip(), password_hash, role, datetime.now(UTC).isoformat()),
            )
            conn.commit()
            logger.info("User created: %s (id=%d)", username, cur.lastrowid)
            return cur.lastrowid
    except sqlite3.IntegrityError:
        logger.warning("Duplicate user attempt: %s / %s", username, email)
        return None
    except Exception as exc:
        logger.error("Failed to create user %s: %s", username, exc)
        return None


def get_user_by_username(username: str) -> dict | None:
    """Returns user dict (includes password_hash) or None."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT id, username, email, password_hash, role, is_active, created_at "
                "FROM users WHERE username = ? AND is_active = 1",
                (username.lower().strip(),),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.error("Failed to get user %s: %s", username, exc)
        return None


def get_user_by_email(email: str) -> dict | None:
    """Returns user dict by email or None."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT id, username, email, role, is_active, created_at "
                "FROM users WHERE email = ? AND is_active = 1",
                (email.lower().strip(),),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.error("Failed to get user by email %s: %s", email, exc)
        return None


def user_exists(username: str) -> bool:
    """Fast check — returns True if username is already taken."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username.lower().strip(),)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def list_users(limit: int = 100) -> list[dict]:
    """Admin helper — returns user list without password hashes."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to list users: %s", exc)
        return []


def readiness():
    """Verify writable database with a rolled-back write, without external API calls."""
    with _get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS health_probe (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.execute("INSERT OR REPLACE INTO health_probe VALUES (1)")
        conn.rollback()

"""
ATOM Database — SQLite-backed report persistence.
Zero heavy ORM dependencies; uses Python's built-in sqlite3.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("ATOM_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "..", "atom_reports.db"))
_DB_PATH = os.path.abspath(_DB_PATH)


def _create_tables(conn: sqlite3.Connection) -> None:
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
    conn.commit()


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        _create_tables(conn)
        yield conn
    finally:
        conn.close()


def save_report(ticker: str, report: dict[str, Any]) -> int:
    """Persists a full AI report. Returns the new row ID."""
    try:
        rec = report.get("recommendation", {})
        md = report.get("market_data", {})
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO reports
                    (ticker, exchange, price, currency, bull_score, action, narrative, full_report, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            logger.info("Report saved to DB: %s (id=%d)", ticker, cur.lastrowid)
            return cur.lastrowid
    except Exception as exc:
        logger.error("Failed to save report for %s: %s", ticker, exc)
        return -1


def list_reports(ticker: Optional[str] = None, limit: int = 20) -> List[dict]:
    """Returns recent reports, optionally filtered by ticker."""
    try:
        with _get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                    "FROM reports WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
                    (ticker.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, ticker, exchange, price, currency, bull_score, action, created_at "
                    "FROM reports ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("Failed to list reports: %s", exc)
        return []


def get_report_by_id(report_id: int) -> Optional[dict]:
    """Returns the full report JSON for a given ID."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT full_report FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
            if row:
                return json.loads(row["full_report"])
            return None
    except Exception as exc:
        logger.error("Failed to get report id=%d: %s", report_id, exc)
        return None

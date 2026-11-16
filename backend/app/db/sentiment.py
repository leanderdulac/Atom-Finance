"""Persist the sentiment thermometer series. Read-only for the client path."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.db.postgres import get_pool


async def insert_snapshot(row: dict[str, Any]) -> str:
    snap_id = str(uuid4())
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO sentiment_snapshots (
            id, ticker, horizon, created_at, score, intensity, momentum,
            price, price_divergence, n_mentions, holding_days, headlines, sources, payload
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        """,
        snap_id,
        row["ticker"],
        row["horizon"],
        row.get("created_at") or datetime.now(UTC),
        float(row["score"]),
        float(row.get("intensity") or 0),
        float(row.get("momentum") or 0),
        row.get("price"),
        row.get("price_divergence"),
        int(row.get("n_mentions") or 0),
        int(row.get("holding_days") or 21),
        row.get("headlines") or [],
        row.get("sources") or [],
        row.get("payload") or {},
    )
    return snap_id


async def list_snapshots(ticker: str, horizon: str, *, limit: int = 200) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, ticker, horizon, created_at, score, intensity, momentum,
               price, price_divergence, n_mentions, holding_days, headlines, sources, payload
        FROM sentiment_snapshots
        WHERE ticker=$1 AND horizon=$2
        ORDER BY created_at ASC
        LIMIT $3
        """,
        ticker, horizon, max(1, min(limit, 2000)),
    )
    return [dict(r) for r in rows]


async def latest_snapshot(ticker: str, horizon: str) -> dict[str, Any] | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ticker, horizon, created_at, score, intensity, momentum,
               price, price_divergence, n_mentions, holding_days, headlines, sources, payload
        FROM sentiment_snapshots
        WHERE ticker=$1 AND horizon=$2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        ticker, horizon,
    )
    return dict(row) if row else None

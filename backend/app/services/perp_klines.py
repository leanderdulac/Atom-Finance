"""
Unsigned Binance USDM mark-price klines.

Public REST only — no API keys, no orders, no account endpoints.
Used by the ETH/SOL paper pipeline when the operator asks for historical marks.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.models.stat_arb_paper import (
    DEFAULT_X,
    DEFAULT_Y,
    HALF_SPREAD_BPS,
    MIN_BARS,
    PairBar,
    align_pair_series,
    require_allowed_pair,
)

logger = logging.getLogger(__name__)

BINANCE_FUTURES = "https://fapi.binance.com"

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


async def fetch_mark_klines(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    interval: str = "1h",
    limit: int = 500,
) -> list[tuple[int, float]]:
    """Return (open_time_ms, mark_close) from ``/fapi/v1/markPriceKlines``."""
    symbol = symbol.upper().strip()
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval {interval!r}")
    if not 80 <= limit <= 1500:
        raise ValueError("limit must be between 80 and 1500")
    response = await client.get(
        f"{BINANCE_FUTURES}/fapi/v1/markPriceKlines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Empty mark kline payload for {symbol}")
    out: list[tuple[int, float]] = []
    for row in rows:
        ts = int(row[0])
        mid = float(row[4])
        if mid <= 0 or mid != mid:  # NaN check without importing math on a hot path
            raise ValueError(f"Non-finite mark mid for {symbol} at {ts}")
        out.append((ts, mid))
    return out


async def fetch_eth_sol_pair(
    *,
    client: httpx.AsyncClient,
    y_symbol: str = DEFAULT_Y,
    x_symbol: str = DEFAULT_X,
    interval: str = "1h",
    limit: int = 500,
    half_spread_bps: float = HALF_SPREAD_BPS,
) -> dict[str, Any]:
    """Fetch both legs, inner-join on timestamp, synthesize bid/ask from half-spread."""
    y_symbol, x_symbol = require_allowed_pair(y_symbol, x_symbol)
    y_rows = await fetch_mark_klines(y_symbol, client=client, interval=interval, limit=limit)
    x_rows = await fetch_mark_klines(x_symbol, client=client, interval=interval, limit=limit)
    expected = INTERVAL_MS[interval]
    bars, gaps = align_pair_series(
        y_rows, x_rows, half_spread_bps=half_spread_bps, expected_interval_ms=expected,
    )
    if len(bars) < MIN_BARS:
        raise ValueError(f"Aligned ETH/SOL marks shorter than {MIN_BARS}")
    return {
        "bars": bars,
        "gaps": gaps,
        "expected_interval_ms": expected,
        "y_symbol": y_symbol.upper(),
        "x_symbol": x_symbol.upper(),
        "interval": interval,
        "source": "binance_usdm_mark_klines",
        "signed": False,
        "broker_orders_sent": 0,
        "note": "Public markPriceKlines only. ATOM does not sign orders or send API keys.",
    }


def bars_as_dicts(bars: list[PairBar]) -> list[dict[str, float | int]]:
    return [
        {
            "ts_ms": b.ts_ms,
            "y_mid": b.y_mid,
            "x_mid": b.x_mid,
            "y_bid": b.y_bid,
            "y_ask": b.y_ask,
            "x_bid": b.x_bid,
            "x_ask": b.x_ask,
        }
        for b in bars
    ]

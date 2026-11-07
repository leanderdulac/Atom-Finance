"""
Unsigned perpetual mark-price klines.

Public REST only — no API keys, no orders, no account endpoints.
Used by the ETH/SOL paper pipeline when the operator asks for historical marks.

Default venue is Binance USDM ``markPriceKlines``. ``venue=okx|hyperliquid``
routes to :mod:`app.services.perp_feeds` (keyless OKX / Hyperliquid adapters).
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

SUPPORTED_VENUES = ("binance", "okx", "hyperliquid")

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

_SOURCE = {
    "binance": "binance_usdm_mark_klines",
    "okx": "okx_swap_mark_candles",
    "hyperliquid": "hyperliquid_perp_candles",
}


def _normalize_venue(venue: str) -> str:
    v = (venue or "binance").lower().strip()
    if v not in SUPPORTED_VENUES:
        raise ValueError(f"Unsupported venue {venue!r}; expected one of {SUPPORTED_VENUES}")
    return v


async def fetch_mark_klines(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    interval: str = "1h",
    limit: int = 500,
    venue: str = "binance",
) -> list[tuple[int, float]]:
    """Return (open_time_ms, mark_close). Default: Binance ``/fapi/v1/markPriceKlines``."""
    symbol = symbol.upper().strip()
    venue = _normalize_venue(venue)
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval {interval!r}")
    if not 80 <= limit <= 1500:
        raise ValueError("limit must be between 80 and 1500")
    if venue != "binance":
        from app.services.perp_feeds import fetch_perp_candles

        candles = await fetch_perp_candles(
            venue, symbol, client=client, interval=interval, limit=limit,
        )
        out = [c.as_close_row() for c in candles]
        if not out:
            raise ValueError(f"Empty mark kline payload for {symbol}")
        return out

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
    venue: str = "binance",
) -> dict[str, Any]:
    """Fetch both legs, inner-join on timestamp, synthesize bid/ask from half-spread."""
    y_symbol, x_symbol = require_allowed_pair(y_symbol, x_symbol)
    venue = _normalize_venue(venue)
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval {interval!r}")
    expected = INTERVAL_MS[interval]
    y_funding: dict[int, float] = {}
    x_funding: dict[int, float] = {}
    if venue == "binance":
        y_rows = await fetch_mark_klines(
            y_symbol, client=client, interval=interval, limit=limit, venue=venue,
        )
        x_rows = await fetch_mark_klines(
            x_symbol, client=client, interval=interval, limit=limit, venue=venue,
        )
    else:
        from app.services.perp_feeds import fetch_perp_candles

        y_candles = await fetch_perp_candles(
            venue, y_symbol, client=client, interval=interval, limit=limit,
        )
        x_candles = await fetch_perp_candles(
            venue, x_symbol, client=client, interval=interval, limit=limit,
        )
        y_rows = [c.as_close_row() for c in y_candles]
        x_rows = [c.as_close_row() for c in x_candles]
        y_funding = {c.ts_ms: c.funding_rate for c in y_candles}
        x_funding = {c.ts_ms: c.funding_rate for c in x_candles}
    bars, gaps = align_pair_series(
        y_rows,
        x_rows,
        half_spread_bps=half_spread_bps,
        expected_interval_ms=expected,
        y_funding=y_funding or None,
        x_funding=x_funding or None,
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
        "venue": venue,
        "source": _SOURCE[venue],
        "signed": False,
        "broker_orders_sent": 0,
        "note": (
            "Public mark candles only. ATOM does not sign orders or send API keys. "
            f"Venue={venue}."
        ),
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
            "y_funding": b.y_funding,
            "x_funding": b.x_funding,
        }
        for b in bars
    ]

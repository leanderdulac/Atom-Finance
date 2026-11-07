"""
Public, keyless perpetual mark-candle and funding feeds (OKX, Hyperliquid).

Adapted from hummingbot/hummingbot (Apache-2.0), specifically the REST
request shapes in:
  hummingbot/data_feed/candles_feed/okx_perpetual_candles
  hummingbot/data_feed/candles_feed/hyperliquid_perpetual_candles

The hummingbot package is not a dependency (its numpy pin conflicts with ATOM).
Only the small unsigned REST client was reimplemented with httpx.

See NOTICE and third_party/hummingbot/. HTTP errors and empty payloads are
logged as warnings and become empty lists — this module does not raise for
upstream failures. Invalid caller arguments (unknown venue/interval) still
raise ValueError.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OKX_REST = "https://www.okx.com"
OKX_MARK_CANDLES = "/api/v5/market/history-mark-price-candles"
OKX_FUNDING = "/api/v5/public/funding-rate"
OKX_FUNDING_HISTORY = "/api/v5/public/funding-rate-history"
OKX_TICKER = "/api/v5/market/ticker"
OKX_MAX_CANDLES = 100
OKX_MAX_FUNDING = 100

HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"
HL_MAX_CANDLES = 500

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

# Mark-price candles: 1H / 1D (not the utc-suffixed history-candles bars).
OKX_BAR = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "8h": "8H",
    "12h": "12H",
    "1d": "1D",
}

HL_INTERVAL = {name: name for name in INTERVAL_MS}

FUNDING_PERIOD_MS = {
    "okx": 8 * 3_600_000,
    "hyperliquid": 1 * 3_600_000,
    "binance": 8 * 3_600_000,
}

SUPPORTED_FEEDS = frozenset({"okx", "hyperliquid"})

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ATOM-Finance paper-research/0.1 (unsigned public market data)",
}


@dataclass(frozen=True)
class PerpCandle:
    """Normalized UTC-ms mark candle. ``close`` is the mid used by the paper loop."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    funding_rate: float = 0.0

    def as_close_row(self) -> tuple[int, float]:
        return self.ts_ms, self.close


def to_utc_ms(value: Any) -> int | None:
    """Coerce exchange timestamps to UTC milliseconds. Seconds (< 1e12) are scaled."""
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if ts < 1_000_000_000_000:
        ts *= 1000
    return ts


def to_okx_inst_id(symbol: str) -> str:
    """ETHUSDT / ETH-USDT → ETH-USDT-SWAP. Already-suffixed ids pass through."""
    raw = symbol.strip().upper()
    if raw.endswith("-SWAP"):
        return raw
    compact = raw.replace("-", "").replace("_", "")
    if compact.endswith("USDT"):
        return f"{compact[:-4]}-USDT-SWAP"
    if compact.endswith("USD"):
        return f"{compact[:-3]}-USD-SWAP"
    return f"{raw}-SWAP"


def to_hyperliquid_coin(symbol: str) -> str:
    s = symbol.strip().upper().replace("-", "").replace("_", "")
    if s.endswith("USDT"):
        return s[:-4]
    if s.endswith("USD"):
        return s[:-3]
    if s.endswith("USDC"):
        return s[:-4]
    return s


def _finite_px(value: Any) -> float | None:
    try:
        px = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(px) or px <= 0:
        return None
    return px


def _finite_rate(value: Any) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate):
        return None
    return rate


def _okx_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and str(payload.get("code", "")) == "0"


def _dedupe_sort(candles: Sequence[PerpCandle]) -> list[PerpCandle]:
    by_ts: dict[int, PerpCandle] = {}
    for c in candles:
        by_ts[c.ts_ms] = c
    return [by_ts[ts] for ts in sorted(by_ts)]


def parse_okx_mark_candles(payload: Any) -> list[PerpCandle]:
    """Parse GET /api/v5/market/history-mark-price-candles. Newest-first from OKX."""
    if not _okx_ok(payload):
        msg = payload.get("msg") if isinstance(payload, dict) else type(payload).__name__
        logger.warning("OKX mark candles empty/error: %s", msg)
        return []
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        logger.warning("OKX mark candles returned no rows")
        return []
    out: list[PerpCandle] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            logger.warning("OKX mark candle skipped (short row): %s", row)
            continue
        ts = to_utc_ms(row[0])
        o, h, l, c = _finite_px(row[1]), _finite_px(row[2]), _finite_px(row[3]), _finite_px(row[4])
        if ts is None or o is None or h is None or l is None or c is None:
            logger.warning("OKX mark candle skipped (non-finite) at %s", row[0] if row else None)
            continue
        out.append(PerpCandle(ts_ms=ts, open=o, high=h, low=l, close=c))
    return _dedupe_sort(out)


def parse_okx_funding_history(payload: Any) -> list[tuple[int, float]]:
    if not _okx_ok(payload):
        msg = payload.get("msg") if isinstance(payload, dict) else type(payload).__name__
        logger.warning("OKX funding history empty/error: %s", msg)
        return []
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        logger.warning("OKX funding history returned no rows")
        return []
    out: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = to_utc_ms(row.get("fundingTime"))
        rate = _finite_rate(row.get("fundingRate") if row.get("fundingRate") not in (None, "") else row.get("realizedRate"))
        if ts is None or rate is None:
            logger.warning("OKX funding row skipped: %s", row)
            continue
        out.append((ts, rate))
    out.sort(key=lambda item: item[0])
    return out


def parse_okx_funding_current(payload: Any) -> list[tuple[int, float]]:
    if not _okx_ok(payload):
        msg = payload.get("msg") if isinstance(payload, dict) else type(payload).__name__
        logger.warning("OKX funding-rate empty/error: %s", msg)
        return []
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        logger.warning("OKX funding-rate returned no rows")
        return []
    out: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = to_utc_ms(row.get("fundingTime") or row.get("ts"))
        rate = _finite_rate(row.get("fundingRate"))
        if ts is None or rate is None:
            continue
        out.append((ts, rate))
    return out


def parse_hyperliquid_candles(payload: Any) -> list[PerpCandle]:
    if payload is None:
        logger.warning("Hyperliquid candleSnapshot returned empty payload")
        return []
    if isinstance(payload, dict):
        # Some error envelopes are JSON objects.
        logger.warning("Hyperliquid candleSnapshot unexpected object: %s", list(payload)[:6])
        return []
    if not isinstance(payload, list):
        logger.warning("Hyperliquid candleSnapshot unexpected type %s", type(payload).__name__)
        return []
    if not payload:
        logger.warning("Hyperliquid candleSnapshot returned no rows")
        return []
    out: list[PerpCandle] = []
    for row in payload:
        if not isinstance(row, dict):
            logger.warning("Hyperliquid candle skipped (not an object)")
            continue
        ts = to_utc_ms(row.get("t"))
        o = _finite_px(row.get("o"))
        h = _finite_px(row.get("h"))
        l = _finite_px(row.get("l"))
        c = _finite_px(row.get("c"))
        if ts is None or o is None or h is None or l is None or c is None:
            logger.warning("Hyperliquid candle skipped (non-finite) at %s", row.get("t"))
            continue
        out.append(PerpCandle(ts_ms=ts, open=o, high=h, low=l, close=c))
    return _dedupe_sort(out)


def parse_hyperliquid_funding(payload: Any) -> list[tuple[int, float]]:
    if not isinstance(payload, list) or not payload:
        logger.warning("Hyperliquid fundingHistory empty/error: %s", type(payload).__name__)
        return []
    out: list[tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        ts = to_utc_ms(row.get("time"))
        rate = _finite_rate(row.get("fundingRate"))
        if ts is None or rate is None:
            logger.warning("Hyperliquid funding row skipped: %s", row)
            continue
        out.append((ts, rate))
    out.sort(key=lambda item: item[0])
    return out


def infer_funding_period_ms(events: Sequence[tuple[int, float]], default_ms: int) -> int:
    if len(events) < 2:
        return default_ms
    dts = sorted(events[i][0] - events[i - 1][0] for i in range(1, len(events)))
    dts = [d for d in dts if d > 0]
    if not dts:
        return default_ms
    return int(dts[len(dts) // 2])


def attach_funding(
    candles: Sequence[PerpCandle],
    events: Sequence[tuple[int, float]],
    *,
    interval_ms: int,
    default_period_ms: int,
) -> list[PerpCandle]:
    """Map venue funding onto each candle as an accrued rate for that interval.

    When the bar is at least half a funding period, settlements that fall inside
    the bar are summed. Otherwise the latest known rate is prorated by
    ``interval / period`` (8h OKX rate on 1h bars → rate/8).
    """
    if not candles:
        return []
    ev = [(int(ts), float(rate)) for ts, rate in events if math.isfinite(rate)]
    ev.sort(key=lambda item: item[0])
    period = infer_funding_period_ms(ev, default_period_ms)
    if period <= 0:
        period = default_period_ms
    scale = float(interval_ms) / float(period)
    half_period = 0.5 * period
    out: list[PerpCandle] = []
    j = -1
    for candle in candles:
        end = candle.ts_ms + interval_ms
        while j + 1 < len(ev) and ev[j + 1][0] < end:
            j += 1
        in_bar = [item for item in ev if candle.ts_ms <= item[0] < end]
        if in_bar and interval_ms >= half_period:
            rate = sum(item[1] for item in in_bar)
        elif j >= 0:
            rate = ev[j][1] * scale
        else:
            rate = 0.0
        out.append(replace(candle, funding_rate=rate))
    return out


async def _okx_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, str],
    *,
    timeout: float = 10.0,
) -> Any:
    try:
        response = await client.get(
            f"{OKX_REST}{path}",
            params=params,
            timeout=timeout,
            headers=_HEADERS,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("OKX GET %s failed: %s", path, exc)
        return None


async def _hl_post(
    client: httpx.AsyncClient,
    body: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> Any:
    try:
        response = await client.post(
            HYPERLIQUID_INFO,
            json=body,
            timeout=timeout,
            headers={**_HEADERS, "Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Hyperliquid info %s failed: %s", body.get("type"), exc)
        return None


async def fetch_okx_mark_candles(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    interval: str = "1h",
    limit: int = 500,
    page_size: int = OKX_MAX_CANDLES,
) -> list[PerpCandle]:
    """Paginated mark-price candles. Newest page first; returned oldest→newest."""
    if interval not in OKX_BAR:
        raise ValueError(f"Unsupported interval {interval!r}")
    if limit < 1:
        return []
    inst = to_okx_inst_id(symbol)
    page_size = min(max(int(page_size), 1), OKX_MAX_CANDLES)
    collected: list[PerpCandle] = []
    after: str | None = None
    remaining = limit
    # Hard cap so a stuck cursor cannot loop.
    for _ in range(20):
        if remaining <= 0:
            break
        params = {
            "instId": inst,
            "bar": OKX_BAR[interval],
            "limit": str(min(page_size, remaining)),
        }
        if after is not None:
            params["after"] = after
        payload = await _okx_get(client, OKX_MARK_CANDLES, params)
        page = parse_okx_mark_candles(payload)
        if not page:
            break
        collected.extend(page)
        oldest = min(c.ts_ms for c in page)
        if len(page) < min(page_size, remaining):
            break
        if after is not None and str(oldest) == after:
            logger.warning("OKX mark candles pagination cursor did not advance for %s", inst)
            break
        after = str(oldest)
        remaining = limit - len(_dedupe_sort(collected))
    return _dedupe_sort(collected)[:limit]


async def fetch_okx_funding_history(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    limit: int = 100,
    after_ms: int | None = None,
    page_size: int = OKX_MAX_FUNDING,
) -> list[tuple[int, float]]:
    inst = to_okx_inst_id(symbol)
    page_size = min(max(int(page_size), 1), OKX_MAX_FUNDING)
    collected: list[tuple[int, float]] = []
    after: str | None = str(after_ms) if after_ms is not None else None
    remaining = max(int(limit), 1)
    for _ in range(20):
        if remaining <= 0:
            break
        params = {"instId": inst, "limit": str(min(page_size, remaining))}
        if after is not None:
            params["after"] = after
        payload = await _okx_get(client, OKX_FUNDING_HISTORY, params)
        page = parse_okx_funding_history(payload)
        if not page:
            break
        collected.extend(page)
        oldest = min(ts for ts, _ in page)
        if len(page) < min(page_size, remaining):
            break
        if after is not None and str(oldest) == after:
            break
        after = str(oldest)
        remaining = limit - len(collected)
    by_ts = {ts: rate for ts, rate in collected}
    return [(ts, by_ts[ts]) for ts in sorted(by_ts)][:limit]


async def fetch_okx_funding_current(
    symbol: str,
    *,
    client: httpx.AsyncClient,
) -> list[tuple[int, float]]:
    inst = to_okx_inst_id(symbol)
    payload = await _okx_get(client, OKX_FUNDING, {"instId": inst})
    return parse_okx_funding_current(payload)


async def fetch_hyperliquid_candles(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    interval: str = "1h",
    limit: int = 500,
    end_ms: int | None = None,
    page_size: int = HL_MAX_CANDLES,
) -> list[PerpCandle]:
    if interval not in HL_INTERVAL:
        raise ValueError(f"Unsupported interval {interval!r}")
    if limit < 1:
        return []
    coin = to_hyperliquid_coin(symbol)
    interval_ms = INTERVAL_MS[interval]
    page_size = min(max(int(page_size), 1), HL_MAX_CANDLES)
    cursor_end = int(end_ms) if end_ms is not None else int(time.time() * 1000)
    collected: list[PerpCandle] = []
    remaining = limit
    for _ in range(20):
        if remaining <= 0:
            break
        take = min(page_size, remaining)
        start = cursor_end - take * interval_ms
        payload = await _hl_post(
            client,
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": HL_INTERVAL[interval],
                    "startTime": start,
                    "endTime": cursor_end,
                },
            },
        )
        page = parse_hyperliquid_candles(payload)
        if not page:
            break
        collected.extend(page)
        oldest = min(c.ts_ms for c in page)
        if len(page) < take:
            break
        if oldest >= cursor_end:
            logger.warning("Hyperliquid candle pagination cursor did not advance for %s", coin)
            break
        cursor_end = oldest
        remaining = limit - len(_dedupe_sort(collected))
    return _dedupe_sort(collected)[:limit]


async def fetch_hyperliquid_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start_ms: int,
    end_ms: int | None = None,
) -> list[tuple[int, float]]:
    coin = to_hyperliquid_coin(symbol)
    body: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": int(start_ms)}
    if end_ms is not None:
        body["endTime"] = int(end_ms)
    payload = await _hl_post(client, body)
    events = parse_hyperliquid_funding(payload)
    if end_ms is None:
        return events
    return [(ts, rate) for ts, rate in events if ts <= end_ms]


async def fetch_perp_candles(
    venue: str,
    symbol: str,
    *,
    client: httpx.AsyncClient,
    interval: str = "1h",
    limit: int = 500,
) -> list[PerpCandle]:
    """Venue candles with funding accrued onto each interval. Never raises on HTTP/empty."""
    venue = venue.lower().strip()
    if venue not in SUPPORTED_FEEDS:
        raise ValueError(f"Unsupported feed venue {venue!r} (okx|hyperliquid)")
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval {interval!r}")
    if venue == "okx":
        candles = await fetch_okx_mark_candles(symbol, client=client, interval=interval, limit=limit)
        events = await fetch_okx_funding_history(symbol, client=client, limit=max(limit, 100))
        if not events:
            events = await fetch_okx_funding_current(symbol, client=client)
    else:
        candles = await fetch_hyperliquid_candles(symbol, client=client, interval=interval, limit=limit)
        if candles:
            start = candles[0].ts_ms - INTERVAL_MS[interval]
            end = candles[-1].ts_ms + INTERVAL_MS[interval]
            events = await fetch_hyperliquid_funding(symbol, client=client, start_ms=start, end_ms=end)
        else:
            events = []
    if not candles:
        return []
    return attach_funding(
        candles,
        events,
        interval_ms=INTERVAL_MS[interval],
        default_period_ms=FUNDING_PERIOD_MS[venue],
    )

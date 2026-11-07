"""
Public (unsigned) perp mid collector.

Binance USDT-M bookTicker + premiumIndex, OKX SWAP ticker + funding-rate,
Hyperliquid L2. No API keys, no orders. Quotes are top-of-book snapshots,
not firm liquidity.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.models.perp_arb import scan as perp_scan
from app.services.perp_feeds import (
    HYPERLIQUID_INFO,
    OKX_FUNDING,
    OKX_REST,
    OKX_TICKER,
    to_hyperliquid_coin,
    to_okx_inst_id,
)

logger = logging.getLogger(__name__)

BINANCE_FUTURES = "https://fapi.binance.com"

DEFAULT_FEES = {
    "binance_usdm": 4.0,
    "okx": 5.0,
    "hyperliquid": 3.5,
}


async def collect_quotes(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    notional: float = 10_000.0,
    binance_fee_bps: float = DEFAULT_FEES["binance_usdm"],
    okx_fee_bps: float = DEFAULT_FEES["okx"],
    hyperliquid_fee_bps: float = DEFAULT_FEES["hyperliquid"],
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    coin = to_hyperliquid_coin(symbol)
    inst = to_okx_inst_id(symbol)
    quotes: list[dict] = []
    errors: list[str] = []

    try:
        book = await client.get(
            f"{BINANCE_FUTURES}/fapi/v1/ticker/bookTicker",
            params={"symbol": symbol},
            timeout=8.0,
        )
        book.raise_for_status()
        b = book.json()
        prem = await client.get(
            f"{BINANCE_FUTURES}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=8.0,
        )
        prem.raise_for_status()
        p = prem.json()
        quotes.append({
            "venue": "binance_usdm",
            "bid": float(b["bidPrice"]),
            "ask": float(b["askPrice"]),
            "taker_fee_bps": binance_fee_bps,
            "funding_8h": float(p.get("lastFundingRate") or 0.0),
        })
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Binance USDM book failed for %s: %s", symbol, exc)
        errors.append(f"binance_usdm: {exc.__class__.__name__}")

    try:
        tick = await client.get(
            f"{OKX_REST}{OKX_TICKER}",
            params={"instId": inst},
            timeout=8.0,
        )
        tick.raise_for_status()
        payload = tick.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise ValueError("empty OKX ticker")
        row = rows[0]
        funding = 0.0
        try:
            fr = await client.get(
                f"{OKX_REST}{OKX_FUNDING}",
                params={"instId": inst},
                timeout=8.0,
            )
            fr.raise_for_status()
            fpayload = fr.json()
            frows = fpayload.get("data") if isinstance(fpayload, dict) else None
            if isinstance(frows, list) and frows and isinstance(frows[0], dict):
                funding = float(frows[0].get("fundingRate") or 0.0)
        except (httpx.HTTPError, ValueError, TypeError, IndexError, KeyError):
            funding = 0.0
        quotes.append({
            "venue": "okx",
            "bid": float(row["bidPx"]),
            "ask": float(row["askPx"]),
            "taker_fee_bps": okx_fee_bps,
            "funding_8h": funding,
        })
    except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError) as exc:
        logger.warning("OKX book failed for %s: %s", inst, exc)
        errors.append(f"okx: {exc.__class__.__name__}")

    try:
        hl = await client.post(
            HYPERLIQUID_INFO,
            json={"type": "l2Book", "coin": coin},
            timeout=8.0,
        )
        hl.raise_for_status()
        payload = hl.json()
        levels = payload.get("levels") or []
        bids = levels[0] if len(levels) > 0 else []
        asks = levels[1] if len(levels) > 1 else []
        if not bids or not asks:
            raise ValueError("empty Hyperliquid book")
        bid_px = float(bids[0]["px"] if isinstance(bids[0], dict) else bids[0][0])
        ask_px = float(asks[0]["px"] if isinstance(asks[0], dict) else asks[0][0])
        funding = 0.0
        try:
            ctx = await client.post(
                HYPERLIQUID_INFO,
                json={"type": "metaAndAssetCtxs"},
                timeout=8.0,
            )
            ctx.raise_for_status()
            meta, ctxs = ctx.json()
            universe = meta.get("universe") or []
            idx = next((i for i, u in enumerate(universe) if u.get("name") == coin), None)
            if idx is not None and idx < len(ctxs):
                funding = float(ctxs[idx].get("funding") or 0.0)
        except (httpx.HTTPError, ValueError, TypeError, IndexError, KeyError):
            funding = 0.0
        quotes.append({
            "venue": "hyperliquid",
            "bid": bid_px,
            "ask": ask_px,
            "taker_fee_bps": hyperliquid_fee_bps,
            "funding_8h": funding,
        })
    except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError) as exc:
        logger.warning("Hyperliquid book failed for %s: %s", coin, exc)
        errors.append(f"hyperliquid: {exc.__class__.__name__}")

    if len(quotes) < 2:
        raise ValueError("Need two live books; got: " + (", ".join(errors) if errors else "none"))

    result = perp_scan(quotes, notional)
    result["symbol"] = symbol
    result["errors"] = errors
    result["live_books"] = True
    result["what_broke"] = [
        "Top-of-book on a REST poll is stale before the next block / matching cycle.",
        "Hyperliquid funding is the latest 1h rate, not the predicted next funding.",
        "OKX fundingRate is the current 8h snapshot, not the path over the hold.",
        "Default taker fees are schedule snapshots, not your VIP tier.",
        "No depth: a $10k notional may walk the book on any venue.",
        "Unsigned public endpoints only — ATOM still does not place orders.",
    ] + result.get("what_broke", [])
    return result

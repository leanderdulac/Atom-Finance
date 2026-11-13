"""Warm Redis (or memory) with quotes, history and a local vol snapshot.

Runs as the 4h regime job's sibling: a loop from FastAPI lifespan or
`python -m app.services.client_worker`. Fetchers are the ones the app
already uses (brapi, yfinance, Binance public). Synthetic quotes are
never cached as a tradeable snapshot.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from app.core.cache import Cache
from app.core.compute import parallel_map
from app.models.ready_operation import UNIVERSE, MarketView, resolve_asset
from app.models.volatility import EWMAVolatility
from app.services.regime_job import last_snapshot, run_snapshot

logger = logging.getLogger(__name__)

CACHE_PREFIX = "client:arsenal:"
CACHE_TTL = int(os.getenv("ATOM_CLIENT_CACHE_TTL", "900"))


def job_enabled() -> bool:
    if os.getenv("ATOM_ENV") == "test":
        return False
    if os.getenv("ATOM_CLIENT_JOB", "").strip() == "1":
        return True
    return os.getenv("ATOM_CLIENT_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def job_interval_seconds() -> int:
    raw = os.getenv("ATOM_CLIENT_JOB_SECONDS", "300")
    try:
        return max(60, int(raw))
    except ValueError:
        return 300


def cache_key(asset_id: str) -> str:
    return f"{CACHE_PREFIX}{asset_id.upper()}"


def _history_from_yahoo(symbol: str) -> dict[str, Any] | None:
    from app.services.data_fetcher import DataFetcher

    frame = DataFetcher.get_historical_data(symbol, period="1y", interval="1d")
    if frame is None or frame.empty:
        return None
    closes = frame["Close"].astype(float).tolist() if "Close" in frame.columns else frame.iloc[:, 0].astype(float).tolist()
    if len(closes) < 60:
        return None
    dates = [idx.strftime("%Y-%m-%d") for idx in frame.index]
    return {"ticker": symbol, "close": closes, "dates": dates, "provider": "yfinance", "source": "yfinance"}


def _quote_live(asset: dict[str, Any]) -> dict[str, Any] | None:
    if asset["asset_class"] == "equity_br":
        from app.services.brapi_service import BrapiService
        quote = BrapiService.get_quote(asset["quote_symbol"])
        if quote and float(quote.get("price") or 0) > 0:
            return quote
    from app.services.data_fetcher import DataFetcher
    quote = DataFetcher.get_quote(asset["yahoo"], use_cache=True)
    if quote and float(quote.get("price") or 0) > 0:
        quote = {**quote, "provider": quote.get("provider") or "yfinance", "source": quote.get("source") or "yfinance"}
        return quote
    return None


def _history_live(asset: dict[str, Any]) -> dict[str, Any] | None:
    if asset["asset_class"] == "equity_br":
        from app.services.brapi_service import BrapiService
        hist = BrapiService.get_history(asset["quote_symbol"], days=252)
        if hist and len(hist.get("close") or []) >= 60 and hist.get("provider") != "synthetic":
            return hist
    return _history_from_yahoo(asset["yahoo"])


def _chain_live(asset: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    if "option" not in asset["instruments"]:
        return None, None
    from app.services.data_fetcher import DataFetcher
    raw = DataFetcher.get_options_chain(asset["yahoo"])
    if not raw:
        return None, None
    expiry = raw.get("expiry")
    rows: list[dict[str, Any]] = []
    for kind, records in (("call", raw.get("calls") or []), ("put", raw.get("puts") or [])):
        for rec in records:
            rows.append({
                "symbol": rec.get("contractSymbol") or rec.get("symbol"),
                "kind": kind,
                "strike": rec.get("strike"),
                "expiry": expiry,
                "exercise": "american",
                "bid": rec.get("bid") or 0,
                "ask": rec.get("ask") or 0,
                "bid_size": rec.get("bidSize") or rec.get("bid_size") or 0,
                "ask_size": rec.get("askSize") or rec.get("ask_size") or 0,
                "multiplier": 100,
                "lot_size": 1,
                "iv": rec.get("impliedVolatility") or rec.get("iv"),
            })
    return rows or None, "yfinance"


def warm_one(asset: dict[str, Any]) -> dict[str, Any]:
    """Fetch + cache one asset. Safe to call from a thread pool."""
    quote = _quote_live(asset)
    history = _history_live(asset)
    chain, chain_source = _chain_live(asset)
    vol = None
    if history and history.get("close"):
        import numpy as np
        closes = np.asarray(history["close"], dtype=float)
        if len(closes) >= 20 and np.all(closes > 0):
            rets = np.diff(np.log(closes))
            vol = EWMAVolatility.compute(rets)["current_vol"]
    snapshot = {
        "asset_id": asset["id"],
        "as_of": datetime.now(UTC).isoformat(),
        "quote": quote,
        "history": history,
        "chain": chain,
        "chain_source": chain_source,
        "ewma_vol": vol,
        "eligible_for_live_trading": False,
    }
    if quote and history:
        Cache.set(cache_key(asset["id"]), snapshot, ex=CACHE_TTL)
    return snapshot


def warm_universe() -> list[dict[str, Any]]:
    return parallel_map(warm_one, UNIVERSE, kind="thread")


def load_market(ticker: str) -> MarketView | None:
    asset = resolve_asset(ticker)
    if asset is None:
        return None
    cached = Cache.get(cache_key(asset["id"]))
    contributions: list[dict[str, Any]] = []
    if cached and cached.get("quote") and cached.get("history"):
        contributions.append({"part": "cache Redis/memória", "used": True, "note": f"snapshot {cached.get('as_of')}"})
        return MarketView(
            quote=cached["quote"],
            history=cached["history"],
            chain=cached.get("chain"),
            chain_source=cached.get("chain_source"),
            regime=last_snapshot(),
            contributions=contributions,
        )
    contributions.append({"part": "cache Redis/memória", "used": False, "note": "frio — buscando feeds agora"})
    snapshot = warm_one(asset)
    if not snapshot.get("quote") or not snapshot.get("history"):
        return None
    return MarketView(
        quote=snapshot["quote"],
        history=snapshot["history"],
        chain=snapshot.get("chain"),
        chain_source=snapshot.get("chain_source"),
        regime=last_snapshot(),
        contributions=contributions,
    )


def tick() -> dict[str, Any]:
    """One scheduler pass: optional regime snapshot + universe warm."""
    regime = None
    try:
        regime = run_snapshot()
    except Exception:
        logger.exception("Client arsenal: regime snapshot failed")
    warmed = []
    try:
        warmed = warm_universe()
    except Exception:
        logger.exception("Client arsenal: universe warm failed")
    ok = sum(1 for row in warmed if row.get("quote") and row.get("history"))
    return {
        "regime": (regime or {}).get("regime") if isinstance(regime, dict) else None,
        "warmed": ok,
        "universe": len(UNIVERSE),
        "as_of": datetime.now(UTC).isoformat(),
        "eligible_for_live_trading": False,
    }


async def loop() -> None:
    interval = job_interval_seconds()
    logger.info("Client arsenal job every %ss (workers via ATOM_COMPUTE_WORKERS / ATOM_IO_WORKERS)", interval)
    # Warm once at boot so the first client click is not a cold fetch.
    try:
        await asyncio.to_thread(tick)
    except Exception:
        logger.exception("Client arsenal boot tick failed")
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Client arsenal tick failed")

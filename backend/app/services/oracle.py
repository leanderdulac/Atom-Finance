"""Unified price oracle: one quote per symbol from many providers, honestly.

Each provider keeps its own fetcher (brapi, yfinance, Binance, Tradier).
This module only routes, timestamps, arbitrates and reports:

- routing: B3 (.SA / XXXX9) → brapi + yfinance; crypto (BTC/ETH/SOL,
  *USDT) → binance + hyperliquid + yfinance; anything else → yfinance
  + tradier (US).
- freshness: a quote is fresh when its *source* timestamp is younger than
  the class threshold. Providers without a source timestamp (brapi,
  Binance spot) have unknown age: usable for display, excluded from
  arbitration unless they are the only source — and then flagged.
- arbitration: median of the fresh lasts. Disagreement above 50 bps across
  fresh sources is reported, not hidden. No synthetic fallback, ever:
  when every provider fails the oracle says so (usable=false + blockers).
- diary: every fetch outcome (ok/error/latency) is recorded for /heartbeat.

All network seams are module-level functions so tests patch them instead
of touching providers.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import UTC, datetime
from statistics import median
from typing import Any

from app.core.cache import Cache
from app.services.market_sources import SourceError

logger = logging.getLogger(__name__)

# Freshness thresholds (seconds) on the SOURCE timestamp, not fetch time.
STALE_AFTER = {"crypto": 30.0, "equity_br": 300.0, "equity_us": 300.0}
DISAGREE_BPS = 50.0
DIARY_KEY = "atom:oracle:diary"
DIARY_MAX = 50
DIARY_TTL = 3600

_B3_RE = re.compile(r"^[A-Z]{4}\d{1,2}$")
_YF_RE = re.compile(r"^[A-Z][A-Z0-9.\-=^]{0,24}$")
_TRADIER_RE = re.compile(r"^[A-Z]{1,6}$")
CRYPTO_SPOT = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def classify(symbol: str) -> str:
    """Route a user symbol to an asset class. Raises SourceError(422) when malformed."""
    sym = (symbol or "").strip().upper()
    if not sym or len(sym) > 25:
        raise SourceError(422, "Símbolo vazio ou longo demais.")
    base = sym[:-4] if sym.endswith("-USD") else sym[:-4] if sym.endswith("USDT") else sym
    if base in CRYPTO_SPOT or re.fullmatch(r"[A-Z]{2,10}", base) and (
            sym.endswith("-USD") or sym.endswith("USDT")):
        return "crypto"
    if sym.endswith(".SA") or _B3_RE.fullmatch(sym):
        return "equity_br"
    if _YF_RE.fullmatch(sym):
        return "equity_us"
    raise SourceError(422, "Símbolo inválido.")


def _age_seconds(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return (now - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return None


def _record(provider: str, ok: bool, latency_ms: float, detail: str = "") -> None:
    try:
        rows = Cache.get(DIARY_KEY)
        if not isinstance(rows, list):
            rows = []
        rows.insert(0, {
            "provider": provider, "ok": ok, "latency_ms": round(latency_ms, 1),
            "at": datetime.now(UTC).isoformat(), "detail": detail[:120],
        })
        Cache.set(DIARY_KEY, rows[:DIARY_MAX], ex=DIARY_TTL)
    except Exception:
        logger.debug("oracle diary write failed", exc_info=True)


# ── Provider seams (patched in tests) ────────────────────────────────────

async def _fetch_yfinance(symbol: str, owner: str) -> dict[str, Any]:
    from app.services.live_quotes import quote
    out = await quote("yfinance", symbol, owner)
    q = out["quote"]
    return {
        "price": q["last"], "bid": q["bid"], "ask": q["ask"],
        "ts": q["last_timestamp"], "data_mode": out["data_mode"],
        "currency": q.get("currency"),
    }


async def _fetch_tradier(symbol: str, owner: str) -> dict[str, Any]:
    from app.services.live_quotes import quote
    out = await quote("tradier", symbol, owner)
    q = out["quote"]
    return {
        "price": q["last"], "bid": q["bid"], "ask": q["ask"],
        "ts": q["last_timestamp"], "data_mode": out["data_mode"],
        "currency": q.get("currency"),
    }


async def _fetch_brapi(ticker: str) -> dict[str, Any]:
    from app.services.brapi_service import BrapiService
    row = await asyncio.to_thread(BrapiService.get_quote, ticker)
    if not row or not row.get("price"):
        raise SourceError(502, "Brapi sem cotação utilizável.")
    return {"price": float(row["price"]), "bid": None, "ask": None,
            "ts": None, "data_mode": "unverified", "currency": row.get("currency", "BRL")}


async def _fetch_hyperliquid(base: str) -> dict[str, Any]:
    import httpx

    from app.services.perp_feeds import fetch_hyperliquid_book
    async with httpx.AsyncClient(timeout=10) as client:
        book = await fetch_hyperliquid_book(base, client=client)
    if not book or book.get("time_ms") is None:
        raise SourceError(502, "Hyperliquid sem livro utilizável.")
    ts = datetime.fromtimestamp(book["time_ms"] / 1000, tz=UTC).isoformat()
    return {"price": (book["bid"] + book["ask"]) / 2.0, "bid": book["bid"],
            "ask": book["ask"], "ts": ts, "data_mode": "realtime", "currency": "USD"}


async def _fetch_binance(symbol: str) -> dict[str, Any]:
    from app.services.binance_service import BinanceService
    row = await BinanceService.get_ticker_price(symbol)
    if not row or not row.get("price"):
        raise SourceError(502, "Binance sem cotação utilizável.")
    return {"price": float(row["price"]), "bid": None, "ask": None,
            "ts": None, "data_mode": "unverified", "currency": "USDT"}


def _yf_ticker(symbol: str):  # seam for chain tests
    import yfinance as yf
    return yf.Ticker(symbol)


# ── Spot ─────────────────────────────────────────────────────────────────

async def spot(symbol: str, owner: str = "") -> dict[str, Any]:
    """Arbitrated spot quote. Never invents: absence is reported, not filled."""
    asset_class = classify(symbol)
    sym = symbol.strip().upper()
    now = datetime.now(UTC)
    threshold = STALE_AFTER[asset_class]

    if asset_class == "crypto":
        base = sym[:-4] if sym.endswith("-USD") else sym[:-4] if sym.endswith("USDT") else sym
        jobs = [
            ("binance", _fetch_binance(f"{base}USDT")),
            ("hyperliquid", _fetch_hyperliquid(base)),
            ("yfinance", _fetch_yfinance(f"{base}-USD", owner)),
        ]
    elif asset_class == "equity_br":
        jobs = [
            ("brapi", _fetch_brapi(sym[:-3] if sym.endswith(".SA") else sym)),
            ("yfinance", _fetch_yfinance(sym if sym.endswith(".SA") else f"{sym}.SA", owner)),
        ]
    else:
        jobs = [("yfinance", _fetch_yfinance(sym, owner))]
        if os.getenv("TRADIER_ACCESS_TOKEN", "").strip() and _TRADIER_RE.fullmatch(sym):
            jobs.append(("tradier", _fetch_tradier(sym, owner)))

    sources: list[dict[str, Any]] = []
    for provider, coro in jobs:
        started = time.monotonic()
        try:
            row = await coro
            latency = (time.monotonic() - started) * 1000
            _record(provider, True, latency)
        except SourceError as exc:
            _record(provider, False, (time.monotonic() - started) * 1000, exc.message)
            sources.append({"provider": provider, "ok": False, "error": exc.message,
                            "status": exc.status})
            continue
        except Exception as exc:  # never let one provider kill the oracle
            _record(provider, False, (time.monotonic() - started) * 1000, type(exc).__name__)
            sources.append({"provider": provider, "ok": False, "error": "Falha inesperada no provedor."})
            continue
        price = row.get("price")
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        if price_f is None or price_f <= 0 or price_f != price_f:  # NaN guard
            sources.append({"provider": provider, "ok": False, "error": "Preço inválido."})
            continue
        age = _age_seconds(row.get("ts"), now)
        stale = age is not None and (age > threshold or age < -60)
        sources.append({
            "provider": provider, "ok": True, "price": price_f,
            "bid": row.get("bid"), "ask": row.get("ask"),
            "ts": row.get("ts"), "age_s": None if age is None else round(age, 1),
            "age_unknown": age is None, "stale": stale,
            "data_mode": row.get("data_mode", "unverified"),
            "currency": row.get("currency"),
        })

    ok_rows = [s for s in sources if s.get("ok")]
    fresh = [s for s in ok_rows if not s["stale"] and not s["age_unknown"]]
    unknown = [s for s in ok_rows if not s["stale"] and s["age_unknown"]]
    blockers: list[str] = []
    for s in sources:
        if not s.get("ok"):
            blockers.append(f"{s['provider']}: {s.get('error')}")
        elif s["stale"]:
            blockers.append(f"{s['provider']}: cotação velha ({s['age_s']}s > {threshold:g}s).")

    pool = fresh or unknown
    if not pool:
        return {"symbol": sym, "asset_class": asset_class, "usable": False,
                "price": None, "method": "none", "sources": sources,
                "disagreement_bps": None, "stale": [s["provider"] for s in ok_rows if s["stale"]],
                "blockers": blockers or ["Nenhum provedor respondeu."],
                "fetched_at": now.isoformat(), "eligible_for_live_trading": False}
    lasts = sorted(s["price"] for s in pool)
    mid = float(median(lasts))
    spread_bps = round((lasts[-1] - lasts[0]) / mid * 1e4, 1) if len(lasts) > 1 else 0.0
    if not fresh:
        blockers.append("Idade desconhecida em todas as fontes — preço só para exibição.")
    elif spread_bps > DISAGREE_BPS:
        blockers.append(f"Fontes divergem {spread_bps} bps — arbitrar com desconfiança.")
    return {"symbol": sym, "asset_class": asset_class, "usable": True,
            "price": round(mid, 6), "method": "median_fresh" if fresh else "sole_unknown_age",
            "sources": sources, "disagreement_bps": spread_bps,
            "stale": [s["provider"] for s in ok_rows if s["stale"]],
            "blockers": blockers, "fetched_at": now.isoformat(),
            "eligible_for_live_trading": False}


# ── Heartbeat ────────────────────────────────────────────────────────────

def heartbeat() -> dict[str, Any]:
    """Provider health from the fetch diary + configured flags. No probing."""
    rows = Cache.get(DIARY_KEY)
    diary = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    diary = diary[:DIARY_MAX]
    seen: dict[str, dict[str, Any]] = {}
    for row in diary:
        provider = str(row.get("provider", "?"))
        if provider not in seen:
            seen[provider] = {"last_ok": bool(row.get("ok")),
                              "last_latency_ms": row.get("latency_ms"),
                              "last_at": row.get("at"),
                              "last_detail": row.get("detail", "")}
    return {"configured": {
                "brapi": bool(os.getenv("BRAPI_TOKEN", "").strip()),
                "tradier": bool(os.getenv("TRADIER_ACCESS_TOKEN", "").strip()),
                "yfinance": True, "binance": True},
            "providers": seen, "diary": diary,
            "fetched_at": datetime.now(UTC).isoformat()}


# ── US options chains (multi-expiry, yfinance) ───────────────────────────

async def chain_us(ticker: str, expiries: list[str] | None = None,
                   max_expiries: int = 4) -> dict[str, Any]:
    """Normalized multi-expiry US chain for Heston calibration.

    Returns DataFetcher-shaped chains ([{expiry, calls, puts}]) plus S0, or
    raises SourceError when the chain is unusable. Expiries beyond
    max_expiries are ignored, never silently half-fetched.
    """
    sym = (ticker or "").strip().upper()
    if not _YF_RE.fullmatch(sym) or sym.endswith(".SA"):
        raise SourceError(422, "Cadeia US: ticker sem .SA (ex.: AAPL).")
    if expiries is not None and (not expiries or len(expiries) > max_expiries):
        raise SourceError(422, f"Escolha de 1 a {max_expiries} vencimentos.")

    def _load() -> dict[str, Any]:
        t = _yf_ticker(sym)
        available = list(getattr(t, "options", []) or [])
        if not available:
            raise SourceError(502, "Sem vencimentos de opções para este ticker.")
        wanted = [e for e in (expiries or []) if e in available]
        if expiries and not wanted:
            raise SourceError(422, f"Vencimentos disponíveis: {', '.join(available[:8])}.")
        picked = wanted or available[:max_expiries]
        chains = []
        for exp in picked:
            oc = t.option_chain(exp)
            calls = oc.calls.to_dict("records") if getattr(oc.calls, "empty", True) is False else []
            puts = oc.puts.to_dict("records") if getattr(oc.puts, "empty", True) is False else []
            chains.append({"symbol": sym, "expiry": exp, "calls": calls, "puts": puts,
                           "available_expirations": available[:10]})
        try:
            spot_px = float(t.fast_info["last_price"])
        except Exception:
            spot_px = 0.0
        return {"chains": chains, "expirations": picked, "available": available[:10],
                "S0": spot_px, "provider": "yfinance"}

    started = time.monotonic()
    try:
        out = await asyncio.to_thread(_load)
        _record("yfinance-chain", True, (time.monotonic() - started) * 1000)
    except SourceError as exc:
        _record("yfinance-chain", False, (time.monotonic() - started) * 1000, exc.message)
        raise
    if out["S0"] <= 0:
        raise SourceError(502, "Spot indisponível para calibrar a cadeia.")
    if sum(len(c["calls"]) + len(c["puts"]) for c in out["chains"]) < 4:
        raise SourceError(502, "Cadeia com contratos demais poucos para calibrar.")
    out["fetched_at"] = datetime.now(UTC).isoformat()
    out["eligible_for_live_trading"] = False
    return out

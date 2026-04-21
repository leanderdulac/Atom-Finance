"""
brapi.dev — Brazilian market data (B3) service.
Docs: https://brapi.dev/docs
Token: set BRAPI_TOKEN in .env (free tier: 15 req/min)
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

import requests

from app.core.cache import Cache

logger = logging.getLogger(__name__)

_BASE = "https://brapi.dev/api"
_CACHE_TTL = 60  # seconds


def _token() -> str:
    return os.getenv("BRAPI_TOKEN", "")


def _headers() -> dict:
    tok = _token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _is_br_ticker(ticker: str) -> bool:
    """Heuristic: Brazilian tickers are 4 letters + 1-2 digits (e.g. PETR4, VALE3, ITUB4F)."""
    t = ticker.upper().rstrip("F")   # strip fractional share suffix
    return len(t) >= 5 and t[:4].isalpha() and t[4:].isdigit()


class BrapiService:
    # ── Quote ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_quote(ticker: str) -> Optional[dict]:
        key = f"brapi:quote:{ticker.upper()}"
        cached = Cache.get(key)
        if cached:
            return cached

        try:
            url = f"{_BASE}/quote/{ticker.upper()}"
            params = {"token": _token()} if _token() else {}
            r = requests.get(url, params=params, headers=_headers(), timeout=8)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return None
            d = results[0]
            quote = {
                "ticker": d.get("symbol", ticker.upper()),
                "price": float(d.get("regularMarketPrice") or 0),
                "change": float(d.get("regularMarketChange") or 0),
                "change_pct": float(d.get("regularMarketChangePercent") or 0),
                "volume": int(d.get("regularMarketVolume") or 0),
                "high": float(d.get("regularMarketDayHigh") or 0),
                "low": float(d.get("regularMarketDayLow") or 0),
                "market_cap": float(d.get("marketCap") or 0),
                "name": d.get("longName") or d.get("shortName") or ticker.upper(),
                "currency": d.get("currency", "BRL"),
                "exchange": d.get("exchange", "BVMF"),
                "provider": "brapi",
                "source": "brapi",
            }
            Cache.set(key, quote, ex=_CACHE_TTL)
            return quote
        except Exception as exc:
            logger.warning("brapi quote %s failed: %s", ticker, exc)
            return None

    @staticmethod
    def get_quotes_batch(tickers: list[str]) -> dict[str, dict]:
        """Fetch multiple quotes in one HTTP call (batch mode)."""
        if not tickers:
            return {}
            
        key = f"brapi:batch:{','.join(sorted(tickers))}"
        cached = Cache.get(key)
        if cached:
            return cached

        try:
            # Brapi supports comma-separated tickers: /quote/PETR4,VALE3,ITUB4
            ticker_str = ",".join([t.upper() for t in tickers])
            url = f"{_BASE}/quote/{ticker_str}"
            params = {"token": _token()} if _token() else {}
            
            logger.info("Fetching brapi batch: %s", ticker_str)
            r = requests.get(url, params=params, headers=_headers(), timeout=15)
            r.raise_for_status()
            
            results = r.json().get("results", [])
            quotes = {}
            for d in results:
                symbol = d.get("symbol", "").upper()
                if not symbol: continue
                
                quotes[symbol] = {
                    "ticker": symbol,
                    "price": float(d.get("regularMarketPrice") or 0),
                    "change": float(d.get("regularMarketChange") or 0),
                    "change_pct": float(d.get("regularMarketChangePercent") or 0),
                    "volume": int(d.get("regularMarketVolume") or 0),
                    "high": float(d.get("regularMarketDayHigh") or 0),
                    "low": float(d.get("regularMarketDayLow") or 0),
                    "market_cap": float(d.get("marketCap") or 0),
                    "name": d.get("longName") or d.get("shortName") or symbol,
                    "currency": d.get("currency", "BRL"),
                    "provider": "brapi",
                    "source": "brapi",
                }
            
            if quotes:
                Cache.set(key, quotes, ex=_CACHE_TTL)
            return quotes
        except Exception as exc:
            logger.error("brapi batch quote failed for %s: %s", tickers, exc)
            return {}

    # ── Historical data ───────────────────────────────────────────────────────

    @staticmethod
    def get_history(ticker: str, days: int = 252) -> Optional[dict]:
        key = f"brapi:history:{ticker.upper()}:{days}"
        cached = Cache.get(key)
        if cached:
            return cached

        try:
            # brapi range param: 1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max
            range_map = {
                5: "5d", 22: "1mo", 66: "3mo", 126: "6mo",
                252: "1y", 504: "2y",
            }
            rng = min(range_map, key=lambda k: abs(k - days))
            brapi_range = range_map[rng]

            url = f"{_BASE}/quote/{ticker.upper()}"
            params = {
                "range": brapi_range,
                "interval": "1d",
                "token": _token(),
            }
            r = requests.get(url, params=params, headers=_headers(), timeout=12)
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return None

            hist = results[0].get("historicalDataPrice", [])
            if not hist:
                return None

            dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
            for bar in sorted(hist, key=lambda b: b.get("date", 0)):
                epoch = bar.get("date")
                if epoch:
                    dates.append(date.fromtimestamp(epoch).strftime("%Y-%m-%d"))
                    opens.append(round(float(bar.get("open") or 0), 2))
                    highs.append(round(float(bar.get("high") or 0), 2))
                    lows.append(round(float(bar.get("low") or 0), 2))
                    closes.append(round(float(bar.get("close") or 0), 2))
                    volumes.append(int(bar.get("volume") or 0))

            if not closes:
                return None

            result = {
                "ticker": ticker.upper(),
                "dates": dates,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
                "currency": results[0].get("currency", "BRL"),
                "provider": "brapi",
                "source": "brapi",
            }
            Cache.set(key, result, ex=300)  # 5 min TTL for history
            return result
        except Exception as exc:
            logger.warning("brapi history %s failed: %s", ticker, exc)
            return None

    # ── Tickers list (B3) ─────────────────────────────────────────────────────

    @staticmethod
    def list_tickers() -> list[str]:
        key = "brapi:tickers"
        cached = Cache.get(key)
        if cached:
            return cached
        try:
            url = f"{_BASE}/quote/list"
            params = {"token": _token()}
            r = requests.get(url, params=params, headers=_headers(), timeout=10)
            r.raise_for_status()
            stocks = r.json().get("stocks", [])
            tickers = [s["stock"] for s in stocks if s.get("stock")]
            Cache.set(key, tickers, ex=3600)  # 1h TTL
            return tickers
        except Exception as exc:
            logger.warning("brapi list_tickers failed: %s", exc)
            return []

    # ── Inflation / macro (IPCA, SELIC) ──────────────────────────────────────

    @staticmethod
    def get_inflation() -> Optional[dict]:
        key = "brapi:inflation"
        cached = Cache.get(key)
        if cached:
            return cached
        try:
            url = f"{_BASE}/v2/inflation"
            params = {"country": "brazil", "token": _token()}
            r = requests.get(url, params=params, headers=_headers(), timeout=8)
            r.raise_for_status()
            data = r.json()
            Cache.set(key, data, ex=3600)
            return data
        except Exception as exc:
            logger.warning("brapi inflation failed: %s", exc)
            return None

    @staticmethod
    def get_prime_rate() -> Optional[dict]:
        """SELIC and CDI rates."""
        key = "brapi:prime"
        cached = Cache.get(key)
        if cached:
            return cached
        try:
            url = f"{_BASE}/v2/prime-rate"
            params = {"country": "brazil", "token": _token()}
            r = requests.get(url, params=params, headers=_headers(), timeout=8)
            r.raise_for_status()
            data = r.json()
            Cache.set(key, data, ex=3600)
            return data
        except Exception as exc:
            logger.warning("brapi prime-rate failed: %s", exc)
            return None

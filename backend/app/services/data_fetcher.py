"""Data Fetching Service — Yahoo Finance with Redis/in-memory caching."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.core.cache import Cache

logger = logging.getLogger(__name__)

CACHE_TTL = int(60)  # seconds

# Lazy-loaded yfinance
_yfinance = None


def _get_yfinance():
    global _yfinance
    if _yfinance is None:
        try:
            import yfinance as yf
            _yfinance = yf
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
    return _yfinance


class DataFetcher:
    """Fetch real market data from Yahoo Finance."""

    # ── Quote ─────────────────────────────────────────────────────────────────

    @classmethod
    def get_quote(cls, symbol: str, use_cache: bool = True) -> Optional[Dict]:
        symbol = symbol.upper()
        cache_key = f"quote:{symbol}"

        if use_cache:
            cached = Cache.get(cache_key)
            if cached is not None:
                return cached

        yf = _get_yfinance()
        if not yf:
            return None

        try:
            data = yf.Ticker(symbol).info
            quote = {
                "ticker": symbol,
                "price": data.get("currentPrice") or data.get("regularMarketPrice", 0),
                "change": data.get("regularMarketChange", 0),
                "change_pct": data.get("regularMarketChangePercent", 0),
                "volume": data.get("volume", 0),
                "high": data.get("regularMarketDayHigh", 0),
                "low": data.get("regularMarketDayLow", 0),
                "open": data.get("regularMarketOpen", 0),
                "bid": data.get("bid", 0),
                "ask": data.get("ask", 0),
                "bid_size": data.get("bidSize", 0),
                "ask_size": data.get("askSize", 0),
                "market_cap": data.get("marketCap", 0),
                "pe_ratio": data.get("trailingPE", 0),
                "dividend_yield": data.get("dividendYield", 0),
                "fifty_two_week_high": data.get("fiftyTwoWeekHigh", 0),
                "fifty_two_week_low": data.get("fiftyTwoWeekLow", 0),
                "timestamp": datetime.now().isoformat(),
            }
            Cache.set(cache_key, quote, ex=CACHE_TTL)
            return quote
        except Exception as exc:
            logger.error("Error fetching quote for %s: %s", symbol, exc)
            return None

    # ── Historical ────────────────────────────────────────────────────────────

    @classmethod
    def get_historical_data(
        cls,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        yf = _get_yfinance()
        if not yf:
            return None
        try:
            return yf.Ticker(symbol).history(period=period, interval=interval)
        except Exception as exc:
            logger.error("Error fetching historical data for %s: %s", symbol, exc)
            return None

    # ── Options Chain ─────────────────────────────────────────────────────────

    @classmethod
    def get_options_chain(cls, symbol: str, expiry_date: Optional[str] = None) -> Optional[Dict]:
        yf = _get_yfinance()
        if not yf:
            return None
        try:
            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                return None
            exp = expiry_date if expiry_date in expirations else expirations[0]
            chain = ticker.option_chain(exp)
            return {
                "symbol": symbol.upper(),
                "expiry": exp,
                "calls": chain.calls.to_dict("records") if not chain.calls.empty else [],
                "puts": chain.puts.to_dict("records") if not chain.puts.empty else [],
                "available_expirations": list(expirations[:10]),
            }
        except Exception as exc:
            logger.error("Error fetching options chain for %s: %s", symbol, exc)
            return None

    # ── Volatility ────────────────────────────────────────────────────────────

    @classmethod
    def get_volatility_data(cls, symbol: str) -> Optional[Dict]:
        try:
            chain = cls.get_options_chain(symbol)
            if not chain or not chain["calls"]:
                return None
            calls = pd.DataFrame(chain["calls"])
            puts = pd.DataFrame(chain["puts"])
            if calls.empty or puts.empty:
                return None
            atm_calls = calls[calls["inTheMoney"] == False].head(5)
            atm_puts = puts[puts["inTheMoney"] == False].head(5)
            avg_iv_calls = atm_calls["impliedVolatility"].mean() if not atm_calls.empty else 0.0
            avg_iv_puts = atm_puts["impliedVolatility"].mean() if not atm_puts.empty else 0.0
            return {
                "symbol": symbol.upper(),
                "iv_call": float(avg_iv_calls),
                "iv_put": float(avg_iv_puts),
                "iv_avg": float((avg_iv_calls + avg_iv_puts) / 2),
                "volatility_skew": float(avg_iv_puts - avg_iv_calls),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Error calculating volatility for %s: %s", symbol, exc)
            return None

    # ── Multiple Quotes (concurrent) ──────────────────────────────────────────

    @classmethod
    async def get_multiple_quotes_async(cls, symbols: List[str]) -> Dict[str, Optional[Dict]]:
        """Fetch multiple quotes concurrently using a thread pool."""
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, cls.get_quote, symbol)
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            symbol: (result if not isinstance(result, Exception) else None)
            for symbol, result in zip(symbols, results)
        }

    @classmethod
    def get_multiple_quotes(cls, symbols: List[str]) -> Dict[str, Optional[Dict]]:
        """Sync wrapper — use get_multiple_quotes_async in async contexts."""
        return {symbol: cls.get_quote(symbol) for symbol in symbols}

    # ── Returns ───────────────────────────────────────────────────────────────

    @classmethod
    def calculate_returns(cls, symbol: str, period: str = "1y") -> Optional[Dict]:
        try:
            df = cls.get_historical_data(symbol, period=period)
            if df is None or df.empty:
                return None
            df["returns"] = df["Close"].pct_change()
            return {
                "symbol": symbol.upper(),
                "period": period,
                "total_return": float((df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100),
                "annual_return": float(df["returns"].mean() * 252 * 100),
                "annual_volatility": float(df["returns"].std() * np.sqrt(252) * 100),
                "sharpe_ratio": float(
                    (df["returns"].mean() * 252) / (df["returns"].std() * np.sqrt(252))
                ),
                "max_drawdown": float(
                    ((df["Close"].cummax() - df["Close"]) / df["Close"].cummax()).max() * 100
                ),
            }
        except Exception as exc:
            logger.error("Error calculating returns for %s: %s", symbol, exc)
            return None

    # ── Cache management ──────────────────────────────────────────────────────

    @classmethod
    def clear_cache(cls) -> None:
        from app.core.cache import _MemStore
        _MemStore.clear()

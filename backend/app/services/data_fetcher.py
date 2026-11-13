"""Data Fetching Service — Yahoo Finance with Redis/in-memory caching."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from app.core.cache import Cache

logger = logging.getLogger(__name__)

CACHE_TTL = 60  # seconds

# Lazy-loaded yfinance
_yfinance = None

# yfinance logs ERROR/WARNING on empty history ("possibly delisted; no price
# data found") for every call. One warning per ticker from this module is enough.
_MISSING_DATA_WARNED: set[str] = set()


class _YFinanceEmptyDataFilter(logging.Filter):
    _FRAGMENTS = ("possibly delisted", "no price data found", "no timezone found")

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("yfinance"):
            return True
        msg = record.getMessage().lower()
        return not any(fragment in msg for fragment in self._FRAGMENTS)


def _silence_yfinance_empty_data_logs() -> None:
    filt = _YFinanceEmptyDataFilter()
    yf_logger = logging.getLogger("yfinance")
    if not any(isinstance(existing, _YFinanceEmptyDataFilter) for existing in yf_logger.filters):
        yf_logger.addFilter(filt)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(existing, _YFinanceEmptyDataFilter) for existing in handler.filters):
            handler.addFilter(filt)


def _warn_missing_data_once(symbol: str, detail: str) -> None:
    key = symbol.upper()
    if key in _MISSING_DATA_WARNED:
        return
    _MISSING_DATA_WARNED.add(key)
    logger.warning(
        "Skipping %s: no market data (%s). Further empty results for this ticker will be silent.",
        key,
        detail,
    )


def _get_yfinance():
    global _yfinance
    if _yfinance is None:
        try:
            import yfinance as yf
            _silence_yfinance_empty_data_logs()
            _yfinance = yf
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
    return _yfinance


class DataFetcher:
    """Fetch real market data from Yahoo Finance."""

    # ── Quote ─────────────────────────────────────────────────────────────────

    @classmethod
    def get_quote(cls, symbol: str, use_cache: bool = True) -> dict | None:
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
            price = data.get("currentPrice") or data.get("regularMarketPrice", 0)
            if not price:
                _warn_missing_data_once(symbol, "no price in quote")
                return None
            quote = {
                "ticker": symbol,
                "price": price,
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
            _warn_missing_data_once(symbol, f"quote error: {type(exc).__name__}")
            return None

    # ── Historical ────────────────────────────────────────────────────────────

    @classmethod
    def get_historical_data(
        cls,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame | None:
        yf = _get_yfinance()
        if not yf:
            return None
        try:
            frame = yf.Ticker(symbol).history(period=period, interval=interval)
        except Exception:
            _warn_missing_data_once(symbol, "history error")
            return None
        if frame is None or frame.empty:
            _warn_missing_data_once(symbol, "empty history")
            return None
        return frame

    # ── Options Chain ─────────────────────────────────────────────────────────

    @classmethod
    def get_options_chain(cls, symbol: str, expiry_date: str | None = None) -> dict | None:
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
    def get_volatility_data(cls, symbol: str) -> dict | None:
        try:
            chain = cls.get_options_chain(symbol)
            if not chain or not chain["calls"]:
                return None
            calls = pd.DataFrame(chain["calls"])
            puts = pd.DataFrame(chain["puts"])
            if calls.empty or puts.empty:
                return None
            atm_calls = calls[~calls["inTheMoney"]].head(5)
            atm_puts = puts[~puts["inTheMoney"]].head(5)
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
    async def get_multiple_quotes_async(cls, symbols: list[str]) -> dict[str, dict | None]:
        """Fetch multiple quotes concurrently using a thread pool."""
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, cls.get_quote, symbol)
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            # BaseException, not Exception: gather(return_exceptions=True) can
            # surface asyncio.CancelledError, which is a BaseException and
            # would otherwise leak through as if it were a valid quote dict.
            symbol: (result if not isinstance(result, BaseException) else None)
            for symbol, result in zip(symbols, results, strict=False)
        }

    @classmethod
    def get_multiple_quotes(cls, symbols: list[str]) -> dict[str, dict | None]:
        """Sync wrapper — use get_multiple_quotes_async in async contexts."""
        return {symbol: cls.get_quote(symbol) for symbol in symbols}

    # ── Returns ───────────────────────────────────────────────────────────────

    @classmethod
    def calculate_returns(cls, symbol: str, period: str = "1y") -> dict | None:
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

"""Market Data API with OpenBB, Yahoo Finance and synthetic fallbacks."""

from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query, Request
from app.core.limiter import limiter

from app.models.pricing import BlackScholes
from app.services.brapi_service import BrapiService, _is_br_ticker
from app.services.data_fetcher import DataFetcher
from app.services.openbb_service import OpenBBService

router = APIRouter()

# Market data endpoints hit external APIs — limit to 30 req/min per IP.
# (Using shared limiter from app.core.limiter)

ProviderName = Literal["auto", "openbb", "openbb_yfinance", "openbb_cboe", "yfinance", "brapi", "synthetic"]

# Approximate prices as of early 2026 — used only as synthetic base values.
_SYNTHETIC_BASE_PRICES: dict[str, float] = {
    "AAPL": 225,
    "GOOGL": 185,
    "MSFT": 415,
    "AMZN": 225,
    "TSLA": 285,
    "SPY": 540,
    "QQQ": 480,
    "BTC-USD": 85000,
    "ETH-USD": 3200,
}


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase all column names to handle OpenBB/yfinance naming differences."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    return df


def _generate_synthetic_prices(ticker: str, days: int = 252) -> dict:
    """Generate synthetic OHLCV data for demo purposes."""
    np.random.seed(hash(ticker) % 2**31)
    base = _SYNTHETIC_BASE_PRICES.get(ticker.upper(), 100.0)

    returns = np.random.normal(0.0004, 0.018, days)
    prices = base * np.cumprod(1 + returns)
    volumes = np.random.lognormal(15, 0.5, days).astype(int)

    dates: list[str] = []
    start = date.today()
    for i in range(days):
        d = start - timedelta(days=days - i)
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))

    n = len(dates)
    prices = prices[:n]
    volumes = volumes[:n]
    highs = prices * (1 + np.abs(np.random.normal(0, 0.01, n)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.01, n)))

    return {
        "ticker": ticker.upper(),
        "dates": dates,
        "open": [round(float(p * (1 + np.random.normal(0, 0.002))), 2) for p in prices],
        "high": [round(float(h), 2) for h in highs],
        "low": [round(float(l), 2) for l in lows],
        "close": [round(float(p), 2) for p in prices],
        "volume": [int(v) for v in volumes],
        "returns": [round(float(r), 6) for r in np.diff(np.log(prices))],
        "provider": "synthetic",
        "source": "synthetic",
    }


def _synthetic_quote(ticker: str) -> dict:
    data = _generate_synthetic_prices(ticker, 5)
    return {
        "ticker": ticker.upper(),
        "price": data["close"][-1],
        "change": round(data["close"][-1] - data["close"][-2], 2),
        "change_pct": round((data["close"][-1] / data["close"][-2] - 1) * 100, 2),
        "volume": data["volume"][-1],
        "high": data["high"][-1],
        "low": data["low"][-1],
        "provider": "synthetic",
        "source": "synthetic",
    }


def _quote_from_yfinance(ticker: str) -> dict | None:
    quote = DataFetcher.get_quote(ticker, use_cache=True)
    if quote:
        quote["provider"] = "yfinance"
        quote.setdefault("source", "yfinance")
    return quote


def _history_from_yfinance(ticker: str, days: int, period: str) -> dict | None:
    period_map = {7: "5d", 30: "1mo", 90: "3mo", 252: "1y", 504: "2y"}
    yf_period = period_map.get(days, period)
    df = DataFetcher.get_historical_data(ticker, period=yf_period, interval="1d")
    if df is None or df.empty:
        return None
    # yfinance returns capitalised columns (Open, High, Low, Close, Volume)
    df = _normalise_df_columns(df)
    return {
        "ticker": ticker.upper(),
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": [round(float(v), 2) for v in df["open"].values],
        "high": [round(float(v), 2) for v in df["high"].values],
        "low": [round(float(v), 2) for v in df["low"].values],
        "close": [round(float(v), 2) for v in df["close"].values],
        "volume": [int(v) for v in df["volume"].values],
        "provider": "yfinance",
        "source": "yfinance",
    }


def _options_from_yfinance(ticker: str) -> dict | None:
    chain = DataFetcher.get_options_chain(ticker)
    if not chain or not chain.get("calls"):
        return None

    calls_df = pd.DataFrame(chain["calls"])
    puts_df = pd.DataFrame(chain["puts"])
    if calls_df.empty:
        return None
    if puts_df.empty:
        puts_df = pd.DataFrame(columns=["strike", "lastPrice", "impliedVolatility"])

    merged = calls_df.merge(puts_df, on="strike", how="left", suffixes=("_call", "_put"))
    rows = []
    for _, row in merged.iterrows():
        rows.append(
            {
                "expiration": chain["expiry"],
                "strike": _safe_float(row.get("strike", 0)),
                "call_price": _safe_float(row.get("lastPrice_call", 0)),
                "call_delta": 0.0,
                "call_iv": _safe_float(row.get("impliedVolatility_call", 0)),
                "put_price": _safe_float(row.get("lastPrice_put", 0)),
                "put_delta": 0.0,
                "put_iv": _safe_float(row.get("impliedVolatility_put", 0)),
                "volume": _safe_int(
                    _safe_float(row.get("volume_call", 0)) + _safe_float(row.get("volume_put", 0))
                ),
                "open_interest": _safe_int(
                    _safe_float(row.get("openInterest_call", 0))
                    + _safe_float(row.get("openInterest_put", 0))
                ),
            }
        )

    return {
        "ticker": ticker.upper(),
        "expirations": chain.get("available_expirations", []),
        "chain": rows,
        "provider": "yfinance",
        "source": "yfinance",
    }


def _synthetic_options(ticker: str) -> dict:
    np.random.seed(hash(ticker) % 2**31)
    spot_data = _generate_synthetic_prices(ticker, 5)
    spot = spot_data["close"][-1]
    strikes = [round(spot * m, 2) for m in np.arange(0.85, 1.16, 0.025)]
    expirations = ["2026-06-19", "2026-09-18", "2026-12-18", "2027-03-19", "2027-06-18"]

    chain = []
    for exp in expirations:
        ttm = (expirations.index(exp) + 1) * 0.25
        for strike in strikes:
            sigma = 0.20 + 0.05 * abs(np.log(strike / spot))
            call = BlackScholes.greeks(spot, strike, ttm, 0.05, sigma, "call")
            put = BlackScholes.greeks(spot, strike, ttm, 0.05, sigma, "put")
            chain.append(
                {
                    "expiration": exp,
                    "strike": strike,
                    "call_price": call.price,
                    "call_delta": call.delta,
                    "call_iv": round(sigma, 4),
                    "put_price": put.price,
                    "put_delta": put.delta,
                    "put_iv": round(sigma, 4),
                    "volume": int(np.random.exponential(500)),
                    "open_interest": int(np.random.exponential(2000)),
                }
            )

    return {
        "ticker": ticker.upper(),
        "spot": round(spot, 2),
        "expirations": expirations,
        "chain": chain,
        "provider": "synthetic",
        "source": "synthetic",
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/providers")
async def get_provider_status():
    """Return configured market-data providers and their availability."""
    import os
    return {
        "default_provider": "auto",
        "providers": {
            "brapi": {
                "available": True,
                "token_configured": bool(os.getenv("BRAPI_TOKEN")),
                "coverage": "B3 (Brazil)",
                "url": "https://brapi.dev",
            },
            "openbb": OpenBBService.get_provider_status(),
            "yfinance": {"available": True, "coverage": "Global"},
            "synthetic": {"available": True, "coverage": "Fallback"},
        },
    }


@router.get("/b3/tickers")
async def list_b3_tickers():
    """List all available B3 tickers via brapi."""
    tickers = BrapiService.list_tickers()
    return {"exchange": "BVMF", "count": len(tickers), "tickers": tickers}


@router.get("/b3/macro")
async def b3_macro():
    """Brazilian macro rates — SELIC, CDI, IPCA inflation."""
    inflation = BrapiService.get_inflation()
    prime = BrapiService.get_prime_rate()
    return {
        "inflation": inflation,
        "prime_rate": prime,
        "source": "brapi",
    }


@router.get("/quote/{ticker}")
@limiter.limit("30/minute")
async def get_quote(request: Request, ticker: str, provider: ProviderName = Query(default="auto")):
    """Get quote — brapi (BR tickers) → OpenBB → Yahoo Finance → synthetic fallback."""
    is_br = _is_br_ticker(ticker)

    # brapi first for Brazilian tickers
    if provider in {"auto", "brapi"} and (is_br or provider == "brapi"):
        quote = BrapiService.get_quote(ticker)
        if quote:
            return quote

    if provider in {"auto", "openbb", "openbb_yfinance"}:
        quote = OpenBBService.get_quote(ticker, provider="yfinance")
        if quote:
            return quote

    if provider in {"auto", "yfinance"}:
        quote = _quote_from_yfinance(ticker)
        if quote:
            return quote

    return _synthetic_quote(ticker)


@router.get("/history/{ticker}")
@limiter.limit("20/minute")
async def get_history(
    request: Request,
    ticker: str,
    days: int = 252,
    period: str = "1y",
    provider: ProviderName = Query(default="auto"),
):
    """Get historical OHLCV data with provider fallbacks."""
    is_br = _is_br_ticker(ticker)

    # brapi first for Brazilian tickers
    if provider in {"auto", "brapi"} and (is_br or provider == "brapi"):
        history = BrapiService.get_history(ticker, days)
        if history:
            return history

    if provider in {"auto", "openbb", "openbb_yfinance"}:
        start_date = (date.today() - timedelta(days=days)).isoformat()
        df = OpenBBService.get_historical_data(
            ticker,
            provider="yfinance",
            interval="1d",
            start_date=start_date,
            end_date=date.today().isoformat(),
        )
        if df is not None and not df.empty:
            # Normalise column names regardless of OpenBB provider casing
            df = _normalise_df_columns(df)
            required = {"open", "high", "low", "close", "volume"}
            if required.issubset(set(df.columns)):
                return {
                    "ticker": ticker.upper(),
                    "dates": [idx.strftime("%Y-%m-%d") for idx in df.index],
                    "open": [round(float(v), 2) for v in df["open"].values],
                    "high": [round(float(v), 2) for v in df["high"].values],
                    "low": [round(float(v), 2) for v in df["low"].values],
                    "close": [round(float(v), 2) for v in df["close"].values],
                    "volume": [int(v) for v in df["volume"].fillna(0).values],
                    "provider": "openbb::yfinance",
                    "source": "openbb",
                }

    if provider in {"auto", "yfinance"}:
        history = _history_from_yfinance(ticker, days, period)
        if history:
            return history

    return _generate_synthetic_prices(ticker, days)


@router.get("/profile/{ticker}")
async def get_profile(ticker: str):
    """Get company profile — OpenBB → Yahoo Finance → synthetic fallback."""
    profile = OpenBBService.get_profile(ticker, provider="yfinance")
    if profile:
        return profile

    quote = _quote_from_yfinance(ticker) or _synthetic_quote(ticker)
    return {
        "symbol": ticker.upper(),
        "name": ticker.upper(),
        "exchange": "NASDAQ",
        "currency": "USD",
        "market_cap": quote.get("market_cap", 0),
        "provider": quote.get("provider", "synthetic"),
        "source": quote.get("source", "synthetic"),
    }


@router.get("/search")
async def search_market(query: str):
    """Search symbols through OpenBB."""
    results = OpenBBService.search_equity(query, provider="sec")
    if results:
        return {"query": query, "results": results, "source": "openbb"}
    return {
        "query": query,
        "results": [{"symbol": query.upper(), "name": query.upper(), "source": "synthetic"}],
        "source": "synthetic",
    }


@router.get("/volatility/{ticker}")
async def get_volatility(ticker: str):
    """Get implied volatility metrics — options → historical → synthetic."""
    vol_data = DataFetcher.get_volatility_data(ticker)
    if vol_data:
        vol_data["provider"] = "yfinance"
        vol_data["source"] = "yfinance"
        return vol_data

    returns_data = DataFetcher.calculate_returns(ticker, period="1y")
    if returns_data:
        iv = returns_data["annual_volatility"] / 100
        return {
            "ticker": ticker.upper(),
            "iv_call": iv,
            "iv_put": iv,
            "iv_avg": iv,
            "volatility_skew": 0.0,
            "provider": "historical",
            "source": "historical",
        }

    return {
        "ticker": ticker.upper(),
        "iv_call": 0.25,
        "iv_put": 0.26,
        "iv_avg": 0.255,
        "volatility_skew": 0.01,
        "provider": "synthetic",
        "source": "synthetic",
    }


@router.get("/returns/{ticker}")
async def get_returns(ticker: str, period: str = "1y"):
    """Get returns and risk metrics."""
    returns_data = DataFetcher.calculate_returns(ticker, period=period)
    if returns_data:
        returns_data["provider"] = "yfinance"
        returns_data["source"] = "yfinance"
        return returns_data

    return {
        "ticker": ticker.upper(),
        "period": period,
        "total_return": 12.5,
        "annual_return": 15.3,
        "annual_volatility": 18.2,
        "sharpe_ratio": 0.84,
        "max_drawdown": 22.5,
        "provider": "synthetic",
        "source": "synthetic",
    }


@router.get("/options-chain/{ticker}")
@limiter.limit("10/minute")
async def get_options_chain(request: Request, ticker: str, provider: ProviderName = Query(default="auto")):
    """Get options chain with provider fallbacks."""
    if provider in {"auto", "openbb", "openbb_cboe"}:
        chain = OpenBBService.get_options_chain(ticker, provider="cboe")
        if chain and chain.get("chain"):
            return chain

    if provider in {"auto", "yfinance", "openbb_yfinance"}:
        chain = _options_from_yfinance(ticker)
        if chain and chain.get("chain"):
            return chain

    return _synthetic_options(ticker)

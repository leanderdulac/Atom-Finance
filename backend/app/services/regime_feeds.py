"""
Public regime books: Yahoo equities/VIX/UST and FRED HY OAS.

No API keys. Delayed prints. Injectable fetchers so tests never hit the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from io import StringIO
from typing import Any

import httpx
import pandas as pd

from app.services.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

EQUITY_TICKERS = ("SPY", "QQQ", "IWM", "EFA", "TLT")
VIX_FRONT = "^VIX"
VIX_BACK_CANDIDATES = ("^VIX3M", "^VXV")
YIELD_2Y = "^IRX"  # 13-week; documented as the short leg we can actually get
YIELD_10Y = "^TNX"
FRED_HY_OAS = "BAMLH0A0HYM2"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"

HistoryFn = Callable[[str], pd.Series | None]


def _close_series(symbol: str) -> pd.Series | None:
    df = DataFetcher.get_historical_data(symbol, period="2y", interval="1d")
    if df is None or df.empty or "Close" not in df.columns:
        return None
    s = pd.Series(df["Close"]).astype(float).dropna()
    idx = pd.DatetimeIndex(pd.to_datetime(s.index))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    # Via the Series .dt accessor: the stubs do not expose normalize/floor on
    # DatetimeIndex itself, and the result is the same midnight-aligned index.
    s.index = pd.DatetimeIndex(pd.Series(idx).dt.normalize())
    return s


def _scale_yield(value: float) -> float:
    """Old Yahoo TNX/IRX printed 42.1 for 4.21%. New prints 4.21."""
    return float(value) / 10.0 if value > 20.0 else float(value)


def fetch_fred_oas(
    series_id: str = FRED_HY_OAS,
    *,
    client: httpx.Client | None = None,
) -> pd.Series:
    url = FRED_CSV.format(id=series_id)
    own = client is None
    http = client or httpx.Client(timeout=20.0)
    try:
        resp = http.get(url, headers={"User-Agent": "ATOM Research regime desk"})
        resp.raise_for_status()
    finally:
        if own:
            http.close()
    frame = pd.read_csv(StringIO(resp.text))
    date_col = next(c for c in frame.columns if c.lower() == "date" or c.lower() == "observation_date")
    val_col = next(c for c in frame.columns if c != date_col)
    s = pd.Series(pd.to_numeric(frame[val_col], errors="coerce"))
    idx = pd.to_datetime(frame[date_col]).dt.normalize()
    out = pd.Series(s.to_numpy(), index=idx, name=series_id).dropna()
    return out


def _align(*series: pd.Series) -> pd.DataFrame:
    frame = pd.concat(list(series), axis=1).sort_index().ffill().dropna()
    if len(frame) < 120:
        raise ValueError(f"Aligned live books too short ({len(frame)} rows); need ≥120")
    return frame


def fetch_live_payload(
    *,
    history_fn: HistoryFn | None = None,
    oas_fn: Callable[..., pd.Series] | None = None,
) -> dict[str, Any]:
    hist = history_fn or _close_series
    equities: dict[str, pd.Series] = {}
    for t in EQUITY_TICKERS:
        s = hist(t)
        if s is None or s.empty:
            raise ValueError(f"Missing Yahoo history for {t}")
        equities[t] = s.rename(t)

    front = hist(VIX_FRONT)
    if front is None or front.empty:
        raise ValueError("Missing ^VIX")
    front = front.rename("vix_front")
    back = None
    back_sym = None
    for cand in VIX_BACK_CANDIDATES:
        b = hist(cand)
        if b is not None and not b.empty:
            back, back_sym = b.rename("vix_back"), cand
            break
    if back is None:
        raise ValueError("Missing VIX3M/VXV")

    y2 = hist(YIELD_2Y)
    y10 = hist(YIELD_10Y)
    if y2 is None or y10 is None or y2.empty or y10.empty:
        raise ValueError("Missing ^IRX or ^TNX")
    y2 = y2.map(_scale_yield).rename("y2")
    y10 = y10.map(_scale_yield).rename("y10")

    oas = (oas_fn or fetch_fred_oas)()
    oas = oas.rename("credit")

    parts = [front, back, y2, y10, oas, *[equities[t] for t in EQUITY_TICKERS]]
    frame = _align(*parts)
    iv = (frame["vix_front"] / 100.0).clip(lower=0.05)
    return {
        "equity_prices": {t: frame[t].tolist() for t in EQUITY_TICKERS},
        "vix_front": frame["vix_front"].tolist(),
        "vix_back": frame["vix_back"].tolist(),
        "implied_vol": iv.tolist(),
        "credit_spread": frame["credit"].tolist(),
        "yield_2y": frame["y2"].tolist(),
        "yield_10y": frame["y10"].tolist(),
        "window": 90,
        "live_books": True,
        "sources": {
            "equities": "yahoo",
            "vix_front": VIX_FRONT,
            "vix_back": back_sym,
            "iv": "VIX/100 as SPX implied vol proxy",
            "credit": f"FRED {FRED_HY_OAS}",
            "curve": f"{YIELD_10Y} minus {YIELD_2Y} (13-week, not 2-year)",
        },
        "n_obs": int(len(frame)),
        "as_of_session": str(pd.Series(frame.index).dt.date.iloc[-1]),
    }

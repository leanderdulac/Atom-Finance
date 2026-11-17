"""Information-driven bars: volume and dollar bars."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _bars(df: pd.DataFrame, measure: np.ndarray, threshold: float, price_col: str,
          vol_col: str, ohlcv: bool) -> pd.DataFrame:
    if threshold <= 0:
        raise ValueError("threshold must be > 0")
    if ohlcv:
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    else:
        p = df[price_col].to_numpy(float)
        o = h = l = c = p
    v = df[vol_col].to_numpy(float)
    idx = df.index
    # Sequential accumulation is the definition of a volume/dollar bar.
    # Work on numpy buffers (not DataFrame.iloc[i]).
    rows, acc, start = [], 0.0, 0
    n = len(df)
    for i in range(n):
        acc += measure[i]
        if acc >= threshold:
            sl = slice(start, i + 1)
            rows.append({
                "timestamp": idx[i],
                "open": o[start],
                "high": h[sl].max(),
                "low": l[sl].min(),
                "close": c[i],
                "volume": v[sl].sum(),
                "measure_sum": measure[sl].sum(),
                "n_ticks": i + 1 - start,
            })
            acc, start = 0.0, i + 1
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "measure_sum", "n_ticks"])
    return out.set_index("timestamp")


def volume_bars(df, threshold, price_col="price", vol_col="volume"):
    """Close a bar every time cumulative volume >= threshold.

    df: tick data (price, volume) or OHLCV (open/high/low/close/volume), time-indexed.
    Unfinished trailing bar is dropped (no lookahead).
    """
    ohlcv = {"open", "high", "low", "close"}.issubset(df.columns)
    v = df[vol_col].to_numpy(float)
    return _bars(df, v, threshold, price_col, vol_col, ohlcv)


def dollar_bars(df, threshold, price_col="price", vol_col="volume"):
    """Close a bar every time cumulative price*volume >= threshold.

    For OHLCV input the bar's typical price (h+l+c)/3 is used.
    """
    ohlcv = {"open", "high", "low", "close"}.issubset(df.columns)
    if ohlcv:
        px = (df["high"] + df["low"] + df["close"]).to_numpy(float) / 3
    else:
        px = df[price_col].to_numpy(float)
    dv = px * df[vol_col].to_numpy(float)
    return _bars(df, dv, threshold, price_col, vol_col, ohlcv)

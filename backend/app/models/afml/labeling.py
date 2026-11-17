"""Volatility, CUSUM filter and triple-barrier labeling (AFML ch. 3)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def rolling_volatility(close: pd.Series, lookback: int = 1, span: int = 100) -> pd.Series:
    """EWM std of `lookback`-bar returns. Value at t uses information ≤ t."""
    ret = close / close.shift(lookback) - 1
    return ret.ewm(span=span, min_periods=max(2, span // 4)).std()


def daily_volatility(close: pd.Series, span: int = 100) -> pd.Series:
    """EWM std of ~1-day returns on an irregular time index."""
    prev = close.index.searchsorted(close.index - pd.Timedelta(days=1)) - 1
    mask = prev >= 0
    r = pd.Series(np.nan, index=close.index)
    r.iloc[mask] = close.to_numpy()[mask] / close.to_numpy()[prev[mask]] - 1
    return r.ewm(span=span, min_periods=max(2, span // 4)).std()


def cusum_filter(close: pd.Series, threshold) -> pd.DatetimeIndex:
    """Symmetric CUSUM on log returns. threshold: float or Series aligned to close."""
    lr = np.log(close).diff()
    thr = threshold if isinstance(threshold, pd.Series) else pd.Series(float(threshold), index=close.index)
    events: list = []
    sp = 0.0
    sn = 0.0
    for t, r in lr.iloc[1:].items():
        h = thr.get(t, np.nan)
        if not np.isfinite(h) or not np.isfinite(r):
            continue
        sp, sn = max(0.0, sp + r), min(0.0, sn + r)
        if sp >= h:
            sp = 0.0
            events.append(t)
        elif sn <= -h:
            sn = 0.0
            events.append(t)
    return pd.DatetimeIndex(events)


def vertical_barrier(
    close: pd.Series,
    t_events,
    num_bars: int | None = None,
    delta: pd.Timedelta | None = None,
) -> pd.Series:
    """Timestamp of the vertical barrier for each event (NaT if beyond data)."""
    t_events = pd.DatetimeIndex(t_events)
    if num_bars is not None:
        pos = close.index.get_indexer(t_events) + num_bars
    else:
        pos = close.index.searchsorted(t_events + delta)
    out = pd.Series(
        pd.NaT,
        index=t_events,
        dtype="datetime64[ns]" if close.index.tz is None else close.index.dtype,
    )
    ok = pos < len(close.index)
    out[ok] = close.index[pos[ok]]
    return out


def triple_barrier_events(
    close: pd.Series,
    t_events,
    target: pd.Series,
    pt_sl: tuple[float, float] = (1.0, 1.0),
    t1: pd.Series | None = None,
    side: pd.Series | None = None,
    min_ret: float = 0.0,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
) -> pd.DataFrame:
    """For each event find first touch of profit-take, stop-loss or vertical barrier.

    target: per-event return width (e.g. volatility). pt_sl multipliers (0 disables).
    side: +1/-1 from primary model (meta-labeling); if None, symmetric barriers, side=+1.
    high/low: optional intrabar extremes; touches checked on bars strictly after t0.
    Returns DataFrame [t1, trgt, side, touch(pt/sl/t1)] with t1 = time of first touch.
    """
    t_events = pd.DatetimeIndex(t_events)
    trgt = target.reindex(t_events)
    trgt = trgt[trgt > min_ret].dropna()
    if t1 is None:
        t1 = pd.Series(pd.NaT, index=trgt.index)
    t1 = t1.reindex(trgt.index)
    sd = pd.Series(1.0, index=trgt.index) if side is None else side.reindex(trgt.index).fillna(0)
    pt_m, sl_m = pt_sl
    hi = close if high is None else high
    lo = close if low is None else low
    idx = close.index
    res = []
    for t0 in trgt.index:
        s = sd[t0]
        if s == 0:
            continue
        i0 = idx.get_loc(t0)
        end = t1[t0]
        i1 = len(idx) - 1 if pd.isna(end) else idx.get_loc(end)
        p0 = close.iloc[i0]
        seg = slice(i0 + 1, i1 + 1)
        up = (hi.iloc[seg] / p0 - 1) * s if s > 0 else (lo.iloc[seg] / p0 - 1) * s
        dn = (lo.iloc[seg] / p0 - 1) * s if s > 0 else (hi.iloc[seg] / p0 - 1) * s
        w = trgt[t0]
        t_pt = up.index[up >= pt_m * w][0] if pt_m > 0 and (up >= pt_m * w).any() else pd.NaT
        t_sl = dn.index[dn <= -sl_m * w][0] if sl_m > 0 and (dn <= -sl_m * w).any() else pd.NaT
        cands = {"pt": t_pt, "sl": t_sl, "t1": end}
        cands = {k: v for k, v in cands.items() if not pd.isna(v)}
        if not cands:
            continue  # unresolved at end of data -> drop (no lookahead fill)
        order = {"sl": 0, "pt": 1, "t1": 2}
        k = min(cands, key=lambda key: (cands[key], order[key]))
        res.append((t0, cands[k], w, s, k))
    out = pd.DataFrame(res, columns=["t0", "t1", "trgt", "side", "touch"]).set_index("t0")
    out.index.name = None
    return out


def get_bins(
    events: pd.DataFrame,
    close: pd.Series,
    meta: bool | None = None,
    cost: float = 0.0,
) -> pd.DataFrame:
    """Return realized side-adjusted return at t1 and the label.

    ``cost`` is subtracted from the return (round-trip fee+spread as a
    fraction). Meta labels (default: inferred from a non-trivial side) are
    {0,1} on the *net* return; otherwise bin = sign(ret_net) in {-1,0,1}.
    """
    ret = close.reindex(events["t1"]).to_numpy() / close.reindex(events.index).to_numpy() - 1
    ret = ret * events["side"].to_numpy()
    net = ret - float(cost)
    out = pd.DataFrame(
        {"ret": ret, "ret_net": net, "touch": events["touch"].to_numpy()},
        index=events.index,
    )
    if meta is None:
        meta = "side" in events and (events["side"] < 0).any()
    out["bin"] = (out["ret_net"] > 0).astype(int) if meta else np.sign(out["ret_net"]).astype(int)
    return out


def triple_barrier_on_pnl(
    pnl_path: np.ndarray,
    t0: Sequence[int],
    side: Sequence[float],
    width: Sequence[float],
    horizon: Sequence[int],
    pt: float = 1.0,
    sl: float = 1.0,
    cost: float = 0.0,
) -> pd.DataFrame:
    """First-touch barriers on a *level* PnL path (pairs residual / unit book).

    ``pnl_path[t]`` is the mark-to-market of a +1 spread unit from bar 0,
    *not* a price. For event i opened at ``t0[i]`` with ``side[i]``:

        pnl = side * (path[t] - path[t0])   for t > t0
        PT if pnl ≥ pt * width; SL if pnl ≤ -sl * width; else vertical at t0+horizon.

    Returns one row per resolved event with columns t0, t1, side, touch, ret, ret_net, bin.
    Unresolved windows (path ends before any touch) are dropped — no lookahead fill.
    Ties: stop-loss first.
    """
    path = np.asarray(pnl_path, dtype=np.float64)
    t0_arr = np.asarray(t0, dtype=int)
    side_arr = np.asarray(side, dtype=np.float64)
    width_arr = np.asarray(width, dtype=np.float64)
    horizon_arr = np.asarray(horizon, dtype=int)
    n = len(path)
    rows = []
    for i, i0 in enumerate(t0_arr):
        s = side_arr[i]
        if s == 0 or not np.isfinite(s) or i0 < 0 or i0 >= n - 1:
            continue
        w = float(width_arr[i])
        if not np.isfinite(w) or w <= 0:
            continue
        i_vert = i0 + int(horizon_arr[i])
        vertical_ok = i_vert < n
        i1 = min(i_vert, n - 1)
        if i1 <= i0:
            continue
        seg = path[i0 + 1 : i1 + 1]
        pnl = s * (seg - path[i0])
        t_pt = t_sl = None
        if pt > 0:
            hit = np.flatnonzero(pnl >= pt * w)
            if hit.size:
                t_pt = i0 + 1 + int(hit[0])
        if sl > 0:
            hit = np.flatnonzero(pnl <= -sl * w)
            if hit.size:
                t_sl = i0 + 1 + int(hit[0])
        cands: dict[str, int] = {}
        if vertical_ok:
            cands["t1"] = i_vert
        if t_pt is not None:
            cands["pt"] = t_pt
        if t_sl is not None:
            cands["sl"] = t_sl
        if not cands:
            continue  # path ended before any barrier — no lookahead fill
        order = {"sl": 0, "pt": 1, "t1": 2}
        touch = min(cands, key=lambda k: (cands[k], order[k]))
        t_end = cands[touch]
        ret = float(s * (path[t_end] - path[i0]))
        net = ret - float(cost)
        rows.append(
            {
                "t0": int(i0),
                "t1": int(t_end),
                "side": float(s),
                "trgt": w,
                "touch": touch,
                "ret": ret,
                "ret_net": net,
                "bin": int(net > 0),
            }
        )
    return pd.DataFrame(rows)

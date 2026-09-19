"""
Row loops over price panels fail a desk hiring screen.

`for i in range(len(df)): ... df['pe'].iloc[i]` is not a style note.
Interpreted Python is 50–100× slower than NumPy/Fortran; the index i vs i-1
is the usual look-ahead hideout; a 40-minute looped backtest is a 2-second
broadcast. Cross-sectional z-scores are `X.sub(mean, axis=0).div(std, axis=0)`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

_WHAT_BROKE = [
    "Synthetic panel: PE is a slow random walk, not fundamentals.",
    "Same-bar scoring of a trailing signal is the i vs i-1 bug, not a trading rule.",
    "Timing ratio is machine-dependent; the order of magnitude is the lesson.",
    "Equal-weight long-only screen has no costs, no risk model, no claim of edge.",
    "This does not authorize live trading. eligible_for_live_trading stays false.",
]

_REJECTED = (
    "for i in range(len(df)):\n"
    "    if df['pe'].iloc[i] < 10 and df['mom'].iloc[i] > 0:\n"
    "        portfolio.append(df['ret'].iloc[i])  # mesmo bar: i, não i+1"
)

_VECTORIZED = (
    "mask = (pe < 10) & (mom > 0)\n"
    "w = mask / np.maximum(mask.sum(axis=1, keepdims=True), 1)\n"
    "pnl = (w[:-1] * ret[1:]).sum(axis=1)  # sinal em t, retorno em t+1\n"
    "z = (X - X.mean(axis=1, keepdims=True)) / X.std(axis=1, keepdims=True)"
)


def demo_panel(
    n_names: int = 80, n_days: int = 504, seed: int = 7
) -> dict[str, np.ndarray]:
    if not 10 <= n_names <= 400:
        raise ValueError("n_names must be in [10, 400]")
    if not 80 <= n_days <= 2000:
        raise ValueError("n_days must be in [80, 2000]")
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0003, 0.012, size=(n_days, n_names))
    pe0 = rng.uniform(6.0, 25.0, size=n_names)
    pe = np.clip(pe0 + np.cumsum(rng.normal(0.0, 0.08, size=ret.shape), axis=0) * 0.05, 3.0, 40.0)
    prices = 100.0 * np.cumprod(1.0 + ret, axis=0)
    mom20 = np.full_like(ret, np.nan)
    mom20[20:] = prices[20:] / prices[:-20] - 1.0
    return {"ret": ret, "pe": pe, "mom20": mom20, "prices": prices}


def loop_mask(pe: np.ndarray, mom: np.ndarray, pe_max: float = 10.0) -> np.ndarray:
    """The hiring-screen anti-pattern: nested Python over names × days."""
    t_days, n_names = pe.shape
    mask = np.zeros((t_days, n_names), dtype=bool)
    for t in range(t_days):
        for i in range(n_names):
            m = mom[t, i]
            if np.isfinite(m) and pe[t, i] < pe_max and m > 0.0:
                mask[t, i] = True
    return mask


def vec_mask(pe: np.ndarray, mom: np.ndarray, pe_max: float = 10.0) -> np.ndarray:
    return (pe < pe_max) & (mom > 0.0) & np.isfinite(mom)


def weights_from_mask(mask: np.ndarray) -> np.ndarray:
    n_sel = mask.sum(axis=1, keepdims=True).astype(np.float64)
    w = np.zeros(mask.shape, dtype=np.float64)
    np.divide(mask.astype(np.float64), n_sel, out=w, where=n_sel > 0)
    return w


def zscore_loop(x: np.ndarray) -> np.ndarray:
    """Row-wise z-score with explicit Python — the 40-minute version."""
    t_days, n_names = x.shape
    z = np.zeros_like(x)
    for t in range(t_days):
        mu = 0.0
        for i in range(n_names):
            mu += x[t, i]
        mu /= n_names
        acc = 0.0
        for i in range(n_names):
            d = x[t, i] - mu
            acc += d * d
        sd = (acc / n_names) ** 0.5
        if sd > 1e-18:
            for i in range(n_names):
                z[t, i] = (x[t, i] - mu) / sd
    return z


def zscore_vec(x: np.ndarray) -> np.ndarray:
    """df.sub(mean, axis=0).div(std, axis=0) as a numpy broadcast."""
    mu = x.mean(axis=1, keepdims=True)
    sd = x.std(axis=1, keepdims=True)
    return np.divide(x - mu, sd, out=np.zeros_like(x), where=sd > 1e-18)


def _ann_sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 20:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd < 1e-18:
        return 0.0
    return float(np.mean(r) / sd * np.sqrt(252.0))


def _time(fn: Callable[[], np.ndarray], repeats: int = 3) -> tuple[np.ndarray, float]:
    best = float("inf")
    out = fn()
    for _ in range(repeats):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return out, best


def evaluate(
    n_names: int = 80, n_days: int = 504, seed: int = 7, pe_max: float = 10.0
) -> dict[str, Any]:
    panel = demo_panel(n_names=n_names, n_days=n_days, seed=seed)
    ret, pe, mom20 = panel["ret"], panel["pe"], panel["mom20"]

    looped, loop_s = _time(lambda: loop_mask(pe, mom20, pe_max))
    vectorized, vec_s = _time(lambda: vec_mask(pe, mom20, pe_max))
    if looped.shape != vectorized.shape or not np.array_equal(looped, vectorized):
        raise RuntimeError("loop mask and vectorized mask diverged")

    w = weights_from_mask(vectorized)
    delayed = (w[:-1] * ret[1:]).sum(axis=1)
    same_bar = (w * ret).sum(axis=1)

    # Pure i vs i-1: treat today's return as if it were already known.
    long_today = ret > 0.0
    leak_1d = np.where(long_today, ret, 0.0).mean(axis=1)
    delayed_1d = np.where(long_today[:-1], ret[1:], 0.0).mean(axis=1)

    z_loop, z_loop_s = _time(lambda: zscore_loop(ret))
    z_vec, z_vec_s = _time(lambda: zscore_vec(ret))
    z_max_abs = float(np.max(np.abs(z_loop - z_vec)))

    step = max(1, (n_days - 1) // 160)
    eq_d = np.cumprod(1.0 + delayed)
    eq_s = np.cumprod(1.0 + same_bar[:-1])
    equity = [
        {
            "t": int(t),
            "delayed": round(float(eq_d[t]), 4),
            "same_bar": round(float(eq_s[t]), 4),
        }
        for t in range(0, len(eq_d), step)
    ]

    speedup_mask = loop_s / max(vec_s, 1e-12)
    speedup_z = z_loop_s / max(z_vec_s, 1e-12)
    n_hits = int(vectorized.sum())

    return {
        "n_names": n_names,
        "n_days": n_days,
        "pe_max": pe_max,
        "n_hits": n_hits,
        "masks_equal": True,
        "z_max_abs_diff": round(z_max_abs, 12),
        "timing": {
            "loop_mask_s": round(loop_s, 6),
            "vec_mask_s": round(vec_s, 6),
            "speedup_mask": round(float(speedup_mask), 1),
            "loop_z_s": round(z_loop_s, 6),
            "vec_z_s": round(z_vec_s, 6),
            "speedup_z": round(float(speedup_z), 1),
        },
        "screen": {
            "delayed_sharpe": round(_ann_sharpe(delayed), 3),
            "same_bar_sharpe": round(_ann_sharpe(same_bar), 3),
        },
        "index_bug": {
            "delayed_sharpe": round(_ann_sharpe(delayed_1d), 3),
            "same_bar_sharpe": round(_ann_sharpe(leak_1d), 3),
            "note": "Sinal = 1{r_t>0}. Mesmo bar usa r_t; o relógio honesto usa r_{t+1}.",
        },
        "rejected_code": _REJECTED,
        "vectorized_code": _VECTORIZED,
        "equity": equity,
        "eligible_for_live_trading": False,
        "math": (
            "Máscara cheap×momentum: pe<10 e mom_20>0. Loop aninhado em Python vs "
            "(pe<10)&(mom>0). PnL honesto é w_t · r_{t+1}; o snippet com .iloc[i] "
            "no retorno do mesmo i é look-ahead. Z-score transversal: "
            "(X - mean(axis=1)) / std(axis=1), o broadcasting de "
            "df.sub(mean, axis=0).div(std, axis=0). "
            f"Neste relógio o Z-score loop/vec diferem no máximo {z_max_abs:.1e}; "
            f"speedup da máscara {speedup_mask:.0f}×, do Z-score {speedup_z:.0f}×."
        ),
        "what_broke": list(_WHAT_BROKE),
    }

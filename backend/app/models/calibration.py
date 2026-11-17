"""Interval calibration: do predicted bands contain reality at the stated rate?

Walk-forward check of GBM forecast intervals on a price history. Volatility
comes from an EWMA recursion (RiskMetrics); blocks are NON-OVERLAPPING
(step = horizon), so no realized return is counted twice — the purged,
honest version of a coverage backtest. Small samples stay small: the
verdict carries a binomial confidence band instead of pretending precision.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm


def interval_coverage(
    prices: list[float] | np.ndarray,
    horizon_days: int,
    vol_lambda: float = 0.94,
    warmup: int = 60,
    level: float = 0.90,
) -> dict:
    """Coverage of h-day GBM intervals over non-overlapping blocks."""
    px = np.asarray(prices, dtype=np.float64)
    if px.ndim != 1 or px.size < warmup + 2 * horizon_days:
        raise ValueError(
            f"Need at least warmup + 2*horizon prices ({warmup + 2 * horizon_days}).")
    if not 1 <= horizon_days <= 63:
        raise ValueError("horizon_days must be within 1..63")
    if not 0.0 < vol_lambda < 1.0:
        raise ValueError("vol_lambda must be within (0, 1)")
    if not 0.5 < level < 0.99:
        raise ValueError("level must be within (0.5, 0.99)")
    if bool((~np.isfinite(px)).any()) or bool((px <= 0).any()):
        raise ValueError("prices must be finite and positive")

    rets = np.diff(np.log(px))
    var = float(np.var(rets[:warmup]))
    z = float(norm.ppf((1.0 + level) / 2.0))
    starts = list(range(warmup, len(rets) - horizon_days + 1, horizon_days))
    hits = 0
    widths: list[float] = []
    pos = warmup
    for t in starts:
        # EWMA variance through t (information available at decision time).
        for r in rets[pos:t]:
            var = vol_lambda * var + (1.0 - vol_lambda) * r * r
        pos = t
        sigma_ann = float(np.sqrt(max(var, 0.0)) * np.sqrt(252.0))
        h_years = horizon_days / 252.0
        sd = sigma_ann * np.sqrt(h_years)
        mean = -0.5 * (sigma_ann**2) * h_years
        lo, hi = mean - z * sd, mean + z * sd
        realized = float(np.log(px[t + horizon_days]) - np.log(px[t]))
        widths.append(hi - lo)
        if lo <= realized <= hi:
            hits += 1
    n = len(starts)
    coverage = hits / n
    # Normal 95% band for a binomial proportion (honest about small n).
    half = 1.96 * float(np.sqrt(max(coverage * (1.0 - coverage), 0.0) / n))
    return {
        "coverage": round(coverage, 4),
        "target_level": level,
        "n_blocks": n,
        "hits": hits,
        "band_95": [round(max(0.0, coverage - half), 4), round(min(1.0, coverage + half), 4)],
        "within_band": bool(max(0.0, coverage - half) <= level <= min(1.0, coverage + half)),
        "mean_width": round(float(np.mean(widths)), 6),
        "horizon_days": horizon_days,
        "vol_lambda": vol_lambda,
        "block_starts": starts,
        "model": "gbm_ewma_vol",
        "eligible_for_live_trading": False,
        "what_broke": [
            "GBM with EWMA vol per block: no jumps, no regime shifts inside the window.",
            "Non-overlapping blocks shrink the sample; wide bands on short histories are honest.",
            "Coverage measures the past; it does not promise future calibration.",
        ],
    }

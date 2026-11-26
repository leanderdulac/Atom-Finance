"""Continuous Kelly sizing on a trailing window.

f* = (μ − r_f) / σ² is the log-optimal leverage. The fraction at t uses the
window of returns that ends at t (apply it from t+1). Estimated μ overstates
the edge, so the haircut ``fraction`` cannot exceed one half and the result
is clipped to ``cap``.

A strategy that has not passed the out-of-sample protocol may have true μ = 0.
This function does not authorise that strategy. ``eligible_for_live_trading``
is false. The discrete derivatives sizer stays in ``kelly_derivatives``.
"""

from __future__ import annotations

import numpy as np

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING, as_1d, check_positive_int

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "growth_rate",
    "kelly_continuous",
    "rolling_kelly",
]


def kelly_continuous(mu: float, sigma: float, rf: float = 0.0) -> float:
    """Full continuous Kelly leverage. Prefer ``rolling_kelly`` (haircut and cap)."""
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    return (mu - rf) / sigma**2


def growth_rate(f: float, mu: float, sigma: float, rf: float = 0.0) -> float:
    """Expected log growth of leverage ``f`` under a continuous approximation."""
    if sigma < 0:
        raise ValueError("sigma must be >= 0")
    return rf + f * (mu - rf) - 0.5 * f**2 * sigma**2


def rolling_kelly(
    returns: object,
    window: int = 250,
    fraction: float = 0.5,
    cap: float = 0.5,
    rf: float = 0.0,
    long_only: bool = True,
) -> np.ndarray:
    """Causal fractional Kelly. NaN until the window is full or the slice has no variance."""
    series = as_1d(returns, "returns")
    check_positive_int(window, "window", 3)
    if not (0.0 < fraction <= 0.5) or cap <= 0:
        raise ValueError("fraction must be in (0, 0.5] and cap > 0")
    out = np.full(len(series), np.nan)
    floor = 0.0 if long_only else -cap
    need = max(3, window // 2)
    for t in range(window - 1, len(series)):
        w = series[t - window + 1 : t + 1]
        w = w[np.isfinite(w)]
        if len(w) < need:
            continue
        sigma = float(w.std(ddof=1))
        if sigma <= 0:
            continue
        raw = fraction * (float(w.mean()) - rf) / sigma**2
        out[t] = float(np.clip(raw, floor, cap))
    return out

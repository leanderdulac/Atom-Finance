"""ADF + KPSS stationarity diagnostics, with a causal rolling ADF p-value.

ADF null is a unit root. KPSS null is stationarity. The combined verdict
avoids treating a low-power ADF failure as evidence of a unit root.

``rolling_adf_pvalue`` recomputes every ``step`` bars on the window that
ends at that bar and carries the value forward. The number at t never uses
data after t. A bad window (too short, or a numerical failure) publishes NaN
and does not raise, so a broken future bar cannot erase the past.

Honest use: a pre-filter before mean-reversion or pairs research. A
stationary in-sample spread does not stay stationary out of sample.
``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
from statsmodels.tools.sm_exceptions import InterpolationWarning
from statsmodels.tsa.stattools import adfuller, kpss

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING, as_1d, check_positive_int

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "StationarityReport",
    "mean_reversion_prefilter",
    "rolling_adf_pvalue",
    "stationarity_report",
]


@dataclass(frozen=True)
class StationarityReport:
    adf_stat: float
    adf_pvalue: float
    kpss_stat: float
    kpss_pvalue: float
    verdict: str
    eligible_for_live_trading: bool = ELIGIBLE_FOR_LIVE_TRADING


def stationarity_report(
    x: object,
    alpha: float = 0.05,
    regression: Literal["c", "ct"] = "c",
) -> StationarityReport:
    """Combined ADF (autolag AIC) and KPSS (automatic lags) on the finite points."""
    series = as_1d(x, "x")
    series = series[np.isfinite(series)]
    if len(series) < 20:
        raise ValueError("need at least 20 finite observations")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InterpolationWarning)
        warnings.simplefilter("ignore", FutureWarning)
        adf = adfuller(series, regression=regression, autolag="AIC")
        kp = kpss(series, regression=regression, nlags="auto")
    adf_rej = bool(adf[1] < alpha)
    kpss_rej = bool(kp[1] < alpha)
    if adf_rej and not kpss_rej:
        verdict = "stationary"
    elif not adf_rej and kpss_rej:
        verdict = "non_stationary"
    elif adf_rej and kpss_rej:
        verdict = "difference_or_inconclusive"
    else:
        verdict = "trend_or_inconclusive"
    return StationarityReport(float(adf[0]), float(adf[1]), float(kp[0]), float(kp[1]), verdict)


def mean_reversion_prefilter(x: object, alpha: float = 0.05) -> dict[str, object]:
    """JSON-safe pre-filter. ``candidate`` is true only when both tests agree on stationarity."""
    report = stationarity_report(x, alpha=alpha)
    return {
        "verdict": report.verdict,
        "candidate": report.verdict == "stationary",
        "adf_stat": _json_float(report.adf_stat),
        "adf_pvalue": _json_float(report.adf_pvalue),
        "kpss_stat": _json_float(report.kpss_stat),
        "kpss_pvalue": _json_float(report.kpss_pvalue),
        "alpha": alpha,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "use": "prefilter_only",
    }


def _json_float(value: float, ndigits: int = 6) -> float | None:
    v = float(value)
    if not np.isfinite(v):
        return None
    return round(v, ndigits)


def rolling_adf_pvalue(
    x: object,
    window: int = 250,
    step: int = 5,
    regression: str = "c",
) -> np.ndarray:
    """ADF p-value of the window ending at t, recomputed every ``step`` bars and carried forward."""
    series = as_1d(x, "x")
    check_positive_int(window, "window", 20)
    check_positive_int(step, "step")
    out = np.full(len(series), np.nan)
    last = np.nan
    for t in range(window - 1, len(series)):
        if (t - (window - 1)) % step == 0:
            w = series[t - window + 1 : t + 1]
            w = w[np.isfinite(w)]
            if len(w) < 20:
                last = np.nan
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", FutureWarning)
                        warnings.simplefilter("ignore", InterpolationWarning)
                        last = float(adfuller(w, regression=regression, autolag="AIC")[1])
                except (ValueError, np.linalg.LinAlgError):
                    last = np.nan
        out[t] = last
    return out

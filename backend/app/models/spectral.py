"""Causal Fourier diagnostics: dominant period and spectral entropy.

The periodogram is linear-detrended and Hann-tapered. Entropy is 0 for one
pure cycle and 1 for a flat spectrum. ``rolling_spectral`` evaluates the
window that ends at t, so the print at t does not use later bars.

Market returns sit near white noise (entropy near 1). A cycle found in a
price level is usually the trend the detrend did not fully remove. This is
a diagnostic, not a signal. ``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import periodogram

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING, as_1d, check_positive_int

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "SpectralRolling",
    "periodogram_peak",
    "rolling_spectral",
    "spectral_entropy",
]


def _spectrum(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    freq, power = periodogram(x, detrend="linear", window="hann", scaling="spectrum")
    return freq[1:], power[1:]


def periodogram_peak(x: object) -> float:
    """Dominant period, in samples, of the finite points of ``x``."""
    series = as_1d(x, "x")
    series = series[np.isfinite(series)]
    if len(series) < 8:
        raise ValueError("need at least 8 finite points")
    freq, power = _spectrum(series)
    return float(1.0 / freq[int(np.argmax(power))])


def spectral_entropy(x: object) -> float:
    """Normalised Shannon entropy of the periodogram, in [0, 1]."""
    series = as_1d(x, "x")
    series = series[np.isfinite(series)]
    if len(series) < 8:
        raise ValueError("need at least 8 finite points")
    _, power = _spectrum(series)
    total = float(power.sum())
    if total <= 0:
        return float("nan")
    q = power / total
    q = q[q > 0]
    return float(-(q * np.log(q)).sum() / np.log(len(power)))


@dataclass(frozen=True)
class SpectralRolling:
    dominant_period: np.ndarray
    entropy: np.ndarray
    eligible_for_live_trading: bool = ELIGIBLE_FOR_LIVE_TRADING


def rolling_spectral(x: object, window: int = 128) -> SpectralRolling:
    """Dominant period and spectral entropy of the window ending at t."""
    series = as_1d(x, "x")
    check_positive_int(window, "window", 8)
    period = np.full(len(series), np.nan)
    entropy = np.full(len(series), np.nan)
    need = max(8, window // 2)
    for t in range(window - 1, len(series)):
        w = series[t - window + 1 : t + 1]
        if int(np.sum(np.isfinite(w))) < need:
            continue
        period[t] = periodogram_peak(w)
        entropy[t] = spectral_entropy(w)
    return SpectralRolling(period, entropy)

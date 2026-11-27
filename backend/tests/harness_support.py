"""Shared series for harness tests. Paper research only."""

from __future__ import annotations

import math

import numpy as np

from app.harness.types import ExperimentSpec


def strong_returns(length: int = 2000) -> np.ndarray:
    rng = np.random.default_rng(1)
    vol = 0.01
    mu = 3.0 / math.sqrt(252) * vol
    return rng.normal(mu, vol, size=length)


def weak_returns(length: int = 400) -> np.ndarray:
    return np.random.default_rng(0).normal(-0.0005, 0.01, size=length)


def prices_from_returns(returns: np.ndarray, start: float = 100.0) -> np.ndarray:
    growth = np.cumprod(1.0 + np.asarray(returns, dtype=np.float64))
    prices = np.concatenate([[start], start * growth])
    if np.any(prices <= 0) or not np.all(np.isfinite(prices)):
        raise RuntimeError("test prices left the positive reals")
    return prices


def make_spec(returns: np.ndarray, **overrides: object) -> ExperimentSpec:
    prices = prices_from_returns(returns)
    signal = overrides.pop("signal", None)
    if signal is None:
        signal_values = tuple(1.0 for _ in returns)
    else:
        signal_values = tuple(float(value) for value in signal)  # type: ignore[union-attr]
    matrix = overrides.pop("feature_matrix", None)
    if matrix is None:
        lagged = np.zeros(len(returns), dtype=np.float64)
        lagged[1:] = np.asarray(returns, dtype=np.float64)[:-1]
        feature_matrix = tuple((float(value),) for value in lagged)
    else:
        feature_matrix = tuple(tuple(float(value) for value in row) for row in matrix)  # type: ignore[union-attr]
    params: dict[str, object] = {
        "statement": "Lagged drift is a testable paper hypothesis.",
        "family": "harness-family",
        "feature_names": ("lagged_return",),
        "feature_formulas": ("prior close-to-close return",),
        "prices": tuple(float(value) for value in prices),
        "signal": signal_values,
        "feature_matrix": feature_matrix,
        "lag": 1,
        "commission_bps": 5.0,
        "slippage_bps": 5.0,
        "half_spread_bps": 2.0,
        "n_trials": 2,
    }
    params.update(overrides)
    return ExperimentSpec(**params)  # type: ignore[arg-type]

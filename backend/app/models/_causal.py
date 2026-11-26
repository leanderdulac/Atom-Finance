"""Shared checks for causal research tools.

Paper only. Nothing here sizes or sends an order.
``eligible_for_live_trading`` stays false at every call site that reports a decision.
"""

from __future__ import annotations

import numpy as np

ELIGIBLE_FOR_LIVE_TRADING = False


def as_1d(x: object, name: str = "x") -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {a.shape}")
    return a


def as_2d(x: object, name: str = "X") -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2:
        raise ValueError(f"{name} must be 2-D, got shape {a.shape}")
    return a


def check_positive_int(v: object, name: str, minimum: int = 1) -> int:
    if isinstance(v, bool) or not isinstance(v, int | np.integer) or int(v) < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {v!r}")
    return int(v)


def finite_rows(x: np.ndarray) -> np.ndarray:
    """True where every column of the row is finite."""
    return np.all(np.isfinite(x), axis=1)


def refit_points(n: int, min_train: int, refit_every: int) -> list[int]:
    """Times k at which a model may be refit.

    The model refit at k is trained only on rows strictly before k and scores
    rows k .. next_k-1. That is the causality contract of the rolling ML tools.
    """
    if isinstance(n, bool) or not isinstance(n, int | np.integer) or int(n) < 0:
        raise ValueError(f"n must be an integer >= 0, got {n!r}")
    return list(range(int(min_train), int(n), int(refit_every)))

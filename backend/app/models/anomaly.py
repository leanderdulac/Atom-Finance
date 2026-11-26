"""Causal Isolation Forest for risk and data-quality flags.

The model refit at time k is trained only on rows strictly before k. It
scores rows k .. next refit. The flag threshold is the (1 − contamination)
quantile of the training anomaly scores, also past-only. A full-sample fit
would leak the future into every flag; this one does not.

Higher ``score`` means more anomalous (``-score_samples``). The flag is a
pause / widen-stops input for the desk monitor, not a return predictor.
An extreme equity day is usually real, not a bad print.
``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

from app.models._causal import (
    ELIGIBLE_FOR_LIVE_TRADING,
    as_2d,
    check_positive_int,
    finite_rows,
    refit_points,
)

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "AnomalyResult",
    "latest_quality_flag",
    "rolling_isolation_forest",
]


@dataclass(frozen=True)
class AnomalyResult:
    score: np.ndarray
    threshold: np.ndarray
    flag: np.ndarray


def rolling_isolation_forest(
    x: object,
    min_train: int = 250,
    window: int | None = 500,
    refit_every: int = 20,
    contamination: float = 0.05,
    n_estimators: int = 200,
    random_state: int = 0,
) -> AnomalyResult:
    """Rolling Isolation Forest. Rows with a non-finite value are left unscored."""
    data = as_2d(x)
    n = len(data)
    check_positive_int(min_train, "min_train", 10)
    check_positive_int(refit_every, "refit_every")
    check_positive_int(n_estimators, "n_estimators", 10)
    if window is not None:
        check_positive_int(window, "window", 10)
    if not (0.0 < contamination < 0.5):
        raise ValueError("contamination must be in (0, 0.5)")
    ok = finite_rows(data)
    score = np.full(n, np.nan)
    threshold = np.full(n, np.nan)
    points = refit_points(n, min_train, refit_every)
    for j, k in enumerate(points):
        lo = 0 if window is None else max(0, k - window)
        train = data[lo:k][ok[lo:k]]
        if len(train) < 10:
            continue
        model = IsolationForest(
            n_estimators=n_estimators,
            contamination="auto",
            random_state=random_state,
        ).fit(train)
        train_score = -model.score_samples(train)
        level = float(np.quantile(train_score, 1.0 - contamination))
        hi = points[j + 1] if j + 1 < len(points) else n
        rows = np.arange(k, hi)
        rows = rows[ok[k:hi]]
        if len(rows):
            score[rows] = -model.score_samples(data[rows])
        threshold[k:hi] = level
    flag = np.zeros(n, dtype=bool)
    valid = np.isfinite(score) & np.isfinite(threshold)
    flag[valid] = score[valid] > threshold[valid]
    return AnomalyResult(score, threshold, flag)


def latest_quality_flag(
    returns: object,
    *,
    min_train: int = 60,
    window: int | None = 120,
    refit_every: int = 20,
    contamination: float = 0.05,
    n_estimators: int = 100,
    random_state: int = 0,
) -> dict[str, object]:
    """Last causal flag on a return history. Pause input for the monitor, not a signal."""
    result = rolling_isolation_forest(
        returns,
        min_train=min_train,
        window=window,
        refit_every=refit_every,
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=random_state,
    )
    score = float(result.score[-1]) if len(result.score) else float("nan")
    level = float(result.threshold[-1]) if len(result.threshold) else float("nan")
    flagged = bool(result.flag[-1]) if len(result.flag) else False
    return {
        "flag": flagged,
        "score": None if not np.isfinite(score) else round(score, 6),
        "threshold": None if not np.isfinite(level) else round(level, 6),
        "n": int(len(result.score)),
        "use": "risk_or_data_quality_filter",
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }

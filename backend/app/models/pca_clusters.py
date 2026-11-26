"""Causal PCA and K-Means for pair pre-filters and regime tags.

* ``rolling_pca`` — absorption ratio (share of correlation-matrix variance in
  the top components; Kritzman et al. 2011) and PC1 weights, from the window
  that ends at t.
* ``cluster_assets`` / ``rolling_asset_clusters`` — K-Means on PCA loadings.
  Labels are canonical (order of first appearance) so refits can be compared.
  The fit at k uses rows strictly before k.
* ``kmeans_regimes`` — K-Means on feature rows. The fit uses the past only.
  Label 0 is the cluster whose centroid is lowest on ``order_by``.

Complement of the rule-based classifier in ``regime.py``. None of these
predict a return by themselves. ``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from app.models._causal import (
    ELIGIBLE_FOR_LIVE_TRADING,
    as_2d,
    check_positive_int,
    finite_rows,
    refit_points,
)

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "RollingPCAResult",
    "cluster_assets",
    "kmeans_regimes",
    "rolling_asset_clusters",
    "rolling_pca",
]


def _corr_eig(returns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sd = returns.std(axis=0, ddof=1)
    if np.any(sd <= 0):
        raise ValueError("an asset has zero variance in the window")
    corr = np.corrcoef(returns, rowvar=False)
    vals, vecs = np.linalg.eigh(corr)
    order = np.argsort(vals)[::-1]
    vals = np.clip(vals[order], 0.0, None)
    vecs = vecs[:, order]
    signs = np.sign(vecs.sum(axis=0))
    signs[signs == 0.0] = 1.0
    return vals, vecs * signs


def _canonical_labels(labels: np.ndarray) -> np.ndarray:
    """Renumber clusters by order of first appearance."""
    mapping: dict[int, int] = {}
    out = np.empty(len(labels), dtype=int)
    for i, lab in enumerate(labels):
        key = int(lab)
        if key not in mapping:
            mapping[key] = len(mapping)
        out[i] = mapping[key]
    return out


@dataclass(frozen=True)
class RollingPCAResult:
    absorption_ratio: np.ndarray
    pc1_weights: np.ndarray
    eligible_for_live_trading: bool = ELIGIBLE_FOR_LIVE_TRADING


def rolling_pca(returns: object, window: int = 120, n_components: int = 1) -> RollingPCAResult:
    """Absorption ratio and PC1 weights of the window that ends at t."""
    data = as_2d(returns, "returns")
    n, m = data.shape
    check_positive_int(window, "window", 3)
    check_positive_int(n_components, "n_components")
    if n_components > m:
        raise ValueError("n_components > number of assets")
    ok = finite_rows(data)
    absorption = np.full(n, np.nan)
    weights = np.full((n, m), np.nan)
    min_rows = max(3, window // 2)
    for t in range(window - 1, n):
        if not ok[t]:
            continue
        block = data[t - window + 1 : t + 1][ok[t - window + 1 : t + 1]]
        if len(block) < min_rows:
            continue
        try:
            vals, vecs = _corr_eig(block)
        except ValueError:
            continue
        total = float(vals.sum())
        if total <= 0:
            continue
        absorption[t] = float(vals[:n_components].sum() / total)
        v = vecs[:, 0]
        denom = float(v.sum())
        if abs(denom) > 1e-12:
            weights[t] = v / denom
    return RollingPCAResult(absorption, weights)


def _fit_kmeans(samples: np.ndarray, n_clusters: int, random_state: int) -> KMeans:
    """Ten restarts. sklearn 1.5 types n_init as str because the default is auto."""
    ctor = cast(Any, KMeans)
    model = ctor(n_clusters=n_clusters, n_init=10, random_state=random_state)
    model.fit(samples)
    return model


def cluster_assets(
    returns_window: object,
    n_clusters: int = 3,
    n_components: int = 3,
    random_state: int = 0,
) -> np.ndarray:
    """K-Means on PCA loadings (eigenvector × √eigenvalue) of one window. One label per asset."""
    data = as_2d(returns_window, "returns_window")
    data = data[finite_rows(data)]
    m = data.shape[1]
    if not (1 <= n_clusters <= m):
        raise ValueError("n_clusters must be in [1, n_assets]")
    vals, vecs = _corr_eig(data)
    k = min(n_components, m)
    load = vecs[:, :k] * np.sqrt(vals[:k])
    model = _fit_kmeans(load, n_clusters, random_state)
    return _canonical_labels(np.asarray(model.labels_, dtype=int))


def rolling_asset_clusters(
    returns: object,
    window: int = 250,
    refit_every: int = 20,
    n_clusters: int = 3,
    n_components: int = 3,
    random_state: int = 0,
) -> np.ndarray:
    """(n, m) labels. Row t comes from a fit on the window strictly before the last refit ≤ t."""
    data = as_2d(returns, "returns")
    n, m = data.shape
    check_positive_int(window, "window", 3)
    check_positive_int(refit_every, "refit_every")
    out = np.full((n, m), np.nan)
    points = refit_points(n, window, refit_every)
    for j, k in enumerate(points):
        hi = points[j + 1] if j + 1 < len(points) else n
        try:
            labels = cluster_assets(data[k - window : k], n_clusters, n_components, random_state)
        except ValueError:
            continue
        out[k:hi] = labels
    return out


def kmeans_regimes(
    features: object,
    n_clusters: int = 3,
    min_train: int = 250,
    window: int | None = None,
    refit_every: int = 20,
    order_by: int = 0,
    random_state: int = 0,
) -> np.ndarray:
    """Causal regime labels. Label 0 is the cluster with the lowest centroid on ``order_by``."""
    data = as_2d(features, "features")
    n, d = data.shape
    if not (0 <= order_by < d):
        raise ValueError("order_by out of range")
    check_positive_int(n_clusters, "n_clusters", 2)
    check_positive_int(min_train, "min_train", n_clusters * 5)
    check_positive_int(refit_every, "refit_every")
    if window is not None:
        check_positive_int(window, "window", n_clusters * 5)
    ok = finite_rows(data)
    labels = np.full(n, np.nan)
    points = refit_points(n, min_train, refit_every)
    for j, k in enumerate(points):
        lo = 0 if window is None else max(0, k - window)
        train = data[lo:k][ok[lo:k]]
        if len(train) < n_clusters * 5:
            continue
        scaler = StandardScaler().fit(train)
        model = _fit_kmeans(np.asarray(scaler.transform(train)), n_clusters, random_state)
        centers = scaler.inverse_transform(model.cluster_centers_)
        rank = np.empty(n_clusters, dtype=int)
        rank[np.argsort(centers[:, order_by], kind="stable")] = np.arange(n_clusters)
        hi = points[j + 1] if j + 1 < len(points) else n
        rows = np.arange(k, hi)[ok[k:hi]]
        if len(rows):
            predicted = model.predict(scaler.transform(data[rows]))
            labels[rows] = rank[predicted]
    return labels

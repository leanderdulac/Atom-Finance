"""Causal autoencoder: common factor and idiosyncratic residual.

A bottleneck MLP (X → X) is fit on a past window of cross-sectional returns,
standardised with that window's mean and standard deviation. For row t it
returns the reconstruction (common part), the residual in original units,
the RMS of the standardised residual, and the bottleneck activation.

The model refit at k trains only on rows strictly before k. With
``activation='identity'`` the map is a linear autoencoder; ``tanh`` allows a
non-linear common factor. Deterministic for a fixed ``random_state`` (lbfgs).

Honest use: residual research and a stress diagnostic. Not a trading signal.
``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPRegressor

from app.models._causal import (
    ELIGIBLE_FOR_LIVE_TRADING,
    as_2d,
    check_positive_int,
    finite_rows,
    refit_points,
)

__all__ = [
    "ELIGIBLE_FOR_LIVE_TRADING",
    "AutoencoderResult",
    "rolling_autoencoder",
]


@dataclass(frozen=True)
class AutoencoderResult:
    reconstruction: np.ndarray
    residual: np.ndarray
    error: np.ndarray
    latent: np.ndarray
    eligible_for_live_trading: bool = ELIGIBLE_FOR_LIVE_TRADING


def _activate(h: np.ndarray, activation: str) -> np.ndarray:
    if activation == "tanh":
        return np.tanh(h)
    if activation == "relu":
        return np.maximum(h, 0.0)
    if activation == "logistic":
        return 1.0 / (1.0 + np.exp(-h))
    return h


def rolling_autoencoder(
    returns: object,
    latent_dim: int = 2,
    min_train: int = 250,
    window: int | None = 500,
    refit_every: int = 20,
    activation: str = "tanh",
    alpha: float = 1e-4,
    max_iter: int = 2000,
    random_state: int = 0,
) -> AutoencoderResult:
    """Past-only autoencoder. Unscored rows (and the warm-up) stay NaN."""
    data = as_2d(returns, "returns")
    n, m = data.shape
    check_positive_int(latent_dim, "latent_dim")
    if latent_dim >= m:
        raise ValueError("latent_dim must be smaller than the number of assets")
    check_positive_int(min_train, "min_train", 20)
    check_positive_int(refit_every, "refit_every")
    check_positive_int(max_iter, "max_iter", 1)
    if activation not in ("identity", "logistic", "tanh", "relu"):
        raise ValueError("activation must be identity, logistic, tanh or relu")
    if window is not None:
        check_positive_int(window, "window", 20)
    ok = finite_rows(data)
    reconstruction = np.full((n, m), np.nan)
    residual = np.full((n, m), np.nan)
    error = np.full(n, np.nan)
    latent = np.full((n, latent_dim), np.nan)
    points = refit_points(n, min_train, refit_every)
    for j, k in enumerate(points):
        lo = 0 if window is None else max(0, k - window)
        train = data[lo:k][ok[lo:k]]
        if len(train) < 20:
            continue
        mu = train.mean(axis=0)
        sd = train.std(axis=0, ddof=1)
        sd = np.where(sd <= 0, 1.0, sd)
        z = (train - mu) / sd
        net = MLPRegressor(
            hidden_layer_sizes=(latent_dim,),
            activation=activation,
            solver="lbfgs",
            alpha=alpha,
            max_iter=max_iter,
            random_state=random_state,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            net.fit(z, z)
        hi = points[j + 1] if j + 1 < len(points) else n
        rows = np.arange(k, hi)[ok[k:hi]]
        if len(rows) == 0:
            continue
        z_t = (data[rows] - mu) / sd
        z_hat = np.asarray(net.predict(z_t), dtype=np.float64)
        reconstruction[rows] = z_hat * sd + mu
        residual[rows] = data[rows] - reconstruction[rows]
        error[rows] = np.sqrt(np.mean((z_t - z_hat) ** 2, axis=1))
        hidden = z_t @ np.asarray(net.coefs_[0], dtype=np.float64) + np.asarray(net.intercepts_[0])
        latent[rows] = _activate(hidden, activation)
    return AutoencoderResult(reconstruction, residual, error, latent)

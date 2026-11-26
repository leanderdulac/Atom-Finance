"""Causal Kalman filters for a dynamic hedge ratio.

Two forward filters (filtering, never smoothing). The value at t uses
observations up to and including t only:

* ``local_level_filter`` — random-walk level observed with noise.
* ``kalman_regression`` — y_t = α_t + β_t x_t + e_t with random-walk
  coefficients (Chan 2013, ch. 3). ``beta_prior`` is known strictly before
  the observation at t; ``beta`` / ``alpha`` are the posterior after it.
  The traded mispricing is the innovation and its predicted variance Q_t.

A missing observation (NaN) runs the prediction step only: the state is
carried and its variance grows. Innovation, Q_t and the z-score stay NaN.

``delta`` and ``obs_var`` are hyperparameters. Choose them on an in-sample
prefix (``select_kalman_hyperparams``) and freeze them. They are not a
source of alpha. ``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING, as_1d

# Pre-registered grid. Scales multiply the in-sample OLS residual variance
# so the observation noise sits on the same scale as the spread.
DELTA_GRID: tuple[float, ...] = (1e-5, 1e-4, 1e-3)
OBS_SCALE_GRID: tuple[float, ...] = (0.25, 1.0, 4.0)

__all__ = [
    "DELTA_GRID",
    "ELIGIBLE_FOR_LIVE_TRADING",
    "OBS_SCALE_GRID",
    "KalmanHyperparams",
    "KalmanRegressionResult",
    "LocalLevelResult",
    "kalman_regression",
    "local_level_filter",
    "select_kalman_hyperparams",
]


@dataclass(frozen=True)
class LocalLevelResult:
    level: np.ndarray
    variance: np.ndarray
    innovation: np.ndarray
    innovation_var: np.ndarray


def local_level_filter(
    y: object,
    q: float,
    r: float,
    x0: float | None = None,
    p0: float = 1e6,
) -> LocalLevelResult:
    """Random walk plus noise. ``q`` is state variance, ``r`` observation variance."""
    series = as_1d(y, "y")
    if q < 0 or r <= 0:
        raise ValueError("q must be >= 0 and r > 0")
    n = len(series)
    level = np.full(n, np.nan)
    var = np.full(n, np.nan)
    innov = np.full(n, np.nan)
    innov_var = np.full(n, np.nan)
    x = 0.0 if x0 is None else float(x0)
    p = float(p0)
    started = x0 is not None
    for t in range(n):
        p_pred = p + q if started else p
        if not np.isfinite(series[t]):
            p = p_pred
            if started:
                level[t] = x
                var[t] = p
            continue
        if not started and x0 is None:
            x = float(series[t])
            p = float(r)
            started = True
            level[t], var[t] = x, p
            continue
        st = p_pred + r
        e = float(series[t]) - x
        k = p_pred / st
        x = x + k * e
        p = (1.0 - k) * p_pred
        level[t], var[t], innov[t], innov_var[t] = x, p, e, st
    return LocalLevelResult(level, var, innov, innov_var)


@dataclass(frozen=True)
class KalmanRegressionResult:
    beta: np.ndarray
    alpha: np.ndarray
    beta_prior: np.ndarray
    alpha_prior: np.ndarray
    spread: np.ndarray
    spread_var: np.ndarray
    zscore: np.ndarray


def kalman_regression(
    y: object,
    x: object,
    delta: float = 1e-4,
    obs_var: float = 1e-3,
    p0: float = 1e3,
) -> KalmanRegressionResult:
    """Dynamic hedge ratio. ``delta`` in (0, 1) is how fast β may drift.

    State θ = [β, α], random-walk transition, state noise
    (δ / (1 − δ)) I, observation noise ``obs_var``. The innovation at the
    first finite bar is against an uninformative prior and is not published.
    """
    yy = as_1d(y, "y")
    xx = as_1d(x, "x")
    if len(xx) != len(yy):
        raise ValueError("x and y must have the same length")
    if not (0.0 < delta < 1.0) or obs_var <= 0:
        raise ValueError("delta must be in (0, 1) and obs_var > 0")
    n = len(yy)
    vw = (delta / (1.0 - delta)) * np.eye(2)
    theta = np.zeros(2)
    p_state = np.eye(2) * float(p0)
    beta = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    beta_prior = np.full(n, np.nan)
    alpha_prior = np.full(n, np.nan)
    spread = np.full(n, np.nan)
    spread_var = np.full(n, np.nan)
    zscore = np.full(n, np.nan)
    started = False
    for t in range(n):
        r_pred = p_state + vw if started else p_state
        if started:
            beta_prior[t] = theta[0]
            alpha_prior[t] = theta[1]
        if not (np.isfinite(yy[t]) and np.isfinite(xx[t])):
            p_state = r_pred
            if started:
                beta[t], alpha[t] = theta
            continue
        f = np.array([xx[t], 1.0])
        yhat = float(f @ theta)
        q_t = float(f @ r_pred @ f) + obs_var
        e = float(yy[t]) - yhat
        k = r_pred @ f / q_t
        theta = theta + k * e
        p_state = r_pred - np.outer(k, f) @ r_pred
        p_state = 0.5 * (p_state + p_state.T)
        beta[t], alpha[t] = theta
        if started:
            spread[t] = e
            spread_var[t] = q_t
            zscore[t] = e / np.sqrt(q_t)
        started = True
    return KalmanRegressionResult(beta, alpha, beta_prior, alpha_prior, spread, spread_var, zscore)


@dataclass(frozen=True)
class KalmanHyperparams:
    """Hyperparameters chosen on one in-sample slice. Freeze them out of sample."""

    delta: float
    obs_var: float
    innovation_nll: float
    n: int
    eligible_for_live_trading: bool = ELIGIBLE_FOR_LIVE_TRADING


def _residual_scale(y: np.ndarray, x: np.ndarray) -> float:
    mask = np.isfinite(y) & np.isfinite(x)
    yv = y[mask]
    xv = x[mask]
    if len(yv) < 20:
        raise ValueError("need at least 20 finite pairs to choose Kalman hyperparameters")
    design = np.column_stack([np.ones(len(yv)), xv])
    coef, _, _, _ = np.linalg.lstsq(design, yv, rcond=None)
    resid = yv - design @ coef
    scale = float(np.var(resid))
    if not np.isfinite(scale) or scale < 1e-12:
        scale = float(np.var(yv))
    if not np.isfinite(scale) or scale < 1e-12:
        scale = 1.0
    return scale


def _innovation_nll(spread: np.ndarray, spread_var: np.ndarray) -> float:
    ok = np.isfinite(spread) & np.isfinite(spread_var) & (spread_var > 0)
    if int(ok.sum()) < 30:
        return float("inf")
    e = spread[ok]
    q = spread_var[ok]
    return float(0.5 * np.sum(np.log(q) + (e * e) / q))


def select_kalman_hyperparams(
    y: object,
    x: object,
    *,
    deltas: tuple[float, ...] = DELTA_GRID,
    obs_scales: tuple[float, ...] = OBS_SCALE_GRID,
) -> KalmanHyperparams:
    """Minimise the Gaussian innovation NLL on the slice that was passed in.

    The caller decides the slice. Pass only the in-sample prefix — this
    function does not look past the arrays it receives.
    """
    yy = as_1d(y, "y")
    xx = as_1d(x, "x")
    if len(yy) != len(xx):
        raise ValueError("x and y must have the same length")
    if len(deltas) == 0 or len(obs_scales) == 0:
        raise ValueError("delta and obs_var grids must be non-empty")
    scale = _residual_scale(yy, xx)
    best: KalmanHyperparams | None = None
    for delta in deltas:
        for mult in obs_scales:
            obs_var = float(scale * mult)
            fit = kalman_regression(yy, xx, delta=float(delta), obs_var=obs_var)
            nll = _innovation_nll(fit.spread, fit.spread_var)
            if best is None or nll < best.innovation_nll:
                best = KalmanHyperparams(float(delta), obs_var, nll, int(len(yy)))
    if best is None or not np.isfinite(best.innovation_nll):
        raise ValueError("Kalman grid produced no finite innovation likelihood")
    return best

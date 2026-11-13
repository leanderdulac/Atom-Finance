"""
Error-maximizer lab: analytical GMV on a sample covariance vs Ledoit–Wolf.

Markowitz ``w* = Σ⁻¹ 1 / (1' Σ⁻¹ 1)`` is taught as gospel. On N assets and
~252 days the sample Σ has Marchenko–Pastur-crushed eigenvalues; inversion
loads the portfolio on risks that were underestimated by luck. Linear
shrinkage (Ledoit–Wolf, constant-correlation target) restores conditioning
before the same inversion.

Paper research. eligible_for_live_trading stays false. This is not
POST /api/ml/evaluate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from app.models.covariance import (
    condition_number,
    correlation_from_cov,
    eigs_descending,
    global_min_variance,
    ledoit_wolf_constant_correlation,
    marchenko_pastur_bounds,
    sample_covariance,
    weight_stats,
)

_WHAT_BROKE = [
    "Constant-correlation F is a structured guess, not the true Σ.",
    "α* is optimal under a Frobenius risk; it is not a Sharpe maximizer.",
    "GMV ignores expected returns — mean estimates are even noisier.",
    "One-factor synthetic DGP; equities have multiple factors and jumps.",
    "OOS here is a research holdout, not evidence. eligible_for_live_trading stays false.",
]


def factor_panel(
    n_assets: int = 80,
    n_obs: int = 315,
    *,
    seed: int = 7,
    factor_vol: float = 0.01,
    idio_vol: float = 0.012,
) -> tuple[np.ndarray, np.ndarray]:
    """One-factor returns (T × N) and the true covariance used to draw them."""
    if n_assets < 2 or n_obs < 16:
        raise ValueError("Need N≥2 assets and T≥16 observations")
    rng = np.random.default_rng(seed)
    beta = rng.uniform(0.4, 1.6, size=n_assets)
    idio = rng.uniform(0.6, 1.4, size=n_assets) * idio_vol
    factor = rng.normal(0.0, factor_vol, size=n_obs)
    noise = rng.normal(0.0, 1.0, size=(n_obs, n_assets)) * idio
    returns = factor[:, None] * beta[None, :] + noise
    true_cov = (factor_vol**2) * np.outer(beta, beta) + np.diag(idio**2)
    return returns, true_cov


def _realized_vol(returns: np.ndarray, weights: np.ndarray) -> float:
    pnl = np.asarray(returns, dtype=np.float64) @ np.asarray(weights, dtype=np.float64)
    if len(pnl) < 2:
        return float("nan")
    return float(np.std(pnl, ddof=1) * np.sqrt(252.0))


def _turnover_path(
    returns: np.ndarray,
    *,
    window: int,
    step: int,
    shrunk: bool,
) -> float:
    """Mean one-way turnover |Δw|/2 across rolling GMV rebalances."""
    t, _n = returns.shape
    if t < window + step:
        return float("nan")
    prev: np.ndarray | None = None
    turns: list[float] = []
    for end in range(window, t + 1, step):
        block = returns[end - window : end]
        cov = ledoit_wolf_constant_correlation(block)[0] if shrunk else sample_covariance(block)
        w = global_min_variance(cov)
        if prev is not None:
            turns.append(float(np.sum(np.abs(w - prev)) / 2.0))
        prev = w
    if not turns:
        return float("nan")
    return float(np.mean(turns))


def _spectrum_payload(cov: np.ndarray, cap: int = 40) -> list[float]:
    vals = eigs_descending(correlation_from_cov(cov))
    if len(vals) > cap:
        idx = np.linspace(0, len(vals) - 1, cap).round().astype(int)
        vals = vals[idx]
    return [round(float(v), 5) for v in vals]


def evaluate(
    *,
    returns: Sequence[Sequence[float]] | None = None,
    n_assets: int = 80,
    t_is: int = 252,
    t_oos: int = 63,
    seed: int = 7,
    rebalance_every: int = 21,
) -> dict[str, Any]:
    if t_is < 30 or t_oos < 10:
        raise ValueError("Need t_is≥30 and t_oos≥10")
    if returns is not None:
        panel = np.asarray(returns, dtype=np.float64)
        if panel.ndim != 2 or panel.shape[0] < t_is + t_oos or panel.shape[1] < 2:
            raise ValueError("Caller returns must be T×N with T ≥ t_is + t_oos and N≥2")
        if not np.all(np.isfinite(panel)):
            raise ValueError("Returns must be finite")
        true_cov = None
        source = "caller"
    else:
        panel, true_cov = factor_panel(n_assets, t_is + t_oos, seed=seed)
        source = "synthetic_one_factor"

    is_ret = panel[:t_is]
    oos_ret = panel[t_is : t_is + t_oos]
    n = is_ret.shape[1]
    sample = sample_covariance(is_ret)
    shrunk, lw_meta = ledoit_wolf_constant_correlation(is_ret)

    w_sample = global_min_variance(sample)
    w_lw = global_min_variance(shrunk)
    w_true = global_min_variance(true_cov) if true_cov is not None else None

    mp = marchenko_pastur_bounds(n, t_is)
    sample_eigs = eigs_descending(correlation_from_cov(sample))
    lw_eigs = eigs_descending(correlation_from_cov(shrunk))
    n_below = int(np.sum(sample_eigs < mp["lambda_minus"] + 1e-12))

    oos_sample = _realized_vol(oos_ret, w_sample)
    oos_lw = _realized_vol(oos_ret, w_lw)
    oos_true = _realized_vol(oos_ret, w_true) if w_true is not None else None
    oos_eq = _realized_vol(oos_ret, np.ones(n) / n)

    turn_sample = _turnover_path(panel[: t_is + t_oos], window=t_is, step=rebalance_every, shrunk=False)
    turn_lw = _turnover_path(panel[: t_is + t_oos], window=t_is, step=rebalance_every, shrunk=True)

    cond_s = condition_number(sample)
    cond_lw = condition_number(shrunk)

    return {
        "pair": None,
        "mode": "paper_only",
        "n_assets": int(n),
        "t_is": int(t_is),
        "t_oos": int(t_oos),
        "source": source,
        "data": {"n_assets": int(n), "t_is": int(t_is), "t_oos": int(t_oos), "source": source},
        "gmv": {
            "formula": "w* = Σ⁻¹ 1 / (1' Σ⁻¹ 1)",
            "sample": weight_stats(w_sample),
            "ledoit_wolf": weight_stats(w_lw),
            "true": None if w_true is None else weight_stats(w_true),
        },
        "covariance": {
            "sample_condition": None if not np.isfinite(cond_s) else round(cond_s, 2),
            "lw_condition": None if not np.isfinite(cond_lw) else round(cond_lw, 2),
            "sample_min_eig": round(float(sample_eigs[-1]), 6),
            "lw_min_eig": round(float(lw_eigs[-1]), 6),
            "ledoit_wolf": lw_meta,
        },
        "marchenko_pastur": {
            **mp,
            "n_sample_eigs_below_bulk": n_below,
            "note": "Smallest sample eigenvalues sit below λ₋ by chance; Σ⁻¹ turns them into huge weights.",
        },
        "spectrum": {
            "sample": _spectrum_payload(sample),
            "ledoit_wolf": _spectrum_payload(shrunk),
        },
        "oos": {
            "vol_sample": round(oos_sample, 6),
            "vol_ledoit_wolf": round(oos_lw, 6),
            "vol_true_gmv": None if oos_true is None else round(oos_true, 6),
            "vol_equal_weight": round(oos_eq, 6),
            "sample_minus_lw": round(oos_sample - oos_lw, 6),
        },
        "turnover": {
            "rebalance_every": int(rebalance_every),
            "sample": None if not np.isfinite(turn_sample) else round(turn_sample, 6),
            "ledoit_wolf": None if not np.isfinite(turn_lw) else round(turn_lw, 6),
        },
        "math": (
            "w* = Σ⁻¹ 1 / (1' Σ⁻¹ 1). Sample Σ on N assets and T days has Marchenko–Pastur "
            f"bulk [(1−√q)², (1+√q)²] with q=N/T={mp['q']}. Inverting crushed eigenvalues "
            "is the error maximizer. Ledoit–Wolf: Σ_LW = α* F + (1−α*) S, F = constant correlation."
        ),
        "what_broke": list(_WHAT_BROKE),
        "eligible_for_live_trading": False,
        "broker_orders_sent": 0,
        "out_of_sample": False,
    }

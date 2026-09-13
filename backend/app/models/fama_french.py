"""
Fama & French (2015) five-factor OLS decomposition.

The caller supplies aligned excess-return and factor series (Ken French library,
or any point-in-time analogue). This module does not scrape the French data
library and does not claim the factors are tradable in the user's market.
"""

from __future__ import annotations

import numpy as np

FACTOR_NAMES = ("mkt_rf", "smb", "hml", "rmw", "cma")


def _ols_with_se(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    n, k = x.shape
    coef, residuals, _, _ = np.linalg.lstsq(x, y, rcond=None)
    if residuals.size:
        sse = float(residuals[0])
    else:
        sse = float(np.sum((y - x @ coef) ** 2))
    df = max(n - k, 1)
    sigma2 = sse / df
    xtx_inv = np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.clip(sigma2 * np.diag(xtx_inv), 0, None))
    fitted = x @ coef
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 0.0
    return coef, se, r2, y - fitted


def decompose(
    excess_returns: np.ndarray,
    factors: dict[str, np.ndarray],
) -> dict:
    y = np.asarray(excess_returns, dtype=np.float64)
    cols = []
    used = []
    for name in FACTOR_NAMES:
        if name not in factors:
            raise ValueError(f"Missing factor series '{name}'")
        series = np.asarray(factors[name], dtype=np.float64)
        if series.shape != y.shape:
            raise ValueError(f"Factor {name} length {len(series)} != returns {len(y)}")
        cols.append(series)
        used.append(name)
    if len(y) < 36:
        raise ValueError("Need at least 36 observations for a 5-factor regression")
    if not np.all(np.isfinite(y)) or any(not np.all(np.isfinite(c)) for c in cols):
        raise ValueError("Returns and factors must be finite")

    x = np.column_stack([np.ones(len(y)), *cols])
    coef, se, r2, resid = _ols_with_se(y, x)
    tstats = coef / np.where(se > 0, se, np.nan)
    names = ("alpha", *used)
    loadings = {}
    for i, name in enumerate(names):
        loadings[name] = {
            "coef": round(float(coef[i]), 8),
            "se": round(float(se[i]), 8),
            "tstat": None if not np.isfinite(tstats[i]) else round(float(tstats[i]), 4),
        }
    alpha_ann = float(coef[0]) * 252
    resid_vol = float(np.std(resid, ddof=x.shape[1]) * np.sqrt(252))
    return {
        "loadings": loadings,
        "alpha_daily": round(float(coef[0]), 8),
        "alpha_annualized": round(alpha_ann, 6),
        "r_squared": round(float(r2), 4),
        "residual_vol_ann": round(resid_vol, 6),
        "n": int(len(y)),
        "math": (
            "R_t − R_f = α + β_MKT MKT_t + β_SMB SMB_t + β_HML HML_t "
            "+ β_RMW RMW_t + β_CMA CMA_t + ε_t  (Fama–French 2015)."
        ),
        "what_broke": [
            "OLS assumes homoskedastic ε; factor returns are clustered in crises (use HAC in a desk notebook).",
            "Alpha is not a tradable residual: you still have to short the factor portfolios, with borrow and capacity.",
            "Brazilian names mapped onto US FF5 loadings are a different experiment than this regression.",
            "No multiple-testing correction across a universe of names — a scanner will manufacture 'alpha'.",
        ],
        "eligible_for_live_trading": False,
    }

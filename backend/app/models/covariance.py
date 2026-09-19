"""Covariance estimators used by the desk — sample vs Ledoit–Wolf shrinkage.

The analytical GMV ``w* = Σ⁻¹ 1 / (1' Σ⁻¹ 1)`` inverts whatever Σ you hand it.
A sample covariance on N ≈ T/2 has Marchenko–Pastur-crushed eigenvalues;
inverting them is the "error maximizer". Linear shrinkage restores the
spectrum before the inversion.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def sample_covariance(returns: np.ndarray, *, mle: bool = True) -> np.ndarray:
    """T × N returns → N × N covariance. ``mle=True`` uses 1/T (Ledoit–Wolf)."""
    x = np.asarray(returns, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] < 3 or x.shape[1] < 2:
        raise ValueError("Need a T×N return matrix with T≥3 and N≥2")
    xc = x - x.mean(axis=0, keepdims=True)
    denom = x.shape[0] if mle else max(x.shape[0] - 1, 1)
    cov = (xc.T @ xc) / denom
    return 0.5 * (cov + cov.T)


def constant_correlation_target(sample: np.ndarray) -> tuple[np.ndarray, float]:
    """F_ii = s_ii, F_ij = r̄ √(s_ii s_jj). Finance's structured LW target."""
    s = np.asarray(sample, dtype=np.float64)
    n = s.shape[0]
    var = np.clip(np.diag(s), 1e-18, None)
    std = np.sqrt(var)
    outer = np.outer(std, std)
    corr = s / outer
    r_bar = float((np.sum(corr) - n) / (n * (n - 1)))
    r_bar = float(np.clip(r_bar, -0.999, 0.999))
    target = r_bar * outer
    np.fill_diagonal(target, var)
    return 0.5 * (target + target.T), r_bar


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Ledoit–Wolf (2003/04) linear shrinkage toward constant correlation.

    Σ_LW = α* F + (1 − α*) S, with α* the analytical intensity in [0, 1].
    S is the MLE sample covariance (1/T) on demeaned returns.
    """
    x = np.asarray(returns, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] < 8 or x.shape[1] < 2:
        raise ValueError("Need T≥8 observations and N≥2 assets")
    t, n = x.shape
    xc = x - x.mean(axis=0, keepdims=True)
    sample = (xc.T @ xc) / t
    sample = 0.5 * (sample + sample.T)
    target, r_bar = constant_correlation_target(sample)

    y2 = xc * xc
    phi_mat = (y2.T @ y2) / t - sample * sample
    pi_hat = float(np.sum(phi_mat))

    var = np.clip(np.diag(sample), 1e-18, None)
    std = np.sqrt(var)
    phi_diag = np.diag(phi_mat)
    ratio_j_over_i = std[None, :] / std[:, None]
    ratio_i_over_j = std[:, None] / std[None, :]
    off = 0.5 * r_bar * (ratio_j_over_i * phi_diag[:, None] + ratio_i_over_j * phi_diag[None, :])
    np.fill_diagonal(off, 0.0)
    rho_hat = float(np.sum(phi_diag) + np.sum(off))

    gamma_hat = float(np.sum((sample - target) ** 2))
    kappa = 0.0 if gamma_hat < 1e-18 else (pi_hat - rho_hat) / gamma_hat
    alpha = float(np.clip(kappa / t, 0.0, 1.0))
    shrunk = alpha * target + (1.0 - alpha) * sample
    shrunk = 0.5 * (shrunk + shrunk.T)
    return shrunk, {
        "alpha": round(alpha, 6),
        "r_bar": round(r_bar, 6),
        "pi": round(pi_hat, 6),
        "rho": round(rho_hat, 6),
        "gamma": round(gamma_hat, 6),
        "target": "constant_correlation",
        "t": int(t),
        "n": int(n),
        "formula": "Σ_LW = α* F + (1 − α*) S",
    }


def global_min_variance(cov: np.ndarray) -> np.ndarray:
    """Unconstrained GMV: w* = Σ⁻¹ 1 / (1' Σ⁻¹ 1). Long-short, sums to 1."""
    sigma = np.asarray(cov, dtype=np.float64)
    n = sigma.shape[0]
    ones = np.ones(n)
    try:
        prec = np.linalg.inv(sigma)
    except np.linalg.LinAlgError:
        prec = np.linalg.pinv(sigma)
    raw = prec @ ones
    total = float(np.sum(raw))
    if not np.isfinite(total) or abs(total) < 1e-18:
        return np.ones(n) / n
    w = raw / total
    if not np.all(np.isfinite(w)):
        return np.ones(n) / n
    return w


def marchenko_pastur_bounds(n_assets: int, n_obs: int, sigma2: float = 1.0) -> dict[str, float]:
    """Bulk edges of the noise spectrum of a sample correlation (σ² = 1)."""
    if n_assets < 2 or n_obs < 2:
        raise ValueError("Need N≥2 and T≥2")
    q = n_assets / n_obs
    root = float(np.sqrt(q))
    lam_minus = 0.0 if q >= 1 else float(sigma2 * (1.0 - root) ** 2)
    lam_plus = float(sigma2 * (1.0 + root) ** 2)
    return {"q": round(q, 6), "lambda_minus": round(lam_minus, 6), "lambda_plus": round(lam_plus, 6)}


def correlation_from_cov(cov: np.ndarray) -> np.ndarray:
    std = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    return 0.5 * (corr + corr.T)


def eigs_descending(matrix: np.ndarray) -> np.ndarray:
    vals = np.linalg.eigvalsh(np.asarray(matrix, dtype=np.float64))
    return np.sort(vals)[::-1]


def condition_number(matrix: np.ndarray) -> float:
    vals = np.linalg.eigvalsh(np.asarray(matrix, dtype=np.float64))
    vals = vals[vals > 0]
    if len(vals) < 2:
        return float("inf")
    return float(vals.max() / vals.min())


def weight_stats(weights: np.ndarray) -> dict[str, float | int]:
    w = np.asarray(weights, dtype=np.float64)
    return {
        "l1": round(float(np.sum(np.abs(w))), 6),
        "max_abs": round(float(np.max(np.abs(w))), 6),
        "hhi": round(float(np.sum(w * w)), 6),
        "n_short": int(np.sum(w < -1e-8)),
        "sum": round(float(np.sum(w)), 6),
    }

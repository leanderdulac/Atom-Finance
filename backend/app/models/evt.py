"""
Extreme Value Theory (EVT) Models
==================================
- Generalized Pareto Distribution (GPD) — Peaks Over Threshold (POT)
- Generalized Extreme Value (GEV)        — Block Maxima
- EVT-based VaR, CVaR and Return Levels
"""

import numpy as np
from dataclasses import dataclass
from functools import partial
from scipy import stats
from scipy.optimize import minimize, minimize_scalar


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GPDFitResult:
    xi: float           # shape  (tail index; >0 heavy tail)
    sigma: float        # scale
    threshold: float
    n_exceedances: int
    n_total: int
    log_likelihood: float


@dataclass
class GEVFitResult:
    xi: float           # shape  (>0 Fréchet, =0 Gumbel, <0 Weibull)
    mu: float           # location
    sigma: float        # scale
    n_blocks: int
    block_maxima_mean: float
    block_maxima_std: float


@dataclass
class EVTRiskMetrics:
    var_evt: float
    cvar_evt: float
    tail_index: float
    return_level_10y: float
    return_level_100y: float
    threshold: float
    n_exceedances: int
    exceedance_rate: float
    normal_var: float           # for comparison
    evt_premium_pct: float      # (evt_var / normal_var - 1) * 100


# ── GPD / POT ─────────────────────────────────────────────────────────────────

class GeneralizedParetoDistribution:
    """GPD fitted to exceedances above a threshold (POT method)."""

    def __init__(self):
        self.xi: float | None = None
        self.sigma: float | None = None
        self.threshold: float | None = None

    # ------------------------------------------------------------------
    def fit(self, data: np.ndarray, threshold_quantile: float = 0.90) -> GPDFitResult:
        """MLE fit of GPD to positive exceedances above *threshold_quantile*."""
        threshold = float(np.quantile(data, threshold_quantile))
        exceedances = data[data > threshold] - threshold
        n_excess = int(len(exceedances))
        n_total = int(len(data))

        if n_excess < 10:
            raise ValueError(
                f"Only {n_excess} exceedances above the {threshold_quantile:.0%} quantile. "
                "Lower threshold_quantile or provide more data."
            )

        # ── MLE ──────────────────────────────────────────────────────
        def neg_ll(params):
            xi, sigma = params
            if sigma <= 0:
                return 1e12
            if xi == 0:
                return -np.sum(stats.expon.logpdf(exceedances, scale=sigma))
            arg = 1.0 + xi * exceedances / sigma
            if np.any(arg <= 0):
                return 1e12
            return float(
                np.sum(np.log(sigma)) + (1.0 + 1.0 / xi) * np.sum(np.log(arg))
            )

        # Method-of-moments starting values
        m1 = float(np.mean(exceedances))
        m2 = float(np.var(exceedances))
        xi0 = 0.5 * (m1 ** 2 / m2 - 1.0)
        sigma0 = 0.5 * m1 * (m1 ** 2 / m2 + 1.0)

        res = minimize(
            neg_ll,
            [xi0, sigma0],
            method="Nelder-Mead",
            options={"xatol": 1e-9, "fatol": 1e-9, "maxiter": 20_000},
        )
        self.xi, self.sigma = float(res.x[0]), float(res.x[1])
        self.threshold = threshold

        return GPDFitResult(
            xi=self.xi,
            sigma=self.sigma,
            threshold=threshold,
            n_exceedances=n_excess,
            n_total=n_total,
            log_likelihood=float(-res.fun),
        )

    # ------------------------------------------------------------------
    def var_evt(self, confidence: float, n_total: int, n_excess: int) -> float:
        """EVT-VaR at *confidence* level (expressed as a loss, i.e. positive)."""
        if self.xi is None:
            raise RuntimeError("Model not fitted — call fit() first.")
        zeta = n_excess / n_total  # exceedance rate
        return self.threshold + (self.sigma / self.xi) * (
            ((1.0 - confidence) / zeta) ** (-self.xi) - 1.0
        )

    def cvar_evt(self, var_value: float) -> float:
        """EVT-CVaR (Expected Shortfall) given a VaR value."""
        if self.xi is None:
            raise RuntimeError("Model not fitted — call fit() first.")
        excess_over_u = var_value - self.threshold
        return (var_value + self.sigma + self.xi * excess_over_u) / (1.0 - self.xi)

    def return_level(
        self,
        return_period_years: float,
        n_obs_per_year: int,
        n_total: int,
        n_excess: int,
    ) -> float:
        """Return level for a given multi-year return period."""
        zeta = n_excess / n_total
        p = 1.0 / (return_period_years * n_obs_per_year)
        return self.threshold + (self.sigma / self.xi) * (
            (p / zeta) ** (-self.xi) - 1.0
        )

    def mean_excess_function(
        self, thresholds: np.ndarray | None = None, data: np.ndarray | None = None
    ) -> dict:
        """Mean excess (mean residual life) function — used to choose threshold."""
        if data is None or thresholds is None:
            return {}
        result = {}
        for u in thresholds:
            exc = data[data > u] - u
            if len(exc) >= 5:
                result[float(u)] = float(np.mean(exc))
        return result


# ── GEV / Block Maxima ────────────────────────────────────────────────────────

class GeneralizedExtremeValue:
    """GEV fitted via Block Maxima (scipy.stats.genextreme wrapper)."""

    def __init__(self):
        self.xi: float | None = None
        self.mu: float | None = None
        self.sigma: float | None = None
        self._n_blocks: int | None = None

    # ------------------------------------------------------------------
    def fit(self, data: np.ndarray, block_size: int = 63) -> GEVFitResult:
        """Fit GEV to block maxima.  *block_size* = 63 ≈ quarterly trading days."""
        n_blocks = len(data) // block_size
        if n_blocks < 10:
            raise ValueError(
                f"Only {n_blocks} complete blocks with block_size={block_size}. "
                "Provide more data or reduce block_size."
            )

        maxima = np.array(
            [np.max(data[i * block_size : (i + 1) * block_size]) for i in range(n_blocks)]
        )

        # scipy.stats.genextreme uses *c = -xi* convention
        c, loc, scale = stats.genextreme.fit(maxima)
        self.xi = float(-c)
        self.mu = float(loc)
        self.sigma = float(scale)
        self._n_blocks = n_blocks

        return GEVFitResult(
            xi=self.xi,
            mu=self.mu,
            sigma=self.sigma,
            n_blocks=n_blocks,
            block_maxima_mean=float(np.mean(maxima)),
            block_maxima_std=float(np.std(maxima)),
        )

    # ------------------------------------------------------------------
    def return_level(self, return_period_blocks: float) -> float:
        """Return level for a given return period *in blocks*."""
        if self.xi is None:
            raise RuntimeError("Model not fitted — call fit() first.")
        p = 1.0 - 1.0 / return_period_blocks
        if abs(self.xi) < 1e-10:
            return self.mu - self.sigma * np.log(-np.log(p))
        return self.mu + self.sigma * ((-np.log(p)) ** (-self.xi) - 1.0) / self.xi


# ── Convenience wrapper ───────────────────────────────────────────────────────

def compute_evt_risk(
    returns: np.ndarray,
    confidence: float = 0.99,
    threshold_quantile: float = 0.90,
    trading_days_per_year: int = 252,
) -> EVTRiskMetrics:
    """
    End-to-end EVT risk analysis (POT / GPD) on a return series.

    Parameters
    ----------
    returns : daily return array (can include negatives — losses are extracted)
    confidence : VaR confidence level (e.g. 0.99 for 99%)
    threshold_quantile : quantile used to define the POT threshold
    trading_days_per_year : for annualised return level calculations
    """
    losses = -returns                       # work in loss space
    losses_pos = losses[losses > 0]

    gpd = GeneralizedParetoDistribution()
    fit = gpd.fit(losses_pos, threshold_quantile)

    var = gpd.var_evt(confidence, fit.n_total, fit.n_exceedances)
    cvar = gpd.cvar_evt(var)

    try:
        rl_10y = gpd.return_level(10, trading_days_per_year, fit.n_total, fit.n_exceedances)
        rl_100y = gpd.return_level(100, trading_days_per_year, fit.n_total, fit.n_exceedances)
    except Exception:
        rl_10y = var * 1.5
        rl_100y = var * 2.5

    # Normal (Gaussian) VaR for comparison
    normal_var = float(-np.quantile(returns, 1.0 - confidence))
    evt_premium_pct = float((var / normal_var - 1.0) * 100) if normal_var > 0 else 0.0

    return EVTRiskMetrics(
        var_evt=float(var),
        cvar_evt=float(cvar),
        tail_index=float(fit.xi),
        return_level_10y=float(rl_10y),
        return_level_100y=float(rl_100y),
        threshold=float(fit.threshold),
        n_exceedances=fit.n_exceedances,
        exceedance_rate=float(fit.n_exceedances / fit.n_total),
        normal_var=normal_var,
        evt_premium_pct=evt_premium_pct,
    )


# ── Hill estimator (classic non-parametric tail index) ───────────────────────

def hill_estimator(data: np.ndarray, k: int | None = None) -> dict:
    """
    Hill estimator for the tail index α (= 1/ξ).

    Parameters
    ----------
    data : positive loss values
    k    : number of upper order statistics (default: top 10%)
    """
    sorted_data = np.sort(data)[::-1]  # descending
    n = len(sorted_data)
    if k is None:
        k = max(10, int(0.10 * n))
    k = min(k, n - 1)

    log_ratios = np.log(sorted_data[:k] / sorted_data[k])
    alpha_hat = k / np.sum(log_ratios)  # Hill estimator
    xi_hat = 1.0 / alpha_hat            # shape parameter

    return {
        "tail_index_alpha": float(alpha_hat),
        "shape_xi": float(xi_hat),
        "k_used": k,
        "threshold_used": float(sorted_data[k]),
        "interpretation": (
            "Heavy tail (Pareto-like)" if xi_hat > 0.5
            else "Moderate tail" if xi_hat > 0.2
            else "Near-normal tails"
        ),
    }

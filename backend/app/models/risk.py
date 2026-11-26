"""
Risk Analysis Models
- Value at Risk (VaR): Historical, Parametric, Monte Carlo (normal)
- Stationary block bootstrap VaR/CVaR (Politis–Romano): keeps fat tails and serial dependence
- Conditional VaR (CVaR / Expected Shortfall)
- Stress Testing & Scenario Analysis

The bootstrap is a risk band on the sample it is given. It does not send an order.
"""

import numpy as np
from scipy.stats import norm
from scipy.stats import t as t_dist


def _horizon_returns(returns: np.ndarray, holding_period: int) -> np.ndarray:
    """Overlapping compounded holding-period returns (not √h scaling of 1-day PnL)."""
    if holding_period <= 1:
        return returns
    if np.any(returns <= -1):
        raise ValueError("Returns ≤ -100% cannot be compounded over a holding period")
    if len(returns) < holding_period:
        raise ValueError("Need at least `holding_period` observations for overlapping h-day returns")
    acc = np.convolve(np.log1p(returns), np.ones(holding_period), mode="valid")
    return np.expm1(acc)


def _tail_cvar(hp_returns: np.ndarray, var_pct: float) -> float:
    tail = hp_returns[hp_returns <= -var_pct]
    if tail.size == 0:
        return var_pct
    return float(-np.mean(tail))


def _stationary_bootstrap_indices(
    n: int,
    length: int,
    n_paths: int,
    mean_block: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Politis–Romano indices. A new block starts with probability 1/mean_block."""
    idx = np.empty((n_paths, length), dtype=int)
    idx[:, 0] = rng.integers(0, n, size=n_paths)
    new_block = rng.random((n_paths, length)) < (1.0 / mean_block)
    jumps = rng.integers(0, n, size=(n_paths, length))
    for h in range(1, length):
        idx[:, h] = np.where(new_block[:, h], jumps[:, h], (idx[:, h - 1] + 1) % n)
    return idx


def bootstrap_horizon_returns(
    returns: np.ndarray,
    holding_period: int = 1,
    n_paths: int = 5_000,
    mean_block: float = 10.0,
    seed: int | None = 42,
) -> np.ndarray:
    """Compounded horizon returns from a stationary block bootstrap of ``returns``.

    The draw uses only the array it is given. Block length is geometric with
    mean ``mean_block``, which keeps runs of serial dependence that an i.i.d.
    normal Monte Carlo erases.
    """
    clean = np.asarray(returns, dtype=np.float64)
    if clean.ndim != 1:
        raise ValueError("returns must be 1-D")
    clean = clean[np.isfinite(clean)]
    if len(clean) < 2:
        raise ValueError("need at least 2 finite returns")
    if holding_period < 1:
        raise ValueError("holding_period must be >= 1")
    if mean_block < 1:
        raise ValueError("mean_block must be >= 1")
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    if holding_period > 1 and np.any(clean <= -1):
        raise ValueError("Returns ≤ -100% cannot be compounded over a holding period")
    rng = np.random.default_rng(42 if seed is None else seed)
    idx = _stationary_bootstrap_indices(len(clean), holding_period, n_paths, mean_block, rng)
    sampled = clean[idx]
    if holding_period == 1:
        return sampled[:, 0]
    return np.expm1(np.sum(np.log1p(sampled), axis=1))


def rolling_stationary_bootstrap_var(
    returns: np.ndarray,
    window: int = 60,
    confidence: float = 0.95,
    holding_period: int = 1,
    n_paths: int = 200,
    mean_block: float = 5.0,
    seed: int = 0,
    step: int = 1,
) -> np.ndarray:
    """Loss fraction at t from a block bootstrap of the window that ends at t.

    Recomputed every ``step`` bars and carried forward. The seed depends on t,
    not on any later return, so a perturbation after t leaves the prefix unchanged.
    """
    series = np.asarray(returns, dtype=np.float64)
    if series.ndim != 1:
        raise ValueError("returns must be 1-D")
    if window < 10 or step < 1:
        raise ValueError("window must be >= 10 and step >= 1")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    out = np.full(len(series), np.nan)
    last = np.nan
    need = max(10, window // 2)
    alpha = (1.0 - confidence) * 100.0
    for t in range(window - 1, len(series)):
        if (t - (window - 1)) % step == 0:
            w = series[t - window + 1 : t + 1]
            w = w[np.isfinite(w)]
            if len(w) < need:
                last = np.nan
            else:
                try:
                    sim = bootstrap_horizon_returns(w, holding_period, n_paths, mean_block, seed + t)
                except ValueError:
                    last = np.nan
                else:
                    last = float(-np.percentile(sim, alpha))
        out[t] = last
    return out


def _estimate_student_t_df(returns: np.ndarray) -> float:
    """MLE degrees-of-freedom of a Student-t fitted to the returns.

    The old parametric-t branch fabricated df as `len(returns)//50`, so the
    tail thickness (and therefore VaR/CVaR) implied a distribution the data
    never exhibited. Here df comes from a full t MLE (loc/scale free) on the
    actual returns.
    """
    z = np.asarray(returns, dtype=np.float64)
    z = z[np.isfinite(z)]
    if z.size < 10 or float(np.std(z)) < 1e-12:
        return 5.0
    try:
        df, _, _ = t_dist.fit(z)
    except Exception:
        df = float("nan")
    if not np.isfinite(df) or df <= 1.0:
        return 5.0
    # Keep finite variance (df > 2) and a tractable tail; above ~30 the t ≈ normal.
    return float(np.clip(df, 2.0, 30.0))


class ValueAtRisk:
    """Value at Risk calculations with multiple methods."""

    @staticmethod
    def historical(returns: np.ndarray, confidence: float = 0.95,
                   portfolio_value: float = 1_000_000, holding_period: int = 1) -> dict:
        returns = np.asarray(returns, dtype=np.float64)
        alpha = 1 - confidence
        hp_returns = _horizon_returns(returns, holding_period)

        var_pct = float(-np.percentile(hp_returns, alpha * 100))
        var_abs = var_pct * portfolio_value
        cvar_pct = _tail_cvar(hp_returns, var_pct)
        cvar_abs = cvar_pct * portfolio_value

        return {
            "method": "historical",
            "confidence": confidence,
            "holding_period_days": holding_period,
            "var_percentage": round(var_pct * 100, 4),
            "var_absolute": round(var_abs, 2),
            "cvar_percentage": round(cvar_pct * 100, 4),
            "cvar_absolute": round(cvar_abs, 2),
            "portfolio_value": portfolio_value,
            "n_observations": int(len(hp_returns)),
            "horizon_method": "overlapping_compounded" if holding_period > 1 else "1d",
        }

    @staticmethod
    def parametric(returns: np.ndarray, confidence: float = 0.95,
                   portfolio_value: float = 1_000_000, holding_period: int = 1,
                   distribution: str = "normal") -> dict:
        returns = np.asarray(returns, dtype=np.float64)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1)) if len(returns) > 1 else float(np.std(returns))
        alpha = 1 - confidence
        h = float(holding_period)
        mu_h = mu * h
        sigma_h = sigma * np.sqrt(h)

        extra: dict = {}
        if distribution == "normal":
            z = float(norm.ppf(alpha))
            var_pct = -(mu_h + z * sigma_h)
            cvar_pct = -(mu_h - sigma_h * float(norm.pdf(z)) / alpha)
        elif distribution == "t":
            # df is estimated (MLE) from the standardized returns, not fabricated.
            # A standard t_nu has variance nu/(nu-2), so its quantiles must be
            # standardized before scaling by the sample sigma — otherwise VaR/ES
            # are overstated by sqrt(nu/(nu-2)) (~29% at nu=5).
            df_est = _estimate_student_t_df(returns)
            std_scale = float(np.sqrt((df_est - 2.0) / df_est))
            z = float(t_dist.ppf(alpha, df_est)) * std_scale
            var_pct = -(mu_h + z * sigma_h)
            if df_est <= 1:
                cvar_pct = float("inf")
            else:
                z_raw = float(t_dist.ppf(alpha, df_est))
                tail_factor = (
                    float(t_dist.pdf(z_raw, df_est)) / alpha
                    * (df_est + z_raw ** 2) / (df_est - 1)
                    * std_scale
                )
                cvar_pct = -mu_h + sigma_h * tail_factor
            extra["df"] = df_est
            extra["df_estimation"] = "mle_standardized"
        else:
            raise ValueError(f"Unknown distribution: {distribution}")

        return {
            "method": f"parametric_{distribution}",
            "confidence": confidence,
            "holding_period_days": holding_period,
            "var_percentage": round(float(var_pct) * 100, 4),
            "var_absolute": round(float(var_pct) * portfolio_value, 2),
            "cvar_percentage": round(float(cvar_pct) * 100, 4),
            "cvar_absolute": round(float(cvar_pct) * portfolio_value, 2),
            "mean_return": round(mu * 100, 4),
            "volatility": round(sigma * 100, 4),
            "portfolio_value": portfolio_value,
            "horizon_method": "mu*h + sigma*sqrt(h)",
            **extra,
        }

    @staticmethod
    def monte_carlo(returns: np.ndarray, confidence: float = 0.95,
                    portfolio_value: float = 1_000_000, holding_period: int = 1,
                    n_simulations: int = 50_000, seed: int | None = 42) -> dict:
        rng = np.random.default_rng(seed)

        returns = np.asarray(returns, dtype=np.float64)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        alpha = 1 - confidence

        # Simulate portfolio returns
        sim_returns = rng.normal(mu * holding_period, sigma * np.sqrt(holding_period), n_simulations)
        sim_values = portfolio_value * (1 + sim_returns)
        sim_pnl = sim_values - portfolio_value

        var_abs = float(-np.percentile(sim_pnl, alpha * 100))
        tail = sim_pnl[sim_pnl <= -var_abs]
        cvar_abs = float(-np.mean(tail)) if tail.size else var_abs

        return {
            "method": "monte_carlo",
            "confidence": confidence,
            "holding_period_days": holding_period,
            "var_percentage": round(var_abs / portfolio_value * 100, 4),
            "var_absolute": round(var_abs, 2),
            "cvar_percentage": round(cvar_abs / portfolio_value * 100, 4),
            "cvar_absolute": round(cvar_abs, 2),
            "n_simulations": n_simulations,
            "portfolio_value": portfolio_value,
            "pnl_distribution": {
                "mean": round(float(np.mean(sim_pnl)), 2),
                "std": round(float(np.std(sim_pnl)), 2),
                "min": round(float(np.min(sim_pnl)), 2),
                "max": round(float(np.max(sim_pnl)), 2),
                "percentiles": {str(p): round(float(np.percentile(sim_pnl, p)), 2) for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]},
            },
        }

    @staticmethod
    def stationary_bootstrap(returns: np.ndarray, confidence: float = 0.95,
                             portfolio_value: float = 1_000_000, holding_period: int = 1,
                             n_paths: int = 5_000, mean_block: float = 10.0,
                             seed: int | None = 42) -> dict:
        """VaR/CVaR from a Politis–Romano stationary block bootstrap.

        Paths resample historical returns in geometric blocks, so the horizon
        loss keeps the sample's fat tails and its serial dependence. The
        normal Monte Carlo next to this method does neither.
        """
        returns = np.asarray(returns, dtype=np.float64)
        if returns.ndim != 1 or len(returns) < 30:
            raise ValueError("Need at least 30 returns")
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        sim = bootstrap_horizon_returns(returns, holding_period, n_paths, mean_block, seed)
        alpha = 1.0 - confidence
        var_pct = float(-np.percentile(sim, alpha * 100))
        cvar_pct = _tail_cvar(sim, var_pct)
        return {
            "method": "stationary_bootstrap",
            "confidence": confidence,
            "holding_period_days": holding_period,
            "var_percentage": round(var_pct * 100, 4),
            "var_absolute": round(var_pct * portfolio_value, 2),
            "cvar_percentage": round(cvar_pct * 100, 4),
            "cvar_absolute": round(cvar_pct * portfolio_value, 2),
            "n_paths": n_paths,
            "mean_block": mean_block,
            "seed": 42 if seed is None else seed,
            "block_scheme": "politis_romano",
            "portfolio_value": portfolio_value,
            "n_observations": int(np.isfinite(returns).sum()),
            "horizon_method": "stationary_block_bootstrap",
        }


class StressTest:
    """Scenario-based stress testing."""

    SCENARIOS = {
        "2008_financial_crisis": {"equity": -0.38, "bonds": 0.05, "gold": 0.25, "vix_change": 300},
        "2020_covid_crash": {"equity": -0.34, "bonds": 0.08, "gold": 0.10, "vix_change": 400},
        "2000_dotcom_bust": {"equity": -0.49, "bonds": 0.15, "gold": -0.05, "vix_change": 150},
        "1987_black_monday": {"equity": -0.22, "bonds": 0.02, "gold": 0.03, "vix_change": 200},
        "2010_flash_crash": {"equity": -0.09, "bonds": 0.01, "gold": 0.02, "vix_change": 250},
        "rate_hike_200bps": {"equity": -0.15, "bonds": -0.12, "gold": -0.05, "vix_change": 50},
        "hyperinflation": {"equity": -0.20, "bonds": -0.25, "gold": 0.40, "vix_change": 100},
        "geopolitical_crisis": {"equity": -0.12, "bonds": 0.05, "gold": 0.15, "vix_change": 80},
    }

    @classmethod
    def run(cls, portfolio: dict[str, float], scenario_name: str,
            portfolio_value: float = 1_000_000) -> dict:
        """
        portfolio: {"equity": 0.6, "bonds": 0.3, "gold": 0.1}
        """
        if scenario_name not in cls.SCENARIOS:
            return {"error": f"Unknown scenario. Available: {list(cls.SCENARIOS.keys())}"}

        scenario = cls.SCENARIOS[scenario_name]
        total_impact = 0.0
        details = {}

        for asset_class, weight in portfolio.items():
            shock = scenario.get(asset_class, 0)
            impact = weight * shock
            total_impact += impact
            details[asset_class] = {
                "weight": round(weight, 4),
                "shock": round(shock * 100, 2),
                "impact": round(impact * 100, 2),
            }

        return {
            "scenario": scenario_name,
            "portfolio_value": portfolio_value,
            "total_impact_pct": round(total_impact * 100, 2),
            "total_impact_abs": round(total_impact * portfolio_value, 2),
            "portfolio_after": round(portfolio_value * (1 + total_impact), 2),
            "vix_change_pct": scenario.get("vix_change", 0),
            "details": details,
        }

    @classmethod
    def run_all(cls, portfolio: dict[str, float], portfolio_value: float = 1_000_000) -> dict:
        results = {}
        for name in cls.SCENARIOS:
            results[name] = cls.run(portfolio, name, portfolio_value)
        return {"scenarios": results, "worst_case": min(results.values(), key=lambda x: x.get("total_impact_pct", 0))}

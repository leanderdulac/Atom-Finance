"""
Risk Analysis Models
- Value at Risk (VaR): Historical, Parametric, Monte Carlo
- Conditional VaR (CVaR / Expected Shortfall)
- Stress Testing & Scenario Analysis
"""
import numpy as np
from scipy.stats import norm, t as t_dist
from typing import Optional


class ValueAtRisk:
    """Value at Risk calculations with multiple methods."""

    @staticmethod
    def historical(returns: np.ndarray, confidence: float = 0.95,
                   portfolio_value: float = 1_000_000, holding_period: int = 1) -> dict:
        returns = np.asarray(returns, dtype=np.float64)
        alpha = 1 - confidence
        hp_returns = returns * np.sqrt(holding_period) if holding_period > 1 else returns

        var_pct = float(-np.percentile(hp_returns, alpha * 100))
        var_abs = var_pct * portfolio_value
        cvar_pct = float(-np.mean(hp_returns[hp_returns <= -var_pct]))
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
            "n_observations": len(returns),
        }

    @staticmethod
    def parametric(returns: np.ndarray, confidence: float = 0.95,
                   portfolio_value: float = 1_000_000, holding_period: int = 1,
                   distribution: str = "normal") -> dict:
        returns = np.asarray(returns, dtype=np.float64)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        alpha = 1 - confidence

        if distribution == "normal":
            z = norm.ppf(alpha)
            var_pct = -(mu + z * sigma) * np.sqrt(holding_period)
            # CVaR for normal distribution
            cvar_pct = -(mu - sigma * norm.pdf(z) / alpha) * np.sqrt(holding_period)
        elif distribution == "t":
            # Fit Student-t
            df_est = max(3, len(returns) // 50)
            z = t_dist.ppf(alpha, df_est)
            var_pct = -(mu + z * sigma) * np.sqrt(holding_period)
            cvar_pct = var_pct * 1.1  # Approximate
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
        }

    @staticmethod
    def monte_carlo(returns: np.ndarray, confidence: float = 0.95,
                    portfolio_value: float = 1_000_000, holding_period: int = 1,
                    n_simulations: int = 50_000, seed: Optional[int] = 42) -> dict:
        if seed is not None:
            np.random.seed(seed)

        returns = np.asarray(returns, dtype=np.float64)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        alpha = 1 - confidence

        # Simulate portfolio returns
        sim_returns = np.random.normal(mu * holding_period, sigma * np.sqrt(holding_period), n_simulations)
        sim_values = portfolio_value * (1 + sim_returns)
        sim_pnl = sim_values - portfolio_value

        var_abs = float(-np.percentile(sim_pnl, alpha * 100))
        cvar_abs = float(-np.mean(sim_pnl[sim_pnl <= -var_abs]))

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


class StressTest:
    """Scenario-based stress testing."""

    SCENARIOS = {
        "2008_financial_crisis": {"equity": -0.38, "bonds": 0.05, "gold": 0.25, "vix_change": 300},
        "2020_covid_crash": {"equity": -0.34, "bonds": 0.08, "gold": 0.10, "vix_change": 400},
        "2000_dotcom_bust": {"equity": -0.49, "bonds": 0.15, "gold": -0.05, "vix_change": 150},
        "1987_black_monday": {"equity": -0.22, "bonds": 0.02, "gold": 0.03, "vix_change": 200},
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

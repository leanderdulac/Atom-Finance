"""
Volatility Models
- GARCH(1,1)
- Heston Stochastic Volatility
- EWMA Volatility
"""
import numpy as np
from scipy.optimize import minimize
from typing import Optional


class GARCHModel:
    """GARCH(1,1) volatility model: σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}"""

    def __init__(self):
        self.omega: float = 0.0
        self.alpha: float = 0.0
        self.beta: float = 0.0
        self.fitted: bool = False

    def fit(self, returns: np.ndarray) -> dict:
        """Fit GARCH(1,1) via maximum likelihood estimation."""
        returns = np.asarray(returns, dtype=np.float64)
        T = len(returns)
        var_target = np.var(returns)

        def neg_log_likelihood(params):
            omega, alpha, beta = params
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
                return 1e10
            sigma2 = np.zeros(T)
            sigma2[0] = var_target
            for t in range(1, T):
                sigma2[t] = omega + alpha * returns[t - 1]**2 + beta * sigma2[t - 1]
                if sigma2[t] <= 0:
                    return 1e10
            ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)
            return -ll

        x0 = [var_target * 0.05, 0.08, 0.85]
        bounds = [(1e-8, None), (1e-8, 0.5), (0.5, 0.9999)]
        result = minimize(neg_log_likelihood, x0, bounds=bounds, method="L-BFGS-B")

        self.omega, self.alpha, self.beta = result.x
        self.fitted = True

        # Compute conditional volatilities
        sigma2 = np.zeros(T)
        sigma2[0] = var_target
        for t in range(1, T):
            sigma2[t] = self.omega + self.alpha * returns[t - 1]**2 + self.beta * sigma2[t - 1]

        persistence = self.alpha + self.beta
        long_run_var = self.omega / (1 - persistence) if persistence < 1 else float("nan")

        return {
            "omega": round(self.omega, 8),
            "alpha": round(self.alpha, 6),
            "beta": round(self.beta, 6),
            "persistence": round(persistence, 6),
            "long_run_variance": round(long_run_var, 8),
            "long_run_volatility": round(np.sqrt(long_run_var) * np.sqrt(252), 4) if not np.isnan(long_run_var) else None,
            "conditional_volatility": (np.sqrt(sigma2) * np.sqrt(252)).tolist(),
            "log_likelihood": round(-result.fun, 4),
        }

    def forecast(self, returns: np.ndarray, horizon: int = 30) -> dict:
        """Forecast volatility h steps ahead."""
        if not self.fitted:
            self.fit(returns)

        T = len(returns)
        sigma2 = np.zeros(T)
        sigma2[0] = np.var(returns)
        for t in range(1, T):
            sigma2[t] = self.omega + self.alpha * returns[t - 1]**2 + self.beta * sigma2[t - 1]

        # h-step forecast
        forecast_var = np.zeros(horizon)
        forecast_var[0] = self.omega + self.alpha * returns[-1]**2 + self.beta * sigma2[-1]
        long_run = self.omega / (1 - self.alpha - self.beta)

        for h in range(1, horizon):
            forecast_var[h] = long_run + (self.alpha + self.beta)**h * (forecast_var[0] - long_run)

        return {
            "forecast_volatility": (np.sqrt(forecast_var) * np.sqrt(252)).tolist(),
            "horizon_days": horizon,
        }


class HestonModel:
    """
    Heston stochastic volatility model.
    dS = μS dt + √v S dW₁
    dv = κ(θ - v)dt + ξ√v dW₂
    <dW₁, dW₂> = ρ dt
    """

    @staticmethod
    def simulate(S0: float, v0: float, mu: float, kappa: float, theta: float,
                 xi: float, rho: float, T: float, n_paths: int = 10000,
                 n_steps: int = 252, seed: Optional[int] = 42) -> dict:
        if seed is not None:
            np.random.seed(seed)

        dt = T / n_steps
        sqrt_dt = np.sqrt(dt)

        S = np.zeros((n_paths, n_steps + 1))
        v = np.zeros((n_paths, n_steps + 1))
        S[:, 0] = S0
        v[:, 0] = v0

        for t in range(1, n_steps + 1):
            z1 = np.random.standard_normal(n_paths)
            z2 = rho * z1 + np.sqrt(1 - rho**2) * np.random.standard_normal(n_paths)

            v_pos = np.maximum(v[:, t - 1], 0)
            sqrt_v = np.sqrt(v_pos)

            S[:, t] = S[:, t - 1] * np.exp((mu - 0.5 * v_pos) * dt + sqrt_v * sqrt_dt * z1)
            v[:, t] = v[:, t - 1] + kappa * (theta - v_pos) * dt + xi * sqrt_v * sqrt_dt * z2
            v[:, t] = np.maximum(v[:, t], 0)  # Reflection scheme

        # Sample paths for visualization
        sample_idx = np.linspace(0, n_paths - 1, min(20, n_paths), dtype=int)
        step = max(1, n_steps // 50)

        return {
            "terminal_prices": {
                "mean": round(float(np.mean(S[:, -1])), 2),
                "std": round(float(np.std(S[:, -1])), 2),
                "percentiles": {str(p): round(float(np.percentile(S[:, -1], p)), 2)
                                for p in [5, 25, 50, 75, 95]},
            },
            "terminal_variance": {
                "mean": round(float(np.mean(v[:, -1])), 6),
                "mean_vol": round(float(np.sqrt(np.mean(v[:, -1]))), 4),
            },
            "sample_price_paths": S[sample_idx, ::step].tolist(),
            "sample_vol_paths": np.sqrt(np.maximum(v[sample_idx, ::step], 0)).tolist(),
            "parameters": {
                "S0": S0, "v0": v0, "mu": mu, "kappa": kappa,
                "theta": theta, "xi": xi, "rho": rho, "T": T,
            },
        }

    @staticmethod
    def price_option(S0: float, K: float, v0: float, r: float, kappa: float,
                     theta: float, xi: float, rho: float, T: float,
                     option_type: str = "call", n_paths: int = 50000,
                     seed: Optional[int] = 42) -> dict:
        result = HestonModel.simulate(S0, v0, r, kappa, theta, xi, rho, T, n_paths, seed=seed)
        # Use simulated terminal prices
        from app.models.pricing import BlackScholes
        # Re-simulate for pricing
        if seed is not None:
            np.random.seed(seed)

        dt = T / 252
        n_steps = 252
        S = np.full(n_paths, S0)
        v = np.full(n_paths, v0)

        for t in range(n_steps):
            z1 = np.random.standard_normal(n_paths)
            z2 = rho * z1 + np.sqrt(1 - rho**2) * np.random.standard_normal(n_paths)
            v_pos = np.maximum(v, 0)
            sqrt_v = np.sqrt(v_pos)
            S = S * np.exp((r - 0.5 * v_pos) * dt + sqrt_v * np.sqrt(dt) * z1)
            v = v + kappa * (theta - v_pos) * dt + xi * sqrt_v * np.sqrt(dt) * z2
            v = np.maximum(v, 0)

        if option_type == "call":
            payoffs = np.maximum(S - K, 0)
        else:
            payoffs = np.maximum(K - S, 0)

        price = float(np.exp(-r * T) * np.mean(payoffs))
        std_err = float(np.exp(-r * T) * np.std(payoffs) / np.sqrt(n_paths))

        return {
            "price": round(price, 6),
            "std_error": round(std_err, 6),
            "confidence_95": [round(price - 1.96 * std_err, 6), round(price + 1.96 * std_err, 6)],
            "model": "heston",
        }


class EWMAVolatility:
    """Exponentially Weighted Moving Average volatility."""

    @staticmethod
    def compute(returns: np.ndarray, lambda_: float = 0.94) -> dict:
        T = len(returns)
        var = np.zeros(T)
        var[0] = returns[0]**2

        for t in range(1, T):
            var[t] = lambda_ * var[t - 1] + (1 - lambda_) * returns[t - 1]**2

        vol = np.sqrt(var) * np.sqrt(252)
        return {
            "volatility": vol.tolist(),
            "current_vol": round(float(vol[-1]), 4),
            "lambda": lambda_,
        }

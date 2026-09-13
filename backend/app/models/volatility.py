"""
Volatility Models
- GARCH(1,1)
- Heston Stochastic Volatility
- EWMA Volatility
"""

import numpy as np
from scipy.optimize import minimize


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
        # α, β ∈ [0, 1) with α+β < 1 enforced in the likelihood — do not floor β at 0.5.
        bounds = [(1e-8, None), (0.0, 0.9999), (0.0, 0.9999)]
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
                 n_steps: int = 252, seed: int | None = 42) -> dict:
        if seed is not None:
            np.random.seed(seed)

        dt = T / n_steps
        sqrt_dt = np.sqrt(dt)
        feller = 2.0 * kappa * theta - xi ** 2

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
                "feller_2k_theta_minus_xi2": round(float(feller), 6),
                "feller_satisfied": bool(feller > 0),
            },
            "limitations": [
                "Euler–Maruyama with reflection biases the variance distribution, especially when the Feller condition fails.",
                "This path simulator is for illustration; European prices should use the characteristic-function pricer.",
            ],
        }

    @staticmethod
    def price_option(S0: float, K: float, v0: float, r: float, kappa: float,
                     theta: float, xi: float, rho: float, T: float,
                     option_type: str = "call", n_paths: int = 50000,
                     seed: int | None = 42) -> dict:
        if seed is not None:
            np.random.seed(seed)

        n_steps = max(1, int(round(252 * T)))
        dt = T / n_steps
        half = n_paths // 2
        remainder = n_paths - 2 * half
        S = np.full(n_paths, S0)
        v = np.full(n_paths, v0)

        for _ in range(n_steps):
            z1_half = np.random.standard_normal(half)
            z2_ind = np.random.standard_normal(half)
            z1 = np.concatenate([z1_half, -z1_half] + ([np.random.standard_normal(remainder)] if remainder else []))
            z2_raw = np.concatenate([z2_ind, -z2_ind] + ([np.random.standard_normal(remainder)] if remainder else []))
            z2 = rho * z1 + np.sqrt(max(1 - rho**2, 0.0)) * z2_raw
            v_pos = np.maximum(v, 0)
            sqrt_v = np.sqrt(v_pos)
            S = S * np.exp((r - 0.5 * v_pos) * dt + sqrt_v * np.sqrt(dt) * z1)
            v = v + kappa * (theta - v_pos) * dt + xi * sqrt_v * np.sqrt(dt) * z2
            v = np.maximum(v, 0)

        if option_type == "call":
            payoffs = np.maximum(S - K, 0)
        else:
            payoffs = np.maximum(K - S, 0)

        disc = np.exp(-r * T)
        price = float(disc * np.mean(payoffs))
        std_err = float(disc * np.std(payoffs, ddof=1) / np.sqrt(n_paths))
        feller = 2.0 * kappa * theta - xi ** 2

        return {
            "price": round(price, 6),
            "std_error": round(std_err, 6),
            "confidence_95": [round(price - 1.96 * std_err, 6), round(price + 1.96 * std_err, 6)],
            "model": "heston_euler_mc",
            "n_steps": n_steps,
            "dt": round(dt, 8),
            "feller_satisfied": bool(feller > 0),
            "limitations": [
                "Euler reflection scheme is biased; use price_option_cf for European quotes.",
                "Antithetic variates reduce variance but do not remove discretisation bias.",
            ],
        }

    @staticmethod
    def price_option_cf(
        S0: float, K: float, v0: float, r: float, kappa: float,
        theta: float, xi: float, rho: float, T: float,
        option_type: str = "call", q: float = 0.0,
    ) -> dict:
        """Heston (1993) European price via the characteristic function (Albrecher 'little trap')."""
        if T <= 0:
            intrinsic = max(S0 - K, 0.0) if option_type == "call" else max(K - S0, 0.0)
            return {"price": round(intrinsic, 6), "model": "heston_cf", "std_error": 0.0}

        ln_s = np.log(S0)
        ln_k = np.log(K)

        def _cf(u: np.ndarray, j: int) -> np.ndarray:
            i = 1j
            uj = 0.5 if j == 1 else -0.5
            bj = kappa - rho * xi if j == 1 else kappa
            disc = (bj - rho * xi * i * u) ** 2 - (xi ** 2) * (2.0 * uj * i * u - u ** 2)
            d = np.sqrt(disc)
            g = (bj - rho * xi * i * u - d) / (bj - rho * xi * i * u + d)
            exp_dt = np.exp(-d * T)
            G = (1.0 - g * exp_dt) / (1.0 - g)
            C = (r - q) * i * u * T + (kappa * theta / xi ** 2) * (
                (bj - rho * xi * i * u - d) * T - 2.0 * np.log(G)
            )
            D = ((bj - rho * xi * i * u - d) / xi ** 2) * ((1.0 - exp_dt) / (1.0 - g * exp_dt))
            return np.exp(C + D * v0 + i * u * ln_s)

        def _pj(j: int) -> float:
            u = np.concatenate([
                np.geomspace(1e-6, 1.0, 96, endpoint=False),
                np.linspace(1.0, 200.0, 192),
            ])
            integrand = np.real(np.exp(-1j * u * ln_k) * _cf(u, j) / (1j * u))
            return float(0.5 + np.trapz(integrand, u) / np.pi)

        p1, p2 = _pj(1), _pj(2)
        call = S0 * np.exp(-q * T) * p1 - K * np.exp(-r * T) * p2
        put = call - S0 * np.exp(-q * T) + K * np.exp(-r * T)
        price = float(call if option_type == "call" else put)
        feller = 2.0 * kappa * theta - xi ** 2
        return {
            "price": round(price, 6),
            "std_error": 0.0,
            "p1": round(float(p1), 6),
            "p2": round(float(p2), 6),
            "model": "heston_cf",
            "feller_satisfied": bool(feller > 0),
            "feller_2k_theta_minus_xi2": round(float(feller), 6),
            "limitations": [
                "Fourier inversion uses a truncated trapezoid; deep OTM short-dated options need a finer grid.",
                "Complex logarithm uses the Albrecher branch; extreme parameters can still oscillate.",
                "This prices Europeans only. Americans need the PDE / tree / Longstaff–Schwartz.",
            ],
        }

    @staticmethod
    def price_cf_raw(
        S0: float, K: float, v0: float, r: float, kappa: float,
        theta: float, xi: float, rho: float, T: float,
        option_type: str = "call", q: float = 0.0,
        n_near: int = 48, n_far: int = 96,
    ) -> float:
        """Unrounded CF price for calibration. Same Albrecher integrand, coarser grid."""
        if T <= 0:
            return max(S0 - K, 0.0) if option_type == "call" else max(K - S0, 0.0)
        ln_s = np.log(S0)
        ln_k = np.log(K)

        def _cf(u: np.ndarray, j: int) -> np.ndarray:
            i = 1j
            uj = 0.5 if j == 1 else -0.5
            bj = kappa - rho * xi if j == 1 else kappa
            disc = (bj - rho * xi * i * u) ** 2 - (xi ** 2) * (2.0 * uj * i * u - u ** 2)
            d = np.sqrt(disc)
            g = (bj - rho * xi * i * u - d) / (bj - rho * xi * i * u + d)
            exp_dt = np.exp(-d * T)
            G = (1.0 - g * exp_dt) / (1.0 - g)
            C = (r - q) * i * u * T + (kappa * theta / xi ** 2) * (
                (bj - rho * xi * i * u - d) * T - 2.0 * np.log(G)
            )
            D = ((bj - rho * xi * i * u - d) / xi ** 2) * ((1.0 - exp_dt) / (1.0 - g * exp_dt))
            return np.exp(C + D * v0 + i * u * ln_s)

        def _pj(j: int) -> float:
            u = np.concatenate([
                np.geomspace(1e-6, 1.0, n_near, endpoint=False),
                np.linspace(1.0, 150.0, n_far),
            ])
            integrand = np.real(np.exp(-1j * u * ln_k) * _cf(u, j) / (1j * u))
            return float(0.5 + np.trapz(integrand, u) / np.pi)

        p1, p2 = _pj(1), _pj(2)
        call = S0 * np.exp(-q * T) * p1 - K * np.exp(-r * T) * p2
        if option_type == "call":
            return float(call)
        return float(call - S0 * np.exp(-q * T) + K * np.exp(-r * T))

    @staticmethod
    def calibrate(
        S0: float,
        r: float,
        quotes: list[dict],
        q: float = 0.0,
        x0: tuple[float, float, float, float, float] | None = None,
        max_nfev: int = 80,
    ) -> dict:
        """
        Least-squares fit of (v0, κ, θ, ξ, ρ) to European quotes.

        Each quote is {K, T, price?} or {K, T, iv?, option_type?}. The objective is
        price RMSE, not IV RMSE — vega-weighting is a desk choice we do not hide.
        Five Heston parameters are not identified from a single expiry; this recovers
        a smile-consistent set, not 'the' physical measure.
        """
        from scipy.optimize import least_squares

        from app.models.pricing import BlackScholes

        if len(quotes) < 4:
            raise ValueError("Need at least 4 quotes to calibrate Heston")
        if S0 <= 0:
            raise ValueError("S0 must be positive")

        market = []
        specs = []
        for raw in quotes:
            K = float(raw["K"])
            T = float(raw["T"])
            otype = str(raw.get("option_type", "call"))
            if T <= 0 or K <= 0:
                raise ValueError("Each quote needs positive K and T")
            if raw.get("price") is not None:
                px = float(raw["price"])
            elif raw.get("iv") is not None:
                px = float(BlackScholes.price(S0, K, T, r, float(raw["iv"]), otype, q))
            else:
                raise ValueError("Each quote needs price or iv")
            market.append(px)
            specs.append((K, T, otype))
        market_arr = np.asarray(market, dtype=np.float64)

        def unpack(z: np.ndarray) -> tuple[float, float, float, float, float]:
            v0, kappa, theta, xi, rho = (float(v) for v in z)
            return v0, kappa, theta, xi, rho

        def residual(z: np.ndarray) -> np.ndarray:
            v0, kappa, theta, xi, rho = unpack(z)
            if xi < 1e-8:
                return np.full(len(specs), 1e2)
            model = np.array([
                HestonModel.price_cf_raw(S0, K, v0, r, kappa, theta, xi, rho, T, otype, q)
                for K, T, otype in specs
            ])
            return model - market_arr

        start = np.array(x0 if x0 is not None else (0.04, 1.5, 0.04, 0.4, -0.5), dtype=float)
        lo = np.array([1e-4, 0.05, 1e-4, 1e-3, -0.99])
        hi = np.array([1.0, 12.0, 1.0, 2.5, 0.99])
        start = np.clip(start, lo + 1e-6, hi - 1e-6)
        fit = least_squares(residual, start, bounds=(lo, hi), xtol=1e-8, ftol=1e-8, max_nfev=max_nfev)
        v0, kappa, theta, xi, rho = unpack(fit.x)
        fitted = market_arr + fit.fun
        rmse = float(np.sqrt(np.mean(fit.fun ** 2)))
        feller = 2.0 * kappa * theta - xi ** 2
        smile = []
        for (K, T, otype), mkt, mdl in zip(specs, market_arr, fitted, strict=True):
            iv_mkt = BlackScholes.implied_volatility(float(mkt), S0, K, T, r, otype, q)
            iv_mdl = BlackScholes.implied_volatility(float(mdl), S0, K, T, r, otype, q)
            smile.append({
                "K": K, "T": T, "option_type": otype,
                "market_price": round(float(mkt), 6),
                "model_price": round(float(mdl), 6),
                "market_iv": None if not np.isfinite(iv_mkt) else round(float(iv_mkt), 6),
                "model_iv": None if not np.isfinite(iv_mdl) else round(float(iv_mdl), 6),
            })
        return {
            "v0": round(v0, 6),
            "kappa": round(kappa, 6),
            "theta": round(theta, 6),
            "xi": round(xi, 6),
            "rho": round(rho, 6),
            "rmse_price": round(rmse, 8),
            "n_quotes": len(specs),
            "nfev": int(fit.nfev),
            "success": bool(fit.success and np.isfinite(rmse)),
            "feller_satisfied": bool(feller > 0),
            "feller_2k_theta_minus_xi2": round(float(feller), 6),
            "smile": smile,
            "math": (
                "min_{v0,κ,θ,ξ,ρ} Σ (C_Heston(K,T) − C_mkt)². "
                "Negative ρ is the leverage effect that puts the skew into puts."
            ),
            "eligible_for_live_trading": False,
            "what_broke": [
                "Five parameters from one expiry are unidentified; a change in κ can hide in θ.",
                "Price RMSE ignores vega: cheap OTM quotes do not pin vol-of-vol.",
                "No bid/ask, no weights, no calendar arbitrage constraints.",
                "Feller can fail at the optimum — the CF still returns a number.",
            ],
        }


class EWMAVolatility:
    """Exponentially Weighted Moving Average volatility."""

    @staticmethod
    def compute(returns: np.ndarray, lambda_: float = 0.94) -> dict:
        T = len(returns)
        var = np.zeros(T)
        var[0] = returns[0]**2

        for t in range(1, T):
            var[t] = lambda_ * var[t - 1] + (1 - lambda_) * returns[t]**2

        vol = np.sqrt(var) * np.sqrt(252)
        return {
            "volatility": vol.tolist(),
            "current_vol": round(float(vol[-1]), 4),
            "lambda": lambda_,
        }

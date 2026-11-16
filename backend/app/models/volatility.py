"""
Volatility Models
- GARCH(1,1)
- Heston Stochastic Volatility
- EWMA Volatility
"""

from typing import Literal

import numpy as np
from scipy.optimize import minimize

# np.trapz was removed in NumPy 2.0 (renamed np.trapezoid); the lock pins
# 1.26.x, but this keeps the Heston CF integrator working on either.
# One name is always missing from stubs (by version); the ignore covers both.
_trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz  # pyright: ignore[reportAttributeAccessIssue]


class GARCHModel:
    """GARCH(1,1) volatility model: σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}"""

    def __init__(self):
        self.omega: float = 0.0
        self.alpha: float = 0.0
        self.beta: float = 0.0
        self.mu: float = 0.0
        self.fitted: bool = False

    def fit(self, returns: np.ndarray) -> dict:
        """Fit GARCH(1,1) via maximum likelihood estimation on demeaned returns.

        The mean is estimated and removed first: fitting raw returns with
        nonzero drift biases variance targeting and the persistence estimate.
        Raises ValueError when the optimizer fails to converge.
        """
        returns = np.asarray(returns, dtype=np.float64)
        T = len(returns)
        self.mu = float(np.mean(returns))
        resid = returns - self.mu
        var_target = float(np.var(resid)) or 1e-12

        def neg_log_likelihood(params):
            omega, alpha, beta = params
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
                return 1e10
            sigma2 = np.zeros(T)
            sigma2[0] = var_target
            for t in range(1, T):
                sigma2[t] = omega + alpha * resid[t - 1]**2 + beta * sigma2[t - 1]
                if sigma2[t] <= 0:
                    return 1e10
            ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + resid**2 / sigma2)
            return -ll

        x0 = [var_target * 0.05, 0.08, 0.85]
        # α, β ∈ [0, 1) with α+β < 1 enforced in the likelihood — do not floor β at 0.5.
        bounds = [(1e-8, None), (0.0, 0.9999), (0.0, 0.9999)]
        result = minimize(neg_log_likelihood, x0, bounds=bounds, method="L-BFGS-B")
        if not result.success:
            raise ValueError(f"GARCH(1,1) MLE failed to converge: {result.message}")

        self.omega, self.alpha, self.beta = (float(v) for v in result.x)
        self.fitted = True

        # Compute conditional volatilities
        sigma2 = np.zeros(T)
        sigma2[0] = var_target
        for t in range(1, T):
            sigma2[t] = self.omega + self.alpha * resid[t - 1]**2 + self.beta * sigma2[t - 1]

        persistence = self.alpha + self.beta
        long_run_var = self.omega / (1 - persistence) if persistence < 1 else float("nan")

        return {
            "omega": round(self.omega, 8),
            "alpha": round(self.alpha, 6),
            "beta": round(self.beta, 6),
            "mu": round(self.mu, 8),
            "persistence": round(persistence, 6),
            "long_run_variance": round(long_run_var, 8),
            "long_run_volatility": round(np.sqrt(long_run_var) * np.sqrt(252), 4) if not np.isnan(long_run_var) else None,
            "conditional_volatility": (np.sqrt(sigma2) * np.sqrt(252)).tolist(),
            "log_likelihood": round(-result.fun, 4),
            "converged": True,
        }

    def forecast(self, returns: np.ndarray, horizon: int = 30) -> dict:
        """Forecast volatility h steps ahead, with 95% predictive return bands.

        Bands are mu ± 1.96·sqrt(var_h) in daily-return units (not
        annualized). Raises ValueError on non-stationary fits instead of
        dividing by zero persistence.
        """
        if not self.fitted:
            self.fit(returns)
        returns = np.asarray(returns, dtype=np.float64)
        resid = returns - self.mu

        T = len(returns)
        sigma2 = np.zeros(T)
        sigma2[0] = float(np.var(resid)) or 1e-12
        for t in range(1, T):
            sigma2[t] = self.omega + self.alpha * resid[t - 1]**2 + self.beta * sigma2[t - 1]

        persistence = self.alpha + self.beta
        if persistence >= 1:
            raise ValueError("cannot forecast a non-stationary GARCH fit (alpha+beta >= 1)")

        # h-step forecast
        forecast_var = np.zeros(horizon)
        forecast_var[0] = self.omega + self.alpha * resid[-1]**2 + self.beta * sigma2[-1]
        long_run = self.omega / (1 - persistence)

        for h in range(1, horizon):
            forecast_var[h] = long_run + persistence**h * (forecast_var[0] - long_run)

        band = 1.96 * np.sqrt(forecast_var)
        return {
            "forecast_volatility": (np.sqrt(forecast_var) * np.sqrt(252)).tolist(),
            "forecast_interval_95": {
                "lower": (self.mu - band).tolist(),
                "upper": (self.mu + band).tolist(),
                "units": "daily returns",
            },
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
        rng = np.random.default_rng(seed)

        dt = T / n_steps
        sqrt_dt = np.sqrt(dt)
        feller = 2.0 * kappa * theta - xi ** 2

        S = np.zeros((n_paths, n_steps + 1))
        v = np.zeros((n_paths, n_steps + 1))
        S[:, 0] = S0
        v[:, 0] = v0

        for t in range(1, n_steps + 1):
            z1 = rng.standard_normal(n_paths)
            z2 = rho * z1 + np.sqrt(1 - rho**2) * rng.standard_normal(n_paths)

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
        rng = np.random.default_rng(seed)

        n_steps = max(1, int(round(252 * T)))
        dt = T / n_steps
        half = n_paths // 2
        remainder = n_paths - 2 * half
        S = np.full(n_paths, S0)
        v = np.full(n_paths, v0)

        for _ in range(n_steps):
            z1_half = rng.standard_normal(half)
            z2_ind = rng.standard_normal(half)
            z1 = np.concatenate([z1_half, -z1_half] + ([rng.standard_normal(remainder)] if remainder else []))
            z2_raw = np.concatenate([z2_ind, -z2_ind] + ([rng.standard_normal(remainder)] if remainder else []))
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
            return float(0.5 + _trapezoid(integrand, u) / np.pi)

        p1_raw, p2_raw = _pj(1), _pj(2)
        # P1/P2 are risk-neutral probabilities: outside [0, 1] is pure
        # quadrature noise, and it would serve an arbitrable quote.
        p1 = min(max(float(p1_raw), 0.0), 1.0)
        p2 = min(max(float(p2_raw), 0.0), 1.0)
        disc_s = S0 * np.exp(-q * T)
        disc_k = K * np.exp(-r * T)
        call = disc_s * p1 - disc_k * p2
        call_floor = max(disc_s - disc_k, 0.0)
        put_floor = max(disc_k - disc_s, 0.0)
        violated = (
            p1 != p1_raw or p2 != p2_raw
            or call < call_floor - 1e-9
        )
        call = max(call, call_floor)
        put = call - disc_s + disc_k
        if put < put_floor - 1e-9:
            violated = True
            put = put_floor
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
            "arbitrage_violation": bool(violated),
            "limitations": [
                "Fourier inversion uses a truncated trapezoid; deep OTM short-dated options need a finer grid.",
                "Complex logarithm uses the Albrecher branch; extreme parameters can still oscillate.",
                "This prices Europeans only. Americans need the PDE / tree / Longstaff–Schwartz.",
            ]
            + (["Raw CF output violated no-arbitrage bounds and was floored; treat this quote as unreliable."] if violated else []),
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
            return float(0.5 + _trapezoid(integrand, u) / np.pi)

        p1, p2 = _pj(1), _pj(2)
        call = S0 * np.exp(-q * T) * p1 - K * np.exp(-r * T) * p2
        if option_type == "call":
            return float(call)
        return float(call - S0 * np.exp(-q * T) + K * np.exp(-r * T))

    @staticmethod
    def _calendar_violations(expiry_iv: dict[float, float]) -> list[dict]:
        """Flag decreasing near-ATM total variance w(T) = iv²·T across expiries.

        A decrease is a calendar-spread arbitrage in the input (market) or a
        fit the desk should not trust (model). Diagnostic only: nothing here
        constrains the optimiser.
        """
        ordered = sorted(expiry_iv.items())
        out = []
        for (t_prev, iv_prev), (t, iv) in zip(ordered, ordered[1:], strict=False):
            w_prev, w = iv_prev**2 * t_prev, iv**2 * t
            if w < w_prev * (1 - 1e-9):
                out.append({
                    "T_prev": t_prev, "T": t,
                    "w_prev": round(w_prev, 8), "w": round(w, 8),
                })
        return out

    @staticmethod
    def calibrate(
        S0: float,
        r: float,
        quotes: list[dict],
        q: float = 0.0,
        x0: tuple[float, float, float, float, float] | None = None,
        max_nfev: int = 80,
        weighting: Literal["price", "vega"] = "price",
        n_restarts: int = 1,
        seed: int = 0,
    ) -> dict:
        """
        Least-squares fit of (v0, κ, θ, ξ, ρ) to European quotes, single or
        multi-expiry.

        Each quote is {K, T, price?} or {K, T, iv?, option_type?}. The objective is
        Σ wᵢ·(C_Heston − C_mkt)² with w = 1 (``weighting="price"``) or
        Black-Scholes vega at the market IV, mean-normalised
        (``weighting="vega"``) — vega-weighting is a desk choice we report, not hide.
        Five Heston parameters are not identified from a single expiry; pass a
        term structure (several T) and check ``rmse_by_expiry`` plus the calendar
        diagnostics. The optimiser is local, so ``n_restarts > 1`` retries from
        seeded jittered starts and keeps the best RMSE.
        """
        from scipy.optimize import least_squares

        from app.models.pricing import BlackScholes

        if weighting not in ("price", "vega"):
            raise ValueError(f"weighting must be 'price' or 'vega', got {weighting!r}")
        if n_restarts < 1:
            raise ValueError(f"n_restarts must be >= 1, got {n_restarts}")
        if len(quotes) < 4:
            raise ValueError("Need at least 4 quotes to calibrate Heston")
        if S0 <= 0:
            raise ValueError("S0 must be positive")

        market = []
        specs = []
        for raw in quotes:
            K = float(raw["K"])
            T = float(raw["T"])
            # BlackScholes.price prices anything that is not exactly "call" as a
            # put, so an unchecked "CALL" here would silently calibrate to the
            # wrong side of the smile.
            otype_raw = str(raw.get("option_type", "call")).strip().lower()
            if otype_raw not in ("call", "put"):
                raise ValueError(f"option_type must be 'call' or 'put', got {raw.get('option_type')!r}")
            otype: Literal["call", "put"] = "call" if otype_raw == "call" else "put"
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

        # Vega weights come from the market smile, not the model: they must not
        # move while the optimiser runs.
        vega_fallback_n = 0
        if weighting == "vega":
            raw_w = []
            for (K, T, otype), mkt in zip(specs, market_arr, strict=True):
                iv = BlackScholes.implied_volatility(float(mkt), S0, K, T, r, otype, q)
                vega = BlackScholes.greeks(S0, K, T, r, iv, otype, q).vega if np.isfinite(iv) else 0.0
                if not np.isfinite(vega) or vega <= 0:
                    vega_fallback_n += 1
                    raw_w.append(1.0)
                else:
                    raw_w.append(float(vega))
            weights = np.asarray(raw_w, dtype=np.float64)
            weights = weights / float(np.mean(weights))
        else:
            weights = np.ones(len(specs))
        weights = np.clip(weights, 1e-6, None)
        root_w = np.sqrt(weights)

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
            return root_w * (model - market_arr)

        lo = np.array([1e-4, 0.05, 1e-4, 1e-3, -0.99])
        hi = np.array([1.0, 12.0, 1.0, 2.5, 0.99])
        base = np.array(x0 if x0 is not None else (0.04, 1.5, 0.04, 0.4, -0.5), dtype=float)
        base = np.clip(base, lo + 1e-6, hi - 1e-6)
        rng = np.random.default_rng(seed)
        starts = [base]
        for _ in range(n_restarts - 1):
            jitter = base.copy()
            jitter[:4] = np.clip(jitter[:4] * rng.uniform(0.5, 1.5, 4), lo[:4] + 1e-6, hi[:4] - 1e-6)
            jitter[4] = float(np.clip(base[4] + rng.uniform(-0.3, 0.3), lo[4] + 1e-6, hi[4] - 1e-6))
            starts.append(jitter)

        runs = []
        for start in starts:
            fit = least_squares(residual, start, bounds=(lo, hi), xtol=1e-8, ftol=1e-8, max_nfev=max_nfev)
            run_rmse = float(np.sqrt(np.mean((fit.fun / root_w) ** 2)))
            runs.append((run_rmse, fit))
        best_restart = int(np.argmin([rmse for rmse, _ in runs]))
        rmse, fit = runs[best_restart]
        v0, kappa, theta, xi, rho = unpack(fit.x)
        fitted = market_arr + fit.fun / root_w
        feller = 2.0 * kappa * theta - xi ** 2
        smile = []
        mkt_expiry_iv: dict[float, tuple[float, float]] = {}
        mdl_expiry_iv: dict[float, tuple[float, float]] = {}
        for (K, T, otype), mkt, mdl, w in zip(specs, market_arr, fitted, weights, strict=True):
            iv_mkt = BlackScholes.implied_volatility(float(mkt), S0, K, T, r, otype, q)
            iv_mdl = BlackScholes.implied_volatility(float(mdl), S0, K, T, r, otype, q)
            dist = abs(K / S0 - 1.0)
            if np.isfinite(iv_mkt) and (T not in mkt_expiry_iv or dist < mkt_expiry_iv[T][0]):
                mkt_expiry_iv[T] = (dist, float(iv_mkt))
            if np.isfinite(iv_mdl) and (T not in mdl_expiry_iv or dist < mdl_expiry_iv[T][0]):
                mdl_expiry_iv[T] = (dist, float(iv_mdl))
            smile.append({
                "K": K, "T": T, "option_type": otype,
                "weight": round(float(w), 6),
                "market_price": round(float(mkt), 6),
                "model_price": round(float(mdl), 6),
                "market_iv": None if not np.isfinite(iv_mkt) else round(float(iv_mkt), 6),
                "model_iv": None if not np.isfinite(iv_mdl) else round(float(iv_mdl), 6),
            })
        rmse_by_expiry = {}
        for T in sorted({t for _, t, _ in specs}):
            idx = [i for i, (_, t, _) in enumerate(specs) if t == T]
            errs = fitted[idx] - market_arr[idx]
            rmse_by_expiry[str(T)] = round(float(np.sqrt(np.mean(errs ** 2))), 8)
        return {
            "v0": round(v0, 6),
            "kappa": round(kappa, 6),
            "theta": round(theta, 6),
            "xi": round(xi, 6),
            "rho": round(rho, 6),
            "rmse_price": round(rmse, 8),
            "rmse_by_expiry": rmse_by_expiry,
            "weighting": weighting,
            "vega_fallback_n": vega_fallback_n,
            "n_quotes": len(specs),
            "nfev": int(fit.nfev),
            "n_restarts": n_restarts,
            "seed": seed,
            "best_restart": best_restart,
            "restarts": [
                {"rmse_price": round(run_rmse, 8), "nfev": int(run_fit.nfev), "success": bool(run_fit.success)}
                for run_rmse, run_fit in runs
            ],
            "success": bool(fit.success and np.isfinite(rmse)),
            "feller_satisfied": bool(feller > 0),
            "feller_2k_theta_minus_xi2": round(float(feller), 6),
            "market_calendar_violations": HestonModel._calendar_violations(
                {t: iv for t, (_, iv) in mkt_expiry_iv.items()}),
            "model_calendar_violations": HestonModel._calendar_violations(
                {t: iv for t, (_, iv) in mdl_expiry_iv.items()}),
            "smile": smile,
            "math": (
                "min_{v0,κ,θ,ξ,ρ} Σ wᵢ·(C_Heston(K,T) − C_mkt)², "
                "w = 1 or mean-normalised BS vega at the market IV. "
                "Negative ρ is the leverage effect that puts the skew into puts."
            ),
            "eligible_for_live_trading": False,
            "what_broke": [
                "Five parameters from one expiry are unidentified; a change in κ can hide in θ.",
                "Vega weights pin vol-of-vol to ATM quotes; wings still barely identify ξ.",
                "Bid/ask is ignored (mid/last only); calendar arbitrage is diagnosed, not constrained.",
                "Feller can fail at the optimum — the CF still returns a number.",
            ],
        }

    @staticmethod
    def quotes_from_option_chain(
        chains: dict | list[dict],
        S0: float,
        as_of: str | None = None,
        min_volume: int = 0,
        moneyness: tuple[float, float] = (0.7, 1.3),
        max_per_expiry: int = 9,
    ) -> list[dict]:
        """Turn real option chains into ``calibrate`` quotes.

        Accepts the ``DataFetcher.get_options_chain`` shape
        (``{expiry, calls:[{strike,lastPrice,bid,ask,volume,...}], puts:[...]}``,
        one dict or a list of them for several expiries) and the
        ``/market-data/options-chain`` endpoint shape (``{chain:[{expiration,
        strike, call_price, put_price, ...}]}``). Price is the bid/ask mid when
        both sides are positive, else lastPrice; zero/negative premiums, expired
        contracts, low volume and off-window moneyness are dropped, not faked.
        """
        from datetime import date

        if S0 <= 0:
            raise ValueError("S0 must be positive")
        lo_m, hi_m = moneyness
        if not (0 < lo_m < hi_m):
            raise ValueError(f"moneyness must satisfy 0 < lo < hi, got {moneyness!r}")
        if max_per_expiry < 1:
            raise ValueError(f"max_per_expiry must be >= 1, got {max_per_expiry}")
        ref = date.fromisoformat(as_of) if as_of else date.today()

        per_expiry: dict[str, dict[str, list[dict]]] = {}

        def _emit(exp: str, strike: float, price: float, otype: str, volume: int) -> None:
            if price <= 0 or not np.isfinite(price):
                return
            m = strike / S0
            if not (lo_m <= m <= hi_m) or volume < min_volume:
                return
            try:
                days = (date.fromisoformat(exp) - ref).days
            except ValueError:
                return
            T = days / 365.0
            if T <= 0:
                return
            per_expiry.setdefault(exp, {"call": [], "put": []})[otype].append(
                {"K": float(strike), "T": T, "price": float(price),
                 "option_type": otype, "_vol": volume}
            )

        def _mid(row: dict) -> float:
            bid = float(row.get("bid") or 0.0)
            ask = float(row.get("ask") or 0.0)
            if bid > 0 and ask >= bid:
                return (bid + ask) / 2.0
            return float(row.get("lastPrice") or 0.0)

        def _yf_volume(row: dict) -> int:
            try:
                return max(0, int(float(row.get("volume") or 0)))
            except (TypeError, ValueError):
                return 0

        items = chains if isinstance(chains, list) else [chains]
        for item in items:
            if "chain" in item:
                for row in item["chain"]:
                    exp = str(row.get("expiration", ""))
                    strike = float(row.get("strike") or 0.0)
                    if strike <= 0 or not exp:
                        continue
                    vol = _yf_volume(row)
                    _emit(exp, strike, float(row.get("call_price") or 0.0), "call", vol)
                    _emit(exp, strike, float(row.get("put_price") or 0.0), "put", vol)
            elif "calls" in item or "puts" in item:
                exp = str(item.get("expiry", ""))
                if not exp:
                    continue
                for row in item.get("calls") or []:
                    strike = float(row.get("strike") or 0.0)
                    if strike > 0:
                        _emit(exp, strike, _mid(row), "call", _yf_volume(row))
                for row in item.get("puts") or []:
                    strike = float(row.get("strike") or 0.0)
                    if strike > 0:
                        _emit(exp, strike, _mid(row), "put", _yf_volume(row))
            else:
                raise ValueError("Unrecognized chain shape: need {expiry,calls,puts} or {chain:[...]}")

        quotes = []
        for exp in sorted(per_expiry):
            for otype in ("call", "put"):
                ranked = sorted(per_expiry[exp][otype], key=lambda r: r["_vol"], reverse=True)
                for row in ranked[:max_per_expiry]:
                    row.pop("_vol", None)
                    quotes.append(row)
        return quotes


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

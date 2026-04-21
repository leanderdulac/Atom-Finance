"""
Options Pricing Models
- Black-Scholes-Merton
- Monte Carlo Simulation
- Binomial Tree
- Finite Difference Methods
- Greeks Calculation
- Implied Volatility
"""
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Literal, Optional
from dataclasses import dataclass


@dataclass
class OptionResult:
    price: float
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0


# ─── Black-Scholes-Merton ────────────────────────────────────────────────────

class BlackScholes:
    """Analytical Black-Scholes-Merton model for European options."""

    @staticmethod
    def d1(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
        return (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))

    @staticmethod
    def d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
        return BlackScholes.d1(S, K, T, r, sigma, q) - sigma * np.sqrt(T)

    @classmethod
    def price(cls, S: float, K: float, T: float, r: float, sigma: float,
              option_type: Literal["call", "put"] = "call", q: float = 0.0) -> float:
        if T <= 0:
            if option_type == "call":
                return max(S - K, 0.0)
            return max(K - S, 0.0)

        d1 = cls.d1(S, K, T, r, sigma, q)
        d2 = cls.d2(S, K, T, r, sigma, q)

        if option_type == "call":
            return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)

    @classmethod
    def greeks(cls, S: float, K: float, T: float, r: float, sigma: float,
               option_type: Literal["call", "put"] = "call", q: float = 0.0) -> OptionResult:
        if T <= 1e-10:
            intrinsic = max(S - K, 0) if option_type == "call" else max(K - S, 0)
            return OptionResult(price=intrinsic)

        d1 = cls.d1(S, K, T, r, sigma, q)
        d2 = cls.d2(S, K, T, r, sigma, q)
        sqrt_T = np.sqrt(T)
        price = cls.price(S, K, T, r, sigma, option_type, q)

        # Delta
        if option_type == "call":
            delta = np.exp(-q * T) * norm.cdf(d1)
        else:
            delta = -np.exp(-q * T) * norm.cdf(-d1)

        # Gamma (same for call and put)
        gamma = np.exp(-q * T) * norm.pdf(d1) / (S * sigma * sqrt_T)

        # Theta
        common_theta = -(S * sigma * np.exp(-q * T) * norm.pdf(d1)) / (2 * sqrt_T)
        if option_type == "call":
            theta = common_theta - r * K * np.exp(-r * T) * norm.cdf(d2) + q * S * np.exp(-q * T) * norm.cdf(d1)
        else:
            theta = common_theta + r * K * np.exp(-r * T) * norm.cdf(-d2) - q * S * np.exp(-q * T) * norm.cdf(-d1)
        theta /= 365.0  # Per day

        # Vega
        vega = S * np.exp(-q * T) * norm.pdf(d1) * sqrt_T / 100.0  # Per 1% move

        # Rho
        if option_type == "call":
            rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100.0
        else:
            rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100.0

        return OptionResult(
            price=round(price, 6),
            delta=round(delta, 6),
            gamma=round(gamma, 6),
            theta=round(theta, 6),
            vega=round(vega, 6),
            rho=round(rho, 6),
        )

    @classmethod
    def implied_volatility(cls, market_price: float, S: float, K: float, T: float,
                           r: float, option_type: Literal["call", "put"] = "call",
                           q: float = 0.0) -> float:
        """Newton-Raphson with Brent fallback for implied volatility."""
        try:
            def objective(sigma):
                return cls.price(S, K, T, r, sigma, option_type, q) - market_price

            iv = brentq(objective, 1e-6, 10.0, xtol=1e-8)
            return round(iv, 6)
        except (ValueError, RuntimeError):
            return float("nan")


# ─── Monte Carlo Simulation ──────────────────────────────────────────────────

class MonteCarlo:
    """Monte Carlo simulation for option pricing with variance reduction."""

    @staticmethod
    def price(S: float, K: float, T: float, r: float, sigma: float,
              option_type: Literal["call", "put"] = "call",
              n_simulations: int = 100_000, n_steps: int = 252,
              q: float = 0.0, seed: Optional[int] = 42) -> dict:

        if seed is not None:
            np.random.seed(seed)

        dt = T / n_steps
        drift = (r - q - 0.5 * sigma**2) * dt
        vol = sigma * np.sqrt(dt)

        # Antithetic variates for variance reduction
        z = np.random.standard_normal((n_simulations // 2, n_steps))
        z = np.concatenate([z, -z], axis=0)

        log_paths = np.cumsum(drift + vol * z, axis=1)
        ST = S * np.exp(log_paths[:, -1])

        if option_type == "call":
            payoffs = np.maximum(ST - K, 0)
        else:
            payoffs = np.maximum(K - ST, 0)

        discounted = np.exp(-r * T) * payoffs
        price = float(np.mean(discounted))
        std_err = float(np.std(discounted) / np.sqrt(len(discounted)))

        # Paths for visualization (sample 200)
        sample_idx = np.linspace(0, len(log_paths) - 1, min(200, len(log_paths)), dtype=int)
        full_paths = S * np.exp(log_paths[sample_idx])
        paths_list = full_paths[:, ::max(1, n_steps // 50)].tolist()

        return {
            "price": round(price, 6),
            "std_error": round(std_err, 6),
            "confidence_95": [round(price - 1.96 * std_err, 6), round(price + 1.96 * std_err, 6)],
            "n_simulations": len(discounted),
            "sample_paths": paths_list[:20],
            "terminal_distribution": {
                "mean": round(float(np.mean(ST)), 2),
                "std": round(float(np.std(ST)), 2),
                "percentiles": {
                    "5": round(float(np.percentile(ST, 5)), 2),
                    "25": round(float(np.percentile(ST, 25)), 2),
                    "50": round(float(np.percentile(ST, 50)), 2),
                    "75": round(float(np.percentile(ST, 75)), 2),
                    "95": round(float(np.percentile(ST, 95)), 2),
                }
            }
        }


# ─── Binomial Tree ────────────────────────────────────────────────────────────

class BinomialTree:
    """Cox-Ross-Rubinstein binomial tree for American/European options."""

    @staticmethod
    def price(S: float, K: float, T: float, r: float, sigma: float,
              option_type: Literal["call", "put"] = "call",
              american: bool = False, n_steps: int = 500,
              q: float = 0.0) -> dict:

        dt = T / n_steps
        u = np.exp(sigma * np.sqrt(dt))
        d = 1.0 / u
        p = (np.exp((r - q) * dt) - d) / (u - d)
        disc = np.exp(-r * dt)

        # Build price tree at maturity
        prices = S * u ** np.arange(n_steps, -1, -1) * d ** np.arange(0, n_steps + 1)

        if option_type == "call":
            values = np.maximum(prices - K, 0)
        else:
            values = np.maximum(K - prices, 0)

        # Backward induction
        early_exercise_nodes = 0
        for i in range(n_steps - 1, -1, -1):
            prices_i = S * u ** np.arange(i, -1, -1) * d ** np.arange(0, i + 1)
            values = disc * (p * values[:-1] + (1 - p) * values[1:])

            if american:
                if option_type == "call":
                    exercise = np.maximum(prices_i - K, 0)
                else:
                    exercise = np.maximum(K - prices_i, 0)
                early = exercise > values
                early_exercise_nodes += int(np.sum(early))
                values = np.maximum(values, exercise)

        return {
            "price": round(float(values[0]), 6),
            "u": round(u, 6),
            "d": round(d, 6),
            "p": round(p, 6),
            "n_steps": n_steps,
            "american": american,
            "early_exercise_nodes": early_exercise_nodes,
        }


# ─── Finite Difference Method ────────────────────────────────────────────────

class FiniteDifference:
    """Crank-Nicolson finite difference method for option pricing."""

    @staticmethod
    def price(S: float, K: float, T: float, r: float, sigma: float,
              option_type: Literal["call", "put"] = "call",
              american: bool = False,
              S_max_mult: float = 3.0, N_S: int = 200, N_t: int = 500,
              q: float = 0.0) -> dict:

        S_max = S_max_mult * K
        dS = S_max / N_S
        dt = T / N_t

        S_grid = np.linspace(0, S_max, N_S + 1)
        j = np.arange(0, N_S + 1)

        # Coefficients for Crank-Nicolson
        alpha = 0.25 * dt * (sigma**2 * j**2 - (r - q) * j)
        beta = -0.5 * dt * (sigma**2 * j**2 + r)
        gamma_c = 0.25 * dt * (sigma**2 * j**2 + (r - q) * j)

        # Terminal condition
        if option_type == "call":
            V = np.maximum(S_grid - K, 0)
        else:
            V = np.maximum(K - S_grid, 0)

        # Tridiagonal matrices
        M1 = np.diag(1 - beta[1:N_S]) + np.diag(-alpha[2:N_S], -1) + np.diag(-gamma_c[1:N_S - 1], 1)
        M2 = np.diag(1 + beta[1:N_S]) + np.diag(alpha[2:N_S], -1) + np.diag(gamma_c[1:N_S - 1], 1)

        for i in range(N_t):
            rhs = M2 @ V[1:N_S]

            # Boundary conditions
            if option_type == "call":
                rhs[0] += alpha[1] * 0
                rhs[-1] += gamma_c[N_S - 1] * (S_max - K * np.exp(-r * (T - (i + 1) * dt)))
            else:
                rhs[0] += alpha[1] * (K * np.exp(-r * (T - (i + 1) * dt)))
                rhs[-1] += gamma_c[N_S - 1] * 0

            V[1:N_S] = np.linalg.solve(M1, rhs)

            if american:
                if option_type == "call":
                    V = np.maximum(V, np.maximum(S_grid - K, 0))
                else:
                    V = np.maximum(V, np.maximum(K - S_grid, 0))

        # Interpolate to get price at S
        idx = int(S / dS)
        idx = min(idx, N_S - 1)
        weight = (S - S_grid[idx]) / dS
        price = V[idx] + weight * (V[idx + 1] - V[idx])

        return {
            "price": round(float(price), 6),
            "method": "crank_nicolson",
            "grid_size": f"{N_S}x{N_t}",
            "american": american,
        }


# ─── Implied Volatility Surface ──────────────────────────────────────────────

class VolatilitySurface:
    """Generate implied volatility surfaces."""

    @staticmethod
    def generate(S: float, r: float, strikes: list[float], maturities: list[float],
                 market_prices: Optional[list[list[float]]] = None,
                 option_type: Literal["call", "put"] = "call",
                 q: float = 0.0) -> dict:
        """
        If market_prices provided, compute IV surface from them.
        Otherwise generate a synthetic smile/skew surface.
        """
        surface = []

        if market_prices is not None:
            for i, T in enumerate(maturities):
                row = []
                for j, K in enumerate(strikes):
                    try:
                        iv = BlackScholes.implied_volatility(
                            market_prices[i][j], S, K, T, r, option_type, q
                        )
                    except Exception:
                        iv = float("nan")
                    row.append(round(iv, 4) if not np.isnan(iv) else None)
                surface.append(row)
        else:
            # Generate synthetic volatility smile
            atm_vol = 0.20
            for T in maturities:
                row = []
                for K in strikes:
                    moneyness = np.log(K / S)
                    # Skew + smile + term structure
                    skew = -0.1 * moneyness
                    smile = 0.05 * moneyness**2
                    term = -0.02 * np.sqrt(T)
                    iv = atm_vol + skew + smile + term
                    iv = max(iv, 0.01)
                    row.append(round(iv, 4))
                surface.append(row)

        return {
            "strikes": strikes,
            "maturities": maturities,
            "surface": surface,
            "spot": S,
        }


# ─── Options Strategies ──────────────────────────────────────────────────────

class OptionsStrategies:
    """Common options strategies: payoff diagrams and analysis."""

    @staticmethod
    def _leg_payoff(S_range: np.ndarray, K: float, option_type: str, position: str, premium: float) -> np.ndarray:
        if option_type == "call":
            intrinsic = np.maximum(S_range - K, 0)
        else:
            intrinsic = np.maximum(K - S_range, 0)
        if position == "long":
            return intrinsic - premium
        else:
            return premium - intrinsic

    @classmethod
    def analyze_strategy(cls, legs: list[dict], S: float, sigma: float = 0.2,
                         r: float = 0.05, T: float = 0.25) -> dict:
        """
        legs: [{"strike": K, "type": "call"/"put", "position": "long"/"short", "quantity": 1}]
        """
        S_range = np.linspace(S * 0.5, S * 1.5, 200)
        total_payoff = np.zeros_like(S_range)
        total_premium = 0.0
        greeks_total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        for leg in legs:
            K = leg["strike"]
            opt_type = leg["type"]
            pos = leg["position"]
            qty = leg.get("quantity", 1)

            premium = BlackScholes.price(S, K, T, r, sigma, opt_type)
            g = BlackScholes.greeks(S, K, T, r, sigma, opt_type)

            sign = 1 if pos == "long" else -1
            total_payoff += qty * sign * cls._leg_payoff(S_range, K, opt_type, "long", 0)
            total_premium += qty * sign * premium

            for gk in greeks_total:
                greeks_total[gk] += qty * sign * getattr(g, gk)

        net_payoff = total_payoff - total_premium

        # Find breakeven points
        sign_changes = np.where(np.diff(np.sign(net_payoff)))[0]
        breakevens = [round(float(S_range[i]), 2) for i in sign_changes]

        max_profit = float(np.max(net_payoff))
        max_loss = float(np.min(net_payoff))

        return {
            "payoff_x": S_range.tolist(),
            "payoff_y": net_payoff.tolist(),
            "total_premium": round(total_premium, 4),
            "max_profit": round(max_profit, 4) if max_profit < 1e6 else "unlimited",
            "max_loss": round(max_loss, 4),
            "breakeven_points": breakevens,
            "greeks": {k: round(v, 6) for k, v in greeks_total.items()},
        }

    @classmethod
    def straddle(cls, S: float, K: float, sigma: float = 0.2, r: float = 0.05, T: float = 0.25, position: str = "long") -> dict:
        legs = [
            {"strike": K, "type": "call", "position": position, "quantity": 1},
            {"strike": K, "type": "put", "position": position, "quantity": 1},
        ]
        return cls.analyze_strategy(legs, S, sigma, r, T)

    @classmethod
    def iron_condor(cls, S: float, K1: float, K2: float, K3: float, K4: float,
                    sigma: float = 0.2, r: float = 0.05, T: float = 0.25) -> dict:
        legs = [
            {"strike": K1, "type": "put", "position": "long", "quantity": 1},
            {"strike": K2, "type": "put", "position": "short", "quantity": 1},
            {"strike": K3, "type": "call", "position": "short", "quantity": 1},
            {"strike": K4, "type": "call", "position": "long", "quantity": 1},
        ]
        return cls.analyze_strategy(legs, S, sigma, r, T)

    @classmethod
    def butterfly(cls, S: float, K1: float, K2: float, K3: float,
                  sigma: float = 0.2, r: float = 0.05, T: float = 0.25,
                  option_type: str = "call") -> dict:
        legs = [
            {"strike": K1, "type": option_type, "position": "long", "quantity": 1},
            {"strike": K2, "type": option_type, "position": "short", "quantity": 2},
            {"strike": K3, "type": option_type, "position": "long", "quantity": 1},
        ]
        return cls.analyze_strategy(legs, S, sigma, r, T)

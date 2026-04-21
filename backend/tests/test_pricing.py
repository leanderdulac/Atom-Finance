"""Tests for options pricing models."""
import math
import pytest
import numpy as np

from app.models.pricing import (
    BinomialTree,
    BlackScholes,
    FiniteDifference,
    MonteCarlo,
    OptionsStrategies,
)


# ── Black-Scholes ──────────────────────────────────────────────────────────────

class TestBlackScholes:
    """Reference values computed from standard BS formulas."""

    # ATM call: S=100, K=100, T=1, r=0.05, σ=0.2 → ~10.4506
    def test_call_price_atm(self):
        price = BlackScholes.price(100, 100, 1.0, 0.05, 0.2, "call")
        assert abs(price - 10.4506) < 0.01

    # Put-call parity: C - P = S·exp(-q·T) - K·exp(-r·T)
    def test_put_call_parity(self):
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.2
        call = BlackScholes.price(S, K, T, r, sigma, "call")
        put = BlackScholes.price(S, K, T, r, sigma, "put")
        lhs = call - put
        rhs = S - K * math.exp(-r * T)
        assert abs(lhs - rhs) < 1e-4

    def test_call_delta_range(self):
        g = BlackScholes.greeks(100, 100, 1.0, 0.05, 0.2, "call")
        assert 0 < g.delta < 1

    def test_put_delta_range(self):
        g = BlackScholes.greeks(100, 100, 1.0, 0.05, 0.2, "put")
        assert -1 < g.delta < 0

    def test_gamma_positive(self):
        g = BlackScholes.greeks(100, 100, 1.0, 0.05, 0.2, "call")
        assert g.gamma > 0

    def test_vega_positive(self):
        g = BlackScholes.greeks(100, 100, 1.0, 0.05, 0.2, "call")
        assert g.vega > 0

    def test_theta_negative_for_long_call(self):
        g = BlackScholes.greeks(100, 100, 1.0, 0.05, 0.2, "call")
        assert g.theta < 0

    def test_expiry_call_intrinsic(self):
        price = BlackScholes.price(110, 100, 0, 0.05, 0.2, "call")
        assert price == 10.0

    def test_expiry_put_otm(self):
        price = BlackScholes.price(110, 100, 0, 0.05, 0.2, "put")
        assert price == 0.0

    def test_implied_volatility_roundtrip(self):
        sigma = 0.25
        price = BlackScholes.price(100, 100, 1.0, 0.05, sigma, "call")
        recovered = BlackScholes.implied_volatility(price, 100, 100, 1.0, 0.05, "call")
        assert abs(recovered - sigma) < 1e-4


# ── Monte Carlo ────────────────────────────────────────────────────────────────

class TestMonteCarlo:
    def test_call_price_close_to_bs(self):
        bs = BlackScholes.price(100, 100, 1.0, 0.05, 0.2, "call")
        mc = MonteCarlo.price(100, 100, 1.0, 0.05, 0.2, "call", n_simulations=200_000, seed=0)
        assert abs(mc["price"] - bs) < 0.15  # MC has statistical error

    def test_returns_required_keys(self):
        result = MonteCarlo.price(100, 100, 1.0, 0.05, 0.2, "call", n_simulations=10_000, seed=1)
        assert "price" in result
        assert "std_error" in result
        assert "confidence_95" in result
        assert "terminal_distribution" in result


# ── Binomial Tree ──────────────────────────────────────────────────────────────

class TestBinomialTree:
    def test_european_call_close_to_bs(self):
        bs = BlackScholes.price(100, 100, 1.0, 0.05, 0.2, "call")
        bt = BinomialTree.price(100, 100, 1.0, 0.05, 0.2, "call", american=False, n_steps=500)
        assert abs(bt["price"] - bs) < 0.05

    def test_american_put_ge_european(self):
        eur = BinomialTree.price(100, 100, 1.0, 0.05, 0.2, "put", american=False)["price"]
        ame = BinomialTree.price(100, 100, 1.0, 0.05, 0.2, "put", american=True)["price"]
        assert ame >= eur


# ── Finite Difference ─────────────────────────────────────────────────────────

class TestFiniteDifference:
    def test_european_call_close_to_bs(self):
        bs = BlackScholes.price(100, 100, 1.0, 0.05, 0.2, "call")
        fd = FiniteDifference.price(100, 100, 1.0, 0.05, 0.2, "call", american=False)
        assert abs(fd["price"] - bs) < 0.10

    def test_american_put_ge_european(self):
        eur = FiniteDifference.price(100, 100, 1.0, 0.05, 0.2, "put", american=False)["price"]
        ame = FiniteDifference.price(100, 100, 1.0, 0.05, 0.2, "put", american=True)["price"]
        assert ame >= eur


# ── Options Strategies ────────────────────────────────────────────────────────

class TestOptionsStrategies:
    def test_straddle_returns_payoff(self):
        result = OptionsStrategies.straddle(100, 100, 0.2)
        assert "payoff_x" in result
        assert "payoff_y" in result
        assert "breakeven_points" in result

    def test_iron_condor_max_profit_finite(self):
        result = OptionsStrategies.iron_condor(100, 90, 95, 105, 110, 0.2)
        assert isinstance(result["max_profit"], float)

    def test_butterfly_max_loss_negative(self):
        result = OptionsStrategies.butterfly(100, 90, 100, 110, 0.2)
        assert result["max_loss"] < 0

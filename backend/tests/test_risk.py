"""Tests for risk analysis models."""
import numpy as np
import pytest

from app.models.risk import StressTest, ValueAtRisk
from app.models.volatility import EWMAVolatility, GARCHModel


@pytest.fixture
def normal_returns():
    rng = np.random.default_rng(42)
    return rng.normal(0.0005, 0.015, 500)


# ── ValueAtRisk ───────────────────────────────────────────────────────────────

class TestVaR:
    def test_historical_var_positive(self, normal_returns):
        result = ValueAtRisk.historical(normal_returns, confidence=0.95)
        assert result["var_percentage"] > 0
        assert result["cvar_percentage"] >= result["var_percentage"]

    def test_parametric_var_positive(self, normal_returns):
        result = ValueAtRisk.parametric(normal_returns, confidence=0.95)
        assert result["var_percentage"] > 0

    def test_mc_var_positive(self, normal_returns):
        result = ValueAtRisk.monte_carlo(normal_returns, confidence=0.95, n_simulations=10_000)
        assert result["var_percentage"] > 0

    def test_higher_confidence_higher_var(self, normal_returns):
        var_95 = ValueAtRisk.historical(normal_returns, confidence=0.95)["var_percentage"]
        var_99 = ValueAtRisk.historical(normal_returns, confidence=0.99)["var_percentage"]
        assert var_99 > var_95

    def test_var_absolute_equals_pct_times_portfolio(self, normal_returns):
        pv = 1_000_000
        result = ValueAtRisk.historical(normal_returns, portfolio_value=pv)
        expected_abs = result["var_percentage"] / 100 * pv
        assert abs(result["var_absolute"] - expected_abs) < 1


# ── StressTest ────────────────────────────────────────────────────────────────

class TestStressTest:
    PORTFOLIO = {"equity": 0.6, "bonds": 0.3, "gold": 0.1}

    def test_2008_crisis_negative_impact(self):
        result = StressTest.run(self.PORTFOLIO, "2008_financial_crisis")
        assert result["total_impact_pct"] < 0

    def test_gold_heavy_portfolio_survives_crisis(self):
        gold_heavy = {"equity": 0.2, "bonds": 0.1, "gold": 0.7}
        result = StressTest.run(gold_heavy, "2008_financial_crisis")
        # Gold was +25% in 2008; should lose less than equity-heavy
        equity_heavy = {"equity": 0.9, "bonds": 0.05, "gold": 0.05}
        result_eq = StressTest.run(equity_heavy, "2008_financial_crisis")
        assert result["total_impact_pct"] > result_eq["total_impact_pct"]

    def test_run_all_returns_all_scenarios(self):
        result = StressTest.run_all(self.PORTFOLIO)
        assert len(result["scenarios"]) == len(StressTest.SCENARIOS)
        assert "worst_case" in result

    def test_unknown_scenario_returns_error(self):
        result = StressTest.run(self.PORTFOLIO, "nonexistent_scenario")
        assert "error" in result


# ── GARCH ─────────────────────────────────────────────────────────────────────

class TestGARCH:
    def test_fit_returns_parameters(self, normal_returns):
        model = GARCHModel()
        result = model.fit(normal_returns)
        assert result["alpha"] > 0
        assert result["beta"] > 0
        assert result["omega"] > 0
        assert result["alpha"] + result["beta"] < 1  # stationarity

    def test_forecast_length(self, normal_returns):
        model = GARCHModel()
        model.fit(normal_returns)
        forecast = model.forecast(normal_returns, horizon=10)
        assert len(forecast["forecast_volatility"]) == 10


# ── EWMA ──────────────────────────────────────────────────────────────────────

class TestEWMA:
    def test_output_length_matches_input(self, normal_returns):
        result = EWMAVolatility.compute(normal_returns, lambda_=0.94)
        assert len(result["volatility"]) == len(normal_returns)

    def test_current_vol_positive(self, normal_returns):
        result = EWMAVolatility.compute(normal_returns)
        assert result["current_vol"] > 0

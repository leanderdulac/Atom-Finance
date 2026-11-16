"""Unit tests for previously uncovered models: Kelly sizing + ML baselines."""
import numpy as np

from app.models.kelly_derivatives import kelly_derivatives
from app.models.ml_models import ExponentialSmoothingForecast


class TestKellyDerivatives:
    def test_known_value(self):
        # p=0.6, b=2: f* = 0.6 - 0.4/2 = 0.4; quarter kelly = 0.1
        out = kelly_derivatives(0.6, 2.0, 10_000.0, 0.25)
        assert out["kelly_full"] == 0.4
        assert out["kelly_frac"] == 0.1
        assert out["alocacao_dolares"] == 1000.0

    def test_no_edge_refused(self):
        out = kelly_derivatives(0.3, 1.0, 10_000.0)
        assert "erro" in out

    def test_zero_payout_is_error_not_crash(self):
        out = kelly_derivatives(0.6, 0.0, 10_000.0)
        assert "erro" in out

    def test_negative_payout_and_bankroll_rejected(self):
        assert "erro" in kelly_derivatives(0.6, -2.0, 10_000.0)
        assert "erro" in kelly_derivatives(0.6, 2.0, 0.0)
        assert "erro" in kelly_derivatives(0.6, 2.0, -5.0)

    def test_win_prob_bounds(self):
        assert "erro" in kelly_derivatives(0.0, 2.0, 10_000.0)
        assert "erro" in kelly_derivatives(1.0, 2.0, 10_000.0)


class TestExponentialSmoothingBaseline:
    def test_shape_and_bands(self):
        prices = np.linspace(100, 110, 61)
        out = ExponentialSmoothingForecast().predict(prices, forecast_days=10)
        assert out["model"] == "exponential_smoothing_baseline"
        assert len(out["predictions"]) == 10
        assert len(out["upper_band"]) == 10
        assert len(out["lower_band"]) == 10
        assert all(u >= p >= lb for u, p, lb in zip(out["upper_band"], out["predictions"], out["lower_band"], strict=True))

    def test_seeded_runs_are_identical(self):
        prices = np.linspace(100, 110, 61)
        a = ExponentialSmoothingForecast().predict(prices, forecast_days=5, seed=3)
        b = ExponentialSmoothingForecast().predict(prices, forecast_days=5, seed=3)
        assert a["predictions"] == b["predictions"]

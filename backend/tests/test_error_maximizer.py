"""Sample GMV is the error maximizer; Ledoit–Wolf restores the spectrum."""

from __future__ import annotations

import numpy as np
import pytest

from app.models.covariance import (
    condition_number,
    global_min_variance,
    ledoit_wolf_constant_correlation,
    marchenko_pastur_bounds,
    sample_covariance,
)
from app.models.error_maximizer import evaluate, factor_panel
from app.models.portfolio import PortfolioOptimizer


class TestLedoitWolf:
    def test_alpha_is_a_probability_and_lw_is_better_conditioned(self):
        returns, _true = factor_panel(40, 200, seed=7)
        sample = sample_covariance(returns)
        shrunk, meta = ledoit_wolf_constant_correlation(returns)
        assert 0.0 <= meta["alpha"] <= 1.0
        assert condition_number(shrunk) < condition_number(sample)
        assert float(np.min(np.linalg.eigvalsh(shrunk))) > float(np.min(np.linalg.eigvalsh(sample)))
        np.testing.assert_allclose(shrunk, shrunk.T, atol=1e-12)
        w = global_min_variance(shrunk)
        assert w.sum() == pytest.approx(1.0)

    def test_large_t_shrinks_less_than_wide_panel(self):
        tall, _ = factor_panel(8, 800, seed=3)
        wide, _ = factor_panel(40, 80, seed=3)
        alpha_tall = ledoit_wolf_constant_correlation(tall)[1]["alpha"]
        alpha_wide = ledoit_wolf_constant_correlation(wide)[1]["alpha"]
        assert alpha_wide > alpha_tall


class TestMarchenkoPastur:
    def test_bounds_match_the_textbook_100_by_252(self):
        mp = marchenko_pastur_bounds(100, 252)
        assert mp["q"] == pytest.approx(100 / 252, rel=1e-5)
        q = 100 / 252
        assert mp["lambda_minus"] == pytest.approx((1 - q**0.5) ** 2, rel=1e-4)
        assert mp["lambda_plus"] == pytest.approx((1 + q**0.5) ** 2, rel=1e-4)


class TestErrorMaximizerLab:
    def test_sample_gmv_is_more_extreme_and_costlier_than_lw(self):
        out = evaluate(n_assets=80, t_is=252, t_oos=63, seed=7)
        assert out["eligible_for_live_trading"] is False
        assert out["broker_orders_sent"] == 0
        assert out["gmv"]["sample"]["sum"] == pytest.approx(1.0, abs=1e-6)
        assert out["gmv"]["ledoit_wolf"]["sum"] == pytest.approx(1.0, abs=1e-6)
        assert out["gmv"]["sample"]["l1"] > out["gmv"]["ledoit_wolf"]["l1"]
        assert out["covariance"]["sample_condition"] > out["covariance"]["lw_condition"]
        assert out["turnover"]["sample"] > out["turnover"]["ledoit_wolf"]
        assert 0.0 <= out["covariance"]["ledoit_wolf"]["alpha"] <= 1.0
        assert "error maximizer" in out["math"].lower() or "maximizadora" in out["math"].lower() or "Σ⁻¹" in out["math"]
        assert out["marchenko_pastur"]["q"] == pytest.approx(80 / 252, rel=1e-5)

    def test_caller_panel_is_split_without_true_cov(self):
        panel, _ = factor_panel(12, 120, seed=1)
        out = evaluate(returns=panel.tolist(), n_assets=12, t_is=80, t_oos=40, seed=0)
        assert out["source"] == "caller"
        assert out["gmv"]["true"] is None
        assert out["eligible_for_live_trading"] is False


class TestDeskRoute:
    def test_evaluate_stays_paper(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from app.api.desk import router
        from app.core.limiter import limiter
        from app.core.security import get_current_user

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(router, prefix="/api/desk", dependencies=[Depends(get_current_user)])
        app.dependency_overrides[get_current_user] = lambda: "tester"
        client = TestClient(app)
        res = client.post(
            "/api/desk/error-maximizer/evaluate",
            json={"n_assets": 24, "t_is": 120, "t_oos": 40, "seed": 7},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible_for_live_trading"] is False
        assert body["gmv"]["sample"]["l1"] >= body["gmv"]["ledoit_wolf"]["l1"]


class TestPortfolioOptIn:
    def test_ledoit_wolf_changes_the_min_variance_book(self):
        rng = np.random.default_rng(0)
        cov = np.eye(6) * 0.0004 + 0.00008
        np.fill_diagonal(cov, 0.0004)
        returns = rng.multivariate_normal(np.zeros(6), cov, size=180)
        raw = PortfolioOptimizer(returns, shrinkage="none").min_variance(allow_short=True)
        lw = PortfolioOptimizer(returns, shrinkage="ledoit_wolf").min_variance(allow_short=True)
        assert raw["weights"] != lw["weights"]
        with pytest.raises(ValueError, match="shrinkage"):
            PortfolioOptimizer(returns, shrinkage="oracle")

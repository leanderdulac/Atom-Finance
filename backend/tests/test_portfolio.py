"""Tests for portfolio optimisation models."""
import numpy as np
import pytest

from app.models.portfolio import PortfolioOptimizer


@pytest.fixture
def returns_3assets():
    rng = np.random.default_rng(0)
    # 3 assets, 252 days
    return rng.multivariate_normal(
        mean=[0.0005, 0.0003, 0.0008],
        cov=[[0.0004, 0.0001, 0.00005],
             [0.0001, 0.0003, 0.00003],
             [0.00005, 0.00003, 0.0005]],
        size=252,
    )


class TestPortfolioOptimizer:
    def test_efficient_frontier_has_points(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets, ["A", "B", "C"])
        result = opt.markowitz_efficient_frontier(n_points=20)
        assert len(result["frontier"]["returns"]) > 0

    def test_max_sharpe_weights_sum_to_one(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets)
        result = opt.max_sharpe_ratio()
        total = sum(result["weights"].values())
        assert abs(total - 1.0) < 1e-4

    def test_min_variance_weights_sum_to_one(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets)
        result = opt.min_variance()
        total = sum(result["weights"].values())
        assert abs(total - 1.0) < 1e-4

    def test_risk_parity_weights_sum_to_one(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets)
        result = opt.risk_parity()
        total = sum(result["weights"].values())
        assert abs(total - 1.0) < 1e-4

    def test_min_variance_vol_le_equal_weight(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets)
        min_var = opt.min_variance()
        equal = opt._portfolio_performance(np.ones(3) / 3)
        assert min_var["volatility"] <= equal[1] * 100 + 0.01  # small tolerance

    def test_black_litterman_weights_finite(self, returns_3assets):
        opt = PortfolioOptimizer(returns_3assets, ["A", "B", "C"])
        result = opt.black_litterman(views={"A": 0.10, "C": 0.05})
        for w in result["weights"].values():
            assert not np.isnan(w) and not np.isinf(w)

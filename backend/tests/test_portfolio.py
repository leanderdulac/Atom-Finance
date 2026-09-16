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


class TestBlackLittermanMarketWeights:
    def _opt(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0.0002, 0.02, (600, 3))
        return PortfolioOptimizer(returns, ['AAA', 'BBB', 'CCC'])

    def test_equal_market_weights_match_legacy_default(self):
        # Backward compatibility: passing equal weights must reproduce the default.
        opt = self._opt()
        views = {'BBB': 0.10}
        base = opt.black_litterman(views)
        eqw = opt.black_litterman(views, market_weights={'AAA': 1/3, 'BBB': 1/3, 'CCC': 1/3})
        assert base['weights'] == eqw['weights']
        assert sum(v for v in eqw['market_cap_weights'].values()) == pytest.approx(1.0, abs=0.02)

    def test_market_weights_shift_equilibrium_and_output(self):
        opt = self._opt()
        views = {'BBB': 0.10}
        tilt = opt.black_litterman(views, market_weights={'AAA': 0.8, 'BBB': 0.1, 'CCC': 0.1})
        assert abs(tilt['market_cap_weights']['AAA'] - 0.8) < 0.02
        # A heavy anchor (AAA) must raise its implied equilibrium return relative
        # to the equal-weight case.
        eqw = opt.black_litterman(views, market_weights={'AAA': 1/3, 'BBB': 1/3, 'CCC': 1/3})
        # equilibrium returns are exposed in percent; AAA should be more demanded
        assert tilt['equilibrium_returns']['AAA'] != eqw['equilibrium_returns']['AAA']

    def test_invalid_market_weights_rejected(self):
        opt = self._opt()
        views = {'BBB': 0.10}
        for bad in ({'AAA': -0.1, 'BBB': 0.5, 'CCC': 0.6},
                    {'AAA': 0.0, 'BBB': 0.0, 'CCC': 0.0}):
            with pytest.raises(ValueError):
                opt.black_litterman(views, market_weights=bad)
        with pytest.raises(ValueError):
            opt.black_litterman(views, market_weights=[0.5, 0.5])  # wrong length

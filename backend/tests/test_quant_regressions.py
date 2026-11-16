"""Regression tests for quant-model fixes (no DB required).

Each test pins a corrected behaviour with a statistical or closed-form
acceptance criterion — not a snapshot of current output.
"""
import math

import numpy as np
import pytest
from scipy.stats import t as t_dist

from app.models.backtesting import BacktestEngine
from app.models.cointegration import engle_granger
from app.models.portfolio import PortfolioOptimizer
from app.models.risk import ValueAtRisk
from app.models.volatility import HestonModel


class TestADFSizeAndPower:
    N_SIM = 3000
    N = 200

    def _random_walks(self, rng):
        x = np.cumsum(rng.normal(size=self.N))
        y = np.cumsum(rng.normal(size=self.N))
        return y, x

    def test_size_under_independent_random_walks(self):
        """Under H0 (no cointegration) the 5% test must reject ~5% (±1.5pp)."""
        rng = np.random.default_rng(11)
        rejects = sum(
            engle_granger(*self._random_walks(rng), significance=0.05)["cointegrated"]
            for _ in range(self.N_SIM)
        )
        rate = rejects / self.N_SIM
        assert rate == pytest.approx(0.05, abs=0.015)

    def test_power_under_cointegration(self):
        """y = x + stationary noise must reject H0 with high probability."""
        rng = np.random.default_rng(12)
        rejects = 0
        for _ in range(500):
            x = np.cumsum(rng.normal(size=self.N))
            noise = np.zeros(self.N)
            for t in range(1, self.N):
                noise[t] = 0.5 * noise[t - 1] + rng.normal()
            y = x + noise
            rejects += engle_granger(y, x, significance=0.05)["cointegrated"]
        assert rejects / 500 > 0.80


class TestStudentTVaR:
    def test_var_matches_theoretical_quantile(self):
        """VaR-t on a t_5 sample must hit the standardized theoretical VaR ±2%."""
        rng = np.random.default_rng(21)
        nu, mu, sigma = 5.0, 0.0005, 0.02
        sample = mu + sigma * rng.standard_t(nu, size=200_000) / math.sqrt(nu / (nu - 2))
        out = ValueAtRisk.parametric(sample, confidence=0.99, distribution="t")
        q = float(t_dist.ppf(0.01, nu)) / math.sqrt(nu / (nu - 2))
        expected = -(mu + q * sigma) * 100
        assert out["var_percentage"] == pytest.approx(expected, rel=0.02)

    def test_collapses_to_normal_as_df_grows(self):
        rng = np.random.default_rng(22)
        sample = rng.normal(0.0002, 0.015, size=100_000)
        var_t = ValueAtRisk.parametric(sample, confidence=0.95, distribution="t")["var_percentage"]
        var_n = ValueAtRisk.parametric(sample, confidence=0.95, distribution="normal")["var_percentage"]
        assert var_t == pytest.approx(var_n, rel=0.05)


class TestBlackLittermanGuards:
    def _optimizer(self, seed=31, n=120, k=3):
        rng = np.random.default_rng(seed)
        rets = rng.normal(0.0004, 0.01, size=(n, k))
        return PortfolioOptimizer(rets, ["A", "B", "C"])

    def test_unknown_ticker_raises(self):
        opt = self._optimizer()
        with pytest.raises(ValueError, match="Unknown tickers"):
            opt.black_litterman({"ZZZ": 0.10})

    def test_rank_deficient_covariance_returns_finite_weights(self):
        rng = np.random.default_rng(32)
        base = rng.normal(size=120)
        rets = np.column_stack([base, base, rng.normal(size=120)])  # rank 2
        opt = PortfolioOptimizer(rets, ["A", "B", "C"])
        out = opt.black_litterman({"A": 0.08})
        weights = np.array(list(out["weights"].values()))
        assert np.all(np.isfinite(weights))
        assert abs(weights.sum() - 1.0) < 1e-3  # weights rounded to 4dp

    def test_default_delta_is_exogenous(self):
        opt = self._optimizer()
        out = opt.black_litterman({"A": 0.08})
        # pi = 2.5 * Sigma @ w_mkt with equal w_mkt
        w = np.ones(3) / 3
        pi = 2.5 * opt.cov_matrix @ w
        got = np.array([out["equilibrium_returns"][a] for a in ["A", "B", "C"]]) / 100
        np.testing.assert_allclose(got, pi, rtol=1e-3)

    def test_sample_delta_opt_in_and_clamped(self):
        rng = np.random.default_rng(33)
        rets = rng.normal(-0.01, 0.01, size=(120, 3))  # mean below rf
        opt = PortfolioOptimizer(rets, ["A", "B", "C"])
        out = opt.black_litterman({"A": 0.08}, risk_aversion=None, risk_free_rate=0.02)
        weights = np.array(list(out["weights"].values()))
        assert np.all(np.isfinite(weights))


class TestHestonNoArbitrage:
    def test_hostile_grid_respects_floors(self):
        import itertools

        for T, moneyness, xi in itertools.product(
            [0.02, 0.1], [0.5, 1.5], [0.3, 1.5]
        ):
            S0, K, r, q = 100.0, 100.0 * moneyness, 0.05, 0.02
            for otype in ("call", "put"):
                out = HestonModel.price_option_cf(
                    S0=S0, K=K, v0=0.04, r=r, kappa=2.0, theta=0.04,
                    xi=xi, rho=-0.7, T=T, option_type=otype, q=q,
                )
                floor = (
                    max(S0 * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
                    if otype == "call"
                    else max(K * math.exp(-r * T) - S0 * math.exp(-q * T), 0.0)
                )
                assert out["price"] >= floor - 1e-6, (T, moneyness, xi, otype, out)
                assert 0.0 <= out["p1"] <= 1.0
                assert 0.0 <= out["p2"] <= 1.0

    def test_clean_quote_has_no_violation_flag(self):
        out = HestonModel.price_option_cf(
            S0=100, K=100, v0=0.04, r=0.05, kappa=2.0, theta=0.04,
            xi=0.3, rho=-0.7, T=1.0, option_type="call",
        )
        assert out["arbitrage_violation"] is False


class TestWilderRSI:
    def test_monotone_up_is_overbought(self):
        prices = np.arange(1.0, 60.0)
        sig = BacktestEngine._rsi_strategy(prices, {"period": 14})
        assert (sig[15:] == -1).all()

    def test_monotone_down_is_oversold(self):
        prices = np.arange(60.0, 1.0, -1.0)
        sig = BacktestEngine._rsi_strategy(prices, {"period": 14})
        assert (sig[15:] == 1).all()

    def test_flat_is_neutral(self):
        prices = np.full(60, 100.0)
        sig = BacktestEngine._rsi_strategy(prices, {"period": 14})
        assert (sig == 0).all()

    def test_matches_manual_wilder_rma(self):
        rng = np.random.default_rng(41)
        prices = 100 + np.cumsum(rng.normal(0, 1, 80))
        period = 14
        sig = BacktestEngine._rsi_strategy(prices, {"period": period})
        # Independent Wilder computation
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        ag, al = gains[:period].mean(), losses[:period].mean()
        for i in range(period + 1, len(prices)):
            ag = (ag * (period - 1) + gains[i - 1]) / period
            al = (al * (period - 1) + losses[i - 1]) / period
            rsi = 100.0 if al == 0 and ag > 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
            expected = 1 if rsi < 30 else (-1 if rsi > 70 else 0)
            assert sig[i] == expected

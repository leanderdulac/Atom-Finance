"""Regression tests for quant-model fixes (no DB required).

Each test pins a corrected behaviour with a statistical or closed-form
acceptance criterion — not a snapshot of current output.
"""
import math

import numpy as np
import pytest
from scipy.stats import t as t_dist

from app.models.backtesting import BacktestEngine
from app.models.capm import CAPMAnalyzer
from app.models.cointegration import engle_granger
from app.models.portfolio import PortfolioOptimizer
from app.models.pricing import BinomialTree, FiniteDifference, MonteCarlo
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


class TestLocalRngHygiene:
    """Engines use local generators: same seed reproduces, global stream untouched."""

    ENGINES = {
        "gbm": lambda seed: CAPMAnalyzer.gbm_paths(100, 0.05, 0.2, 1.0, 50, 200, seed=seed)["paths"],
        "mc_var": lambda seed: ValueAtRisk.monte_carlo(
            np.random.default_rng(0).normal(0, 0.01, 500), n_simulations=2000, seed=seed
        )["var_percentage"],
        "heston": lambda seed: HestonModel.simulate(
            100, 0.04, 0.05, 2.0, 0.04, 0.3, -0.7, 0.5, n_paths=500, n_steps=50, seed=seed
        )["terminal_prices"]["mean"],
    }

    @pytest.mark.parametrize("name", ["gbm", "mc_var", "heston"])
    def test_reproduces_and_spares_global(self, name):
        run = self.ENGINES[name]
        first = run(11)
        np.random.seed(999)
        before = np.random.standard_normal(3).copy()
        np.random.seed(999)
        run(11)
        after = np.random.standard_normal(3)
        assert (before == after).all()
        second = run(11)
        assert np.asarray(first).tolist() == np.asarray(second).tolist()


class TestCorrelationGuard:
    def _assets(self):
        return [
            {"ticker": "A", "S0": 100, "mu": 0.05, "sigma": 0.2},
            {"ticker": "B", "S0": 50, "mu": 0.03, "sigma": 0.25},
        ]

    def test_valid_matrix_passes_through_unflagged(self):
        out = CAPMAnalyzer.gbm_multi_paths(
            self._assets(), 0.5, 20, 100, corr_matrix=[[1.0, 0.5], [0.5, 1.0]], seed=4
        )
        assert out["correlation_repaired"] is False

    def test_indefinite_matrix_repaired_not_crashed(self):
        # [1, .99; .99, 1] is PD; push past the edge with an impossible triple
        out = CAPMAnalyzer.gbm_multi_paths(
            self._assets() + [{"ticker": "C", "S0": 10, "mu": 0.01, "sigma": 0.3}],
            0.25, 10, 50,
            corr_matrix=[[1.0, 0.99, -0.99], [0.99, 1.0, 0.99], [-0.99, 0.99, 1.0]],
            seed=4,
        )
        assert out["correlation_repaired"] is True
        assert len(out["assets"]) == 3

    def test_malformed_matrix_raises(self):
        with pytest.raises(ValueError, match="2x2"):
            CAPMAnalyzer.gbm_multi_paths(self._assets(), 0.25, 10, 50, corr_matrix=[[1.0]])
        with pytest.raises(ValueError, match="\\[-1, 1\\]"):
            CAPMAnalyzer.gbm_multi_paths(
                self._assets(), 0.25, 10, 50, corr_matrix=[[1.0, 1.5], [1.5, 1.0]]
            )


class TestSharpeDegenerate:
    def test_constant_series_returns_zero_not_inf(self):
        from app.models.winners_curse import annualized_sharpe

        assert annualized_sharpe(np.full(100, 0.001)) == 0.0
        assert annualized_sharpe(np.zeros(100)) == 0.0


class TestPricingWhatBroke:
    def test_mc_flags_noisy_and_coarse_runs(self):
        noisy = MonteCarlo.price(100, 100, 1.0, 0.05, 0.2, "call", n_simulations=1000, seed=9)
        assert any("standard error" in w for w in noisy["what_broke"])
        assert noisy["what_broke"] != []
        fine = MonteCarlo.price(100, 100, 1.0, 0.05, 0.2, "call", n_simulations=200_000, seed=9)
        assert fine["what_broke"] == []
        coarse = MonteCarlo.price(100, 100, 1.0, 0.05, 0.2, "call", n_simulations=5000,
                                 n_steps=10, seed=9)
        assert any("Coarse time grid" in w for w in coarse["what_broke"])

    def test_crr_flags_coarse_tree_and_divless_american_call(self):
        coarse = BinomialTree.price(100, 100, 1.0, 0.05, 0.2, "call", n_steps=50)
        assert any("Coarse tree" in w for w in coarse["what_broke"])
        divless = BinomialTree.price(100, 100, 1.0, 0.05, 0.2, "call", american=True)
        assert any("never exercises early" in w for w in divless["what_broke"])

    def test_fd_flags_coarse_grid_and_boundary_spot(self):
        coarse = FiniteDifference.price(100, 100, 1.0, 0.05, 0.2, "call", N_S=50, N_t=50)
        assert any("Coarse grid" in w for w in coarse["what_broke"])
        edge = FiniteDifference.price(280, 100, 1.0, 0.05, 0.2, "call")
        assert any("upper boundary" in w for w in edge["what_broke"])

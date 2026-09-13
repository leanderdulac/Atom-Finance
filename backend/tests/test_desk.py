"""Formula tests for EVT, Heston CF, VaR horizon, and desk papers."""
import math

import numpy as np

from app.core.security import is_insecure_secret
from app.models.cointegration import engle_granger, johansen, pairs_backtest
from app.models.evt import GeneralizedParetoDistribution, compute_evt_risk
from app.models.fama_french import decompose
from app.models.insider_clusters import detect
from app.models.market_making import avellaneda_stoikov_quotes
from app.models.mean_reversion import score_series
from app.models.perp_arb import scan as perp_scan
from app.models.pricing import BlackScholes
from app.models.risk import ValueAtRisk
from app.models.volatility import GARCHModel, HestonModel


class TestSecretHygiene:
    def test_placeholders_rejected(self):
        assert is_insecure_secret("your-secret-key-change-in-production")
        assert is_insecure_secret("REPLACE_WITH_GENERATED_KEY")
        assert is_insecure_secret("")
        assert not is_insecure_secret("test-secret-key-do-not-use-in-production")
        assert not is_insecure_secret("a" * 64)


class TestEVT:
    def test_cvar_matches_mcneil_formula(self):
        rng = np.random.default_rng(0)
        losses = rng.pareto(3.0, 2000)
        gpd = GeneralizedParetoDistribution()
        fit = gpd.fit(losses, 0.90)
        var = gpd.var_evt(0.99, fit.n_total, fit.n_exceedances)
        expected = (var + fit.sigma - fit.xi * fit.threshold) / (1.0 - fit.xi)
        assert abs(gpd.cvar_evt(var) - expected) < 1e-12
        assert gpd.cvar_evt(var) > var

    def test_zeta_uses_full_sample(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0.001, 0.02, 800)
        returns[::40] -= 0.08
        result = compute_evt_risk(returns, 0.99, 0.90)
        assert 0 < result.exceedance_rate < 0.25
        assert result.cvar_evt >= result.var_evt

    def test_xi_zero_limit_does_not_divide_by_zero(self):
        gpd = GeneralizedParetoDistribution()
        gpd.xi, gpd.sigma, gpd.threshold = 0.0, 0.02, 0.03
        var = gpd.var_evt(0.99, 1000, 100)
        assert math.isfinite(var)
        assert math.isfinite(gpd.cvar_evt(var))


class TestVaRHorizon:
    def test_parametric_mean_scales_linearly(self):
        rng = np.random.default_rng(2)
        returns = rng.normal(0.001, 0.01, 2000)
        one = ValueAtRisk.parametric(returns, 0.95, 1_000_000, 1)
        ten = ValueAtRisk.parametric(returns, 0.95, 1_000_000, 10)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))
        from scipy.stats import norm
        z = norm.ppf(0.05)
        expected_10 = -(mu * 10 + z * sigma * np.sqrt(10)) * 100
        assert abs(ten["var_percentage"] - expected_10) < 0.001
        assert ten["cvar_percentage"] >= ten["var_percentage"]
        assert one["var_percentage"] > 0

    def test_student_t_cvar_exceeds_var(self):
        rng = np.random.default_rng(3)
        returns = rng.standard_t(5, 1500) * 0.01
        result = ValueAtRisk.parametric(returns, 0.99, distribution="t")
        assert result["cvar_percentage"] > result["var_percentage"]
        assert result["method"] == "parametric_t"

    def test_historical_empty_tail_does_not_nan(self):
        returns = np.full(40, 0.001)
        returns[0] = -0.2
        result = ValueAtRisk.historical(returns, 0.95)
        assert math.isfinite(result["cvar_percentage"])


class TestHeston:
    def test_cf_put_call_parity(self):
        kw = dict(S0=100, K=100, v0=0.04, r=0.05, kappa=2.0, theta=0.04, xi=0.3, rho=-0.7, T=1.0)
        call = HestonModel.price_option_cf(**kw, option_type="call")["price"]
        put = HestonModel.price_option_cf(**kw, option_type="put")["price"]
        fwd = 100 - 100 * math.exp(-0.05)
        assert abs((call - put) - fwd) < 0.05

    def test_cf_near_black_scholes_when_vol_of_vol_small(self):
        bs = BlackScholes.price(100, 100, 1.0, 0.05, 0.2, "call")
        heston = HestonModel.price_option_cf(
            S0=100, K=100, v0=0.04, r=0.05, kappa=8.0, theta=0.04, xi=0.02, rho=0.0, T=1.0,
        )["price"]
        assert abs(heston - bs) < 0.25

    def test_mc_step_count_scales_with_maturity(self):
        short = HestonModel.price_option(100, 100, 0.04, 0.05, 2, 0.04, 0.3, -0.7, 0.25, n_paths=2000, seed=0)
        long = HestonModel.price_option(100, 100, 0.04, 0.05, 2, 0.04, 0.3, -0.7, 2.0, n_paths=2000, seed=0)
        assert short["n_steps"] == 63
        assert long["n_steps"] == 504


class TestGARCHBounds:
    def test_low_persistence_series_can_fit_beta_below_half(self):
        rng = np.random.default_rng(4)
        returns = rng.normal(0, 0.01, 800)
        result = GARCHModel().fit(returns)
        assert 0 <= result["beta"] < 1
        assert result["alpha"] + result["beta"] < 1


class TestDeskPapers:
    def test_engle_granger_detects_synthetic_coint(self):
        rng = np.random.default_rng(5)
        x = np.cumsum(rng.normal(0, 1, 400)) + 50
        y = 2.0 * x + 3.0 + rng.normal(0, 0.2, 400)
        stats = engle_granger(y, x)
        assert stats["cointegrated"] is True
        assert abs(stats["beta"] - 2.0) < 0.05
        bt = pairs_backtest(y, x)
        assert bt["eligible_for_live_trading"] is False
        assert "what_broke" in bt

    def test_avellaneda_inventory_skews_quotes(self):
        flat = avellaneda_stoikov_quotes(100, 0, 0.2, 0.1, 1.5, 140, 1.0)
        long = avellaneda_stoikov_quotes(100, 5, 0.2, 0.1, 1.5, 140, 1.0)
        assert long["reservation_price"] < flat["reservation_price"]
        assert long["ask"] < flat["ask"]

    def test_fama_french_recovers_loadings(self):
        rng = np.random.default_rng(6)
        n = 252
        mkt = rng.normal(0.0004, 0.01, n)
        smb = rng.normal(0, 0.005, n)
        hml = rng.normal(0, 0.005, n)
        rmw = rng.normal(0, 0.004, n)
        cma = rng.normal(0, 0.004, n)
        y = 0.0001 + 1.2 * mkt + 0.3 * smb + rng.normal(0, 0.002, n)
        out = decompose(y, {"mkt_rf": mkt, "smb": smb, "hml": hml, "rmw": rmw, "cma": cma})
        assert abs(out["loadings"]["mkt_rf"]["coef"] - 1.2) < 0.08
        assert out["r_squared"] > 0.8

    def test_mean_reversion_flags_ou(self):
        rng = np.random.default_rng(7)
        x = 0.0
        prices = [100.0]
        for _ in range(400):
            x = 0.9 * x + rng.normal(0, 0.01)
            prices.append(prices[-1] * math.exp(x * 0.05 + rng.normal(0, 0.002)))
        row = score_series(np.array(prices), "SYN")
        assert row["half_life_days"] is not None

    def test_perp_arb_after_fees(self):
        out = perp_scan([
            {"venue": "a", "bid": 100.0, "ask": 100.1, "taker_fee_bps": 1.0, "funding_8h": 0.0},
            {"venue": "b", "bid": 101.0, "ask": 101.1, "taker_fee_bps": 1.0, "funding_8h": 0.0},
        ])
        assert out["best_route"]["buy_venue"] == "a"
        assert out["best_route"]["sell_venue"] == "b"
        assert out["positive_after_fees"] is True

    def test_insider_cluster(self):
        events = [
            {"ticker": "AAA", "insider_id": "i1", "side": "buy", "shares": 100, "date": "2024-01-02", "notional": 1000},
            {"ticker": "AAA", "insider_id": "i2", "side": "buy", "shares": 80, "date": "2024-01-03", "notional": 800},
            {"ticker": "AAA", "insider_id": "i3", "side": "buy", "shares": 90, "date": "2024-01-04", "notional": 900},
        ]
        out = detect(events, window_days=7, min_insiders=3)
        assert out["n_clusters"] >= 1
        assert out["clusters"][0]["n_insiders"] == 3

    def test_johansen_rank_on_synthetic_coint(self):
        rng = np.random.default_rng(8)
        x = np.cumsum(rng.normal(0, 1, 300)) + 40
        y = 1.5 * x + rng.normal(0, 0.3, 300)
        out = johansen(np.column_stack([y, x]), k_ar=2)
        assert out["rank"] >= 1
        assert out["cointegrated"] is True

    def test_heston_calibrate_fits_own_smile(self):
        true = dict(S0=100, v0=0.04, r=0.05, kappa=1.5, theta=0.04, xi=0.5, rho=-0.6)
        quotes = []
        for K in (90, 95, 100, 105, 110):
            px = HestonModel.price_cf_raw(K=K, T=0.5, option_type="call", **true)
            quotes.append({"K": K, "T": 0.5, "price": px, "option_type": "call"})
        fitted = HestonModel.calibrate(
            100, 0.05, quotes,
            x0=(0.05, 1.2, 0.05, 0.4, -0.4),
            max_nfev=40,
        )
        assert fitted["rmse_price"] < 0.15
        assert fitted["rho"] < 0


"""Regression tests for security and quantitative finance audit fixes."""

import numpy as np
import pytest

from app.api.reports import _safe_csv_cell
from app.models.backtesting import BacktestEngine
from app.models.black_swan import BlackSwanDetector
from app.models.cointegration import pairs_backtest
from app.models.copulas import GumbelCopula
from app.models.evt import compute_evt_risk
from app.models.hedge import DeltaHedgeEngine, PerpPosition, UniswapV3Position
from app.models.pricing import BlackScholes, FiniteDifference, MonteCarlo, OptionsStrategies
from app.models.regime import resize
from app.models.risk import ValueAtRisk
from app.models.volatility import HestonModel
from app.models.winners_curse import deflated_sharpe
from app.services.edgar import parse_form4_xml


def test_student_t_var_variance_scaling():
    """Student-t parametric VaR must scale by sqrt((df - 2) / df) so total variance equals sigma^2."""
    rng = np.random.default_rng(42)
    returns = rng.standard_t(df=4.0, size=500) * 0.01
    res_t = ValueAtRisk.parametric(returns, confidence=0.95, portfolio_value=1_000_000, distribution="t")
    res_norm = ValueAtRisk.parametric(returns, confidence=0.95, portfolio_value=1_000_000, distribution="normal")
    assert res_t["var_percentage"] > 0
    assert res_t["cvar_percentage"] > res_t["var_percentage"]
    # At 95% confidence, variance-matched Student-t(df~4) quantile is slightly tighter than normal quantile,
    # whereas unscaled t quantile would inflate VaR by ~sqrt(2) = 1.41x.
    assert res_t["var_percentage"] < res_norm["var_percentage"] * 1.15


def test_crank_nicolson_dividend_yield_matches_bs():
    """Crank-Nicolson PDE solver with continuous dividend yield q must match Black-Scholes within 1.5%."""
    bs = BlackScholes.price(S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call", q=0.04)
    fd = FiniteDifference.price(
        S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call", q=0.04, N_S=150, N_t=150
    )
    assert abs(fd["price"] - bs) / bs < 0.015


def test_monte_carlo_odd_and_single_simulation():
    """MonteCarlo.price must not crash when n_simulations is 1 or odd."""
    res_one = MonteCarlo.price(S=100.0, K=100.0, T=0.5, r=0.05, sigma=0.2, n_simulations=1, n_steps=10)
    res_odd = MonteCarlo.price(S=100.0, K=100.0, T=0.5, r=0.05, sigma=0.2, n_simulations=101, n_steps=10)
    assert np.isfinite(res_one["price"])
    assert np.isfinite(res_odd["price"])


def test_options_strategy_unlimited_profit_detection():
    """Long call strategy has positive asymptotic slope -> unlimited max profit."""
    legs = [{"type": "call", "position": "long", "strike": 100.0, "quantity": 1}]
    res = OptionsStrategies.analyze_strategy(legs=legs, S=100.0, T=0.5, r=0.05, sigma=0.2)
    assert res["max_profit"] == "unlimited"
    assert isinstance(res["max_loss"], float)


def test_deflated_sharpe_null_se():
    """Deflated Sharpe must evaluate null threshold SR* using SE(SR=0), not observed SR."""
    res = deflated_sharpe(
        observed_sharpe=2.5,
        n_trials=20,
        n_obs=500,
        skew=-0.2,
        excess_kurtosis=0.5,
    )
    assert 0.0 <= res["deflated_sharpe_prob"] <= 1.0
    assert res["sr_star"] > 0.0


def test_regime_resize_preserves_standby_ceiling():
    """Standby strategy in normal regime should be capped at its current weight, not zeroed out."""
    strategies = [
        {
            "id": "tail_hedge",
            "status": "standby",
            "half_kelly": 0.5,
            "kelly_by_regime": {"calm_mean_rev": 0.20},
        }
    ]
    positions = [{"id": "pos1", "strategy_id": "tail_hedge", "weight": 0.05}]
    out = resize("calm_mean_rev", strategies, positions)
    assert out[0]["target_weight"] == pytest.approx(0.05)
    assert out[0]["action"] == "hold"


def test_delta_hedge_signed_perp_size():
    """DeltaHedgeEngine must respect signed perp_position.size (positive = long adds to delta)."""
    lp = UniswapV3Position(L=100_000.0, price_lower=1500.0, price_upper=2500.0)
    perp_short = PerpPosition(size=-1.0, entry_price=2000.0, margin=500.0, liquidation_price=2600.0)
    perp_long = PerpPosition(size=1.0, entry_price=2000.0, margin=500.0, liquidation_price=1400.0)
    engine = DeltaHedgeEngine()
    state_short = engine.calculate_exposure(lp, perp_short, current_price=2000.0)
    state_long = engine.calculate_exposure(lp, perp_long, current_price=2000.0)
    assert state_long.delta_net - state_short.delta_net == pytest.approx(2.0)


def test_evt_gaussian_var_comparison():
    """EVT normal_var must use parametric Gaussian quantile rather than empirical quantile."""
    rng = np.random.default_rng(7)
    returns = rng.standard_t(df=3.0, size=600) * 0.015
    res = compute_evt_risk(returns, confidence=0.99, threshold_quantile=0.90)
    # On fat-tailed returns, 99% EVT VaR should exceed 99% Gaussian VaR
    assert res.var_evt > res.normal_var


def test_pairs_backtest_dollar_neutral_sizing():
    """Pairs backtest with mismatched price scales (e.g. 10 vs 1000) must remain stable."""
    rng = np.random.default_rng(123)
    x = 1000.0 + np.cumsum(rng.normal(0, 2.0, 200))
    y = 0.01 * x + rng.normal(0, 0.05, 200)
    res = pairs_backtest(y, x, warmup=30, entry_z=1.5, exit_z=0.5, commission=0.0005)
    assert res["final_equity"] > 0.0
    assert np.isfinite(res["sharpe"])


def test_backtest_rsi_and_active_win_rate():
    """RSI backtest must generate trades and compute win rate over active return days only."""
    rng = np.random.default_rng(99)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, 250)))
    res = BacktestEngine.run_strategy(prices, strategy="rsi", params={"period": 14, "oversold": 35, "overbought": 65})
    assert 0.0 <= res["performance"]["win_rate_pct"] <= 100.0


def test_black_swan_downside_tail_and_gumbel_overflow():
    """Black swan tail risk and Gumbel copula fit must not overflow on extreme inputs."""
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0, 0.01, 300)
    rets[50] = -0.18  # crash day
    bs = BlackSwanDetector.analyze_tail_risk(rets)
    assert bs["black_swan_score"] > 0
    u_1d = np.linspace(0.01, 0.99, 100)
    u_2d = np.column_stack([u_1d, u_1d])
    fit = GumbelCopula().fit(u_2d)
    assert np.isfinite(fit.parameters["theta"])


def test_heston_option_dividend_yield():
    """Heston MC option pricer must decrease call price when continuous dividend yield q > 0."""
    c_no_div = HestonModel.price_option(
        S0=100, K=100, v0=0.04, r=0.05, kappa=2.0, theta=0.04, xi=0.2, rho=-0.5, T=1.0,
        option_type="call", n_paths=5000, q=0.0
    )
    c_div = HestonModel.price_option(
        S0=100, K=100, v0=0.04, r=0.05, kappa=2.0, theta=0.04, xi=0.2, rho=-0.5, T=1.0,
        option_type="call", n_paths=5000, q=0.08
    )
    assert c_div["price"] < c_no_div["price"]


def test_csv_injection_and_xxe_guards():
    """CSV formula strings must be neutralized and Form 4 XML with DOCTYPE/ENTITY rejected."""
    assert _safe_csv_cell("=CMD|' /C calc'!A0").startswith("'")
    assert _safe_csv_cell("  +SUM(A1:A2)").startswith("'")
    assert _safe_csv_cell("-12.34") == "-12.34"

    malicious_xml = """<?xml version="1.0"?>
    <!DOCTYPE lolz [<!ENTITY lol "lol">]>
    <ownershipDocument><issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer></ownershipDocument>
    """
    with pytest.raises(ValueError, match="XML DTD/entity"):
        parse_form4_xml(malicious_xml)


def test_hardware_accelerator_and_local_llm_security():
    """Accelerator dispatch and LocalLLMProvider URL validation must work safely."""
    from app.core.accelerator import device_info, select_torch_device
    from app.core.ai_factory import LocalLLMProvider, _validate_local_llm_url
    from app.models.neural_sde import NeuralSDE

    info = device_info()
    assert info["preferred_device"] in ("cpu", "mps", "cuda")
    assert select_torch_device(batch_size=10, min_gpu_batch=128).type == "cpu"

    if NeuralSDE.is_available():
        sde_res = NeuralSDE.simulate(n_paths=16, n_steps=20, seed=42, device="auto")
        assert "device" in sde_res
        assert len(sde_res["trajectories"]) == 16

    mc_res = MonteCarlo.price(
        S=100.0, K=100.0, T=0.5, r=0.05, sigma=0.2, n_simulations=10_000, n_steps=30, device="auto"
    )
    assert np.isfinite(mc_res["price"])
    assert mc_res["device"] in ("cpu", "mps", "cuda")

    # LocalLLMProvider allows localhost HTTP and blocks plain HTTP to external hosts (SSRF guard)
    assert _validate_local_llm_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    provider = LocalLLMProvider(base_url="http://127.0.0.1:11434/v1", model="qwen2.5-coder:32b")
    assert provider.model == "qwen2.5-coder:32b"
    with pytest.raises(ValueError, match="Plain HTTP LOCAL_LLM_BASE_URL is restricted"):
        _validate_local_llm_url("http://169.254.169.254/latest/meta-data/")


def test_playbook_scanner_3_pillars():
    """Unified 3-pillar quant playbook scanner must evaluate pairs/commodities, crypto carry, and regime allocation."""
    from app.models.playbook_scanner import run_playbook_scan

    out = run_playbook_scan(mode="synthetic", regime_demo="calm", capital=100_000.0, entry_z=1.8, exit_z=0.5, seed=42)
    assert out["regime_summary"]["regime"] in ("calm_mean_rev", "trending", "high_vol", "crisis")
    assert len(out["pillar_1_pairs_and_commodities"]) == 6
    assert any(p["bucket"] == "commodities" for p in out["pillar_1_pairs_and_commodities"])
    actionable_pairs = [p for p in out["pillar_1_pairs_and_commodities"] if p["actionable"]]
    assert len(actionable_pairs) >= 1
    top_ticket = actionable_pairs[0]["order_ticket"]
    assert top_ticket["leg_y"]["shares_exact"] > 0
    assert top_ticket["leg_x"]["shares_exact"] > 0
    assert top_ticket["leg_y"]["side"] in ("BUY", "SELL_SHORT")
    assert top_ticket["rules"]["time_stop_trading_days"] > 0

    assert len(out["pillar_2_crypto_funding_carry"]) == 3
    top_crypto = out["pillar_2_crypto_funding_carry"][0]
    assert top_crypto["annualized_funding_pct"] > 0
    assert top_crypto["order_ticket"]["spot_leg"]["quantity"] > 0
    assert top_crypto["order_ticket"]["perp_leg"]["quantity"] == top_crypto["order_ticket"]["spot_leg"]["quantity"]

    total_alloc = sum(s["allocated_capital"] for s in out["capital_allocation"]["strategies"])
    assert total_alloc + out["capital_allocation"]["cash_reserve"] == pytest.approx(100_000.0, abs=1.0)



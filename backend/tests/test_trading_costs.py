"""Cost model: fee, half-spread, size slippage, entry gate, limits, liquidity.

Deterministic. No network. Paper only — nothing here places an order.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.models.backtesting import BacktestEngine
from app.models.forward_test import sequential_pnl
from app.models.pairs_meta import evaluate_pairs_meta, round_trip_cost
from app.models.simulation import simulate_levels
from app.models.stat_arb_paper import PipelineConfig, evaluate, run_paper_pipeline, synthetic_perp_pair
from app.models.trading_costs import (
    BookTop,
    check_liquidity,
    classify_limit,
    costs_included_flag,
    entry_allowed,
    four_leg_fraction,
    limit_cross_index,
    pairs_entry_allowed,
    quote_fill,
    venue_fees,
)


def test_round_trip_matches_the_old_pairs_fractions():
    assert round_trip_cost(0.0005, 0.0002) == pytest.approx(0.0014)
    assert round_trip_cost(0.0010, 0.0002) == pytest.approx(0.0024)
    assert four_leg_fraction(5.0, 2.0, 0.0) == pytest.approx(0.0014)


def test_venue_fees_maker_below_taker_except_where_the_schedule_says_so():
    usdm = venue_fees("binance_usdm")
    assert usdm.taker_bps == 4.0 and usdm.maker_bps == 2.0
    assert venue_fees("okx").taker_bps == 5.0
    assert venue_fees("hyperliquid").taker_bps == 3.5
    assert venue_fees("b3").maker_bps == venue_fees("b3").taker_bps == 5.0
    assert venue_fees("crypto_spot").taker_bps == 10.0


def test_half_spread_comes_from_the_book_and_an_estimate_is_flagged():
    book = BookTop(bid=99.0, ask=101.0, mid=100.0, estimated=False)
    buy = quote_fill(side="buy", qty=2.0, mid=100.0, book=book, fee_bps=0.0, venue="binance_usdm")
    assert buy.fill_px == pytest.approx(101.0)
    assert buy.half_spread == pytest.approx(2.0)  # 2 shares × (101 − 100)
    assert buy.slippage == 0.0
    assert buy.spread_source == "book"
    # No displayed size: the walk is the zero fallback, so the fill is flagged.
    assert buy.slippage_source == "estimate"
    assert buy.flagged_estimate is True
    assert buy.fee + buy.half_spread + buy.slippage - buy.spread_capture == pytest.approx(buy.total)
    sized = quote_fill(
        side="buy", qty=2.0, mid=100.0,
        book=BookTop(bid=99.0, ask=101.0, mid=100.0, ask_size=10.0, bid_size=10.0),
        fee_bps=0.0, impact_bps=10.0,
    )
    assert sized.spread_source == "book" and sized.slippage_source == "depth"
    assert sized.flagged_estimate is False

    synthetic = BookTop(bid=99.8, ask=100.2, mid=100.0, estimated=True)
    flagged = quote_fill(side="buy", qty=1.0, mid=100.0, book=synthetic, fee_bps=0.0)
    assert flagged.spread_source == "estimate"
    assert flagged.flagged_estimate is True

    missing = quote_fill(
        side="buy", qty=1.0, mid=100.0, book=BookTop(), fee_bps=0.0, fallback_half_spread_bps=2.0,
    )
    assert missing.half_spread == pytest.approx(0.02)
    assert missing.spread_source == "estimate"
    assert missing.flagged_estimate is True


def test_slippage_grows_with_size_versus_depth():
    thin = BookTop(bid=100.0, ask=100.0, mid=100.0, ask_size=1.0, bid_size=1.0)
    small = quote_fill(side="buy", qty=1.0, mid=100.0, book=thin, fee_bps=0.0, impact_bps=10.0)
    large = quote_fill(side="buy", qty=4.0, mid=100.0, book=thin, fee_bps=0.0, impact_bps=10.0)
    assert small.slippage_bps == pytest.approx(10.0)
    assert large.slippage_bps == pytest.approx(40.0)
    assert large.slippage > small.slippage
    assert small.slippage_source == "depth"

    no_depth = quote_fill(
        side="buy", qty=3.0, mid=100.0, book=BookTop(bid=99.0, ask=101.0, mid=100.0),
        fee_bps=4.0, fallback_slippage_bps=0.0,
    )
    assert no_depth.slippage == 0.0
    assert no_depth.slippage_source == "estimate"
    assert no_depth.fill_px == pytest.approx(101.0)
    assert no_depth.fee == pytest.approx(3.0 * 101.0 * 4.0 / 10_000.0)


def test_maker_pays_the_maker_fee_and_captures_the_spread():
    book = BookTop(bid=99.0, ask=101.0, mid=100.0, estimated=False)
    maker = quote_fill(
        side="buy", qty=1.0, mid=100.0, book=book, liquidity="maker", limit_px=99.0, venue="binance_usdm",
    )
    taker = quote_fill(side="buy", qty=1.0, mid=100.0, book=book, liquidity="taker", venue="binance_usdm")
    assert maker.fee_bps == 2.0
    assert taker.fee_bps == 4.0
    assert maker.half_spread == 0.0 and maker.slippage == 0.0
    assert maker.spread_capture == pytest.approx(1.0)
    assert maker.total < taker.total


def test_entry_gate_and_four_leg_hurdle():
    # One-leg rate 10 bps → four-leg fraction 20 bps. k=1 hurdle is 0.002.
    assert four_leg_fraction(10.0, 0.0, 0.0) == pytest.approx(0.002)
    assert pairs_entry_allowed(0.0015, 10.0, 0.0, 0.0, k=1.0) is False
    # k=2 hurdle is 0.004. A gain that covers the four legs once still fails.
    assert pairs_entry_allowed(0.003, 10.0, 0.0, 0.0, k=2.0) is False
    assert pairs_entry_allowed(0.004, 10.0, 0.0, 0.0, k=2.0) is True
    assert entry_allowed(0.01, 0.0, k=2.0) is True
    assert entry_allowed(float("nan"), 0.01, k=2.0) is False
    assert entry_allowed(0.0, 0.01, k=0.0) is True
    assert costs_included_flag(round_trip_cost=0.0, model_applied=True) is False
    assert costs_included_flag(round_trip_cost=0.0014, model_applied=False) is False
    assert costs_included_flag(round_trip_cost=0.0014, model_applied=True) is True


def test_limit_cross_timeout_and_fill_rate():
    # Starts on the level: not a fill. The next bar leaves and the one after comes back.
    prices = [100.0, 101.0, 99.0]
    assert limit_cross_index(prices, origin=100.0, level=100.0, timeout=2) == 2
    assert classify_limit([100.0, 101.0, 102.0], 100.0, 100.0, timeout=1) == "expired"
    assert classify_limit([100.0, 101.0, 102.0], 100.0, 100.0, timeout=5) == "unfilled"
    assert classify_limit([101.0, 99.0], 102.0, 100.0, timeout=1) == "filled"

    blocked = simulate_levels(
        S0=100.0, direction="long", entry=100.0, stop=95.0, target=101.0,
        horizon_days=10, vol_annual=0.2, n_paths=200, seed=1, size=1.0,
        cost_total=3.0, entry_cost_k=2.0,
    )
    # Expected gain is 1; hurdle is 2 × 3. Nothing enters.
    assert blocked["n_entered"] == 0
    assert blocked["entry_blocked"] is True
    assert blocked["costs"]["flagged_estimate"] is True

    limited = simulate_levels(
        S0=100.0, direction="long", entry=100.0, stop=90.0, target=130.0,
        horizon_days=8, vol_annual=0.4, n_paths=300, seed=4, order_style="limit",
        limit_timeout=1, entry_cost_k=0.0,
    )
    assert limited["order_style"] == "limit"
    assert limited["n_filled"] + limited["n_expired"] + limited["n_unfilled"] == limited["n_orders"]
    assert limited["n_expired"] > 0
    assert 0.0 <= limited["fill_rate"] < 1.0
    # Resting on the level is not an immediate fill, unlike the market clock.
    assert limited["p_enter"] < 1.0


def test_liquidity_skip_reasons():
    wide = check_liquidity(spread_bps_value=40.0, volume=1e6, max_spread_bps=25.0, min_volume=0.0)
    assert wide.ok is False and wide.reason == "spread"
    thin = check_liquidity(spread_bps_value=4.0, volume=10.0, max_spread_bps=25.0, min_volume=100.0)
    assert thin.reason == "volume"
    missing = check_liquidity(spread_bps_value=4.0, volume=None, max_spread_bps=25.0, min_volume=1.0)
    assert missing.reason == "volume_unavailable"
    fine = check_liquidity(spread_bps_value=4.0, volume=None, max_spread_bps=25.0, min_volume=0.0)
    assert fine.ok is True


def test_forward_net_is_the_sum_of_the_three_components():
    prices = 100 * np.exp(np.cumsum(np.array([0.0, 0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.0, 0.01, -0.004])))
    pos = np.array([0, 1, 1, 1, 0, -1, -1, 0, 1, 1], dtype=float)
    out = sequential_pnl(prices, pos, commission=0.001, slippage=0.0005)
    np.testing.assert_allclose(out["fee"] + out["half_spread"] + out["slippage"], (0.001 + 0.0005) * np.abs(np.diff(np.concatenate([[0.0], out["signal"]]))))
    assert out["flagged_estimate"] is True
    assert out["half_spread_total"] > 0


def test_backtest_market_path_keeps_the_trade_day_and_splits_costs():
    prices = np.concatenate([np.full(50, 100.0), np.full(20, 120.0)])
    result = BacktestEngine.run_strategy(prices, "sma_crossover", params={"short_window": 5, "long_window": 20})
    assert result["trades"][0]["day"] == 51
    perf = result["performance"]
    assert perf["fee"] + perf["half_spread"] + perf["slippage"] == pytest.approx(perf["transaction_costs"], abs=0.02)
    assert result["execution"]["flagged_estimate"] is True

    tight = BacktestEngine.run_strategy(
        prices, "sma_crossover", params={"short_window": 5, "long_window": 20}, entry_cost_k=50.0,
    )
    assert tight["execution"]["skipped_by_reason"]["expected_gain"] > 0
    assert all(t["type"] != "BUY" for t in tight["trades"])


def test_pairs_labels_are_net_and_a_tight_spread_filter_removes_signals():
    rng = np.random.default_rng(11)
    x = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800)))
    y = 2.0 * x + rng.normal(0, 0.4, 800)
    out = evaluate_pairs_meta(y, x, min_events=0, min_oos_scored=0, apply_gate=True)
    assert out["cost_model"]["flagged_estimate"] is True
    assert out["cost_model"]["four_leg_fraction"] == pytest.approx(0.0014)
    assert out["signals"]["gross_total"] >= out["signals"]["net_total"]
    if out["gate"] is not None:
        assert out["gate"]["costs_included"] is True

    blocked = evaluate_pairs_meta(
        y, x, min_events=0, min_oos_scored=0, apply_gate=False, max_spread_bps=0.1,
    )
    assert blocked["signals"]["n_skipped"] > 0
    assert blocked["signals"]["skipped_by_reason"]["spread"] == blocked["signals"]["n_skipped"]
    assert blocked["signals"]["labeled"] == 0


def test_paper_spread_filter_and_maker_limits(monkeypatch):
    bars = synthetic_perp_pair(360, seed=2, half_life=8.0, resid_vol=3.5)
    wide = run_paper_pipeline(bars, PipelineConfig(warmup=80, z_window=30, max_spread_bps=0.1))
    if wide["accepted"]:
        assert wide["execution"]["n_skipped"] > 0
        assert wide["execution"]["skipped_by_reason"]["spread"] == wide["execution"]["n_skipped"]
        assert wide["decision"]["n_enters"] == 0

    maker = run_paper_pipeline(
        bars, PipelineConfig(warmup=80, z_window=30, execution="maker", entry_cost_k=0.0, limit_timeout_bars=2),
    )
    if maker["accepted"]:
        ex = maker["execution"]
        assert ex["order_style"] == "maker"
        assert ex["n_orders"] >= 1
        assert ex["n_expired"] + ex["n_filled"] == ex["n_orders"] or ex["fill_rate"] is not None
        assert 0.0 <= (ex["fill_rate"] or 0.0) <= 1.0

    huge_k = run_paper_pipeline(bars, PipelineConfig(warmup=80, z_window=30, entry_cost_k=1e6))
    if huge_k["accepted"]:
        assert huge_k["execution"]["skipped_by_reason"]["expected_gain"] > 0
        assert huge_k["decision"]["n_enters"] == 0


def test_paper_demo_still_refuses_live_trading():
    out = evaluate(demo=True, n=120, seed=2, warmup=60, z_window=20)
    assert out["eligible_for_live_trading"] is False
    assert out.get("broker_orders_sent", 0) == 0 or out["risk"]["kill_switch"]["broker_orders_sent"] == 0

"""Regime classifier: percentiles, crisis rule, mapping, resize, context files."""
from pathlib import Path

import numpy as np

from app.models.regime import (
    classify,
    demo_payload,
    evaluate,
    kill_switch,
    map_strategies,
    percentile_snapshot,
    resize,
)
from app.services.regime_context import write_context


class TestPercentileGate:
    def test_top_decile_flags_high(self):
        x = np.concatenate([np.full(85, 1.0), np.linspace(1.0, 10.0, 5)])
        snap = percentile_snapshot(x, window=90)
        assert snap["flag"] == "high"
        assert snap["percentile"] >= 90

    def test_bottom_decile_flags_low(self):
        x = np.concatenate([np.full(85, 10.0), np.linspace(10.0, 1.0, 5)])
        snap = percentile_snapshot(x, window=90)
        assert snap["flag"] == "low"


class TestClassifierRules:
    def test_credit_and_corr_is_crisis(self):
        flags = {
            "credit_spread": "high",
            "cross_asset_corr": "high",
            "vix_term_structure": None,
            "rates_curve_slope": None,
            "rv_iv_spread": None,
            "hurst": "low",
        }
        assert classify(flags) == "crisis"

    def test_vol_selling_dies_in_crisis(self):
        mapped = map_strategies("crisis")
        vol = next(s for s in mapped if s["id"] == "vol_selling")
        stat = next(s for s in mapped if s["id"] == "stat_arb")
        mom = next(s for s in mapped if s["id"] == "momentum")
        assert vol["status"] == "flatten"
        assert stat["status"] == "flatten"
        assert mom["status"] == "flatten"

    def test_stat_arb_live_only_in_mean_reversion(self):
        assert next(s for s in map_strategies("mean_reverting") if s["id"] == "stat_arb")["status"] == "live"
        assert next(s for s in map_strategies("trending") if s["id"] == "stat_arb")["status"] == "standby"

    def test_momentum_live_in_trending(self):
        assert next(s for s in map_strategies("trending") if s["id"] == "momentum")["status"] == "live"

    def test_high_vol_from_rv_iv(self):
        flags = {k: None for k in (
            "credit_spread", "cross_asset_corr", "vix_term_structure",
            "rates_curve_slope", "rv_iv_spread", "hurst",
        )}
        flags["rv_iv_spread"] = "high"
        assert classify(flags) == "high_vol"

    def test_kill_switch_never_sends_orders(self):
        ks = kill_switch("crisis")
        assert ks["armed"] is True
        assert ks["broker_orders_sent"] == 0
        assert ks["eligible_for_live_trading"] is False
        assert kill_switch("trending")["armed"] is False


class TestResize:
    def test_crisis_flattens_open_weights(self):
        mapped = map_strategies("crisis")
        adj = resize("crisis", mapped, [
            {"id": "p1", "strategy_id": "vol_selling", "weight": 0.12},
            {"id": "p2", "strategy_id": "momentum", "weight": 0.20},
        ])
        assert all(a["target_weight"] == 0 and a["action"] == "flatten" for a in adj)

    def test_favored_regime_scales_up_from_tiny_weight(self):
        mapped = map_strategies("mean_reverting")
        adj = resize("mean_reverting", mapped, [
            {"id": "p1", "strategy_id": "stat_arb", "weight": 0.01},
        ])
        row = adj[0]
        assert row["action"] == "scale_up"
        assert row["target_weight"] > row["current_weight"]


class TestDemoBooks:
    def test_crisis_demo_arms_kill_switch(self):
        out = evaluate(**demo_payload("crisis"), as_of="2026-09-13T00:00:00+00:00")
        assert out["regime"] == "crisis"
        assert out["kill_switch"]["armed"] is True
        assert out["eligible_for_live_trading"] is False
        vol = next(s for s in out["strategies"] if s["id"] == "vol_selling")
        assert vol["status"] == "flatten"

    def test_calm_demo_is_not_crisis(self):
        out = evaluate(**demo_payload("calm"))
        assert out["regime"] != "crisis"
        assert out["kill_switch"]["armed"] is False
        assert next(s for s in out["strategies"] if s["id"] == "stat_arb")["status"] in {"live", "standby"}

    def test_context_files_land_on_disk(self, tmp_path: Path):
        out = evaluate(**demo_payload("crisis"), as_of="2026-09-13T12:00:00+00:00")
        files = write_context(tmp_path, out)
        current = (tmp_path / "current-regime.md").read_text()
        assert "**crisis**" in current
        assert "Broker orders sent: `0`" in current
        assert "flatten" in files["position-adjustments.md"]
        assert "crisis" in (tmp_path / "regime-history.md").read_text()

"""ETH/SOL paper stat-arb: gates, fills, costs, and an authoritative kill switch."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.models.stat_arb_paper import (
    ENTRY_Z,
    EXIT_Z,
    PairBar,
    PipelineConfig,
    apply_spread_target,
    bars_from_arrays,
    decide_target,
    evaluate,
    fill_leg,
    reconcile_book,
    rolling_zscore,
    run_paper_pipeline,
    signal_gate,
    spread_half_life,
    synthetic_perp_pair,
)
from app.services.perp_klines import fetch_eth_sol_pair, fetch_mark_klines


def _coint_bars(n=400, seed=7, half_life=10.0, **kw) -> list[PairBar]:
    return synthetic_perp_pair(n, seed=seed, half_life=half_life, **kw)


class TestHalfLife:
    def test_ou_half_life_matches_phi(self):
        rng = np.random.default_rng(0)
        phi = 0.5
        e = np.zeros(800)
        for t in range(1, 800):
            e[t] = phi * e[t - 1] + rng.normal(0.0, 0.02)
        expected = -math.log(2.0) / math.log(phi)
        assert spread_half_life(e) == pytest.approx(expected, rel=0.15)

    def test_unit_root_is_infinite(self):
        e = np.cumsum(np.random.default_rng(1).normal(0, 1, 200))
        assert not math.isfinite(spread_half_life(e))


class TestZScoreAndDecision:
    def test_rolling_z_is_causal(self):
        x = np.arange(20, dtype=float)
        z = rolling_zscore(x, 5)
        w = x[10:15]
        assert z[14] == pytest.approx((x[14] - w.mean()) / w.std(ddof=1))
        # Changing the future must not move z at t.
        x2 = x.copy()
        x2[-1] = 1e6
        assert rolling_zscore(x2, 5)[14] == pytest.approx(z[14])

    def test_entry_exit_rules(self):
        assert decide_target(2.1, 0, ENTRY_Z, EXIT_Z) == -1
        assert decide_target(-2.1, 0, ENTRY_Z, EXIT_Z) == 1
        assert decide_target(2.0, 0, ENTRY_Z, EXIT_Z) == 0
        assert decide_target(-2.0, 0, ENTRY_Z, EXIT_Z) == 0
        assert decide_target(0.4, 1, ENTRY_Z, EXIT_Z) == 0
        assert decide_target(-0.4, -1, ENTRY_Z, EXIT_Z) == 0
        assert decide_target(0.5, 1, ENTRY_Z, EXIT_Z) == 1
        assert decide_target(1.2, -1, ENTRY_Z, EXIT_Z) == -1
        assert decide_target(0.0, 0, ENTRY_Z, EXIT_Z) == 0
        assert decide_target(float("nan"), 1, ENTRY_Z, EXIT_Z) == 1

    def test_long_spread_is_long_y_short_x(self):
        book = type("B", (), {})()  # filled below via PaperBook
        from app.models.stat_arb_paper import PaperBook

        book = PaperBook(cash=10_000.0, shadow_cash=10_000.0)
        bar = PairBar(1, 100.0, 10.0, 99.9, 100.1, 9.99, 10.01)
        fill = apply_spread_target(book, 1, beta=2.0, unit_qty=1.0, bar=bar, fee_bps=0.0, action="enter_long_spread")
        assert fill["y_side"] == "buy"
        assert fill["x_side"] == "sell"
        assert book.y_qty == pytest.approx(1.0)
        assert book.x_qty == pytest.approx(-2.0)
        assert book.position == 1
        assert reconcile_book(book, 1.0)["ok"] is True


class TestFillsAndCosts:
    def test_buy_at_ask_sell_at_bid(self):
        cash, fee, px = fill_leg(2.0, bid=99.0, ask=101.0, fee_bps=0.0)
        assert px == 101.0 and cash == pytest.approx(-202.0) and fee == 0.0
        cash, fee, px = fill_leg(-2.0, bid=99.0, ask=101.0, fee_bps=0.0)
        assert px == 99.0 and cash == pytest.approx(198.0)

    def test_fee_is_charged_on_notional(self):
        cash, fee, px = fill_leg(1.0, bid=99.0, ask=100.0, fee_bps=4.0)
        assert px == 100.0
        assert fee == pytest.approx(0.04)
        assert cash == pytest.approx(-100.04)

    def test_cost_aware_pnl_identity(self):
        bars = _coint_bars(n=360, seed=11, half_life=8.0, resid_vol=3.5)
        out = run_paper_pipeline(
            bars,
            PipelineConfig(entry_z=1.5, exit_z=0.4, taker_fee_bps=4.0, half_spread_bps=2.0, warmup=60),
            source="synthetic",
        )
        assert out["eligible_for_live_trading"] is False
        assert out["accepted"] is True
        net = out["monitoring"]["pnl_net"]
        gross = out["monitoring"]["pnl_gross"]
        costs = out["execution"]["costs_paid"]
        assert costs > 0
        assert net == pytest.approx(gross - costs, abs=1e-3)
        assert net <= gross + 1e-9
        assert out["execution"]["reconciled"] is True
        assert out["execution"]["inventory"]["position"] == 0
        assert out["broker_orders_sent"] == 0


class TestKillSwitch:
    def test_flattens_before_further_paper_fills(self):
        bars = _coint_bars(n=360, seed=3, half_life=8.0, resid_vol=4.0)
        out = run_paper_pipeline(
            bars,
            PipelineConfig(entry_z=1.25, exit_z=0.3, max_drawdown=0.0005, warmup=60, taker_fee_bps=8.0),
            source="synthetic",
        )
        assert out["eligible_for_live_trading"] is False
        assert out["risk"]["kill_switch"]["armed"] is True
        assert out["risk"]["kill_switch"]["reason"] == "max_drawdown"
        assert out["risk"]["kill_switch"]["broker_orders_sent"] == 0
        assert out["monitoring"]["kill_switch_reason"] == "max_drawdown"
        fills = out["execution"]["fills"]
        kill_idx = next(i for i, f in enumerate(fills) if f["action"] == "kill_flatten")
        after = fills[kill_idx + 1 :]
        assert all(f["action"] == "kill_flatten" for f in after) or after == []
        assert not any(str(f["action"]).startswith("enter_") for f in after)
        assert out["execution"]["inventory"]["position"] == 0
        assert out["execution"]["inventory"]["y"] == pytest.approx(0.0, abs=1e-9)
        assert out["execution"]["inventory"]["x"] == pytest.approx(0.0, abs=1e-9)
        assert out["execution"]["reconciled"] is True


class TestRejection:
    def test_gate_rejects_failed_coint_and_slow_ou(self):
        assert signal_gate(
            cointegrated=False, pvalue=1.0, significance=0.05,
            half_life_bars=8.0, max_half_life_bars=48.0,
        )["reason"] == "cointegration_failed"
        assert signal_gate(
            cointegrated=True, pvalue=0.01, significance=0.05,
            half_life_bars=80.0, max_half_life_bars=48.0,
        )["reason"] == "half_life_too_slow"
        assert signal_gate(
            cointegrated=True, pvalue=0.01, significance=0.05,
            half_life_bars=float("inf"), max_half_life_bars=48.0,
        )["reason"] == "half_life_too_slow"
        assert signal_gate(
            cointegrated=True, pvalue=0.01, significance=0.05,
            half_life_bars=12.0, max_half_life_bars=48.0,
        )["ok"] is True

    def test_independent_walks_are_rejected(self):
        bars = synthetic_perp_pair(n=360, seed=21, independent=True)
        out = run_paper_pipeline(bars, PipelineConfig(warmup=60), source="synthetic")
        assert out["accepted"] is False
        assert out["rejection"]["reason"] == "cointegration_failed"
        assert out["execution"]["fills"] == []
        assert out["eligible_for_live_trading"] is False

    def test_slow_half_life_is_rejected(self):
        bars = _coint_bars(n=500, seed=5, half_life=10.0, resid_vol=0.4)
        accepted = run_paper_pipeline(bars, PipelineConfig(warmup=60), source="synthetic")
        assert accepted["accepted"] is True
        hl = accepted["signal"]["half_life_bars"]
        assert hl is not None and hl > 0
        out = run_paper_pipeline(
            bars, PipelineConfig(max_half_life_bars=max(hl * 0.25, 0.05), warmup=60), source="synthetic",
        )
        assert out["accepted"] is False
        assert out["rejection"]["reason"] == "half_life_too_slow"
        assert out["execution"]["fills"] == []
        assert out["eligible_for_live_trading"] is False


class TestDataHygiene:
    def test_silent_nan_is_refused(self):
        ts = list(range(100))
        y = [100.0] * 100
        x = [10.0] * 100
        y[10] = float("nan")
        with pytest.raises(ValueError, match="non-finite"):
            bars_from_arrays(ts, y, x)

    def test_gaps_are_documented(self):
        ts = [1_700_000_000_000 + i * 3_600_000 for i in range(90)]
        ts[40] += 3_600_000  # skip one hour, then continue — actually this just shifts
        # Make an explicit hole: jump 3 hours at index 40.
        ts = [1_700_000_000_000 + i * 3_600_000 for i in range(40)]
        ts += [1_700_000_000_000 + (40 + 3 + i) * 3_600_000 for i in range(50)]
        y = list(np.linspace(2000, 2100, 90))
        x = list(np.linspace(140, 150, 90))
        _, gaps = bars_from_arrays(ts, y, x, expected_interval_ms=3_600_000)
        assert gaps["n_gaps"] >= 1
        assert gaps["gaps"][0]["missing_bars_est"] >= 2


class TestDemoAndRoute:
    def test_evaluate_demo_stays_paper(self):
        out = evaluate(demo=True, n=400, seed=2, entry_z=1.5)
        assert out["accepted"] is True
        assert out["eligible_for_live_trading"] is False
        assert out["mode"] == "paper_only"
        assert out["pair"] == {"y": "ETHUSDT", "x": "SOLUSDT"}
        assert "what_broke" in out
        assert out["broker_orders_sent"] == 0
        assert out["decision"]["trades"] >= 1

    def test_desk_route_demo(self):
        import sys
        import types
        from pathlib import Path

        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        # Import desk.py without executing app.api.__init__ (that module pulls every
        # legacy router and optional LLM SDK). CI still loads the full package.
        api_dir = Path(__file__).resolve().parents[1] / "app" / "api"
        pkg = types.ModuleType("app.api")
        pkg.__path__ = [str(api_dir)]
        pkg.__package__ = "app.api"
        sys.modules["app.api"] = pkg

        from app.api.stat_arb_paper import router
        from app.core.limiter import limiter
        from app.core.security import get_current_user

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(router, prefix="/api/desk", dependencies=[Depends(get_current_user)])
        app.dependency_overrides[get_current_user] = lambda: "tester"
        client = TestClient(app)
        res = client.post("/api/desk/pairs/eth-sol-paper", json={"demo": True, "n": 320, "seed": 4})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible_for_live_trading"] is False
        assert body["mode"] == "paper_only"
        assert body["broker_orders_sent"] == 0
        assert body["pair"]["y"] == "ETHUSDT"


class TestPublicMarksMocked:
    @pytest.mark.asyncio
    async def test_mark_klines_refuse_nan(self):
        async def _get(url, params=None, timeout=None):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.json.return_value = [[1_700_000_000_000, "1", "1", "1", "nan"]]
            return r

        client = MagicMock()
        client.get = _get
        with pytest.raises(ValueError, match="Non-finite"):
            await fetch_mark_klines("ETHUSDT", client=client, interval="1h", limit=80)

    @pytest.mark.asyncio
    async def test_aligns_two_legs_without_keys(self):
        eth = [[1_700_000_000_000 + i * 3_600_000, "1", "1", "1", str(2000 + i)] for i in range(90)]
        sol = [[1_700_000_000_000 + i * 3_600_000, "1", "1", "1", str(150 + 0.1 * i)] for i in range(90)]
        # Drop one SOL stamp so the join documents an unmatched ETH bar.
        sol.pop(10)

        async def _get(url, params=None, timeout=None):
            r = MagicMock()
            r.raise_for_status = MagicMock()
            r.json.return_value = eth if params["symbol"] == "ETHUSDT" else sol
            return r

        client = MagicMock()
        client.get = _get
        pulled = await fetch_eth_sol_pair(client=client, interval="1h", limit=90)
        assert pulled["signed"] is False
        assert pulled["broker_orders_sent"] == 0
        assert pulled["gaps"]["n_unmatched_y"] == 1
        assert len(pulled["bars"]) == 89

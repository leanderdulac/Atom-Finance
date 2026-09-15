"""Sequential forward test: locked SMA vs mined TA vs walk-forward."""
import numpy as np

from app.models.forward_test import (
    CANDIDATES,
    demo_prices,
    evaluate,
    sequential_pnl,
    sma_position,
)


class TestCausality:
    def test_sma_at_t_ignores_future_prints(self):
        p = demo_prices(n=400, seed=2)
        pos = sma_position(p, 10, 40)
        p2 = p.copy()
        p2[-1] *= 1.8
        pos2 = sma_position(p2, 10, 40)
        assert np.allclose(pos[:-1], pos2[:-1])

    def test_delay_is_not_the_same_bar(self):
        p = demo_prices(n=400, seed=3)
        pos = sma_position(p, 10, 40)
        delayed = sequential_pnl(p, pos, delay=True)
        leaked = sequential_pnl(p, pos, delay=False)
        assert delayed["sharpe"] != leaked["sharpe"] or delayed["ic"] != leaked["ic"]
        assert len(delayed["net"]) == len(p) - 1


class TestSelectionBias:
    def test_mined_delayed_dominates_the_locked_member(self):
        out = evaluate(seed=11, n=756)
        assert (10, 40) in CANDIDATES
        assert out["mined_delayed"]["sharpe"] >= out["locked"]["sharpe"]
        assert out["mined_same_bar"]["sharpe"] >= out["locked"]["same_bar_sharpe"]
        assert out["n_candidates"] == len(CANDIDATES)
        assert out["eligible_for_live_trading"] is False
        assert out["dsr_mined"]["n_trials"] == len(CANDIDATES)
        assert out["today_signal"]["position"] in (-1, 0, 1)
        assert "ainda não conhecido" in out["today_signal"]["note"]
        assert out["walk_forward"]["n_refits"] >= 2


class TestDeskRoute:
    def test_evaluate_endpoint_keeps_live_trading_false(self):
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
        res = client.post("/api/desk/forward-test/evaluate", json={"n": 400, "seed": 2})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible_for_live_trading"] is False
        assert body["today_signal"]["side"] in ("long", "short", "flat")
        assert body["n_candidates"] == len(CANDIDATES)

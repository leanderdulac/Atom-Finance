"""Row loops over prices: vectorize, or the hiring screen ends."""
import numpy as np

from app.models.vectorize import (
    demo_panel,
    evaluate,
    loop_mask,
    vec_mask,
    zscore_loop,
    zscore_vec,
)


class TestMasksMatch:
    def test_nested_python_equals_boolean_broadcast(self):
        panel = demo_panel(n_names=25, n_days=120, seed=3)
        a = loop_mask(panel["pe"], panel["mom20"], pe_max=10.0)
        b = vec_mask(panel["pe"], panel["mom20"], pe_max=10.0)
        assert np.array_equal(a, b)
        assert a.sum() > 0


class TestLookAhead:
    def test_same_bar_index_is_the_i_versus_i_minus_one_bug(self):
        out = evaluate(n_names=40, n_days=200, seed=7)
        assert out["index_bug"]["same_bar_sharpe"] > out["index_bug"]["delayed_sharpe"] + 1.0
        assert out["screen"]["same_bar_sharpe"] != out["screen"]["delayed_sharpe"]
        assert out["eligible_for_live_trading"] is False


class TestZScore:
    def test_broadcast_matches_row_loop_and_is_faster(self):
        panel = demo_panel(n_names=40, n_days=180, seed=1)
        z_l = zscore_loop(panel["ret"])
        z_v = zscore_vec(panel["ret"])
        assert np.allclose(z_l, z_v, atol=1e-10)
        row_mean = z_v.mean(axis=1)
        row_std = z_v.std(axis=1)
        assert np.allclose(row_mean, 0.0, atol=1e-10)
        assert np.allclose(row_std, 1.0, atol=1e-10)
        out = evaluate(n_names=40, n_days=180, seed=1)
        assert out["z_max_abs_diff"] < 1e-9
        assert out["timing"]["speedup_z"] > 2
        assert "iloc" in out["rejected_code"]


class TestDeskRoute:
    def test_evaluate_keeps_live_trading_false(self):
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
        res = client.post(
            "/api/desk/vectorize/evaluate",
            json={"n_names": 20, "n_days": 100, "seed": 2},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible_for_live_trading"] is False
        assert body["masks_equal"] is True
        assert "for i in range" in body["rejected_code"]

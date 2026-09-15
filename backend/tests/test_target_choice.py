"""Price is a bad target: scale, unit root, vs returns and vol-regime."""
import numpy as np

from app.models.target_choice import MOVE_BRL, demo_pair, evaluate


class TestScale:
    def test_same_return_path_five_hundred_reais_is_not_the_same_move(self):
        pair = demo_pair(n=300, seed=1)
        assert np.allclose(np.diff(np.log(pair["petr4"])), np.diff(np.log(pair["btc"])))
        petr_pct = MOVE_BRL / pair["petr4"][-1]
        btc_pct = MOVE_BRL / pair["btc"][-1]
        assert petr_pct > 20 * btc_pct


class TestStationarityAndTargets:
    def test_returns_are_more_stationary_than_prices_and_price_r2_is_a_unit_root_trick(self):
        out = evaluate(n=400, seed=5)
        st = out["stationarity"]
        assert st["adf_returns"] < st["adf_petr4_price"]
        assert st["returns_reject_unit_root"] is True
        price = out["targets"]["next_price_petr4"]
        ret = out["targets"]["next_return"]
        assert price["r2"] > 0.9
        assert ret["r2"] < price["r2"] - 0.5
        assert out["transfer"]["price_rmse_ratio_btc_over_petr"] > 50
        assert out["targets"]["next_vol_regime"]["accuracy"] > 0.55
        assert out["scale"]["petr4_move_pct"] > out["scale"]["btc_move_pct"] * 20
        assert out["eligible_for_live_trading"] is False
        assert out["scale"]["same_log_return_path"] is True


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
        res = client.post("/api/desk/target-choice/evaluate", json={"n": 300, "seed": 2})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["eligible_for_live_trading"] is False
        assert body["scale"]["same_log_return_path"] is True

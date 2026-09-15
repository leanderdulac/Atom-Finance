"""Winner's curse: zero-edge max Sharpe and Deflated Sharpe Ratio."""
import math

import numpy as np

from app.models.winners_curse import (
    annualized_sharpe,
    deflated_sharpe,
    expected_max_sharpe,
    simulate,
)


class TestSharpeSe:
    def test_zero_mean_se_matches_lo(self):
        env = expected_max_sharpe(n_trials=100, n_obs=505, sharpe_ann=0.0)
        se = math.sqrt(252.0 / 504.0)
        assert abs(env["se"] - se) < 1e-6
        assert abs(env["expected_max_sqrt_2lnN"] - se * math.sqrt(2 * math.log(100))) < 1e-6


class TestDeflatedSharpe:
    def test_lucky_winner_is_not_significant(self):
        # SR = 2 with T=252 after searching 400 names is still luck under H0.
        out = deflated_sharpe(2.0, n_trials=400, n_obs=252)
        assert out["sr_star"] > 1.5
        assert out["deflated_sharpe_prob"] < 0.95
        assert out["significant_at_95"] is False

    def test_huge_sharpe_few_trials_can_pass(self):
        out = deflated_sharpe(4.0, n_trials=2, n_obs=2000)
        assert out["deflated_sharpe_prob"] > 0.95


class TestSimulation:
    def test_champion_is_max_and_oos_is_not_the_backtest(self):
        out = simulate(n_strategies=80, t_is=400, t_oos=200, seed=3)
        assert out["true_sharpe"] == 0.0
        assert out["winner_is"] == max(p["is"] for p in out["cloud"])
        assert out["winner_is"] > out["median_is"]
        # Lottery settlement: OOS of the winner is not the IS print.
        assert out["winner_oos"] < out["winner_is"]
        assert abs(out["is_oos_corr"]) < 0.35
        assert out["eligible_for_live_trading"] is False
        assert out["dsr"]["n_trials"] == 80

    def test_mean_max_tracks_sqrt_2lnN(self):
        rng = np.random.default_rng(0)
        n, t = 30, 252
        maxima = []
        for seed in range(25):
            panel = rng.normal(0.0, 0.01, size=(n, t))
            srs = [annualized_sharpe(panel[i]) for i in range(n)]
            maxima.append(max(srs))
        env = expected_max_sharpe(n, t, 0.0)
        assert abs(float(np.mean(maxima)) - env["expected_max_sqrt_2lnN"]) < 0.55


class TestDeskRoutes:
    def test_simulate_and_deflate_require_the_search_size(self):
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

        sim = client.post(
            "/api/desk/winners-curse/simulate",
            json={"n_strategies": 20, "t_is": 120, "t_oos": 80, "seed": 1},
        )
        assert sim.status_code == 200
        body = sim.json()
        assert body["n_strategies"] == 20
        assert body["eligible_for_live_trading"] is False
        assert len(body["cloud"]) == 20
        assert body["winner_is"] == max(p["is"] for p in body["cloud"])

        haircut = client.post(
            "/api/desk/winners-curse/deflate",
            json={"observed_sharpe": 2.96, "n_trials": 400, "n_obs": 252},
        )
        assert haircut.status_code == 200
        dsr = haircut.json()
        assert dsr["significant_at_95"] is False
        assert dsr["sr_star"] > 1.5

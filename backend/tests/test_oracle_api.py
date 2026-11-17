"""Endpoint tests: /client/simulate and /desk/heston/calibrate-live.

Mini FastAPI apps with dependency_overrides — no database, no network
(chain_us is monkeypatched with a recorded-shape fixture).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.client import router as client_router
from app.api.desk import router as desk_router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.services import oracle


def _client(router, monkeypatch):
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router, prefix="/t")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    return TestClient(app, raise_server_exceptions=False)


def _sim_body(**kw):
    body = {"S0": 100.0, "direction": "long", "entry": 100.0, "stop": 95.0,
            "target": 110.0, "horizon_days": 21, "vol_annual": 0.3,
            "n_paths": 500, "seed": 5}
    body.update(kw)
    return body


def test_simulate_returns_distribution(monkeypatch):
    client = _client(client_router, monkeypatch)
    res = client.post("/t/simulate", json=_sim_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["n_paths"] == 500
    assert body["pnl_p5"] <= body["pnl_p50"] <= body["pnl_p95"]
    assert body["model"] == "gbm_constant_vol"
    assert body["eligible_for_live_trading"] is False
    assert body["what_broke"]


def test_simulate_rejects_bad_geometry(monkeypatch):
    client = _client(client_router, monkeypatch)
    res = client.post("/t/simulate", json=_sim_body(stop=105.0))
    assert res.status_code == 400
    res = client.post("/t/simulate", json=_sim_body(vol_annual=0))
    assert res.status_code == 422


def _chain_fixture():
    from datetime import date, timedelta

    today = date.today()
    exps = [(today + timedelta(days=d)).isoformat() for d in (60, 120)]
    row = {"strike": 100, "lastPrice": 4.0, "bid": 3.9, "ask": 4.1,
           "volume": 10, "openInterest": 50, "impliedVolatility": 0.3}
    makes = []
    for exp in exps:
        calls = [dict(row, strike=k) for k in (90, 95, 100, 105, 110)]
        puts = [dict(row, strike=k, lastPrice=5.0) for k in (90, 95, 100, 105, 110)]
        makes.append({"symbol": "AAPL", "expiry": exp, "calls": calls,
                      "puts": puts, "available_expirations": [exp]})
    return {"chains": makes, "expirations": exps,
            "available": exps, "S0": 100.0,
            "provider": "yfinance", "fetched_at": "2026-01-02T00:00:00+00:00",
            "eligible_for_live_trading": False}


def test_calibrate_live_fits_mock_chain(monkeypatch):
    async def _fake(ticker, expiries=None, max_expiries=4):
        assert ticker == "AAPL"
        return _chain_fixture()

    monkeypatch.setattr(oracle, "chain_us", _fake)
    client = _client(desk_router, monkeypatch)
    res = client.post("/t/heston/calibrate-live",
                      json={"ticker": "AAPL", "n_restarts": 1, "seed": 1})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chain"]["provider"] == "yfinance"
    assert body["weighting"] == "vega"
    assert body["n_quotes"] == 20
    assert "rmse_by_expiry" in body


def test_calibrate_live_maps_source_errors(monkeypatch):
    from app.services.market_sources import SourceError

    async def _fail(ticker, expiries=None, max_expiries=4):
        raise SourceError(502, "Sem vencimentos.")

    monkeypatch.setattr(oracle, "chain_us", _fail)
    client = _client(desk_router, monkeypatch)
    res = client.post("/t/heston/calibrate-live", json={"ticker": "ZZZ"})
    assert res.status_code == 502


def test_oracle_router_spot_validation(monkeypatch):
    from app.api.oracle import router as oracle_router

    async def _boom(symbol, owner=""):
        raise AssertionError("must not fetch on invalid input")

    monkeypatch.setattr(oracle, "spot", _boom)
    client = _client(oracle_router, monkeypatch)
    assert client.get("/t/spot", params={"ticker": ""}).status_code == 422
    assert client.get("/t/spot").status_code == 422
    assert client.get("/t/heartbeat").status_code == 200

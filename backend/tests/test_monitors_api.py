"""Monitor endpoints with a fake pool: routing, validation, wiring, scoping.

No postgres, no network: get_pool and oracle.spot are stubbed. Owner
scoping is asserted on the SQL parameters the handlers pass.
"""
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.monitors import router as monitors_router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.services import oracle


class FakeConn:
    def __init__(self, store):
        self.store = store
        self.calls = []

    async def execute(self, sql, *params):
        self.calls.append((sql, params))
        if sql.startswith("DELETE FROM operation_monitors"):
            return self.store.get("delete_result", "DELETE 1")
        return "INSERT 0 1"

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return self.store.get("fetchrow")

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return self.store.get("fetch", [])

    @asynccontextmanager
    async def transaction(self):
        yield self


class FakePool:
    def __init__(self, store):
        self.conn = FakeConn(store)

    def acquire(self):
        conn = self.conn

        @asynccontextmanager
        async def _acquire():
            yield conn

        return _acquire()


def _client(monkeypatch, store):
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    async def _noop_lock(conn, owner):
        return None

    async def _pool():
        return FakePool(store)

    monkeypatch.setattr("app.api.monitors.get_pool", _pool)
    monkeypatch.setattr("app.api.paper_trades.lock_owner", _noop_lock)
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(monitors_router, prefix="/t")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    pool_holder = {}
    orig_pool = _pool

    async def _capture():
        pool = await orig_pool()
        pool_holder["pool"] = pool
        return pool

    monkeypatch.setattr("app.api.monitors.get_pool", _capture)
    return TestClient(app, raise_server_exceptions=False), pool_holder


def _declared(days_ago=1):
    return datetime.now(UTC) - timedelta(days=days_ago)


def test_declare_persists_baseline_and_owner(monkeypatch):
    store = {}
    client, holder = _client(monkeypatch, store)
    res = client.post("/t/monitors", json={
        "ticker": "PETR4", "direction": "long", "entry": 38.0, "stop": 36.0,
        "target": 41.0, "horizon_days": 21, "size": 20, "vol_annual": 0.3,
        "note": "tese",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["state"] == "watching"
    assert body["baseline"]["pnl_p5"] <= body["baseline"]["pnl_p95"]
    assert body["baseline"]["what_broke"]
    inserts = [c for c in holder["pool"].conn.calls if c[0].startswith("INSERT INTO operation_monitors")]
    assert len(inserts) == 1
    assert inserts[0][1][1] == "alice"  # owner bound
    assert inserts[0][1][2] == "PETR4"


def test_declare_rejects_bad_input(monkeypatch):
    client, _ = _client(monkeypatch, {})
    bad = {"ticker": "PETR4", "direction": "long", "entry": 38.0, "stop": 39.0,
           "target": 41.0, "horizon_days": 21, "vol_annual": 0.3}
    assert client.post("/t/monitors", json=bad).status_code == 400
    bad["stop"] = 36.0
    bad["ticker"] = "x" * 26
    assert client.post("/t/monitors", json=bad).status_code == 422


def test_get_scopes_by_owner(monkeypatch):
    store = {"fetchrow": None, "fetch": []}
    client, holder = _client(monkeypatch, store)
    assert client.get("/t/monitors/abc").status_code == 404
    sql, params = holder["pool"].conn.calls[0]
    assert "owner=$2" in sql and params[1] == "alice"


def test_check_runs_oracle_and_persists_transition(monkeypatch):
    async def _spot(symbol, owner=""):
        assert symbol == "PETR4" and owner == "alice"
        return {"usable": True, "price": 38.2, "stale": [], "disagreement_bps": 0.0,
                "blockers": [], "eligible_for_live_trading": False}

    monkeypatch.setattr(oracle, "spot", _spot)
    store = {"fetchrow": {
        "id": "m1", "owner": "alice", "ticker": "PETR4", "direction": "long",
        "entry": 38.0, "stop": 36.0, "target": 41.0, "horizon_days": 21,
        "state": "watching", "declared_at": _declared(), "last_spot": 37.9,
        "entered_at": None, "entry_px": None}}
    client, holder = _client(monkeypatch, store)
    res = client.post("/t/monitors/m1/check")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "active"
    assert body["prev_state"] == "watching"
    updates = [c for c in holder["pool"].conn.calls if c[0].startswith("UPDATE operation_monitors")]
    assert updates and updates[0][1][0] == "active"
    inserts = [c for c in holder["pool"].conn.calls if c[0].startswith("INSERT INTO monitor_checks")]
    assert len(inserts) == 1 and inserts[0][1][2] == "alice"


def test_check_terminal_short_circuits_without_fetch(monkeypatch):
    called = []

    async def _spot(symbol, owner=""):
        called.append(symbol)
        raise AssertionError("must not fetch")

    monkeypatch.setattr(oracle, "spot", _spot)
    store = {"fetchrow": {
        "id": "m1", "owner": "alice", "ticker": "PETR4", "direction": "long",
        "entry": 38.0, "stop": 36.0, "target": 41.0, "horizon_days": 21,
        "state": "stopped", "declared_at": _declared(30), "last_spot": 35.0,
        "entered_at": _declared(29), "entry_px": 38.0}}
    client, _ = _client(monkeypatch, store)
    res = client.post("/t/monitors/m1/check")
    assert res.status_code == 200
    assert res.json()["terminal"] is True
    assert called == []


def test_check_oracle_down_maps_502(monkeypatch):
    from app.services.market_sources import SourceError

    async def _down(symbol, owner=""):
        raise SourceError(502, "Sem fontes.")

    monkeypatch.setattr(oracle, "spot", _down)
    store = {"fetchrow": {
        "id": "m1", "owner": "alice", "ticker": "PETR4", "direction": "long",
        "entry": 38.0, "stop": 36.0, "target": 41.0, "horizon_days": 21,
        "state": "watching", "declared_at": _declared(), "last_spot": None,
        "entered_at": None, "entry_px": None}}
    client, _ = _client(monkeypatch, store)
    assert client.post("/t/monitors/m1/check").status_code == 502


def test_delete_scopes_and_reports_missing(monkeypatch):
    store = {"delete_result": "DELETE 1"}
    client, holder = _client(monkeypatch, store)
    assert client.delete("/t/monitors/m1").status_code == 200
    assert any("owner=$2" in c[0] for c in holder["pool"].conn.calls)
    store["delete_result"] = "DELETE 0"
    assert client.delete("/t/monitors/m1").status_code == 404

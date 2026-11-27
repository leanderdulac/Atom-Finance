"""HTTP surface of the paper research harness."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.harness import router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.harness.runtime import HarnessRuntime
from tests.harness_support import prices_from_returns, weak_returns


def _body() -> dict:
    returns = weak_returns(80)
    prices = prices_from_returns(returns)
    return {
        "statement": "A short paper hypothesis used by the route test.",
        "family": "route",
        "feature_names": ["lagged_return"],
        "prices": [float(value) for value in prices],
        "signal": [1.0] * len(returns),
        "commission_bps": 5,
        "slippage_bps": 5,
        "half_spread_bps": 2,
        "n_trials": 2,
        "eligible_for_live_trading": False,
    }


def _client(tmp_path: Path) -> tuple[TestClient, FastAPI]:
    app = FastAPI()
    app.state.limiter = limiter
    app.state.harness = HarnessRuntime(tmp_path)
    app.include_router(router, prefix="/api/harness", dependencies=[Depends(get_current_user)])
    return TestClient(app), app


def test_harness_routes_require_auth_and_stay_paper(tmp_path: Path):
    client, app = _client(tmp_path)
    body = _body()
    assert client.post("/api/harness/runs", json=body).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: "tester"

    created = client.post("/api/harness/runs", json=body)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["eligible_for_live_trading"] is False
    assert payload["approved"] is False
    assert payload["terminal"] == "rejected"

    stored = client.get(f"/api/harness/memory/{payload['fingerprint']}")
    assert stored.status_code == 200
    assert stored.json()["status"] == "rejected"
    assert stored.json()["eligible_for_live_trading"] is False
    assert client.get("/api/harness/memory/" + "ab" * 32).status_code == 404

    audit = client.get("/api/harness/audit")
    assert audit.status_code == 200
    assert audit.json()["ok"] is True
    assert audit.json()["eligible_for_live_trading"] is False

    refused = dict(body)
    refused["eligible_for_live_trading"] = True
    assert client.post("/api/harness/runs", json=refused).status_code == 422

    allocated = client.post(
        "/api/harness/allocate",
        json={
            "branches": [
                {
                    "branch_id": "b1",
                    "fingerprint": "deadbeef01",
                    "leakage": True,
                    "eligible_for_live_trading": False,
                }
            ]
        },
    )
    assert allocated.status_code == 200, allocated.text
    plan = allocated.json()
    assert plan["items"][0]["action"] == "prune"
    assert plan["experiments_spent"] == 0
    assert plan["eligible_for_live_trading"] is False

    ledger = tmp_path / "audit.jsonl"
    rows = ledger.read_text(encoding="utf-8").splitlines()
    parsed = json.loads(rows[0])
    parsed["decision"] = "tampered"
    rows[0] = json.dumps(parsed)
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert client.get("/api/harness/audit").status_code == 409

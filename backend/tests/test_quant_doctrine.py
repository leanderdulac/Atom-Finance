"""Desk doctrine is loaded into every LLM call."""
from app.core.quant_doctrine import SYSTEM, compose_system, payload


def test_doctrine_covers_the_posted_curriculum():
    text = SYSTEM.lower()
    assert "√(2" in SYSTEM or "sqrt" in text or "ln n" in text
    assert "maldição" in text or "vencedor" in text
    assert "k-fold" in text
    assert "retorno" in text
    assert "eligible_for_live_trading" in text
    assert "preço" in text
    assert "iloc" in text or "range(len" in text or "vetoriz" in text


def test_compose_system_prefixes_task_without_dropping_doctrine():
    out = compose_system("Explique um straddle.")
    assert out.startswith(SYSTEM.strip()[:40])
    assert "straddle" in out


def test_payload_lists_labs():
    body = payload()
    labs = {t["lab"] for t in body["tenets"]}
    assert labs >= {
        "/winners-curse",
        "/forward-test",
        "/target-choice",
        "/ml",
        "/regime",
        "/vectorize",
    }
    assert body["eligible_for_live_trading"] is False


def test_desk_doctrine_route_requires_auth_and_returns_constitution():
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app.api.desk import router
    from app.core.limiter import limiter
    from app.core.security import get_current_user

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/desk", dependencies=[Depends(get_current_user)])
    client = TestClient(app)
    assert client.get("/api/desk/doctrine").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: "tester"
    body = client.get("/api/desk/doctrine").json()
    assert body["version"] == "ATOM-QUANT-1.0"
    assert body["eligible_for_live_trading"] is False
    assert "maldição" in body["system"].lower() or "vencedor" in body["system"].lower()

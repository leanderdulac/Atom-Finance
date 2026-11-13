"""Ready-made client operation: arsenal assembly, refusals, paper track."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.limiter import limiter
from app.core.security import get_current_user, hash_password
from app.db import database
from app.models.ready_operation import MarketView, assemble, resolve_asset
from app.services.ollama import draft_why


def _history(start=40.0, n=120, daily=0.004):
    closes = start * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily)])
    dates = [(datetime.now(UTC).date() - timedelta(days=n - i)).isoformat() for i in range(n)]
    return {
        "close": [round(float(x), 4) for x in closes],
        "dates": dates,
        "provider": "brapi",
        "source": "brapi",
    }


def _quote(price, provider="brapi"):
    return {"ticker": "PETR4", "price": price, "provider": provider, "source": provider}


def _chain(spot, kind="call"):
    expiry = (datetime.now(UTC).date() + timedelta(days=50)).isoformat()
    k1 = round(spot, 2)
    k2 = round(spot * 1.1, 2)
    rows = []
    for strike, bid, ask in ((k1, 0.80, 0.85), (k2, 0.35, 0.40)):
        rows.append({
            "symbol": f"PETR{kind[0].upper()}{int(strike)}",
            "kind": kind,
            "strike": strike,
            "expiry": expiry,
            "exercise": "european",
            "bid": bid,
            "ask": ask,
            "bid_size": 1000,
            "ask_size": 1000,
            "multiplier": 1,
            "lot_size": 1,
            "iv": 0.35,
        })
    return rows


def test_universe_aliases():
    assert resolve_asset("btc-usd")["id"] == "BTC"
    assert resolve_asset("PETR4")["id"] == "PETR4"
    assert resolve_asset("XXXX") is None


def test_spot_trending_up_is_bullish():
    hist = _history(start=40, daily=0.005)
    spot = hist["close"][-1]
    view = MarketView(quote=_quote(spot), history=hist, regime={"regime": "trending", "kill_switch": {"armed": False}})
    out = assemble("PETR4", "spot", "days", market=view)
    assert out["status"] == "ready"
    assert out["direction"] == "bullish"
    assert out["instrument"] == "spot"
    assert out["eligible_for_live_trading"] is False
    assert out["entry"] > 0 and out["invalidation"] < out["entry"] < out["target"]
    assert out["paper_plan"]["strategy"] == "long_stock"
    assert out["suggested_size"]["can_register_paper"] is True
    assert "EWMA" in {row["part"] for row in out["arsenal"]}
    assert "não é recomendação" in out["disclaimer"].lower() or "Não é recomendação" in out["disclaimer"]


def test_synthetic_quote_is_refused():
    hist = _history()
    view = MarketView(quote=_quote(hist["close"][-1], provider="synthetic"), history=hist)
    out = assemble("PETR4", "spot", "days", market=view)
    assert out["status"] == "insufficient"
    assert "sintétic" in out["reason"].lower()


def test_short_history_is_refused():
    hist = _history(n=20)
    view = MarketView(quote=_quote(hist["close"][-1]), history=hist)
    out = assemble("VALE3", "spot", "weeks", market=view)
    assert out["status"] == "insufficient"
    assert "Histórico" in out["reason"]


def test_b3_future_is_refused():
    hist = _history()
    view = MarketView(quote=_quote(hist["close"][-1]), history=hist)
    out = assemble("PETR4", "future", "days", market=view)
    assert out["status"] == "insufficient"
    assert "futuro B3" in out["reason"] or "Binance" in out["reason"]


def test_option_without_book_is_refused():
    hist = _history()
    view = MarketView(quote=_quote(hist["close"][-1]), history=hist, chain=None)
    out = assemble("PETR4", "option", "weeks", market=view)
    assert out["status"] == "insufficient"
    assert "livro" in out["reason"].lower()


def test_option_with_usable_book_builds_structure():
    hist = _history(start=100, daily=0.02)
    spot = hist["close"][-1]
    view = MarketView(
        quote=_quote(spot),
        history=hist,
        chain=_chain(spot, "call"),
        chain_source="test",
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    out = assemble("PETR4", "option", "days", market=view)
    assert out["status"] == "ready", out.get("reason")
    assert out["instrument"] == "option"
    assert out["structure"]["strategy"] in {"long_call", "bull_call_spread"}
    assert out["paper_plan"]["legs"]
    assert out["greeks"] is not None
    assert out["eligible_for_live_trading"] is False


def test_crisis_kill_switch_refuses():
    hist = _history()
    view = MarketView(
        quote=_quote(hist["close"][-1]),
        history=hist,
        regime={"regime": "crisis", "kill_switch": {"armed": True}},
    )
    out = assemble("BTC", "spot", "days", market=view)
    assert out["status"] == "insufficient"
    assert "crise" in out["reason"].lower()


def test_unknown_ticker():
    out = assemble("XXXX", "spot", "days", market=None)
    assert out["status"] == "insufficient"


def test_noisy_flat_series_refuses_direction():
    closes = np.full(120, 40.0)
    closes[-1] = 40.01  # almost no momentum
    hist = {
        "close": closes.tolist(),
        "dates": [(datetime.now(UTC).date() - timedelta(days=120 - i)).isoformat() for i in range(120)],
        "provider": "yfinance",
        "source": "yfinance",
    }
    view = MarketView(quote=_quote(40.01, provider="yfinance"), history=hist)
    out = assemble("ETH", "spot", "months", market=view)
    assert out["status"] == "insufficient"


@pytest.mark.asyncio
async def test_ollama_disabled_returns_none():
    assert await draft_why("facts") is None


@pytest.mark.asyncio
async def test_api_ready_and_paper(monkeypatch):
    await database.create_user("alice", "alice@example.test", hash_password("a-secure-test-password"))
    hist = _history(start=40, daily=0.005)
    spot = hist["close"][-1]
    view = MarketView(quote=_quote(spot), history=hist, regime={"regime": "trending", "kill_switch": {"armed": False}})

    def fake_load(ticker: str):
        return view

    monkeypatch.setattr("app.api.client.load_market", fake_load)
    monkeypatch.setattr("app.services.client_arsenal.load_market", fake_load)

    from app.api.client import router as client_router
    from app.api.paper_trades import router as paper_router

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(client_router, prefix="/api/client")
    app.include_router(paper_router, prefix="/api/paper-trades")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    client = TestClient(app)

    cfg = client.get("/api/client/config")
    assert cfg.status_code == 200
    assert cfg.json()["eligible_for_live_trading"] is False
    assert any(row["id"] == "PETR4" for row in cfg.json()["universe"])

    ready = client.post("/api/client/ready-operation", json={"ticker": "PETR4", "instrument": "spot", "horizon": "days"})
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert body["status"] == "ready"
    assert body["why"]
    assert body["eligible_for_live_trading"] is False

    tracked = client.post(
        "/api/client/ready-operation/paper",
        json={"ticker": "PETR4", "instrument": "spot", "horizon": "days"},
    )
    assert tracked.status_code == 201, tracked.text
    trade = tracked.json()["trade"]
    assert trade["status"] == "watching"
    assert trade["eligible_for_live_trading"] is False

    ops = client.get("/api/paper-trades/operations")
    assert ops.status_code == 200
    assert ops.json()["aggregate"]["watching_count"] >= 1


@pytest.mark.asyncio
async def test_api_option_paper(monkeypatch):
    await database.create_user("alice", "alice@example.test", hash_password("a-secure-test-password"))
    hist = _history(start=100, daily=0.02)
    spot = hist["close"][-1]
    view = MarketView(
        quote=_quote(spot),
        history=hist,
        chain=_chain(spot, "call"),
        chain_source="test",
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    monkeypatch.setattr("app.api.client.load_market", lambda ticker: view)

    from app.api.client import router as client_router

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(client_router, prefix="/api/client")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    client = TestClient(app)
    ready = client.post("/api/client/ready-operation", json={"ticker": "PETR4", "instrument": "option", "horizon": "days"})
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    assert ready.json()["greeks"]
    tracked = client.post(
        "/api/client/ready-operation/paper",
        json={"ticker": "PETR4", "instrument": "option", "horizon": "days"},
    )
    assert tracked.status_code == 201, tracked.text
    assert tracked.json()["trade"]["status"] == "watching"

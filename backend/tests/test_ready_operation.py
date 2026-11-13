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
from app.models.ready_operation import MarketView, assemble, client_facing_why, resolve_asset
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
    assert resolve_asset("SOLUSDT")["id"] == "SOL"
    assert resolve_asset("XXXX") is None


def _crypto_downtrend(spot=1956.0, n=150):
    """Strong down-move so a short is allowed; last print near `spot`."""
    daily = -0.008
    closes = spot / ((1 + daily) ** (n - 1)) * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily)])
    closes[-1] = spot
    dates = [(datetime.now(UTC).date() - timedelta(days=n - i)).isoformat() for i in range(n)]
    return {
        "close": [round(float(x), 4) for x in closes],
        "dates": dates,
        "provider": "binance",
        "source": "binance",
    }


def test_eth_future_stop_is_capped_and_size_is_fractional():
    hist = _crypto_downtrend()
    view = MarketView(
        quote={"ticker": "ETH", "price": 1956.0, "provider": "binance", "source": "binance"},
        history=hist,
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    out = assemble("ETH", "future", "months", market=view, capital=10000, risk_pct=1)
    assert out["status"] == "ready", out.get("reason")
    assert out["direction"] == "bearish"
    stop_pct = abs(out["invalidation"] / out["spot"] - 1)
    target_pct = abs(out["target"] / out["spot"] - 1)
    assert stop_pct <= 0.13, stop_pct
    assert 1.4 <= target_pct / stop_pct <= 1.8
    qty = out["suggested_size"]["quantity"]
    assert 0 < qty < 1
    assert out["suggested_size"]["can_register_paper"] is True
    why = (out["why"] + out["disclaimer"] + out["invalidation_reason"]).lower()
    assert "z_score" not in why
    assert "eligible_for_live_trading" not in why
    assert "ewma" not in why
    assert out["paper_plan"]["legs"][0]["quantity"] == qty


def test_btc_and_sol_assemble_or_refuse_in_portuguese():
    hist = _history(start=90000, daily=0.004)
    view = MarketView(
        quote={"ticker": "BTC", "price": hist["close"][-1], "provider": "binance", "source": "binance"},
        history={**hist, "provider": "binance", "source": "binance"},
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    btc = assemble("BTC", "future", "weeks", market=view)
    assert btc["status"] in {"ready", "insufficient"}
    if btc["status"] == "insufficient":
        assert btc["reason"]
        assert "invent" in btc["reason"].lower() or "sinal" in btc["reason"].lower() or "regime" in btc["reason"].lower() or "volatil" in btc["reason"].lower()
    else:
        assert btc["suggested_size"]["quantity"] > 0
        assert btc["suggested_size"]["quantity"] < 1
    missing = assemble("BTC", "future", "weeks", market=None)
    assert missing["status"] == "insufficient"
    assert "BTC" in missing["reason"]
    sol = assemble("SOL", "spot", "days", market=None)
    assert sol["status"] == "insufficient"
    assert "SOL" in sol["reason"]


def test_client_facing_why_strips_jargon():
    clean = client_facing_why(
        "Cenário de baixa em Ethereum. Simulação paper.",
        "fallback",
    )
    assert "Ethereum" in clean
    stripped = client_facing_why(
        "Regime local trending e z_score -0,817. eligible_for_live_trading é falso.",
        "O movimento recente de Ethereum levou o arsenal a montar um cenário de baixa.",
    )
    assert "z_score" not in stripped
    assert "eligible_for_live_trading" not in stripped


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

    async def _no_news(*_a, **_k):
        return None

    monkeypatch.setattr("app.api.client.run_news_agent", _no_news)

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
    assert any(row["id"] == "SOL" for row in cfg.json()["universe"])

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

    async def _no_news(*_a, **_k):
        return None

    monkeypatch.setattr("app.api.client.run_news_agent", _no_news)

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


@pytest.mark.asyncio
async def test_api_ready_includes_thermometer(monkeypatch):
    await database.create_user("alice", "alice@example.test", hash_password("a-secure-test-password"))
    hist = _history(start=40, daily=0.005)
    spot = hist["close"][-1]
    view = MarketView(quote=_quote(spot), history=hist, regime={"regime": "trending", "kill_switch": {"armed": False}})
    monkeypatch.setattr("app.api.client.load_market", lambda ticker: view)

    from app.services.agents.schemas import NewsBrief

    async def _news(*_a, **_k):
        return NewsBrief.model_validate({
            "eventos_proximos": [],
            "sentimento": 0.7,
            "riscos": [],
            "fontes": [{
                "titulo": "Petrobras sobe com recorde de produção",
                "url": "https://www.bcb.gov.br/noticia",
                "data": "2026-11-13",
            }],
        })

    monkeypatch.setattr("app.api.client.run_news_agent", _news)

    from app.api.client import router as client_router

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(client_router, prefix="/api/client")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    client = TestClient(app)
    ready = client.post("/api/client/ready-operation", json={"ticker": "PETR4", "instrument": "spot", "horizon": "days"})
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert body["thermometer"]["tone"] == "otimista"
    assert "Clima do mercado para PETR4" in body["thermometer"]["label"]
    assert body["thermometer"]["headlines"][0]["url"].startswith("https://")
    assert body["eligible_for_live_trading"] is False
    if body["status"] == "ready":
        assert body["direction"] == "bullish"

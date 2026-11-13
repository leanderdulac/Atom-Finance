"""Thermometer score, arsenal blend, and honest skill — no live xAI."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.ready_operation import MarketView, assemble
from app.models.sentiment_signal import (
    adjust_confidence,
    blend_direction,
    build_signal,
    climate_label,
    effective_weight,
    lexical_score,
    quant_score,
)
from app.services.agents.schemas import NewsBrief
from app.services.sentiment_eval import evaluate_pairs


def _news(*, sentimento=0.6, titulo="Petrobras sobe com recorde de produção"):
    return NewsBrief.model_validate({
        "eventos_proximos": [],
        "sentimento": sentimento,
        "riscos": [],
        "fontes": [{
            "titulo": titulo,
            "url": "https://www.bcb.gov.br/noticia",
            "data": "2026-11-13",
        }],
    })


def test_lexical_and_climate():
    assert lexical_score(["Petrobras sobe com recorde"]) > 0
    assert lexical_score(["Bitcoin desaba em crash"]) < 0
    assert "otimista" in climate_label("BTC", 0.5)
    assert "pessimista" in climate_label("BTC", -0.5)


def test_build_signal_requires_sources():
    assert build_signal("PETR4", "weeks", news=None) is None
    sig = build_signal("PETR4", "weeks", news=_news(), price=38.0, price_mom=0.04)
    assert sig is not None
    assert -1 <= sig["score"] <= 1
    assert sig["headlines"][0]["url"].startswith("https://")
    assert sig["label"].startswith("Clima do mercado")


def test_effective_weight_does_not_rise_without_evidence(monkeypatch):
    monkeypatch.setenv("ATOM_SENTIMENT_WEIGHT", "0.4")
    assert effective_weight(None) == 0.2
    assert effective_weight({"allows_raise": False}) == 0.2
    assert effective_weight({"allows_raise": True}) == 0.4


def test_blend_agreement_and_disagreement():
    d, rel, c = blend_direction(1.0, 0.8, 0.2)
    assert d == "bullish"
    assert rel == "acordo"
    d, rel, c = blend_direction(1.0, -0.8, 0.2)
    assert rel == "desacordo"
    assert d in {"bullish", None}  # still follows quant unless combined is weak
    d, rel, c = blend_direction(0.1, -0.9, 0.2)
    assert d is None
    assert adjust_confidence("média", "acordo") == "moderada"
    assert adjust_confidence("moderada", "desacordo") == "baixa"


def test_evaluate_pairs_needs_history():
    empty = evaluate_pairs([])
    assert empty["allows_raise"] is False
    assert empty["assessment"] == "insufficient_evidence"
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    price = 100.0
    for i in range(40):
        score = 0.7 if (i % 10) < 5 else -0.7
        rows.append({
            "created_at": start + timedelta(days=i),
            "score": score,
            "price": price,
            "holding_days": 1,
        })
        price = price * (1.01 if score > 0 else 0.99)
    report = evaluate_pairs(rows)
    assert report["n"] >= 20
    assert report["hit_rate"] is not None
    assert report["hit_rate"] > 0.7
    assert report["allows_raise"] is True


def test_assemble_without_sentiment_unchanged():
    import numpy as np
    daily = 0.004
    n = 120
    closes = 40 * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily)])
    dates = [(datetime.now(UTC).date() - timedelta(days=n - i)).isoformat() for i in range(n)]
    view = MarketView(
        quote={"ticker": "PETR4", "price": float(closes[-1]), "provider": "brapi", "source": "brapi"},
        history={"close": [round(float(x), 4) for x in closes], "dates": dates, "provider": "brapi", "source": "brapi"},
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    out = assemble("PETR4", "spot", "days", market=view)
    assert out["status"] == "ready"
    assert out["direction"] == "bullish"
    assert out.get("thermometer") in (None, {}) or out["thermometer"] is None


def test_assemble_sentiment_agreement_keeps_levels_from_arsenal():
    import numpy as np
    daily = 0.004
    n = 120
    closes = 40 * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily)])
    dates = [(datetime.now(UTC).date() - timedelta(days=n - i)).isoformat() for i in range(n)]
    view = MarketView(
        quote={"ticker": "PETR4", "price": float(closes[-1]), "provider": "brapi", "source": "brapi"},
        history={"close": [round(float(x), 4) for x in closes], "dates": dates, "provider": "brapi", "source": "brapi"},
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    )
    plain = assemble("PETR4", "spot", "days", market=view)
    sent = build_signal("PETR4", "days", news=_news(sentimento=0.8), price=float(closes[-1]), price_mom=0.05)
    out = assemble("PETR4", "spot", "days", market=view, sentiment=sent, sentiment_weight=0.2)
    assert out["status"] == "ready"
    assert out["direction"] == "bullish"
    assert out["entry"] == plain["entry"]
    assert out["invalidation"] == plain["invalidation"]
    assert out["target"] == plain["target"]
    assert out["thermometer"]["tone"] == "otimista"
    assert "Clima do mercado" in out["thermometer"]["label"]
    assert out["eligible_for_live_trading"] is False


def test_assemble_source_disagreement_drops_confidence():
    view, spot = _trending_view()
    sent = build_signal(
        "PETR4", "days", news=_news(sentimento=0.8), price=spot, price_mom=0.05,
    )
    assert sent is not None
    sent["source_disagreement"] = True
    sent["providers"] = ["xai", "openai"]
    out = assemble("PETR4", "spot", "days", market=view, sentiment=sent, sentiment_weight=0.2)
    assert out["eligible_for_live_trading"] is False
    if out["status"] == "ready":
        assert out["confidence"] == "baixa"
        assert out["entry"] > 0
        assert out["invalidation"] > 0
        assert out["target"] > 0


def test_quant_score_mean_reverting():
    assert quant_score("mean_reverting", 1.2, 0.01, 0.05) == -1.0
    assert quant_score("mean_reverting", -1.2, 0.01, 0.05) == 1.0
    assert quant_score("mean_reverting", 0.1, 0.01, 0.05) == 0.0


def _trending_view():
    import numpy as np
    daily = 0.004
    n = 120
    closes = 40 * np.cumprod(np.r_[1.0, np.full(n - 1, 1.0 + daily)])
    dates = [(datetime.now(UTC).date() - timedelta(days=n - i)).isoformat() for i in range(n)]
    return MarketView(
        quote={"ticker": "PETR4", "price": float(closes[-1]), "provider": "brapi", "source": "brapi"},
        history={"close": [round(float(x), 4) for x in closes], "dates": dates, "provider": "brapi", "source": "brapi"},
        regime={"regime": "trending", "kill_switch": {"armed": False}},
    ), float(closes[-1])


def test_assemble_sentiment_disagreement_drops_confidence():
    view, spot = _trending_view()
    plain = assemble("PETR4", "spot", "days", market=view)
    sent = build_signal(
        "PETR4", "days",
        news=_news(sentimento=-0.9, titulo="Petrobras desaba em crash"),
        price=spot, price_mom=0.05,
    )
    out = assemble("PETR4", "spot", "days", market=view, sentiment=sent, sentiment_weight=0.2)
    assert out["eligible_for_live_trading"] is False
    if out["status"] == "ready":
        assert out["entry"] == plain["entry"]
        assert out["invalidation"] == plain["invalidation"]
        assert out["target"] == plain["target"]
        order = ("baixa", "média", "moderada")
        assert order.index(out["confidence"]) <= order.index(plain["confidence"])
        assert out["sentiment"]["relation"] in {"desacordo", "neutro", "acordo"}
    else:
        assert out["status"] == "insufficient"
        assert out.get("thermometer")


@pytest.mark.asyncio
async def test_snapshot_roundtrip_and_skill():
    from app.db.sentiment import insert_snapshot, list_snapshots

    start = datetime(2026, 2, 1, tzinfo=UTC)
    price = 100.0
    for i in range(28):
        score = 0.6 if (i % 10) < 5 else -0.6
        await insert_snapshot({
            "ticker": "BTC",
            "horizon": "weeks",
            "created_at": start + timedelta(days=i),
            "score": score,
            "intensity": 1.2,
            "momentum": 0.05,
            "price": price,
            "price_divergence": 0.0,
            "n_mentions": 4,
            "holding_days": 1,
            "headlines": [{"title": "BTC sobe", "url": "https://example.com/a", "date": "2026-02-01"}],
            "sources": [{"title": "BTC sobe", "url": "https://example.com/a", "date": "2026-02-01"}],
            "payload": {"label": "Clima do mercado para BTC: otimista"},
        })
        price *= 1.01 if score > 0 else 0.99
    rows = await list_snapshots("BTC", "weeks", limit=100)
    assert len(rows) >= 28
    report = evaluate_pairs(rows)
    assert report["n"] >= 20
    assert report["hit_rate"] is not None and report["hit_rate"] > 0.7
    assert report["allows_raise"] is True
    assert report["eligible_for_live_trading"] is False


@pytest.mark.asyncio
async def test_desk_sentiment_skill_empty():
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from app.api.desk import router
    from app.core.security import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/desk")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    client = TestClient(app)
    res = client.get("/api/desk/sentiment-skill", params={"ticker": "ZZZ9", "horizon": "weeks"})
    assert res.status_code == 200
    body = res.json()
    assert body["allows_raise"] is False
    assert body["assessment"] == "insufficient_evidence"
    assert body["eligible_for_live_trading"] is False
    posted = client.post("/api/desk/sentiment-skill", params={"ticker": "ZZZ9", "horizon": "weeks"})
    assert posted.status_code == 200
    diary = posted.json()
    assert diary["experiment_id"]
    assert diary["allows_raise"] is False
    assert diary["eligible_for_live_trading"] is False

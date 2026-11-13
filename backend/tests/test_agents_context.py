"""News/risk agents with mocked LLM; overlay never moves entry/stop/target."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.agents.apply import apply_context_risk
from app.services.agents.audit import list_audits, record_audit_sync
from app.services.agents.llm import DisabledCloudProvider, get_agent_llm, parse_json_object
from app.services.agents.news import news_from_bundle
from app.services.agents.risk import risk_from_rules
from app.services.agents.schemas import NewsBrief, RiskBrief
from app.services.agents.writer import cite_sources


def _payload(**over):
    base = {
        "status": "ready",
        "ticker": "PETR4",
        "entry": 38.2,
        "invalidation": 36.0,
        "target": 41.5,
        "quantity": 20,
        "confidence": "média",
        "suggested_size": {"quantity": 20, "can_register_paper": True, "paper_block": None},
        "paper_plan": {"quantity_per_leg": 20, "legs": [{"side": "buy", "symbol": "PETR4", "quantity": 20}]},
        "eligible_for_live_trading": False,
        "arsenal": [],
        "holding_days": 21,
    }
    base.update(over)
    return base


def _news(*, binary=True):
    return NewsBrief.model_validate({
        "eventos_proximos": [
            {"nome": "FOMC", "data": "2026-12-09", "tipo": "binary", "impacto": "alto"},
        ] if binary else [],
        "sentimento": 0.1,
        "riscos": ["FOMC no horizonte"],
        "fontes": [{"titulo": "Fed", "url": "https://www.federalreserve.gov/fomc.htm", "data": "2026-11-01"}],
    })


def test_news_brief_requires_sources():
    with pytest.raises(ValidationError):
        NewsBrief.model_validate({
            "eventos_proximos": [],
            "sentimento": 0,
            "riscos": [],
            "fontes": [],
        })


def test_news_from_bundle_discards_without_fontes():
    assert news_from_bundle({"fontes": [], "eventos": []}) is None
    brief = news_from_bundle({
        "fontes": [{"titulo": "BCB", "url": "https://www.bcb.gov.br/x", "data": "2026-11-12"}],
        "eventos": [{"nome": "Copom", "data": "2026-12-09", "tipo": "binary", "impacto": "alto"}],
    })
    assert brief is not None
    assert brief.fontes[0].url.startswith("https://")


def test_invalid_json_parse():
    assert parse_json_object("not json") is None
    assert parse_json_object('```json\n{"sentimento": 0, "fontes": []}\n```')["sentimento"] == 0


def test_apply_reduce_keeps_levels():
    news = _news()
    risk = RiskBrief(objecoes=["FOMC"], severidade="alta", recomendacao="reduzir")
    out = apply_context_risk(_payload(), news, risk)
    assert out["entry"] == 38.2
    assert out["invalidation"] == 36.0
    assert out["target"] == 41.5
    assert out["quantity"] == 10
    assert out["confidence"] == "baixa"
    assert out["context_effect"] == "reduzir"
    assert out["status"] == "ready"
    assert out["sources"][0]["url"].startswith("https://")
    assert out["eligible_for_live_trading"] is False


def test_apply_refuse_keeps_levels():
    news = _news()
    risk = RiskBrief(objecoes=["evento binário"], severidade="alta", recomendacao="recusar")
    out = apply_context_risk(_payload(), news, risk)
    assert out["status"] == "insufficient"
    assert out["entry"] == 38.2
    assert out["invalidation"] == 36.0
    assert out["target"] == 41.5
    assert out["quantity"] == 0
    assert out["suggested_size"]["can_register_paper"] is False
    assert out["context_effect"] == "recusar"


def test_apply_binary_reduces_not_moves_levels():
    news = _news(binary=True)
    risk = risk_from_rules(_payload(), news)
    assert risk.recomendacao in {"reduzir", "recusar"}
    out = apply_context_risk(_payload(), news, risk)
    assert out["entry"] == 38.2
    assert out["invalidation"] == 36.0
    assert out["target"] == 41.5
    if out["status"] == "ready":
        assert out["quantity"] == 10


def test_writer_cites_link_and_date():
    text = cite_sources("Cenário de alta em PETR4. Simulação.", _news())
    assert "https://www.federalreserve.gov" in text
    assert "2026-11-01" in text
    assert "Fontes consultadas" in text


def test_audit_stores_objections_off_client_payload():
    news = _news()
    risk = RiskBrief(objecoes=["não ignorar o FOMC"], severidade="media", recomendacao="reduzir")
    payload = apply_context_risk(_payload(), news, risk)
    item = record_audit_sync(
        owner="alice", ticker="PETR4", horizon="weeks", payload=payload, news=news, risk=risk,
    )
    assert "não ignorar o FOMC" in item["objecoes"]
    listed = list_audits(5)
    assert listed[0]["id"] == item["id"]
    assert "objecoes" not in payload  # client payload never got the brief


@pytest.mark.asyncio
async def test_cloud_llm_off_without_key(monkeypatch):
    from app.core.ai_factory import LLMException

    monkeypatch.setenv("ATOM_AGENT_LLM", "grok")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert get_agent_llm() is None
    stub = DisabledCloudProvider("grok", "XAI_API_KEY")
    with pytest.raises(LLMException):
        await stub.complete("hi")


def test_default_agent_llm_is_ollama_when_enabled(monkeypatch):
    monkeypatch.setenv("ATOM_AGENT_LLM", "ollama")
    monkeypatch.setenv("OLLAMA_ENABLED", "0")
    assert get_agent_llm() is None

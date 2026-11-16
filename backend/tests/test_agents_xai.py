"""xAI news agent: citations are mandatory; hourly cap; cache; no live calls."""
from __future__ import annotations

import pytest

from app.core.cache import Cache
from app.services.agents.llm import get_risk_llm
from app.services.agents.xai import (
    XAIProvider,
    allow_call,
    brief_from_xai,
    extract_citations,
    extract_output_text,
    news_brief,
    news_cache_key,
    xai_configured,
    xai_model,
)


def _responses_payload(*, text: str, citations: list[str], extra_ann: str | None = None) -> dict:
    annotations = []
    if extra_ann:
        annotations.append({"type": "url_citation", "url": extra_ann, "title": "1"})
    return {
        "citations": citations,
        "output_text": text,
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": text, "annotations": annotations}],
        }],
    }


def test_xai_off_without_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "")
    assert xai_configured() is False


def test_xai_model_default_and_reasoning(monkeypatch):
    monkeypatch.delenv("XAI_MODEL", raising=False)
    assert xai_model() == "grok-4.3"
    monkeypatch.setenv("XAI_MODEL", "grok-4.20-0309-reasoning")
    assert xai_model() == "grok-4.20-0309-reasoning"


def test_extract_citations_from_list_and_inline():
    payload = _responses_payload(
        text='ver [[1]](https://www.bcb.gov.br/x) e [[2]](https://x.com/i/status/1)',
        citations=["https://www.federalreserve.gov/fomc.htm"],
        extra_ann="https://www.bls.gov/cpi/",
    )
    urls = extract_citations(payload, payload["output_text"])
    assert "https://www.federalreserve.gov/fomc.htm" in urls
    assert "https://www.bcb.gov.br/x" in urls
    assert "https://x.com/i/status/1" in urls
    assert "https://www.bls.gov/cpi/" in urls


def test_brief_drops_hallucinated_urls():
    raw = {
        "sentimento": 0.2,
        "riscos": ["Copom"],
        "eventos_proximos": [{"nome": "Copom", "data": "2026-12-09", "tipo": "binary", "impacto": "alto"}],
        "fontes": [
            {"titulo": "inventado", "url": "https://evil.example/fake", "data": ""},
            {"titulo": "BCB", "url": "https://www.bcb.gov.br/copom", "data": "2026-11-12"},
        ],
    }
    brief = brief_from_xai(raw, ["https://www.bcb.gov.br/copom", "https://x.com/i/status/9"])
    assert brief is not None
    urls = {s.url for s in brief.fontes}
    assert "https://evil.example/fake" not in urls
    assert "https://www.bcb.gov.br/copom" in urls
    assert "https://x.com/i/status/9" in urls


def test_brief_discards_without_citations():
    raw = {
        "sentimento": 0,
        "riscos": [],
        "eventos_proximos": [],
        "fontes": [{"titulo": "x", "url": "https://www.bcb.gov.br/x", "data": ""}],
    }
    assert brief_from_xai(raw, []) is None


def test_extract_output_text():
    payload = _responses_payload(text='{"sentimento": 0}', citations=[])
    assert extract_output_text(payload) == '{"sentimento": 0}'


@pytest.mark.asyncio
async def test_news_brief_uses_cache_without_http(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    ticker, horizon = "PETR4", "weeks"
    key = news_cache_key(ticker, horizon)
    cached = {
        "eventos_proximos": [],
        "sentimento": 0.0,
        "riscos": [],
        "fontes": [{"titulo": "Fed", "url": "https://www.federalreserve.gov/x", "data": "2026-11-01"}],
    }
    Cache.set(key, cached, ex=900)

    async def boom(*_a, **_k):
        raise AssertionError("cache hit must not call xAI")

    monkeypatch.setattr("app.services.agents.xai._post_json", boom)
    brief = await news_brief(ticker, horizon, {"eventos": [], "horizon_days": 21})
    assert brief is not None
    assert brief.fontes[0].url.startswith("https://www.federalreserve.gov")


@pytest.mark.asyncio
async def test_news_brief_hourly_cap(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_XAI_MAX_CALLS_PER_HOUR", "1")
    monkeypatch.setattr("app.services.agents.xai._hour_key", lambda: "atom:xai:calls:test-cap")
    Cache.delete("atom:xai:calls:test-cap")
    Cache.delete("ctx:xai:news:VALE3:days")
    assert allow_call() is True
    assert allow_call() is False

    called = {"n": 0}

    async def fake_post(*_a, **_k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.agents.xai._post_json", fake_post)
    brief = await news_brief("VALE3", "days", {"eventos": [], "horizon_days": 5})
    assert brief is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_news_brief_parses_mocked_responses(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_XAI_MAX_CALLS_PER_HOUR", "60")
    Cache.delete(news_cache_key("BTC", "days"))
    text = (
        '{"sentimento": -0.2, "riscos": ["funding"], "eventos_proximos": [], '
        '"fontes": [{"titulo": "CoinDesk", "url": "https://www.coindesk.com/a", "data": "2026-11-13"}]}'
    )

    async def fake_post(path, payload, **_k):
        assert path == "/responses"
        tools = {t["type"] for t in payload["tools"]}
        assert tools == {"web_search", "x_search"}
        assert payload["model"] == "grok-4.3"
        return _responses_payload(text=text, citations=["https://www.coindesk.com/a"])

    monkeypatch.setattr("app.services.agents.xai._post_json", fake_post)
    brief = await news_brief("BTC", "days", {"eventos": [], "horizon_days": 5})
    assert brief is not None
    assert brief.sentimento == -0.2
    assert brief.fontes[0].url == "https://www.coindesk.com/a"


@pytest.mark.asyncio
async def test_xai_provider_complete_mocked(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_XAI_MAX_CALLS_PER_HOUR", "60")

    async def fake_post(path, payload, **_k):
        assert path == "/chat/completions"
        assert payload["model"] == "grok-4.3"
        return {"choices": [{"message": {"content": '{"objecoes":[],"severidade":"baixa","recomendacao":"manter"}'}}]}

    monkeypatch.setattr("app.services.agents.xai._post_json", fake_post)
    text = await XAIProvider().complete("hi", system_prompt="json only")
    assert "manter" in text


def test_risk_provider_defaults_to_ollama_when_disabled(monkeypatch):
    monkeypatch.setenv("ATOM_RISK_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_ENABLED", "0")
    monkeypatch.setenv("XAI_API_KEY", "")
    assert get_risk_llm() is None

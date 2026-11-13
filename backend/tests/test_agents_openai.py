"""OpenAI news agent: citations mandatory; hourly cap; cache; no live calls."""
from __future__ import annotations

import pytest

from app.core.cache import Cache
from app.services.agents.llm import get_risk_llm
from app.services.agents.news import merge_news_briefs
from app.services.agents.openai_news import (
    OpenAIProvider,
    allow_call,
    estimate_usd,
    news_brief,
    news_cache_key,
    openai_configured,
    openai_model,
    recent_costs,
)
from app.services.agents.schemas import NewsBrief
from app.services.agents.xai import brief_from_xai


def _responses_payload(*, text: str, citations: list[str], extra_ann: str | None = None) -> dict:
    annotations = []
    if extra_ann:
        annotations.append({"type": "url_citation", "url": extra_ann, "title": "1"})
    return {
        "citations": citations,
        "output_text": text,
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text, "annotations": annotations}],
            },
        ],
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }


def test_openai_off_without_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert openai_configured() is False


def test_openai_model_default(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert openai_model() == "gpt-5-mini"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5")
    assert openai_model() == "gpt-5"


def test_brief_drops_hallucinated_openai_urls():
    raw = {
        "sentimento": 0.1,
        "riscos": [],
        "eventos_proximos": [],
        "fontes": [
            {"titulo": "fake", "url": "https://evil.example/x", "data": ""},
            {"titulo": "Fed", "url": "https://www.federalreserve.gov/fomc.htm", "data": "2026-11-12"},
        ],
    }
    brief = brief_from_xai(raw, ["https://www.federalreserve.gov/fomc.htm"])
    assert brief is not None
    urls = {s.url for s in brief.fontes}
    assert "https://evil.example/x" not in urls
    assert "https://www.federalreserve.gov/fomc.htm" in urls


def test_estimate_usd_is_labelled_estimate():
    usd = estimate_usd(input_tokens=1_000_000, output_tokens=0, web_search_calls=1)
    assert usd > 0
    Cache.delete("atom:openai:costs")
    from app.services.agents.openai_news import log_cost
    log_cost({"kind": "news", "estimated_usd": usd, "model": "gpt-5-mini"})
    rows = recent_costs()
    assert rows[0]["estimate"] is True
    assert rows[0]["eligible_for_live_trading"] is False


@pytest.mark.asyncio
async def test_openai_news_brief_uses_cache_without_http(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    ticker, horizon = "PETR4", "weeks"
    key = news_cache_key(ticker, horizon)
    cached = {
        "eventos_proximos": [],
        "sentimento": 0.1,
        "riscos": [],
        "fontes": [{"titulo": "Fed", "url": "https://www.federalreserve.gov/x", "data": "2026-11-01"}],
    }
    Cache.set(key, cached, ex=900)

    async def boom(*_a, **_k):
        raise AssertionError("cache hit must not call OpenAI")

    monkeypatch.setattr("app.services.agents.openai_news._post_json", boom)
    brief = await news_brief(ticker, horizon, {"eventos": [], "horizon_days": 21})
    assert brief is not None
    assert brief.fontes[0].url.startswith("https://www.federalreserve.gov")


@pytest.mark.asyncio
async def test_openai_news_brief_hourly_cap(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_OPENAI_MAX_CALLS_PER_HOUR", "1")
    monkeypatch.setattr("app.services.agents.openai_news._hour_key", lambda: "atom:openai:calls:test-cap")
    Cache.delete("atom:openai:calls:test-cap")
    Cache.delete("ctx:openai:news:VALE3:days")
    assert allow_call() is True
    assert allow_call() is False

    called = {"n": 0}

    async def fake_post(*_a, **_k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.agents.openai_news._post_json", fake_post)
    brief = await news_brief("VALE3", "days", {"eventos": [], "horizon_days": 5})
    assert brief is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_openai_news_brief_parses_mocked_responses(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_OPENAI_MAX_CALLS_PER_HOUR", "60")
    Cache.delete(news_cache_key("BTC", "days"))
    Cache.delete("atom:openai:costs")
    text = (
        '{"sentimento": 0.4, "riscos": ["CPI"], "eventos_proximos": [], '
        '"fontes": [{"titulo": "BLS", "url": "https://www.bls.gov/cpi/", "data": "2026-11-13"}]}'
    )

    async def fake_post(path, payload, **_k):
        assert path == "/responses"
        tools = {t["type"] for t in payload["tools"]}
        assert tools == {"web_search"}
        assert payload["model"] == "gpt-5-mini"
        return _responses_payload(text=text, citations=["https://www.bls.gov/cpi/"])

    monkeypatch.setattr("app.services.agents.openai_news._post_json", fake_post)
    brief = await news_brief("BTC", "days", {"eventos": [], "horizon_days": 5})
    assert brief is not None
    assert brief.sentimento == 0.4
    assert brief.fontes[0].url == "https://www.bls.gov/cpi/"
    costs = recent_costs()
    assert costs
    assert costs[0]["kind"] == "news"
    assert costs[0]["web_search_calls"] == 1
    assert costs[0]["estimated_usd"] > 0


@pytest.mark.asyncio
async def test_openai_provider_complete_mocked(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_OPENAI_MAX_CALLS_PER_HOUR", "60")

    async def fake_post(path, payload, **_k):
        assert path == "/responses"
        assert "tools" not in payload
        assert payload["model"] == "gpt-5-mini"
        return {
            "output_text": '{"objecoes":[],"severidade":"baixa","recomendacao":"manter"}',
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": '{"objecoes":[],"severidade":"baixa","recomendacao":"manter"}'}],
            }],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }

    monkeypatch.setattr("app.services.agents.openai_news._post_json", fake_post)
    text = await OpenAIProvider().complete("hi", system_prompt="json only")
    assert "manter" in text


def test_risk_provider_defaults_to_openai_when_key_present(monkeypatch):
    monkeypatch.delenv("ATOM_RISK_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OLLAMA_ENABLED", "0")
    llm = get_risk_llm()
    assert isinstance(llm, OpenAIProvider)


def test_risk_provider_openai_falls_back_to_ollama(monkeypatch):
    monkeypatch.setenv("ATOM_RISK_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OLLAMA_ENABLED", "0")
    assert get_risk_llm() is None


def _brief(score: float, url: str, titulo: str = "src") -> NewsBrief:
    return NewsBrief.model_validate({
        "eventos_proximos": [],
        "sentimento": score,
        "riscos": [],
        "fontes": [{"titulo": titulo, "url": url, "data": "2026-11-13"}],
    })


def test_merge_consensus_and_disagreement():
    xai = _brief(0.8, "https://x.com/a", "x")
    oai = _brief(0.6, "https://www.bls.gov/a", "bls")
    merged = merge_news_briefs(xai, oai)
    assert merged is not None
    assert merged.providers == ["xai", "openai"]
    assert merged.source_disagreement is False
    assert abs(merged.sentimento - 0.7) < 1e-9
    urls = {s.url for s in merged.fontes}
    assert "https://x.com/a" in urls
    assert "https://www.bls.gov/a" in urls

    clash = merge_news_briefs(_brief(0.8, "https://x.com/a"), _brief(-0.7, "https://www.bls.gov/a"))
    assert clash is not None
    assert clash.source_disagreement is True
    assert clash.sentimento == pytest.approx(0.05)
    assert merge_news_briefs(xai, None).providers == ["xai"]
    assert merge_news_briefs(None, oai).providers == ["openai"]
    assert merge_news_briefs(None, None) is None

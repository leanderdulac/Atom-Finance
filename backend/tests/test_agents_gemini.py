"""Gemini news agent: grounding citations mandatory; hourly cap; cache; no live calls."""
from __future__ import annotations

import pytest

from app.core.cache import Cache
from app.services.agents.cost_log import COST_KEY, recent_costs
from app.services.agents.gemini_news import (
    GeminiNewsProvider,
    allow_call,
    estimate_usd,
    extract_gemini_citations,
    gemini_api_key,
    gemini_configured,
    gemini_model,
    news_brief,
    news_cache_key,
)
from app.services.agents.news import merge_news_briefs, run_news_agent
from app.services.agents.schemas import NewsBrief


def _grounded_payload(*, text: str, urls: list[str]) -> dict:
    return {
        "text": text,
        "grounding_chunks": [{"web": {"uri": u, "title": "src"}} for u in urls],
        "web_search_queries": [f"news {u}" for u in urls[:1]],
        "usage": {"prompt_token_count": 800, "candidates_token_count": 120},
    }


def test_gemini_off_without_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    assert gemini_configured() is False


def test_gemini_prefers_gemini_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-first")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-fallback")
    assert gemini_api_key() == "gemini-first"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert gemini_api_key() == "google-fallback"
    assert gemini_configured() is True


def test_gemini_model_default_and_aliases(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert gemini_model() == "gemini-2.5-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    assert gemini_model() == "gemini-2.5-pro"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    assert gemini_model() == "gemini-3.1-pro-preview"
    monkeypatch.setenv("GEMINI_MODEL", "pro")
    assert gemini_model() == "gemini-2.5-pro"


def test_extract_gemini_citations_from_grounding():
    payload = _grounded_payload(text="{}", urls=["https://www.bcb.gov.br/copom", "https://www.google.com/news"])
    urls = extract_gemini_citations(payload)
    assert "https://www.bcb.gov.br/copom" in urls
    assert "https://www.google.com/news" in urls


def test_estimate_usd_positive():
    assert estimate_usd(input_tokens=1_000_000, output_tokens=0, search_calls=1) > 0


@pytest.mark.asyncio
async def test_gemini_news_brief_uses_cache_without_sdk(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    ticker, horizon = "PETR4", "weeks"
    key = news_cache_key(ticker, horizon)
    Cache.set(key, {
        "eventos_proximos": [],
        "sentimento": 0.2,
        "riscos": [],
        "fontes": [{"titulo": "BCB", "url": "https://www.bcb.gov.br/x", "data": "2026-11-01"}],
    }, ex=900)

    async def boom(*_a, **_k):
        raise AssertionError("cache hit must not call Gemini")

    monkeypatch.setattr("app.services.agents.gemini_news._generate", boom)
    brief = await news_brief(ticker, horizon, {"eventos": [], "horizon_days": 21, "asset_class": "equity_br"})
    assert brief is not None
    assert brief.fontes[0].url.startswith("https://www.bcb.gov.br")


@pytest.mark.asyncio
async def test_gemini_news_brief_hourly_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_GEMINI_MAX_CALLS_PER_HOUR", "1")
    monkeypatch.setattr("app.services.agents.gemini_news._hour_key", lambda: "atom:gemini:calls:test-cap")
    Cache.delete("atom:gemini:calls:test-cap")
    Cache.delete(news_cache_key("VALE3", "days"))
    assert allow_call() is True
    assert allow_call() is False
    called = {"n": 0}

    async def fake_gen(*_a, **_k):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.agents.gemini_news._generate", fake_gen)
    brief = await news_brief("VALE3", "days", {"eventos": [], "horizon_days": 5})
    assert brief is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_gemini_news_brief_parses_mocked_grounding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_GEMINI_MAX_CALLS_PER_HOUR", "60")
    Cache.delete(news_cache_key("PETR4", "days"))
    Cache.delete(COST_KEY)
    text = (
        '{"sentimento": 0.3, "riscos": ["Copom"], "eventos_proximos": [], '
        '"fontes": [{"titulo": "BCB", "url": "https://www.bcb.gov.br/copom", "data": "2026-11-13"}, '
        '{"titulo": "fake", "url": "https://evil.example/x", "data": ""}]}'
    )

    async def fake_gen(*, prompt, system, grounded, model):
        assert grounded is True
        assert model == "gemini-2.5-flash"
        assert "português" in prompt.lower() or "Brasil" in prompt
        return _grounded_payload(text=text, urls=["https://www.bcb.gov.br/copom"])

    monkeypatch.setattr("app.services.agents.gemini_news._generate", fake_gen)
    brief = await news_brief("PETR4", "days", {
        "eventos": [], "horizon_days": 5, "asset_class": "equity_br",
    })
    assert brief is not None
    assert brief.sentimento == 0.3
    urls = {s.url for s in brief.fontes}
    assert "https://www.bcb.gov.br/copom" in urls
    assert "https://evil.example/x" not in urls
    costs = recent_costs()
    assert costs
    assert costs[0]["provider"] == "gemini"
    assert costs[0]["estimate"] is True


@pytest.mark.asyncio
async def test_gemini_provider_complete_mocked(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ATOM_GEMINI_MAX_CALLS_PER_HOUR", "60")

    async def fake_gen(*, prompt, system, grounded, model):
        assert grounded is False
        return {"text": '{"objecoes":[],"severidade":"baixa","recomendacao":"manter"}', "usage": {}}

    monkeypatch.setattr("app.services.agents.gemini_news._generate", fake_gen)
    text = await GeminiNewsProvider().complete("hi", system_prompt="json only")
    assert "manter" in text


def _brief(score: float, url: str, titulo: str = "src") -> NewsBrief:
    return NewsBrief.model_validate({
        "eventos_proximos": [],
        "sentimento": score,
        "riscos": [],
        "fontes": [{"titulo": titulo, "url": url, "data": "2026-11-13"}],
    })


def test_three_way_consensus_and_dispersion():
    xai = _brief(0.6, "https://x.com/a")
    oai = _brief(0.5, "https://www.bls.gov/a")
    gem = _brief(0.7, "https://www.bcb.gov.br/a")
    merged = merge_news_briefs(xai, oai, gem)
    assert merged is not None
    assert merged.providers == ["xai", "openai", "gemini"]
    assert merged.source_disagreement is False
    assert merged.sentimento == pytest.approx(0.6)
    assert merged.gemini_sentimento == 0.7
    assert merged.dispersion < 0.35

    clash = merge_news_briefs(
        _brief(0.9, "https://x.com/a"),
        _brief(-0.8, "https://www.bls.gov/a"),
        _brief(0.1, "https://www.bcb.gov.br/a"),
    )
    assert clash is not None
    assert clash.source_disagreement is True
    assert clash.dispersion > 0

    only_gem = merge_news_briefs(None, None, gem)
    assert only_gem is not None
    assert only_gem.providers == ["gemini"]
    assert only_gem.source_disagreement is False

    # one failed source: remaining still vote
    two = merge_news_briefs(xai, None, gem)
    assert two is not None
    assert two.providers == ["xai", "gemini"]
    assert two.openai_sentimento is None


@pytest.mark.asyncio
async def test_run_news_agent_keeps_remaining_when_one_provider_fails(monkeypatch):
    monkeypatch.setattr("app.services.agents.news.xai_configured", lambda: True)
    monkeypatch.setattr("app.services.agents.news.openai_configured", lambda: True)
    monkeypatch.setattr("app.services.agents.news.gemini_configured", lambda: True)

    async def xai_ok(*_a, **_k):
        return _brief(0.4, "https://x.com/a")

    async def openai_boom(*_a, **_k):
        raise RuntimeError("openai down")

    async def gemini_ok(*_a, **_k):
        return _brief(0.6, "https://www.bcb.gov.br/a")

    monkeypatch.setattr("app.services.agents.news.xai_news_brief", xai_ok)
    monkeypatch.setattr("app.services.agents.news.openai_news_brief", openai_boom)
    monkeypatch.setattr("app.services.agents.news.gemini_news_brief", gemini_ok)
    monkeypatch.setattr(
        "app.services.context.gather.gather_context",
        lambda *_a, **_k: {"eventos": [], "fontes": []},
    )
    brief = await run_news_agent("PETR4", "days")
    assert brief is not None
    assert brief.providers == ["xai", "gemini"]
    assert brief.openai_sentimento is None
    assert brief.sentimento == pytest.approx(0.5)

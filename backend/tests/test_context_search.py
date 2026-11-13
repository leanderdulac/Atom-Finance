"""Search providers: env-gated, silent when unset, never invent hits."""
from __future__ import annotations

from app.services.context import search


def test_no_provider_returns_empty(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert search.search_news("PETR4") == []


def test_searxng_parses_results(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def fake_get(url, **kwargs):
        assert "/search" in url
        return {"results": [
            {"title": "Copom mantém juros", "url": "https://www.bcb.gov.br/noticia", "publishedDate": "2026-11-12"},
            {"title": "sem url", "url": ""},
        ]}

    monkeypatch.setattr("app.services.context.search.cached_get_json", fake_get)
    rows = search.search_news("PETR4")
    assert len(rows) == 1
    assert rows[0]["url"].startswith("https://")
    assert rows[0]["fonte"] == "searxng"


def test_brave_and_tavily_dedupe(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "y")
    url = "https://example.com/a"

    monkeypatch.setattr(
        "app.services.context.search.cached_get_json",
        lambda *a, **k: {"results": [{"title": "A", "url": url, "page_age": "1d"}]},
    )
    monkeypatch.setattr(
        "app.services.context.search.cached_post_json",
        lambda *a, **k: {"results": [{"title": "A de novo", "url": url}]},
    )
    rows = search.search_news("BTC")
    assert len(rows) == 1
    assert rows[0]["url"] == url

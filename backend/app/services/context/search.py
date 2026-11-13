"""Pluggable web/news search: SearXNG (default if URL set), Brave, Tavily.

No key and no URL → empty list. Never invent hits.
"""
from __future__ import annotations

import os
from typing import Any

from app.services.context.http import cached_get_json, cached_post_json


def _enabled(value: str | None) -> bool:
    return bool((value or "").strip())


def searxng_configured() -> bool:
    return _enabled(os.getenv("SEARXNG_URL"))


def brave_configured() -> bool:
    return _enabled(os.getenv("BRAVE_API_KEY"))


def tavily_configured() -> bool:
    return _enabled(os.getenv("TAVILY_API_KEY"))


def search_news(query: str, *, language: str = "pt-BR") -> list[dict[str, Any]]:
    """Fan out to every configured provider; de-dupe by URL."""
    rows: list[dict[str, Any]] = []
    if searxng_configured():
        rows.extend(_searxng(query, language))
    if brave_configured():
        rows.extend(_brave(query))
    if tavily_configured():
        rows.extend(_tavily(query))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(row)
    return unique[:12]


def _searxng(query: str, language: str) -> list[dict[str, Any]]:
    base = os.getenv("SEARXNG_URL", "").rstrip("/")
    payload = cached_get_json(
        f"{base}/search",
        params={
            "q": query,
            "format": "json",
            "categories": "news",
            "language": language.split("-")[0],
        },
        prefix="searxng",
        timeout=4.0,
    )
    if not isinstance(payload, dict):
        return []
    out = []
    for hit in payload.get("results") or []:
        url = hit.get("url") or hit.get("link")
        title = hit.get("title")
        if url and title:
            out.append({
                "titulo": str(title)[:200],
                "url": str(url),
                "data": str(hit.get("publishedDate") or hit.get("pubdate") or ""),
                "fonte": "searxng",
            })
    return out


def _brave(query: str) -> list[dict[str, Any]]:
    key = os.getenv("BRAVE_API_KEY", "").strip()
    payload = cached_get_json(
        "https://api.search.brave.com/res/v1/news/search",
        params={"q": query, "count": 8},
        headers={"Accept": "application/json", "X-Subscription-Token": key},
        prefix="brave",
        timeout=4.0,
    )
    if not isinstance(payload, dict):
        return []
    out = []
    for hit in (payload.get("results") or []):
        url = hit.get("url")
        title = hit.get("title")
        if url and title:
            out.append({
                "titulo": str(title)[:200],
                "url": str(url),
                "data": str(hit.get("page_age") or hit.get("age") or ""),
                "fonte": "brave",
            })
    return out


def _tavily(query: str) -> list[dict[str, Any]]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    payload = cached_post_json(
        "https://api.tavily.com/search",
        json_body={"api_key": key, "query": query, "topic": "news", "max_results": 8},
        prefix="tavily",
        timeout=4.0,
    )
    if not isinstance(payload, dict):
        return []
    out = []
    for hit in payload.get("results") or []:
        url = hit.get("url")
        title = hit.get("title")
        if url and title:
            out.append({
                "titulo": str(title)[:200],
                "url": str(url),
                "data": str(hit.get("published_date") or ""),
                "fonte": "tavily",
            })
    return out

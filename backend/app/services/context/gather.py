"""Deterministic context gather. Empty sources → no context. Never invent."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.cache import Cache
from app.services.context import calendar, crypto, rss, search

logger = logging.getLogger(__name__)

HORIZON_DAYS = {"days": 5, "weeks": 21, "months": 63}


def gather_context(ticker: str, horizon: str, *, asset_class: str = "equity_br") -> dict[str, Any]:
    cache_key = f"ctx:bundle:{ticker}:{horizon}:{asset_class}"
    hit = Cache.get(cache_key)
    if isinstance(hit, dict) and "fontes" in hit:
        return hit

    days = HORIZON_DAYS.get(horizon, 21)
    query = f"{ticker} mercado OR ações OR crypto"
    news = search.search_news(query)
    feeds = rss.fetch_rss(ticker, asset_class=asset_class)
    events = calendar.upcoming_events(horizon_days=days)
    pos = crypto.positioning(ticker) if asset_class == "crypto" else None

    fontes: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in news + feeds:
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        fontes.append({
            "titulo": str(row.get("titulo") or url)[:200],
            "url": url,
            "data": str(row.get("data") or "")[:40],
        })
    for event in events:
        url = str(event.get("url") or "")
        if url and url not in seen:
            seen.add(url)
            fontes.append({
                "titulo": str(event.get("nome") or "macro"),
                "url": url,
                "data": str(event.get("data") or ""),
            })
    if pos:
        for row in pos.get("fontes") or []:
            url = str(row.get("url") or "")
            if url and url not in seen:
                seen.add(url)
                fontes.append({
                    "titulo": str(row.get("titulo") or url),
                    "url": url,
                    "data": str(row.get("data") or datetime.now(UTC).date().isoformat()),
                })

    bundle = {
        "ticker": ticker,
        "horizon": horizon,
        "horizon_days": days,
        "collected_at": datetime.now(UTC).isoformat(),
        "news": news,
        "rss": feeds,
        "eventos": events,
        "crypto": pos,
        "fontes": fontes,
    }
    Cache.set(cache_key, bundle, ex=300)
    return bundle

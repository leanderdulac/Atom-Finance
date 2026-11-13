"""Optional live OpenAI check. Skipped without OPENAI_API_KEY / ATOM_OPENAI_LIVE=1."""
from __future__ import annotations

import os

import pytest

from app.services.agents.openai_news import news_brief, openai_configured

pytestmark = pytest.mark.openai


@pytest.mark.asyncio
async def test_live_openai_search_returns_citation_urls():
    live = os.getenv("ATOM_OPENAI_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not live or not openai_configured():
        pytest.skip("teste pago: ATOM_OPENAI_LIVE=1 e OPENAI_API_KEY no ambiente (não commitar a chave)")
    brief = await news_brief(
        "PETR4",
        "days",
        {"eventos": [], "horizon_days": 5, "fontes": [], "crypto": None},
    )
    assert brief is not None, "OpenAI devolveu brief vazio ou sem citações"
    assert brief.fontes, "citações/URLs são obrigatórias"
    assert all(s.url.startswith("http") for s in brief.fontes)

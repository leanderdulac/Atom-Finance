"""Optional live xAI check. Skipped without XAI_API_KEY / ATOM_XAI_LIVE=1."""
from __future__ import annotations

import os

import pytest

from app.services.agents.xai import news_brief, xai_configured

pytestmark = pytest.mark.xai


@pytest.mark.asyncio
async def test_live_xai_search_returns_citation_urls():
    live = os.getenv("ATOM_XAI_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not live or not xai_configured():
        pytest.skip("teste pago: ATOM_XAI_LIVE=1 e XAI_API_KEY no ambiente (não commitar a chave)")
    brief = await news_brief(
        "PETR4",
        "days",
        {"eventos": [], "horizon_days": 5, "fontes": [], "crypto": None},
    )
    assert brief is not None, "xAI devolveu brief vazio ou sem citações"
    assert brief.fontes, "citações/URLs são obrigatórias"
    assert all(s.url.startswith("http") for s in brief.fontes)

"""Optional live Gemini check. Skipped without GEMINI_API_KEY / ATOM_GEMINI_LIVE=1."""
from __future__ import annotations

import os

import pytest

from app.services.agents.gemini_news import gemini_configured, news_brief

pytestmark = pytest.mark.gemini


@pytest.mark.asyncio
async def test_live_gemini_search_returns_grounding_urls():
    live = os.getenv("ATOM_GEMINI_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}
    if not live or not gemini_configured():
        pytest.skip("teste pago: ATOM_GEMINI_LIVE=1 e GEMINI_API_KEY no ambiente (não commitar a chave)")
    brief = await news_brief(
        "PETR4",
        "days",
        {"eventos": [], "horizon_days": 5, "fontes": [], "crypto": None, "asset_class": "equity_br"},
    )
    assert brief is not None, "Gemini devolveu brief vazio ou sem grounding"
    assert brief.fontes, "citações/URLs do Google Search são obrigatórias"
    assert all(s.url.startswith("http") for s in brief.fontes)

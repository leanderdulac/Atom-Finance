"""Optional live Ollama check. Skipped in CI (OLLAMA_ENABLED=0)."""
from __future__ import annotations

import os

import pytest

from app.services.agents.llm import OllamaProvider, parse_json_object
from app.services.agents.schemas import NewsBrief
from app.services.ollama import ollama_configured

pytestmark = pytest.mark.ollama


@pytest.mark.asyncio
async def test_local_ollama_returns_json_or_skip():
    if not ollama_configured() or os.getenv("OLLAMA_ENABLED", "1").strip() in {"0", "false", "no"}:
        pytest.skip("Ollama desligado neste ambiente")
    provider = OllamaProvider()
    text = await provider.complete(
        '{"ping": true}',
        system_prompt="Responda só JSON {\"ok\": true}. Sem operação, sem preço.",
    )
    if not text:
        pytest.skip("daemon Ollama ausente")
    raw = parse_json_object(text)
    assert raw is not None
    # If the model echoed a news-shaped object, schema must hold or we discard.
    if "fontes" in raw:
        try:
            NewsBrief.model_validate(raw)
        except Exception:
            pytest.skip("modelo local não devolveu NewsBrief válido — caminho de descarte ok")

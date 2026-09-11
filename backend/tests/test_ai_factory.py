import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import ai_factory
from app.core.ai_factory import GeminiProvider, LLMException


def _make_provider(mock_client):
    with patch.object(ai_factory.genai, "Client", return_value=mock_client):
        return GeminiProvider(api_key="test-key")


def test_gemini_provider_initializes_genai_client_with_api_key():
    mock_client = MagicMock()
    with patch.object(ai_factory.genai, "Client", return_value=mock_client) as client_cls:
        GeminiProvider(api_key="my-key")
    client_cls.assert_called_once_with(api_key="my-key")


def test_gemini_provider_complete_returns_response_text():
    mock_response = MagicMock(text="Gemini says hi")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider = _make_provider(mock_client)

    result = asyncio.run(provider.complete("Hello", system_prompt="Be nice"))

    assert result == "Gemini says hi"
    mock_client.aio.models.generate_content.assert_awaited_once_with(
        model=provider.model,
        contents="Be nice\n\nHello",
    )


def test_gemini_provider_complete_without_system_prompt_uses_raw_prompt():
    mock_response = MagicMock(text="ok")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider = _make_provider(mock_client)

    asyncio.run(provider.complete("Just the prompt"))

    mock_client.aio.models.generate_content.assert_awaited_once_with(
        model=provider.model,
        contents="Just the prompt",
    )


def test_gemini_provider_wraps_errors_as_llm_exception():
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("boom"))
    provider = _make_provider(mock_client)

    with pytest.raises(LLMException):
        asyncio.run(provider.complete("Hello"))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import ai_factory
from app.core.ai_factory import (
    CreditException,
    GeminiProvider,
    GrokProvider,
    LLMException,
    PerplexityProvider,
    QuotaException,
)


def _make_openai_provider(cls, mock_client):
    with patch.object(ai_factory.openai, "AsyncOpenAI", return_value=mock_client):
        return cls(api_key="test-key")


def _openai_client_raising(side_effect):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    return client


@pytest.mark.parametrize("provider_cls", [GrokProvider, PerplexityProvider])
def test_openai_compatible_providers_wrap_errors_as_llm_exception(provider_cls):
    """Grok/Perplexity must raise instead of returning an error string: a swallowed
    failure would be presented as a valid completion and silently break the
    generate_robust_complete() fallback chain."""
    mock_client = _openai_client_raising(RuntimeError("connection refused"))
    provider = _make_openai_provider(provider_cls, mock_client)

    with pytest.raises(LLMException):
        asyncio.run(provider.complete("Hello"))


@pytest.mark.parametrize("provider_cls", [GrokProvider, PerplexityProvider])
def test_openai_compatible_providers_map_quota_errors(provider_cls):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("insufficient_quota: rate_limit exceeded"))
    provider = _make_openai_provider(provider_cls, client)

    with pytest.raises(QuotaException):
        asyncio.run(provider.complete("Hello"))


@pytest.mark.parametrize("provider_cls", [GrokProvider, PerplexityProvider])
def test_openai_compatible_providers_map_credit_errors(provider_cls):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("insufficient_balance in account"))
    provider = _make_openai_provider(provider_cls, client)

    with pytest.raises(CreditException):
        asyncio.run(provider.complete("Hello"))


@pytest.mark.parametrize("provider_cls", [GrokProvider, PerplexityProvider])
def test_openai_compatible_fallback_chain_continues_past_dead_provider(provider_cls):
    """A dead provider in the default order must not stop generate_robust_complete()
    from reaching the next configured provider."""
    mock_client = _openai_client_raising(RuntimeError("boom"))
    factory = ai_factory.AIFactory()
    dead = _make_openai_provider(provider_cls, mock_client)
    healthy = MagicMock()
    healthy.complete = AsyncMock(return_value="fallback answer")

    with patch.object(factory, "get_provider", side_effect=lambda name: healthy if name == "gpt" else dead):
        result = asyncio.run(
            factory.generate_robust_complete("Hello", preferred_order=["grok", "gpt"])
        )

    assert result == "fallback answer"


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
    contents = mock_client.aio.models.generate_content.await_args.kwargs["contents"]
    assert contents.endswith("Hello")
    assert "Be nice" in contents
    assert "mesa de pesquisa ATOM" in contents


def test_gemini_provider_complete_without_system_prompt_still_loads_doctrine():
    mock_response = MagicMock(text="ok")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    provider = _make_provider(mock_client)

    asyncio.run(provider.complete("Just the prompt"))

    contents = mock_client.aio.models.generate_content.await_args.kwargs["contents"]
    assert contents.endswith("Just the prompt")
    assert "eligible_for_live_trading" in contents


def test_gemini_provider_wraps_errors_as_llm_exception():
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("boom"))
    provider = _make_provider(mock_client)

    with pytest.raises(LLMException):
        asyncio.run(provider.complete("Hello"))

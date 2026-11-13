"""Agent LLM: Ollama is the default. Cloud stubs stay off unless ATOM_AGENT_LLM + key."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.core.ai_factory import LLMException, LLMProvider
from app.core.quant_doctrine import compose_system
from app.services.ollama import ollama_configured

logger = logging.getLogger(__name__)

CLOUD_KEYS = {
    "grok": ("XAI_API_KEY", "grok"),
    "xai": ("XAI_API_KEY", "grok"),
    "anthropic": ("ANTHROPIC_API_KEY", "claude"),
    "claude": ("ANTHROPIC_API_KEY", "claude"),
    "openai": ("OPENAI_API_KEY", "gpt"),
    "gpt": ("OPENAI_API_KEY", "gpt"),
    "perplexity": ("PERPLEXITY_API_KEY", "perplexity"),
}


class OllamaProvider(LLMProvider):
    """Local Ollama. Used by news/risk agents. Never decides prices or size."""

    def __init__(self) -> None:
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_AGENT_MODEL") or os.getenv("OLLAMA_MODEL") or "gpt-oss:20b"
        self.timeout = float(os.getenv("ATOM_AGENT_TIMEOUT", "25"))

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        payload = {
            "model": kwargs.get("model") or self.model,
            "stream": False,
            "format": kwargs.get("format", "json"),
            "messages": [
                {"role": "system", "content": compose_system(system_prompt)},
                {"role": "user", "content": prompt},
            ],
        }
        text = await self._post(payload)
        return text or ""

    async def chat_with_tools(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        dispatch: dict[str, Any],
        max_rounds: int = 3,
    ) -> str | None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": compose_system(system_prompt)},
            {"role": "user", "content": user_prompt},
        ]
        for round_i in range(max_rounds):
            payload: dict[str, Any] = {
                "model": self.model,
                "stream": False,
                "messages": messages,
                "tools": tools,
            }
            if round_i == max_rounds - 1:
                payload["format"] = "json"
                payload.pop("tools", None)
            body = await self._post_raw(payload)
            if body is None:
                return None
            message = body.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()
            if tool_calls:
                messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "")
                    raw_args = fn.get("arguments") or {}
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            raw_args = {}
                    handler = dispatch.get(name)
                    result = handler(**raw_args) if callable(handler) else {"error": "tool unknown"}
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result, default=str)[:8000],
                    })
                continue
            if content:
                return content
        return None

    async def _post(self, payload: dict[str, Any]) -> str | None:
        body = await self._post_raw(payload)
        if not body:
            return None
        message = body.get("message") or {}
        text = (message.get("content") or "").strip()
        return text or None

    async def _post_raw(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.host}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.info("Ollama agent call failed (%s)", type(exc).__name__)
            return None
        return data if isinstance(data, dict) else None


class DisabledCloudProvider(LLMProvider):
    """Named stub. Raises unless ATOM_AGENT_LLM matches and the API key is set."""

    def __init__(self, name: str, env_key: str) -> None:
        self.name = name
        self.env_key = env_key

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        raise LLMException(
            f"{self.name} desligado. Defina {self.env_key} e ATOM_AGENT_LLM={self.name} "
            "para ligar; o padrão é Ollama local."
        )


def agent_llm_kind() -> str:
    return (os.getenv("ATOM_AGENT_LLM") or "ollama").strip().lower() or "ollama"


def get_agent_llm() -> LLMProvider | None:
    """Ollama unless ATOM_AGENT_LLM names a cloud provider that has a key.

    No key → None (deterministic path). Never calls a paid API by accident.
    """
    kind = agent_llm_kind()
    if kind in {"ollama", "local", ""}:
        if ollama_configured():
            return OllamaProvider()
        return None
    mapping = CLOUD_KEYS.get(kind)
    if not mapping:
        logger.info("ATOM_AGENT_LLM=%s unknown — no agent LLM", kind)
        return None
    env_key, factory_name = mapping
    if not (os.getenv(env_key) or "").strip():
        logger.info("%s requested but %s empty — cloud agent off", kind, env_key)
        return None
    from app.core.ai_factory import AIFactory
    inner = AIFactory().get_provider(factory_name)
    return inner


def parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None

"""OpenAI Responses API for web/news search — second thermometer source.

POST https://api.openai.com/v1/responses with the hosted `web_search` tool.
Citations are mandatory: URLs the model typed that did not come back on the
response are dropped. No key → no call. Hourly cap + 15 min Redis cache.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.ai_factory import LLMException, LLMProvider
from app.core.cache import Cache
from app.core.quant_doctrine import compose_system
from app.services.agents.cost_log import log_cost
from app.services.agents.llm import parse_json_object
from app.services.agents.schemas import NewsBrief
from app.services.agents.xai import brief_from_xai as brief_from_citations
from app.services.agents.xai import extract_citations, extract_output_text

logger = logging.getLogger(__name__)

OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5-mini"
CACHE_TTL_DEFAULT = 900
CALLS_PER_HOUR_DEFAULT = 60
# Published list prices change; these are estimates labelled as such in the diary.
USD_PER_MTOK_IN = 0.25
USD_PER_MTOK_OUT = 2.00
USD_PER_WEB_SEARCH = 0.01


def openai_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("ATOM_OPENAI_CACHE_TTL", str(CACHE_TTL_DEFAULT))))
    except ValueError:
        return CACHE_TTL_DEFAULT


def max_calls_per_hour() -> int:
    try:
        return max(1, int(os.getenv("ATOM_OPENAI_MAX_CALLS_PER_HOUR", str(CALLS_PER_HOUR_DEFAULT))))
    except ValueError:
        return CALLS_PER_HOUR_DEFAULT


def _hour_key() -> str:
    return f"atom:openai:calls:{datetime.now(UTC).strftime('%Y%m%d%H')}"


def allow_call() -> bool:
    """Hourly cap. Cache hits must not call this."""
    limit = max_calls_per_hour()
    key = _hour_key()
    used = Cache.get(key)
    n = int(used or 0)
    if n >= limit:
        logger.info("OpenAI hourly cap reached (%s/%s)", n, limit)
        return False
    Cache.set(key, n + 1, ex=3700)
    return True


def news_cache_key(ticker: str, horizon: str) -> str:
    return f"ctx:openai:news:{ticker.upper()}:{horizon}"


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def estimate_usd(*, input_tokens: int, output_tokens: int, web_search_calls: int) -> float:
    inn = _float_env("ATOM_OPENAI_USD_PER_MTOK_IN", USD_PER_MTOK_IN)
    out = _float_env("ATOM_OPENAI_USD_PER_MTOK_OUT", USD_PER_MTOK_OUT)
    search = _float_env("ATOM_OPENAI_USD_PER_SEARCH", USD_PER_WEB_SEARCH)
    usd = (
        (max(input_tokens, 0) / 1_000_000.0) * inn
        + (max(output_tokens, 0) / 1_000_000.0) * out
        + max(web_search_calls, 0) * search
    )
    return round(usd, 6)


def _usage_tokens(payload: dict[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0
    inn = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    try:
        return int(inn), int(out)
    except (TypeError, ValueError):
        return 0, 0


def _web_search_calls(payload: dict[str, Any]) -> int:
    n = 0
    for item in payload.get("output") or []:
        if isinstance(item, dict) and str(item.get("type") or "").startswith("web_search"):
            n += 1
    return n


def _record_call_cost(payload: dict[str, Any], *, kind: str, ticker: str | None = None) -> dict[str, Any]:
    inn, out = _usage_tokens(payload)
    searches = _web_search_calls(payload)
    usd = estimate_usd(input_tokens=inn, output_tokens=out, web_search_calls=searches)
    return log_cost({
        "provider": "openai",
        "kind": kind,
        "model": openai_model(),
        "input_tokens": inn,
        "output_tokens": out,
        "web_search_calls": searches,
        "estimated_usd": usd,
        "ticker": ticker,
    })


class OpenAIProvider(LLMProvider):
    """Responses API complete() — used by the devil's-advocate risk agent."""

    def __init__(self) -> None:
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = openai_model()
        self.timeout = float(os.getenv("ATOM_OPENAI_TIMEOUT", os.getenv("ATOM_AGENT_TIMEOUT", "45")))

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            raise LLMException("OPENAI_API_KEY ausente — OpenAI desligado")
        if not allow_call():
            raise LLMException("OpenAI acima do ATOM_OPENAI_MAX_CALLS_PER_HOUR")
        payload = {
            "model": kwargs.get("model") or self.model,
            "instructions": compose_system(system_prompt),
            "input": [{"role": "user", "content": prompt}],
            "store": False,
        }
        data = await _post_json("/responses", payload, timeout=self.timeout)
        if not data:
            raise LLMException("OpenAI Responses sem resposta")
        _record_call_cost(data, kind="risk")
        text = extract_output_text(data)
        if not text:
            raise LLMException("OpenAI Responses vazio")
        return text


_NEWS_INSTRUCTIONS = (
    "Agente de notícias/macro ATOM. Use web_search (notícias e web). "
    "Devolva SOMENTE JSON: {eventos_proximos:[{nome,data,tipo,impacto}], "
    "sentimento: number -1..1, riscos:[], fontes:[{titulo,url,data}]}. "
    "Cada fontes.url TEM de ser uma URL que a ferramenta devolveu. "
    "Sem URL = não afirme. Não invente preço, stop, alvo, direção nem tamanho. "
    "Não recomende operação. Paper/simulação apenas."
)


async def news_brief(
    ticker: str,
    horizon: str,
    bundle: dict[str, Any],
) -> NewsBrief | None:
    if not openai_configured():
        return None
    key = news_cache_key(ticker, horizon)
    hit = Cache.get(key)
    if isinstance(hit, dict):
        try:
            cached = NewsBrief.model_validate(hit)
        except ValidationError:
            cached = None
        if cached and cached.fontes:
            return cached
    if not allow_call():
        return None

    days = int(bundle.get("horizon_days") or 21)
    user = (
        f"Ativo={ticker} horizonte={horizon} (~{days} dias). "
        f"Notícias e web recentes que afetam o cenário paper. "
        f"Calendário já conhecido: {bundle.get('eventos') or []}"
    )
    payload = {
        "model": openai_model(),
        "instructions": compose_system(_NEWS_INSTRUCTIONS),
        "input": [{"role": "user", "content": user}],
        "tools": [{"type": "web_search"}],
        "store": False,
    }
    timeout = float(os.getenv("ATOM_OPENAI_TIMEOUT", "45"))
    data = await _post_json("/responses", payload, timeout=timeout)
    if not data:
        return None
    _record_call_cost(data, kind="news", ticker=ticker)
    text = extract_output_text(data)
    citations = extract_citations(data, text)
    brief = brief_from_citations(parse_json_object(text), citations, bundle=bundle)
    if brief:
        Cache.set(key, brief.model_dump(), ex=cache_ttl())
    else:
        logger.info("OpenAI news discarded (sem citações/URLs válidas)")
    return brief


async def _post_json(path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    url = f"{OPENAI_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.info("OpenAI %s failed (%s)", path, type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None

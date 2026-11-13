"""Gemini v1beta (google-genai) with Google Search grounding — third thermometer.

Citations come from grounding_metadata.grounding_chunks. URLs the model typed
that did not come back as grounding are dropped. No key → no call.
Hourly cap + 15 min Redis cache. GEMINI_API_KEY preferred; GOOGLE_API_KEY works.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.ai_factory import LLMException, LLMProvider
from app.core.cache import Cache
from app.core.quant_doctrine import compose_system
from app.services.agents.cost_log import log_cost, recent_costs
from app.services.agents.llm import parse_json_object
from app.services.agents.schemas import NewsBrief
from app.services.agents.xai import brief_from_xai as brief_from_citations

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
CACHE_TTL_DEFAULT = 900
CALLS_PER_HOUR_DEFAULT = 60
USD_PER_MTOK_IN = 0.15
USD_PER_MTOK_OUT = 0.60
USD_PER_SEARCH = 0.014

__all__ = [
    "GeminiNewsProvider",
    "allow_call",
    "estimate_usd",
    "extract_gemini_citations",
    "gemini_api_key",
    "gemini_configured",
    "gemini_model",
    "log_cost",
    "news_brief",
    "news_cache_key",
    "recent_costs",
]


def gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def gemini_configured() -> bool:
    return bool(gemini_api_key())


def gemini_model() -> str:
    raw = (os.getenv("GEMINI_MODEL") or DEFAULT_MODEL).strip()
    aliases = {
        "flash": DEFAULT_MODEL,
        "pro": "gemini-2.5-pro",
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
        "3.1": "gemini-3.1-pro-preview",
        "preview": "gemini-3.1-pro-preview",
    }
    return aliases.get(raw, raw) or DEFAULT_MODEL


def cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("ATOM_GEMINI_CACHE_TTL", str(CACHE_TTL_DEFAULT))))
    except ValueError:
        return CACHE_TTL_DEFAULT


def max_calls_per_hour() -> int:
    try:
        return max(1, int(os.getenv("ATOM_GEMINI_MAX_CALLS_PER_HOUR", str(CALLS_PER_HOUR_DEFAULT))))
    except ValueError:
        return CALLS_PER_HOUR_DEFAULT


def _hour_key() -> str:
    return f"atom:gemini:calls:{datetime.now(UTC).strftime('%Y%m%d%H')}"


def allow_call() -> bool:
    limit = max_calls_per_hour()
    key = _hour_key()
    used = Cache.get(key)
    n = int(used or 0)
    if n >= limit:
        logger.info("Gemini hourly cap reached (%s/%s)", n, limit)
        return False
    Cache.set(key, n + 1, ex=3700)
    return True


def news_cache_key(ticker: str, horizon: str) -> str:
    return f"ctx:gemini:news:{ticker.upper()}:{horizon}"


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def estimate_usd(*, input_tokens: int, output_tokens: int, search_calls: int) -> float:
    inn = _float_env("ATOM_GEMINI_USD_PER_MTOK_IN", USD_PER_MTOK_IN)
    out = _float_env("ATOM_GEMINI_USD_PER_MTOK_OUT", USD_PER_MTOK_OUT)
    search = _float_env("ATOM_GEMINI_USD_PER_SEARCH", USD_PER_SEARCH)
    usd = (
        (max(input_tokens, 0) / 1_000_000.0) * inn
        + (max(output_tokens, 0) / 1_000_000.0) * out
        + max(search_calls, 0) * search
    )
    return round(usd, 6)


def extract_gemini_citations(payload: dict[str, Any], text: str = "") -> list[str]:
    """URLs from Google Search grounding — never the model's free-typed fontes."""
    urls: list[str] = []
    for chunk in payload.get("grounding_chunks") or []:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") if isinstance(chunk.get("web"), dict) else chunk
        urls.append(str((web or {}).get("uri") or (web or {}).get("url") or ""))
    for item in payload.get("citations") or []:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            urls.append(str(item.get("uri") or item.get("url") or ""))
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        url = url.strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(url)
    _ = text
    return out


def _record_call_cost(payload: dict[str, Any], *, kind: str, ticker: str | None = None) -> dict[str, Any]:
    usage = payload.get("usage") or {}
    inn = int(usage.get("prompt_token_count") or usage.get("input_tokens") or 0)
    out = int(usage.get("candidates_token_count") or usage.get("output_tokens") or 0)
    searches = 1 if payload.get("grounding_chunks") or payload.get("web_search_queries") else 0
    usd = estimate_usd(input_tokens=inn, output_tokens=out, search_calls=searches)
    return log_cost({
        "provider": "gemini",
        "kind": kind,
        "model": gemini_model(),
        "input_tokens": inn,
        "output_tokens": out,
        "web_search_calls": searches,
        "estimated_usd": usd,
        "ticker": ticker,
    })


class GeminiNewsProvider(LLMProvider):
    """generate_content without search — optional ATOM_AGENT_LLM=gemini path."""

    def __init__(self) -> None:
        self.api_key = gemini_api_key()
        self.model = gemini_model()

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            raise LLMException("GEMINI_API_KEY ausente — Gemini desligado")
        if not allow_call():
            raise LLMException("Gemini acima do ATOM_GEMINI_MAX_CALLS_PER_HOUR")
        data = await _generate(
            prompt=prompt,
            system=compose_system(system_prompt),
            grounded=False,
            model=str(kwargs.get("model") or self.model),
        )
        if not data:
            raise LLMException("Gemini sem resposta")
        _record_call_cost(data, kind="complete")
        text = str(data.get("text") or "").strip()
        if not text:
            raise LLMException("Gemini vazio")
        return text


_NEWS_INSTRUCTIONS = (
    "Agente de notícias/macro ATOM. Use Google Search / Google News. "
    "Devolva SOMENTE JSON: {eventos_proximos:[{nome,data,tipo,impacto}], "
    "sentimento: number -1..1, riscos:[], fontes:[{titulo,url,data}]}. "
    "Cada fontes.url TEM de ser uma URL devolvida pelo grounding. "
    "Sem URL = não afirme. Não invente preço, stop, alvo, direção nem tamanho. "
    "Não recomende operação. Paper/simulação apenas."
)


def _user_prompt(ticker: str, horizon: str, bundle: dict[str, Any]) -> str:
    days = int(bundle.get("horizon_days") or 21)
    asset_class = str(bundle.get("asset_class") or "")
    locale = (
        "Priorize Google News em português do Brasil e fontes B3/CVM/BCB/Valor/Estadão."
        if asset_class == "equity_br" or (ticker[:4].isalpha() and ticker[-1:].isdigit())
        else "Priorize Google News e Google Search (EN/pt) relevantes ao ativo."
    )
    return (
        f"Ativo={ticker} horizonte={horizon} (~{days} dias). {locale} "
        f"Notícias recentes que afetam o cenário paper. "
        f"Calendário já conhecido: {bundle.get('eventos') or []}"
    )


async def news_brief(
    ticker: str,
    horizon: str,
    bundle: dict[str, Any],
) -> NewsBrief | None:
    if not gemini_configured():
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
    data = await _generate(
        prompt=_user_prompt(ticker, horizon, bundle),
        system=compose_system(_NEWS_INSTRUCTIONS),
        grounded=True,
        model=gemini_model(),
    )
    if not data:
        return None
    _record_call_cost(data, kind="news", ticker=ticker)
    text = str(data.get("text") or "")
    citations = extract_gemini_citations(data, text)
    brief = brief_from_citations(parse_json_object(text), citations, bundle=bundle)
    if brief:
        Cache.set(key, brief.model_dump(), ex=cache_ttl())
    else:
        logger.info("Gemini news discarded (sem grounding/URLs válidas)")
    return brief


def _chunks_from_response(response: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return chunks
    meta = getattr(candidates[0], "grounding_metadata", None)
    if meta is None:
        return chunks
    for chunk in getattr(meta, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        uri = getattr(web, "uri", None) if web is not None else None
        title = getattr(web, "title", None) if web is not None else None
        if uri:
            chunks.append({"web": {"uri": uri, "title": title or ""}})
    return chunks


def _queries_from_response(response: Any) -> list[str]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []
    meta = getattr(candidates[0], "grounding_metadata", None)
    if meta is None:
        return []
    return [str(q) for q in (getattr(meta, "web_search_queries", None) or [])]


async def _generate(
    *,
    prompt: str,
    system: str,
    grounded: bool,
    model: str,
) -> dict[str, Any] | None:
    key = gemini_api_key()
    if not key:
        return None
    timeout = float(os.getenv("ATOM_GEMINI_TIMEOUT", os.getenv("ATOM_AGENT_TIMEOUT", "45")))
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        logger.info("google-genai unavailable (%s)", type(exc).__name__)
        return None
    tools = [types.Tool(google_search=types.GoogleSearch())] if grounded else None
    try:
        client = genai.Client(api_key=key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=tools,
                http_options=types.HttpOptions(timeout=int(timeout * 1000)),
            ),
        )
    except Exception as exc:
        logger.info("Gemini generate failed (%s)", type(exc).__name__)
        return None
    usage = getattr(response, "usage_metadata", None)
    return {
        "text": getattr(response, "text", None) or "",
        "grounding_chunks": _chunks_from_response(response),
        "web_search_queries": _queries_from_response(response),
        "usage": {
            "prompt_token_count": getattr(usage, "prompt_token_count", 0) or 0,
            "candidates_token_count": getattr(usage, "candidates_token_count", 0) or 0,
        },
    }

"""xAI Grok for news search+summary. OpenAI-compatible API + Agent Tools.

POST https://api.x.ai/v1/responses with server-side `web_search` and `x_search`
(docs: https://docs.x.ai/developers/tools/overview). Citations are mandatory:
URLs that did not come back on the response are dropped. No key → no call.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.core.ai_factory import LLMException, LLMProvider
from app.core.cache import Cache
from app.core.quant_doctrine import compose_system
from app.services.agents.llm import parse_json_object
from app.services.agents.schemas import EventoProximo, NewsBrief, SourceRef

logger = logging.getLogger(__name__)

XAI_BASE = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.3"
REASONING_MODEL = "grok-4.20-0309-reasoning"
CACHE_TTL_DEFAULT = 900
CALLS_PER_HOUR_DEFAULT = 60
_INLINE_CITE = re.compile(r"\[\[\d+\]\]\((https?://[^)\s]+)\)")


def xai_configured() -> bool:
    return bool((os.getenv("XAI_API_KEY") or "").strip())


def xai_model() -> str:
    raw = (os.getenv("XAI_MODEL") or DEFAULT_MODEL).strip()
    if raw in {"reasoning", "grok-reasoning", REASONING_MODEL}:
        return REASONING_MODEL
    return raw or DEFAULT_MODEL


def cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("ATOM_XAI_CACHE_TTL", str(CACHE_TTL_DEFAULT))))
    except ValueError:
        return CACHE_TTL_DEFAULT


def max_calls_per_hour() -> int:
    try:
        return max(1, int(os.getenv("ATOM_XAI_MAX_CALLS_PER_HOUR", str(CALLS_PER_HOUR_DEFAULT))))
    except ValueError:
        return CALLS_PER_HOUR_DEFAULT


def _hour_key() -> str:
    return f"atom:xai:calls:{datetime.now(UTC).strftime('%Y%m%d%H')}"


def allow_call() -> bool:
    """Hourly cap. Cache hits must not call this."""
    limit = max_calls_per_hour()
    key = _hour_key()
    used = Cache.get(key)
    n = int(used or 0)
    if n >= limit:
        logger.info("xAI hourly cap reached (%s/%s)", n, limit)
        return False
    Cache.set(key, n + 1, ex=3700)
    return True


def calls_used_this_hour() -> int:
    try:
        return int(Cache.get(_hour_key()) or 0)
    except (TypeError, ValueError):
        return 0


def news_cache_key(ticker: str, horizon: str) -> str:
    return f"ctx:xai:news:{ticker.upper()}:{horizon}"


class XAIProvider(LLMProvider):
    """Chat Completions at https://api.x.ai/v1 — no search tools (risk agent)."""

    def __init__(self) -> None:
        self.api_key = (os.getenv("XAI_API_KEY") or "").strip()
        self.model = xai_model()
        self.timeout = float(os.getenv("ATOM_XAI_TIMEOUT", os.getenv("ATOM_AGENT_TIMEOUT", "45")))

    async def complete(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            raise LLMException("XAI_API_KEY ausente — xAI desligado")
        if not allow_call():
            raise LLMException("xAI acima do ATOM_XAI_MAX_CALLS_PER_HOUR")
        payload = {
            "model": kwargs.get("model") or self.model,
            "messages": [
                {"role": "system", "content": compose_system(system_prompt)},
                {"role": "user", "content": prompt},
            ],
        }
        data = await _post_json("/chat/completions", payload, timeout=self.timeout)
        if not data:
            raise LLMException("xAI chat sem resposta")
        choices = data.get("choices") or []
        if not choices:
            raise LLMException("xAI chat sem choices")
        message = (choices[0] or {}).get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise LLMException("xAI chat vazio")
        return text


def extract_citations(payload: dict[str, Any], text: str = "") -> list[str]:
    """URLs the API actually returned — never the model's free-typed fontes."""
    urls: list[str] = []
    raw = payload.get("citations") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                urls.append(str(item.get("url") or ""))
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            for ann in content.get("annotations") or []:
                if isinstance(ann, dict):
                    urls.append(str(ann.get("url") or ""))
    urls.extend(_INLINE_CITE.findall(text or ""))
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        url = url.strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                chunks.append(str(content.get("text") or ""))
    return "\n".join(chunks).strip()


def _title_from_url(url: str) -> str:
    host = urlparse(url).netloc or url
    return host.replace("www.", "")[:120]


def brief_from_xai(
    raw_json: dict[str, Any] | None,
    citation_urls: list[str],
    *,
    bundle: dict[str, Any] | None = None,
) -> NewsBrief | None:
    """Keep only URLs that appear in API citations. No citations → discard."""
    if not citation_urls:
        return None
    allowed = set(citation_urls)
    fontes: list[SourceRef] = []
    seen: set[str] = set()
    for row in (raw_json or {}).get("fontes") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url not in allowed or url in seen:
            continue
        try:
            fontes.append(SourceRef.model_validate({
                "titulo": row.get("titulo") or _title_from_url(url),
                "url": url,
                "data": row.get("data") or "",
            }))
            seen.add(url)
        except ValidationError:
            continue
    for url in citation_urls:
        if url in seen:
            continue
        try:
            fontes.append(SourceRef(titulo=_title_from_url(url), url=url, data=""))
            seen.add(url)
        except ValidationError:
            continue
    if not fontes:
        return None
    eventos: list[EventoProximo] = []
    for row in (raw_json or {}).get("eventos_proximos") or []:
        try:
            eventos.append(EventoProximo.model_validate(row))
        except ValidationError:
            continue
    if not eventos and bundle:
        for row in bundle.get("eventos") or []:
            try:
                eventos.append(EventoProximo.model_validate({
                    "nome": row.get("nome"),
                    "data": row.get("data"),
                    "tipo": "binary" if row.get("tipo") == "binary" else "macro",
                    "impacto": row.get("impacto") or "alto",
                }))
            except ValidationError:
                continue
    sentimento = 0.0
    if raw_json and "sentimento" in raw_json:
        try:
            sentimento = max(-1.0, min(1.0, float(raw_json["sentimento"])))
        except (TypeError, ValueError):
            sentimento = 0.0
    riscos = [str(r) for r in (raw_json or {}).get("riscos") or [] if str(r).strip()][:8]
    try:
        return NewsBrief(
            eventos_proximos=eventos,
            sentimento=sentimento,
            riscos=riscos,
            fontes=fontes,
        )
    except ValidationError:
        return None


_NEWS_INSTRUCTIONS = (
    "Agente de notícias/macro ATOM. Use web_search e x_search. "
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
    if not xai_configured():
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
    from_date = (datetime.now(UTC).date() - timedelta(days=min(days, 30))).isoformat()
    user = (
        f"Ativo={ticker} horizonte={horizon} (~{days} dias). "
        f"Notícias, macro e posts recentes que afetam o cenário paper. "
        f"Calendário já conhecido: {bundle.get('eventos') or []}"
    )
    payload = {
        "model": xai_model(),
        "instructions": compose_system(_NEWS_INSTRUCTIONS),
        "input": [{"role": "user", "content": user}],
        "tools": [
            {"type": "web_search"},
            {"type": "x_search", "from_date": from_date},
        ],
        "store": False,
    }
    timeout = float(os.getenv("ATOM_XAI_TIMEOUT", "45"))
    data = await _post_json("/responses", payload, timeout=timeout)
    if not data:
        return None
    text = extract_output_text(data)
    citations = extract_citations(data, text)
    brief = brief_from_xai(parse_json_object(text), citations, bundle=bundle)
    if brief:
        Cache.set(key, brief.model_dump(), ex=cache_ttl())
    else:
        logger.info("xAI news discarded (sem citações/URLs válidas)")
    return brief


async def _post_json(path: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    key = (os.getenv("XAI_API_KEY") or "").strip()
    if not key:
        return None
    url = f"{XAI_BASE}{path}"
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
        logger.info("xAI %s failed (%s)", path, type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None

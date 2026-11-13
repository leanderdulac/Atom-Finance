"""News/macro agent. LLM may summarise sources; it never invents URLs or prices."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from app.services.agents.llm import OllamaProvider, get_agent_llm, parse_json_object
from app.services.agents.schemas import EventoProximo, NewsBrief, SourceRef
from app.services.context import calendar, crypto, gather, search

logger = logging.getLogger(__name__)

_NEWS_SYSTEM = (
    "Você é o agente de notícias/macro do ATOM. Use só as ferramentas e o pacote "
    "já coletado. Devolva JSON com eventos_proximos, sentimento (-1 a 1), riscos[], "
    "fontes[{titulo,url,data}]. Sem fonte = sem afirmação. Não invente URL, preço, "
    "nível, direção nem tamanho. Não recomende operação."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Busca notícias públicas (SearXNG/Brave/Tavily se configurados).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_macro_events",
            "description": "Calendário macro no horizonte (Copom, FOMC, CPI, payroll).",
            "parameters": {
                "type": "object",
                "properties": {"horizon_days": {"type": "integer"}},
                "required": ["horizon_days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crypto_positioning",
            "description": "Funding e open interest públicos (Binance/OKX) e on-chain BTC.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
]


def _dispatch(ticker: str, horizon_days: int) -> dict[str, Any]:
    return {
        "search_news": lambda query="", **_: search.search_news(str(query or ticker)),
        "list_macro_events": lambda horizon_days=horizon_days, **_: calendar.upcoming_events(
            horizon_days=int(horizon_days or 21)
        ),
        "crypto_positioning": lambda ticker=ticker, **_: crypto.positioning(str(ticker or "")),
    }


def news_from_bundle(bundle: dict[str, Any]) -> NewsBrief | None:
    fontes_raw = bundle.get("fontes") or []
    fontes: list[SourceRef] = []
    for row in fontes_raw:
        try:
            fontes.append(SourceRef.model_validate({
                "titulo": row.get("titulo") or row.get("url"),
                "url": row.get("url"),
                "data": row.get("data") or "",
            }))
        except ValidationError:
            continue
    if not fontes:
        return None
    eventos: list[EventoProximo] = []
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
    riscos = [f"Evento {e.nome} em {e.data}" for e in eventos if e.impacto == "alto"]
    return NewsBrief(
        eventos_proximos=eventos,
        sentimento=0.0,
        riscos=riscos,
        fontes=fontes,
    )


def _validate_brief(raw: dict[str, Any] | None) -> NewsBrief | None:
    if not raw:
        return None
    try:
        return NewsBrief.model_validate(raw)
    except ValidationError as exc:
        logger.info("News brief discarded: %s", exc)
        return None


async def run_news_agent(ticker: str, horizon: str, *, asset_class: str = "equity_br") -> NewsBrief | None:
    from app.services.context.gather import HORIZON_DAYS

    bundle = await asyncio.to_thread(
        gather.gather_context, ticker, horizon, asset_class=asset_class,
    )
    llm = get_agent_llm()
    if isinstance(llm, OllamaProvider):
        days = HORIZON_DAYS.get(horizon, 21)
        user = (
            f"Ativo={ticker} horizonte={horizon} ({days} dias). "
            f"Pacote já coletado (use como base; ferramentas só para completar):\n"
            f"{_clip(bundle)}"
        )
        try:
            text = await llm.chat_with_tools(
                system_prompt=_NEWS_SYSTEM,
                user_prompt=user,
                tools=TOOLS,
                dispatch=_dispatch(ticker, days),
            )
        except Exception as exc:
            logger.info("News agent LLM failed (%s)", type(exc).__name__)
            text = None
        brief = _validate_brief(parse_json_object(text or ""))
        if brief:
            return brief
    return news_from_bundle(bundle)


def _clip(bundle: dict[str, Any]) -> str:
    slim = {
        "eventos": bundle.get("eventos"),
        "fontes": (bundle.get("fontes") or [])[:8],
        "crypto": bundle.get("crypto"),
    }
    return json.dumps(slim, default=str)[:6000]

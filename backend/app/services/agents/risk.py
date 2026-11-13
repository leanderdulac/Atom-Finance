"""Devil's-advocate risk agent. Does not choose entry, stop, target or size."""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.services.agents.llm import get_risk_llm, parse_json_object
from app.services.agents.schemas import NewsBrief, RiskBrief

logger = logging.getLogger(__name__)

_RISK_SYSTEM = (
    "Você é o advogado do diabo da mesa ATOM. A operação JÁ foi montada pelo arsenal "
    "(entrada, stop, alvo, tamanho). Você NÃO altera preços nem níveis. Aponte objeções "
    "ao cenário paper. Devolva JSON {objecoes[], severidade: baixa|media|alta, "
    "recomendacao: manter|reduzir|recusar}. Recusar só se evento binário no horizonte "
    "ou risco que invalida o cenário. Sem fonte, não invente fato."
)


def risk_from_rules(payload: dict[str, Any], news: NewsBrief | None) -> RiskBrief:
    objecoes: list[str] = []
    binary = False
    if news:
        for event in news.eventos_proximos:
            if event.tipo == "binary" or event.impacto == "alto":
                binary = True
                objecoes.append(f"{event.nome} em {event.data} cai no horizonte paper.")
        for risco in news.riscos:
            if risco not in objecoes:
                objecoes.append(risco)
        pos = (payload.get("regime") or {}).get("desk")
        if pos == "crisis":
            objecoes.append("Regime de mesa em crise — cenário paper já frágil.")
    if not objecoes:
        return RiskBrief(objecoes=[], severidade="baixa", recomendacao="manter")
    if binary:
        return RiskBrief(objecoes=objecoes[:8], severidade="alta", recomendacao="reduzir")
    return RiskBrief(objecoes=objecoes[:8], severidade="media", recomendacao="reduzir")


async def run_risk_agent(payload: dict[str, Any], news: NewsBrief | None) -> RiskBrief:
    fallback = risk_from_rules(payload, news)
    llm = get_risk_llm()
    if llm is None:
        return fallback
    facts = {
        "ticker": payload.get("ticker"),
        "horizon": payload.get("horizon"),
        "holding_days": payload.get("holding_days"),
        "direction": payload.get("direction"),
        "status": payload.get("status"),
        "confidence": payload.get("confidence"),
        "entry": payload.get("entry"),
        "invalidation": payload.get("invalidation"),
        "target": payload.get("target"),
        "quantity": payload.get("quantity"),
        "news": news.model_dump() if news else None,
        "instrucao": "Não mude entrada, stop nem alvo. Só objeções e recomendação de tamanho.",
    }
    try:
        text = await llm.complete(json.dumps(facts, default=str)[:8000], system_prompt=_RISK_SYSTEM)
    except Exception as exc:
        logger.info("Risk agent LLM failed (%s)", type(exc).__name__)
        return fallback
    raw = parse_json_object(text or "")
    if not raw:
        return fallback
    try:
        return RiskBrief.model_validate(raw)
    except ValidationError:
        logger.info("Risk brief discarded (invalid JSON schema)")
        return fallback

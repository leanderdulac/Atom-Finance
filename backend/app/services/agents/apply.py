"""Deterministic overlay: context may shrink or refuse size — never move levels."""
from __future__ import annotations

from typing import Any

from app.services.agents.schemas import NewsBrief, RiskBrief


def has_binary_in_horizon(news: NewsBrief | None) -> bool:
    if news is None:
        return False
    return any(e.tipo == "binary" or e.impacto == "alto" for e in news.eventos_proximos)


def apply_context_risk(
    payload: dict[str, Any],
    news: NewsBrief | None,
    risk: RiskBrief | None,
) -> dict[str, Any]:
    """Mutate size/confidence/status only. entry / invalidation / target stay put."""
    entry = payload.get("entry")
    invalidation = payload.get("invalidation")
    target = payload.get("target")

    fontes = []
    if news:
        fontes = [{"title": s.titulo, "url": s.url, "date": s.data} for s in news.fontes]
    payload["sources"] = fontes
    payload["context_used"] = bool(news)
    payload["eligible_for_live_trading"] = False

    if payload.get("status") != "ready":
        payload["context_effect"] = "nenhum"
        return payload

    rec = risk.recomendacao if risk else "manter"
    sev = risk.severidade if risk else "baixa"
    binary = has_binary_in_horizon(news)
    # Recusar só quando o agente pede recusar. Severidade alta ou evento
    # binário no horizonte → reduzir tamanho/confiança; níveis ficam.
    refuse = rec == "recusar"
    reduce = rec == "reduzir" or sev == "alta" or binary

    if refuse:
        reason = (
            "Há evento binário no horizonte ou o agente de risco recusou o cenário paper. "
            "Entrada, stop e alvo do arsenal não mudam — não registramos operação."
        )
        payload["status"] = "insufficient"
        payload["reason"] = reason
        payload["quantity"] = 0
        size = dict(payload.get("suggested_size") or {})
        size["quantity"] = 0
        size["can_register_paper"] = False
        size["paper_block"] = reason
        payload["suggested_size"] = size
        payload["confidence"] = "baixa"
        payload["context_effect"] = "recusar"
    elif reduce:
        qty = float(payload.get("quantity") or 0) * 0.5
        payload["quantity"] = qty
        size = dict(payload.get("suggested_size") or {})
        size["quantity"] = qty
        payload["suggested_size"] = size
        payload["confidence"] = "baixa"
        plan = payload.get("paper_plan")
        if isinstance(plan, dict):
            plan = {**plan, "quantity_per_leg": qty}
            legs = []
            for leg in plan.get("legs") or []:
                if isinstance(leg, dict) and "quantity" in leg:
                    legs.append({**leg, "quantity": qty})
                else:
                    legs.append(leg)
            if legs:
                plan["legs"] = legs
            payload["paper_plan"] = plan
        payload["context_effect"] = "reduzir"
        payload.setdefault("arsenal", []).append({
            "part": "Contexto (risco)",
            "used": True,
            "note": "tamanho/confiança reduzidos; entrada, stop e alvo intactos",
        })
    else:
        payload["context_effect"] = "manter"

    if payload.get("entry") != entry or payload.get("invalidation") != invalidation or payload.get("target") != target:
        payload["entry"] = entry
        payload["invalidation"] = invalidation
        payload["target"] = target
    payload["eligible_for_live_trading"] = False
    return payload

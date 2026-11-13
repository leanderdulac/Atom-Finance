"""Research-diary + Redis audit of context. Client never sees objections."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.cache import Cache
from app.core.client_mode import is_operator_role
from app.services.agents.schemas import NewsBrief, RiskBrief

logger = logging.getLogger(__name__)

AUDIT_KEY = "atom:context:audits"
AUDIT_TTL = 7 * 24 * 3600
AUDIT_MAX = 200


def _public_sources(news: NewsBrief | None) -> list[dict[str, str]]:
    if not news:
        return []
    return [{"title": s.titulo, "url": s.url, "date": s.data} for s in news.fontes]


def record_audit_sync(
    *,
    owner: str | None,
    ticker: str,
    horizon: str,
    payload: dict[str, Any],
    news: NewsBrief | None,
    risk: RiskBrief | None,
) -> dict[str, Any]:
    item = {
        "id": str(uuid4()),
        "at": datetime.now(UTC).isoformat(),
        "owner": owner,
        "ticker": ticker,
        "horizon": horizon,
        "status": payload.get("status"),
        "effect": payload.get("context_effect") or "nenhum",
        "entry": payload.get("entry"),
        "invalidation": payload.get("invalidation"),
        "target": payload.get("target"),
        "quantity": payload.get("quantity"),
        "confidence": payload.get("confidence"),
        "news": news.model_dump() if news else None,
        "objecoes": list(risk.objecoes) if risk else [],
        "severidade": risk.severidade if risk else None,
        "recomendacao": risk.recomendacao if risk else None,
        "sources": _public_sources(news),
        "eligible_for_live_trading": False,
    }
    rows = Cache.get(AUDIT_KEY)
    if not isinstance(rows, list):
        rows = []
    rows.insert(0, item)
    Cache.set(AUDIT_KEY, rows[:AUDIT_MAX], ex=AUDIT_TTL)
    return item


async def record_audit(
    *,
    owner: str | None,
    role: str | None,
    ticker: str,
    horizon: str,
    payload: dict[str, Any],
    news: NewsBrief | None,
    risk: RiskBrief | None,
) -> dict[str, Any]:
    item = record_audit_sync(
        owner=owner, ticker=ticker, horizon=horizon, payload=payload, news=news, risk=risk,
    )
    if owner and is_operator_role(role):
        try:
            from app.db import experiments
            await experiments.begin(owner, {
                "hypothesis": (
                    "O contexto em tempo real (notícias, macro, funding) só altera "
                    "tamanho, confiança ou recusa de uma operação já montada pelo arsenal; "
                    "não escolhe entrada, stop nem alvo."
                ),
                "data_source": "searxng_rss_calendar_crypto_public",
                "model": "ollama:gpt-oss:20b+regras",
                "ticker": ticker,
                "horizon": horizon,
                "audit_id": item["id"],
                "effect": item["effect"],
                "objecoes": item["objecoes"],
                "sources": item["sources"],
                "news": item["news"],
                "levels": {
                    "entry": item["entry"],
                    "invalidation": item["invalidation"],
                    "target": item["target"],
                },
            })
        except Exception as exc:
            logger.info("Experiment diary skip (%s)", type(exc).__name__)
    return item


def list_audits(limit: int = 50) -> list[dict[str, Any]]:
    rows = Cache.get(AUDIT_KEY)
    if not isinstance(rows, list):
        return []
    return rows[: max(1, min(limit, AUDIT_MAX))]

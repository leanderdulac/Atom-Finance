"""Client surface: config, ready-made paper operation, paper registration.

Does not send broker orders. The diary (paper_trades) remains the only writer
of trade state — this module saves a plan and calls the same INSERT as track().
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.core.client_mode import client_mode_enabled, is_operator_role
from app.core.compute import compute_workers, db_pool_max, io_workers, torch_device
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.models.derivatives_planner import StrictModel
from app.models.ready_operation import (
    HORIZONS,
    Horizon,
    Instrument,
    assemble,
    client_facing_why,
    facts_for_llm,
    resolve_asset,
    universe_public,
)
from app.services.agents.apply import apply_context_risk
from app.services.agents.audit import record_audit
from app.services.agents.news import run_news_agent
from app.services.agents.risk import run_risk_agent
from app.services.agents.writer import cite_sources
from app.services.client_arsenal import load_market
from app.services.ollama import draft_why, ollama_configured

router = APIRouter()


class ReadyRequest(StrictModel):
    ticker: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9.\-]{3,20}$")
    instrument: Instrument
    horizon: Horizon


def _public_config() -> dict:
    from app.core.client_mode import OPERATOR_ROLES
    return {
        "client_mode": client_mode_enabled(),
        "universe": universe_public(),
        "instruments": [
            {"id": "spot", "label": "À vista (ação ou cripto)",
             "hint": "Compra ou venda simulada do próprio ativo."},
            {"id": "option", "label": "Opção",
             "hint": "Estrutura condicional se o arsenal tiver livro com bid, ask e quantidade."},
            {"id": "future", "label": "Futuro / perpétuo",
             "hint": "Só BTC, ETH e SOL, via feed público da Binance. Sem futuro B3 neste modo."},
        ],
        "horizons": [{"id": key, **{k: v for k, v in val.items() if k != "holding_days"}, "holding_days": val["holding_days"]}
                     for key, val in HORIZONS.items()],
        "eligible_for_live_trading": False,
        "disclaimer": (
            "Cenário e simulação paper. Não é recomendação, não é ordem, não promete retorno. "
            "Quando o arsenal não tem dado ou sinal, a tela diz isso e não inventa operação."
        ),
        "operator_roles": sorted(OPERATOR_ROLES),
        "compute": {
            "torch_device": torch_device(),
            "compute_workers": compute_workers(),
            "io_workers": io_workers(),
            "db_pool_max": db_pool_max(),
            "ollama": ollama_configured(),
        },
    }


@router.get("/config")
@limiter.exempt
def config():
    """Public: the landing page needs to know client mode before login."""
    return _public_config()


@router.get("/me")
async def me(owner: str = Depends(get_current_user)):
    from app.db.database import get_user_by_username
    user = await get_user_by_username(owner)
    role = (user or {}).get("role")
    return {
        **_public_config(),
        "username": owner,
        "role": role,
        "is_operator": is_operator_role(role),
    }


async def _decorate_why(payload: dict) -> dict:
    fallback = payload.get("why_fallback") or payload.get("why") or ""
    text = await draft_why(facts_for_llm(payload))
    if text:
        payload["why"] = client_facing_why(text, fallback)
        payload["why_source"] = "ollama" if payload["why"] == text else "template"
        payload.setdefault("arsenal", []).append(
            {"part": "Ollama (texto)", "used": True, "note": "redigiu o porquê a partir dos números; não escolheu a operação"}
        )
    else:
        payload["why"] = client_facing_why(fallback, fallback)
        payload["why_source"] = "template"
        payload.setdefault("arsenal", []).append(
            {"part": "Ollama (texto)", "used": False, "note": "daemon ausente ou mudo — texto-padrão do arsenal"}
        )
    return payload


def _client_view(payload: dict) -> dict:
    """Client sees the result and sources — not the devil's-advocate brief."""
    out = dict(payload)
    out.pop("risk_brief", None)
    out.pop("news_brief", None)
    out["eligible_for_live_trading"] = False
    return out


async def build_ready_operation(
    req: ReadyRequest,
    *,
    owner: str | None = None,
    role: str | None = None,
) -> dict:
    market = await asyncio.to_thread(load_market, req.ticker)
    payload = await asyncio.to_thread(
        assemble, req.ticker, req.instrument, req.horizon, market=market,
    )
    payload = await _decorate_why(payload)
    asset = resolve_asset(req.ticker)
    asset_class = str((asset or {}).get("asset_class") or "equity_br")
    news = await run_news_agent(req.ticker, req.horizon, asset_class=asset_class)
    risk = await run_risk_agent(payload, news)
    payload = apply_context_risk(payload, news, risk)
    payload["why"] = cite_sources(str(payload.get("why") or ""), news)
    payload.setdefault("arsenal", []).append({
        "part": "Contexto (notícias/macro)",
        "used": bool(news),
        "note": "fontes públicas em cache; LLM não escolhe preço nem nível" if news
        else "sem fonte pública — nenhum contexto inventado",
    })
    await record_audit(
        owner=owner, role=role, ticker=req.ticker, horizon=req.horizon,
        payload=payload, news=news, risk=risk,
    )
    return _client_view(payload)


@router.post("/ready-operation")
@limiter.limit("20/minute")
async def ready_operation(request: Request, req: ReadyRequest, owner: str = Depends(get_current_user)):
    from app.db.database import get_user_by_username
    user = await get_user_by_username(owner)
    return await build_ready_operation(req, owner=owner, role=(user or {}).get("role"))


async def _persist_watching(owner: str, assembled: dict) -> dict:
    plan = assembled.get("paper_plan")
    if not plan or not assembled.get("suggested_size", {}).get("can_register_paper"):
        raise HTTPException(
            409,
            assembled.get("suggested_size", {}).get("paper_block")
            or assembled.get("reason")
            or "Não há operação paper para registrar.",
        )
    inputs = assembled.get("plan_inputs") or {}
    report = {
        "version": "ATOM-CLIENT-READY-1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "source": inputs.get("source", "ATOM cliente"),
        "provenance": inputs.get("provenance", "user_supplied"),
        "eligible_for_live_trading": False,
        "status": "conditional_review",
        "plans": [plan],
        "rejected": [],
        "limitations": [
            "Operação montada automaticamente para o cliente; calendário de eventos não foi conferido por um humano.",
            "Paper only. O diário permanece o único escritor. Nenhuma ordem vai à corretora.",
        ],
    }
    run_id = str(uuid4())
    report["id"] = run_id
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        from app.api.paper_trades import lock_owner, read_record
        await lock_owner(conn, owner)
        await conn.execute(
            "INSERT INTO derivative_plans (id, owner, created_at, payload, result) VALUES ($1,$2,$3,$4,$5)",
            run_id, owner, datetime.now(UTC), {**inputs, "ready": {
                "ticker": assembled.get("ticker"),
                "instrument": assembled.get("instrument"),
                "horizon": assembled.get("horizon"),
            }}, report,
        )
        existing = await conn.fetchrow(
            "SELECT id FROM paper_trades WHERE owner=$1 AND plan_id=$2 AND plan_index=$3",
            owner, run_id, 0,
        )
        trade_id = existing["id"] if existing else str(uuid4())
        if not existing:
            context = {k: inputs.get(k) for k in (
                "source", "provenance", "capital", "total_risk_pct", "existing_risk_brl", "fee_per_contract_side",
            )}
            context["source"] = context.get("source") or "ATOM cliente"
            context["provenance"] = context.get("provenance") or "user_supplied"
            context["capital"] = context.get("capital") or 10000
            context["total_risk_pct"] = context.get("total_risk_pct") or 3
            context["existing_risk_brl"] = context.get("existing_risk_brl") or 0
            context["fee_per_contract_side"] = context.get("fee_per_contract_side") or 0.05
            await conn.execute(
                "INSERT INTO paper_trades (id, owner, plan_id, plan_index, status, created_at, plan, context) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                trade_id, owner, run_id, 0, "watching", datetime.now(UTC), plan, context,
            )
        record = await read_record(conn, owner, trade_id)
    record["eligible_for_live_trading"] = False
    return record


@router.post("/ready-operation/paper", status_code=201)
@limiter.limit("10/minute")
async def register_paper(request: Request, req: ReadyRequest, owner: str = Depends(get_current_user)):
    from app.db.database import get_user_by_username
    user = await get_user_by_username(owner)
    assembled = await build_ready_operation(req, owner=owner, role=(user or {}).get("role"))
    if assembled.get("status") != "ready":
        raise HTTPException(409, assembled.get("reason") or "Sem operação para registrar.")
    if not assembled.get("suggested_size", {}).get("can_register_paper"):
        raise HTTPException(409, assembled.get("suggested_size", {}).get("paper_block") or "Sem lote paper.")
    record = await _persist_watching(owner, assembled)
    return {
        "trade": record,
        "operation": assembled,
        "status": record.get("status"),
        "eligible_for_live_trading": False,
        "message": "Registrada como operação paper, aguardando gatilho. O diário é o único escritor.",
    }

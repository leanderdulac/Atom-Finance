"""Client surface: config, ready-made paper operation, paper registration.

Does not send broker orders. The diary (paper_trades) remains the only writer
of trade state — this module saves a plan and calls the same INSERT as track().
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from math import isfinite
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator

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
    assemble_basket,
    client_facing_why,
    facts_for_llm,
    unique_tickers,
    universe_public,
)
from app.services.client_arsenal import load_market
from app.services.ollama import draft_why, ollama_configured

router = APIRouter()


_TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{3,20}$")


class ReadyRequest(StrictModel):
    ticker: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9.\-]{3,20}$")
    instrument: Instrument
    horizon: Horizon
    tickers: list[str] | None = Field(default=None, max_length=8)
    weights: list[float] | None = Field(default=None, max_length=8)

    @field_validator("tickers")
    @classmethod
    def _clean_tickers(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        seen: list[str] = []
        for raw in value:
            token = (raw or "").strip()
            if not token:
                continue
            if not _TICKER_RE.fullmatch(token):
                raise ValueError("ticker inválido na carteira mista")
            if token not in seen:
                seen.append(token)
            if len(seen) >= 8:
                break
        return seen or None

    @field_validator("weights")
    @classmethod
    def _clean_weights(cls, value: list[float] | None) -> list[float] | None:
        if not value:
            return None
        cleaned: list[float] = []
        for raw in value:
            number = float(raw)
            if number < 0 or not isfinite(number):
                raise ValueError("peso inválido")
            cleaned.append(number)
        return cleaned[:8]

    def resolved_tickers(self) -> list[str]:
        return unique_tickers(self.tickers or [self.ticker])


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


async def build_ready_operation(req: ReadyRequest) -> dict:
    tickers = req.resolved_tickers()
    if len(tickers) <= 1:
        ticker = tickers[0] if tickers else req.ticker
        market = await asyncio.to_thread(load_market, ticker)
        payload = await asyncio.to_thread(
            assemble, ticker, req.instrument, req.horizon, market=market,
        )
        return await _decorate_why(payload)
    loaded = await asyncio.gather(*[asyncio.to_thread(load_market, ticker) for ticker in tickers])
    markets = dict(zip(tickers, loaded, strict=True))
    payload = await asyncio.to_thread(
        assemble_basket, tickers, req.instrument, req.horizon,
        markets=markets, weights=req.weights,
    )
    return await _decorate_why(payload)


@router.post("/ready-operation")
@limiter.limit("20/minute")
async def ready_operation(request: Request, req: ReadyRequest, owner: str = Depends(get_current_user)):
    return await build_ready_operation(req)


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
    assembled = await build_ready_operation(req)
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

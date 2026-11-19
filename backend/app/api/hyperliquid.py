"""Hyperliquid broker link. Testnet-first; mainnet writes stay blocked unless
armed via env AND an explicit live=True call argument. Never logs keys.

GET routes stay authenticated (the protected router). POST /order and
POST /cancel also require an admin or operator role.
"""

from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import Field, field_validator

from app.core.client_mode import is_operator_role
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.database import get_user_by_username
from app.models.derivatives_planner import StrictModel
from app.services import hyperliquid_trading as hl

router = APIRouter()


class _CoinBody(StrictModel):
    coin: str

    @field_validator("coin", mode="before")
    @classmethod
    def _coin(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return hl.normalize_coin(value)


class OrderRequest(_CoinBody):
    side: str = Field(pattern="^(buy|sell)$")
    size: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    reduce_only: bool = False
    live: bool = False


class CancelRequest(_CoinBody):
    oid: int = Field(ge=0)
    live: bool = False


def _cfg_or_503() -> hl.HLConfig:
    cfg = hl.load_config()
    missing = hl.sdk_missing()
    if missing is not None:
        raise HTTPException(503, f"SDK Hyperliquid ausente: {missing}")
    return cfg


def _public_error(cfg: hl.HLConfig, exc: BaseException) -> str:
    text = str(exc)
    secret = cfg.api_wallet_key
    if secret and secret in text:
        return "erro interno ao falar com a exchange"
    return text[:300]


def _scrub(cfg: hl.HLConfig, message: str) -> str:
    secret = cfg.api_wallet_key
    if secret:
        return message.replace(secret, "[redacted]")
    return message


def _raise_if_rejected(cfg: hl.HLConfig, payload: object) -> None:
    found = hl.sdk_rejection(payload)
    if found is None:
        return
    code, message = found
    raise HTTPException(code, _scrub(cfg, message))


async def _require_operator(username: str) -> None:
    """Same lookup as the admin user list, extended to the operator role."""
    me = await get_user_by_username(username)
    if not me or not is_operator_role(me.get("role")):
        raise HTTPException(status_code=403, detail="Admin or operator access required.")


@router.get("/status")
@limiter.limit("30/minute")
async def status(request: Request):
    return hl.status_payload(hl.load_config())


@router.get("/markets")
@limiter.limit("30/minute")
async def markets(request: Request):
    cfg = _cfg_or_503()
    what_broke = list(cfg.what_broke)
    try:
        mids, meta = await run_in_threadpool(hl.fetch_markets, cfg)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler /info: {_public_error(cfg, exc)}") from exc
    return {"network": cfg.network, "mids": mids, "meta": meta, "what_broke": what_broke}


@router.get("/account")
@limiter.limit("30/minute")
async def account(request: Request):
    cfg = _cfg_or_503()
    if not cfg.account_address:
        raise HTTPException(422, "HYPERLIQUID_ACCOUNT_ADDRESS ausente.")
    what_broke = list(cfg.what_broke)
    try:
        state, orders = await run_in_threadpool(hl.fetch_account, cfg)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler conta: {_public_error(cfg, exc)}") from exc
    return {"network": cfg.network, "state": state, "open_orders": orders, "what_broke": what_broke}


@router.post("/order")
@limiter.limit("10/minute")
async def place_order(
    request: Request,
    req: OrderRequest,
    username: str = Depends(get_current_user),
):
    await _require_operator(username)
    cfg = _cfg_or_503()
    coin = req.coin
    try:
        mids, meta = await run_in_threadpool(hl.fetch_markets, cfg)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler /info: {_public_error(cfg, exc)}") from exc
    spec = meta.get(coin)
    if spec is None:
        raise HTTPException(422, f"Ativo desconhecido: {coin}.")
    ref_px = float(mids.get(coin, 0) or 0)
    px = req.price if req.price is not None else ref_px
    if px <= 0:
        raise HTTPException(422, f"Sem preço de referência para {coin}; informe price.")
    size = hl.round_to_lot(req.size, spec["sz_decimals"])
    if size <= 0:
        raise HTTPException(422, "Tamanho zerou após arredondar no lote mínimo.")
    if req.price is None:
        notional = hl.market_notional(size, ref_px, req.side, cfg.market_slippage)
    else:
        notional = size * px
    blockers = hl.guard_write(cfg, live=req.live, notional_usd=notional)
    if blockers:
        raise HTTPException(403, {"detail": "Ordem bloqueada.", "blockers": blockers})
    try:
        resp = await run_in_threadpool(
            partial(
                hl.submit_order,
                cfg,
                coin=coin,
                is_buy=req.side == "buy",
                size=size,
                limit_px=req.price,
                mid=ref_px,
                reduce_only=req.reduce_only,
            )
        )
    except Exception as exc:
        raise HTTPException(502, f"Falha ao enviar ordem: {_public_error(cfg, exc)}") from exc
    _raise_if_rejected(cfg, resp)
    return {
        "network": cfg.network,
        "coin": coin,
        "side": req.side,
        "size": size,
        "price": px,
        "notional_usd": notional,
        "slippage": None if req.price is not None else cfg.market_slippage,
        "reduce_only": req.reduce_only,
        "response": resp,
        "what_broke": list(cfg.what_broke),
    }


@router.post("/cancel")
@limiter.limit("10/minute")
async def cancel_order(
    request: Request,
    req: CancelRequest,
    username: str = Depends(get_current_user),
):
    await _require_operator(username)
    cfg = _cfg_or_503()
    blockers = hl.guard_cancel(cfg, live=req.live)
    if blockers:
        raise HTTPException(403, {"detail": "Cancelamento bloqueado.", "blockers": blockers})
    try:
        resp = await run_in_threadpool(hl.submit_cancel, cfg, req.coin, req.oid)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao cancelar: {_public_error(cfg, exc)}") from exc
    _raise_if_rejected(cfg, resp)
    return {"network": cfg.network, "response": resp, "what_broke": list(cfg.what_broke)}

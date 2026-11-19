"""Hyperliquid broker link. Testnet-first; mainnet writes stay blocked unless
armed via env AND an explicit live=True call argument. Never logs keys."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.core.limiter import limiter
from app.models.derivatives_planner import StrictModel
from app.services import hyperliquid_trading as hl

router = APIRouter()


class OrderRequest(StrictModel):
    coin: str = Field(min_length=1, max_length=12)
    side: str = Field(pattern="^(buy|sell)$")
    size: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    reduce_only: bool = False
    live: bool = False


class CancelRequest(StrictModel):
    coin: str = Field(min_length=1, max_length=12)
    oid: int = Field(ge=0)


def _cfg_or_503():
    cfg = hl.load_config()
    if hl._SDK_MISSING is not None:
        raise HTTPException(503, f"SDK Hyperliquid ausente: {hl._SDK_MISSING}")
    return cfg


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
        client = hl.info_client(cfg)
        mids = client.all_mids()
        meta = hl.meta_map(client)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler /info: {exc}") from exc
    return {"network": cfg.network, "mids": mids, "meta": meta, "what_broke": what_broke}


@router.get("/account")
@limiter.limit("30/minute")
async def account(request: Request):
    cfg = _cfg_or_503()
    if not cfg.account_address:
        raise HTTPException(422, "HYPERLIQUID_ACCOUNT_ADDRESS ausente.")
    what_broke = list(cfg.what_broke)
    try:
        client = hl.info_client(cfg)
        state = client.user_state(cfg.account_address)
        orders = client.open_orders(cfg.account_address)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler conta: {exc}") from exc
    return {"network": cfg.network, "state": state, "open_orders": orders, "what_broke": what_broke}


@router.post("/order")
@limiter.limit("10/minute")
async def place_order(request: Request, req: OrderRequest):
    cfg = _cfg_or_503()
    coin = req.coin.strip().upper()
    try:
        client = hl.info_client(cfg)
        mids = client.all_mids()
        meta = hl.meta_map(client)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao ler /info: {exc}") from exc
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
    notional = size * px
    blockers = hl.guard_write(cfg, live=req.live, notional_usd=notional)
    if blockers:
        raise HTTPException(403, {"detail": "Ordem bloqueada.", "blockers": blockers})
    try:
        ex = hl.exchange_client(cfg)
        if req.price is None:
            resp = ex.market_open(coin, req.side == "buy", size)
        else:
            from hyperliquid.utils.signing import OrderType

            resp = ex.order(
                coin, req.side == "buy", size, px, OrderType({"limit": {"tif": "Gtc"}}),
                reduce_only=req.reduce_only,
            )
    except Exception as exc:
        raise HTTPException(502, f"Falha ao enviar ordem: {exc}") from exc
    return {
        "network": cfg.network,
        "coin": coin,
        "side": req.side,
        "size": size,
        "price": px,
        "notional_usd": notional,
        "reduce_only": req.reduce_only,
        "response": resp,
        "what_broke": list(cfg.what_broke),
    }


@router.post("/cancel")
@limiter.limit("10/minute")
async def cancel_order(request: Request, req: CancelRequest):
    cfg = _cfg_or_503()
    try:
        ex = hl.exchange_client(cfg)
    except Exception as exc:
        raise HTTPException(422, f"Cliente de escrita indisponível: {exc}") from exc
    if not cfg.testnet and not (cfg.live_trading):
        raise HTTPException(403, {"detail": "Cancelamento bloqueado.", "blockers": list(cfg.what_broke)})
    try:
        resp = ex.cancel(req.coin.strip().upper(), req.oid)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao cancelar: {exc}") from exc
    return {"network": cfg.network, "response": resp, "what_broke": list(cfg.what_broke)}

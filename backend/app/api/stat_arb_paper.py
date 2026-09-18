"""ETH/SOL paper stat-arb desk route. Never sends real orders."""

from __future__ import annotations

import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.models.stat_arb_paper import evaluate as eth_sol_paper_evaluate

router = APIRouter()


async def _run(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


class EthSolPaperBarIn(BaseModel):
    ts_ms: int
    y_mid: float = Field(..., gt=0)
    x_mid: float = Field(..., gt=0)
    y_bid: float | None = Field(None, gt=0)
    y_ask: float | None = Field(None, gt=0)
    x_bid: float | None = Field(None, gt=0)
    x_ask: float | None = Field(None, gt=0)


class EthSolPaperRequest(BaseModel):
    demo: bool = False
    fetch_public: bool = False
    interval: str = Field("1h", min_length=2, max_length=4)
    limit: int = Field(500, ge=80, le=1500)
    y_symbol: str = Field("ETHUSDT", min_length=3, max_length=20)
    x_symbol: str = Field("SOLUSDT", min_length=3, max_length=20)
    bars: list[EthSolPaperBarIn] | None = None
    timestamps: list[int] | None = None
    y_mid: list[float] | None = Field(None, min_length=80)
    x_mid: list[float] | None = Field(None, min_length=80)
    y_bid: list[float] | None = None
    y_ask: list[float] | None = None
    x_bid: list[float] | None = None
    x_ask: list[float] | None = None
    entry_z: float = Field(2.0, gt=0, le=5)
    exit_z: float = Field(0.5, gt=0, le=2)
    significance: float = Field(0.05, gt=0, le=0.1)
    max_half_life_bars: float = Field(48.0, gt=0, le=500)
    z_window: int = Field(60, ge=10, le=250)
    warmup: int = Field(60, ge=20, le=400)
    max_drawdown: float = Field(0.15, gt=0, le=0.9)
    max_position: float = Field(1.0, gt=0, le=5)
    half_spread_bps: float = Field(2.0, ge=0, le=50)
    taker_fee_bps: float = Field(4.0, ge=0, le=50)
    unit_qty: float = Field(1.0, gt=0, le=100)
    initial_cash: float = Field(100_000.0, gt=0)
    n: int = Field(400, ge=80, le=2000)
    seed: int = Field(2, ge=0)
    expected_interval_ms: int | None = Field(None, gt=0)


def _cfg(req: EthSolPaperRequest) -> dict:
    return {
        "y_symbol": req.y_symbol.upper(),
        "x_symbol": req.x_symbol.upper(),
        "entry_z": req.entry_z,
        "exit_z": req.exit_z,
        "significance": req.significance,
        "max_half_life_bars": req.max_half_life_bars,
        "z_window": req.z_window,
        "warmup": req.warmup,
        "max_drawdown": req.max_drawdown,
        "max_position": req.max_position,
        "half_spread_bps": req.half_spread_bps,
        "taker_fee_bps": req.taker_fee_bps,
        "unit_qty": req.unit_qty,
        "initial_cash": req.initial_cash,
        "expected_interval_ms": req.expected_interval_ms,
    }


@router.post("/pairs/eth-sol-paper")
@limiter.limit("20/minute")
async def eth_sol_paper(request: Request, req: EthSolPaperRequest):
    """Paper ETH/SOL stat-arb loop. Never sends real orders or uses private keys."""
    cfg = _cfg(req)
    try:
        if req.bars:
            return await _run(eth_sol_paper_evaluate, bars=[b.model_dump() for b in req.bars], source="caller", **cfg)
        if req.y_mid is not None and req.x_mid is not None:
            if len(req.y_mid) != len(req.x_mid):
                raise HTTPException(400, "y_mid and x_mid must have the same length")
            return await _run(
                eth_sol_paper_evaluate,
                timestamps_ms=req.timestamps,
                y_mid=req.y_mid,
                x_mid=req.x_mid,
                y_bid=req.y_bid,
                y_ask=req.y_ask,
                x_bid=req.x_bid,
                x_ask=req.x_ask,
                source="caller",
                **cfg,
            )
        if req.demo:
            return await _run(eth_sol_paper_evaluate, demo=True, n=req.n, seed=req.seed, **cfg)
        if req.fetch_public:
            import httpx

            from app.models.stat_arb_paper import PipelineConfig, run_paper_pipeline
            from app.services.perp_klines import fetch_eth_sol_pair

            try:
                async with httpx.AsyncClient() as client:
                    pulled = await fetch_eth_sol_pair(
                        client=client,
                        y_symbol=req.y_symbol,
                        x_symbol=req.x_symbol,
                        interval=req.interval,
                        limit=req.limit,
                        half_spread_bps=req.half_spread_bps,
                    )
            except httpx.HTTPError as exc:
                raise HTTPException(502, "Public mark klines failed") from exc
            cfg["expected_interval_ms"] = pulled.get("expected_interval_ms")
            return await _run(
                run_paper_pipeline,
                pulled["bars"],
                PipelineConfig(**cfg),
                source="binance_usdm_mark_klines",
                gap_doc=pulled.get("gaps"),
            )
        raise HTTPException(400, "Supply bars, y_mid+x_mid, demo=true, or fetch_public=true")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

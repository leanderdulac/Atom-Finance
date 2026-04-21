"""Dynamic Delta Hedge API endpoints."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.hedge import (
    DeltaHedgeEngine,
    PerpPosition,
    TailRiskAnalyzer,
    UniswapV3Position,
)

router = APIRouter()


# ── Pydantic request / response models ────────────────────────────────────────

class UniswapV3PositionIn(BaseModel):
    L: float = Field(..., gt=0, description="Uniswap V3 liquidity value")
    price_lower: float = Field(..., gt=0, description="Lower tick price bound")
    price_upper: float = Field(..., gt=0, description="Upper tick price bound")


class PerpPositionIn(BaseModel):
    size: float = Field(..., description="Signed contract size (negative = short)")
    entry_price: float = Field(..., gt=0, description="Average fill price")
    margin: float = Field(..., gt=0, description="Collateral posted (quote asset)")
    liquidation_price: float = Field(..., gt=0, description="Exchange liquidation price")


class DeltaRequest(BaseModel):
    position: UniswapV3PositionIn
    perp: PerpPositionIn
    current_price: float = Field(..., gt=0, description="Current spot price (e.g. ETH/USDC)")
    funding_rate_annual: float = Field(0.0, description="Annualised funding rate (e.g. 0.12 = 12%)")


class RebalanceRequest(DeltaRequest):
    tolerance: float = Field(0.05, ge=0.001, le=1.0, description="Fractional deviation threshold")
    high_funding_threshold: float = Field(0.30, ge=0.0, description="Funding rate that widens the tolerance band")
    funding_band_multiplier: float = Field(1.5, ge=1.0, description="Tolerance multiplier under high funding")
    tail_risk_threshold: float = Field(0.05, ge=0.0, le=1.0, description="Liquidation probability that forces a rebalance")
    volatility_annual: float = Field(0.80, gt=0, description="Annualised price volatility for GBM simulation")
    horizon_hours: float = Field(8.0, gt=0, description="Tail-risk look-ahead window (hours)")
    n_paths: int = Field(10_000, ge=100, le=100_000, description="Monte Carlo paths for tail-risk estimation")


class TailRiskRequest(BaseModel):
    current_price: float = Field(..., gt=0)
    liquidation_price: float = Field(..., gt=0)
    volatility_annual: float = Field(0.80, gt=0, description="Annualised volatility")
    drift_annual: float = Field(0.0, description="Annualised drift (use 0 for risk-neutral)")
    horizon_hours: float = Field(8.0, gt=0)
    n_paths: int = Field(10_000, ge=100, le=100_000)
    seed: Optional[int] = Field(42)


# ── Thread-pool helper ─────────────────────────────────────────────────────────

async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def hedge_health():
    """Module status."""
    return {
        "module": "dynamic_hedge",
        "status": "operational",
        "description": (
            "Delta-neutral LP hedge engine: Uniswap V3 inventory math + "
            "perpetual-futures short sizing + GBM tail-risk estimation."
        ),
    }


@router.post("/delta")
async def calculate_delta(req: DeltaRequest):
    """
    Compute the net delta exposure of a Uniswap V3 LP position
    hedged with a perpetual-futures short.

    Maps to pseudocode: **Calcular_Exposicao_Delta**
    """
    lp_pos   = UniswapV3Position(L=req.position.L, price_lower=req.position.price_lower, price_upper=req.position.price_upper)
    perp_pos = PerpPosition(size=req.perp.size, entry_price=req.perp.entry_price, margin=req.perp.margin, liquidation_price=req.perp.liquidation_price)

    engine = DeltaHedgeEngine()
    state  = engine.calculate_exposure(lp_pos, perp_pos, req.current_price, req.funding_rate_annual)

    return {
        "eth_in_pool":        round(state.eth_in_pool, 6),
        "short_size":         round(state.short_size, 6),
        "delta_net":          round(state.delta_net, 6),
        "deviation_pct":      round(state.deviation_pct, 4),
        "current_price":      state.current_price,
        "funding_rate_annual": state.funding_rate_annual,
        "is_fully_hedged":    abs(state.delta_net) < 1e-8,
    }


@router.post("/rebalance")
async def evaluate_rebalance(req: RebalanceRequest):
    """
    Full hedge rebalance decision engine.

    Combines:
    - Deviation threshold check (tolerance, widened under high funding)
    - GBM-based tail-risk estimation (Monte Carlo)
    - Forced rebalance when liquidation probability exceeds the threshold

    Maps to pseudocode: **Executar_Rebalanceamento_Hedge** + *prompt_claude_hedge* logic.

    Returns the same JSON schema as the `decisao_hedge` AI response:
    `{ ajustar_hedge, novo_tamanho_alvo, justificativa }` plus extended fields.
    """
    lp_pos   = UniswapV3Position(L=req.position.L, price_lower=req.position.price_lower, price_upper=req.position.price_upper)
    perp_pos = PerpPosition(size=req.perp.size, entry_price=req.perp.entry_price, margin=req.perp.margin, liquidation_price=req.perp.liquidation_price)

    engine = DeltaHedgeEngine(
        tolerance               = req.tolerance,
        high_funding_threshold  = req.high_funding_threshold,
        funding_band_multiplier = req.funding_band_multiplier,
        tail_risk_threshold     = req.tail_risk_threshold,
    )

    # Step 1 — exposure (fast, no I/O)
    state = engine.calculate_exposure(lp_pos, perp_pos, req.current_price, req.funding_rate_annual)

    # Step 2 — rebalance decision (runs GBM MC in thread pool)
    decision = await _run_in_thread(
        engine.rebalance_decision,
        state,
        req.volatility_annual,
        req.horizon_hours,
        perp_pos,
        req.n_paths,
    )

    return {
        # Primary decision (pseudocode schema)
        "ajustar_hedge":      decision.adjust_hedge,
        "novo_tamanho_alvo":  round(decision.target_short_size, 6),
        "justificativa":      decision.rationale,

        # Extended fields
        "order": {
            "side":  decision.order_side,
            "delta": round(decision.order_delta, 6),
        },
        "tail_risk": {
            "liquidation_prob": round(decision.tail_risk_prob, 6),
            "horizon_hours":    req.horizon_hours,
            "volatility_annual": req.volatility_annual,
            "forced_rebalance": decision.tail_risk_prob >= req.tail_risk_threshold,
        },
        "portfolio_state": {
            "eth_in_pool":   round(state.eth_in_pool, 6),
            "short_size":    round(state.short_size, 6),
            "delta_net":     round(state.delta_net, 6),
            "deviation_pct": round(state.deviation_pct, 4),
        },
    }


@router.post("/tail-risk")
async def estimate_tail_risk(req: TailRiskRequest):
    """
    Standalone GBM-based first-passage probability estimate.

    Answers: "What is the probability that price reaches the liquidation
    level within *horizon_hours* hours, given current volatility?"
    """
    result = await _run_in_thread(
        TailRiskAnalyzer.liquidation_probability,
        req.current_price,
        req.liquidation_price,
        req.volatility_annual,
        req.drift_annual,
        req.horizon_hours,
        req.n_paths,
        req.n_steps if hasattr(req, "n_steps") else 480,
        req.seed,
    )
    return result

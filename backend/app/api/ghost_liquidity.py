"""Ghost Liquidity API endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
from app.models.ghost_liquidity import GhostLiquidityAnalyzer

router = APIRouter()


class OrderBookRequest(BaseModel):
    bids: list[dict] = Field(default_factory=list)
    asks: list[dict] = Field(default_factory=list)
    hft_cancel_rate: float = Field(0.7, ge=0, le=1)
    cross_venue_duplication: float = Field(0.3, ge=0, le=1)


@router.post("/analyze")
async def analyze_ghost_liquidity(req: OrderBookRequest):
    return GhostLiquidityAnalyzer.analyze_order_book(
        req.bids, req.asks,
        hft_cancel_rate=req.hft_cancel_rate,
        cross_venue_duplication=req.cross_venue_duplication,
    )


@router.get("/monitor")
async def monitor_liquidity(n_snapshots: int = 100):
    return GhostLiquidityAnalyzer.monitor_liquidity_over_time(n_snapshots)


@router.get("/demo")
async def demo_analysis():
    """Run a demo analysis with synthetic order book data."""
    return GhostLiquidityAnalyzer.analyze_order_book([], [])

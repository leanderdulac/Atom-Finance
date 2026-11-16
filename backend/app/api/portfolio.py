"""Portfolio Optimisation API endpoints."""

import asyncio
from functools import partial
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.numeric import FiniteFloat
from app.models.portfolio import PortfolioOptimizer

router = APIRouter()


class PortfolioRequest(BaseModel):
    returns: list[list[FiniteFloat]] = Field(..., description="Matrix of returns [n_days × n_assets]")
    asset_names: list[str] | None = None
    risk_free_rate: float = 0.02
    allow_short: bool = False
    shrinkage: Literal["none", "ledoit_wolf"] = "none"


class BlackLittermanRequest(PortfolioRequest):
    views: dict[str, float] = Field(..., description="Absolute return views per asset")
    # Optional market-cap weights keyed by asset name; when absent the model
    # falls back to equal weights. Anchoring the equilibrium to real market caps
    # is the correct BL prior (the old equal-weighted benchmark was arbitrary).
    market_weights: dict[str, float] | None = None
    risk_aversion: float | None = Field(
        default=2.5, description="Exogenous delta (>= 0.5 after clamp); null calibrates from sample means"
    )


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def _run_guarded(func, *args, **kwargs):
    """Domain errors (bad tickers, singular inputs, failed optimisers) are 400s, not 500s."""
    try:
        return await _run_in_thread(func, *args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/efficient-frontier")
async def efficient_frontier(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names, shrinkage=req.shrinkage)
    return await _run_guarded(
        optimizer.markowitz_efficient_frontier,
        risk_free_rate=req.risk_free_rate,
        allow_short=req.allow_short,
    )


@router.post("/max-sharpe")
async def max_sharpe(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names, shrinkage=req.shrinkage)
    return await _run_guarded(optimizer.max_sharpe_ratio, req.risk_free_rate, req.allow_short)


@router.post("/min-variance")
async def min_variance(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names, shrinkage=req.shrinkage)
    return await _run_guarded(optimizer.min_variance, req.allow_short)


@router.post("/risk-parity")
async def risk_parity(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names, shrinkage=req.shrinkage)
    return await _run_guarded(optimizer.risk_parity)


@router.post("/black-litterman")
async def black_litterman(req: BlackLittermanRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names, shrinkage=req.shrinkage)
    return await _run_guarded(
        optimizer.black_litterman, req.views,
        risk_free_rate=req.risk_free_rate, market_weights=req.market_weights,
        risk_aversion=req.risk_aversion,
    )

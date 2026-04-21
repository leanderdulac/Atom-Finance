"""Portfolio Optimisation API endpoints."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.portfolio import PortfolioOptimizer

router = APIRouter()


class PortfolioRequest(BaseModel):
    returns: list[list[float]] = Field(..., description="Matrix of returns [n_days × n_assets]")
    asset_names: Optional[list[str]] = None
    risk_free_rate: float = 0.02
    allow_short: bool = False


class BlackLittermanRequest(PortfolioRequest):
    views: dict[str, float] = Field(..., description="Absolute return views per asset")


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.post("/efficient-frontier")
async def efficient_frontier(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names)
    return await _run_in_thread(
        optimizer.markowitz_efficient_frontier,
        risk_free_rate=req.risk_free_rate,
        allow_short=req.allow_short,
    )


@router.post("/max-sharpe")
async def max_sharpe(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names)
    return await _run_in_thread(optimizer.max_sharpe_ratio, req.risk_free_rate, req.allow_short)


@router.post("/min-variance")
async def min_variance(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names)
    return await _run_in_thread(optimizer.min_variance, req.allow_short)


@router.post("/risk-parity")
async def risk_parity(req: PortfolioRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names)
    return await _run_in_thread(optimizer.risk_parity)


@router.post("/black-litterman")
async def black_litterman(req: BlackLittermanRequest):
    returns = np.array(req.returns)
    optimizer = PortfolioOptimizer(returns, req.asset_names)
    return await _run_in_thread(
        optimizer.black_litterman, req.views, risk_free_rate=req.risk_free_rate
    )

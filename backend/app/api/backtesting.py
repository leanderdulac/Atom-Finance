"""Backtesting API endpoints."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.backtesting import BacktestEngine

router = APIRouter()


class BacktestRequest(BaseModel):
    prices: list[float] = Field(..., min_length=100)
    strategy: str = Field("sma_crossover", pattern="^(sma_crossover|mean_reversion|momentum|rsi)$")
    params: Optional[dict] = None
    initial_capital: float = Field(100_000, gt=0)
    commission: float = Field(0.001, ge=0, le=0.01)


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    return await _run_in_thread(
        BacktestEngine.run_strategy,
        np.array(req.prices),
        req.strategy,
        req.params,
        req.initial_capital,
        req.commission,
    )


@router.post("/compare")
async def compare_strategies(prices: list[float], initial_capital: float = 100_000):
    """Compare all strategies on the same data concurrently."""
    prices_arr = np.array(prices)
    strategies = ["sma_crossover", "mean_reversion", "momentum", "rsi"]

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            None,
            partial(BacktestEngine.run_strategy, prices_arr, s, initial_capital=initial_capital),
        )
        for s in strategies
    ]
    results_list = await asyncio.gather(*tasks)
    return {"comparison": dict(zip(strategies, results_list))}

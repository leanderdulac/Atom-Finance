"""Backtesting API endpoints."""

import asyncio
from functools import partial
from typing import Annotated

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.backtesting import BacktestEngine

router = APIRouter()


class BacktestRequest(BaseModel):
    prices: list[Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(..., min_length=100, max_length=5000)
    strategy: str = Field("sma_crossover", pattern="^(sma_crossover|mean_reversion|momentum|rsi)$")
    params: dict | None = None
    initial_capital: float = Field(100_000, gt=0)
    commission: float = Field(0.001, ge=0, le=0.01, allow_inf_nan=False)
    slippage: float = Field(0.0005, ge=0, le=0.01, allow_inf_nan=False)
    data_source: str = Field("unverified", max_length=200)


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    result = await _run_in_thread(
        BacktestEngine.run_strategy,
        np.array(req.prices),
        req.strategy,
        req.params,
        req.initial_capital,
        req.commission,
        slippage=req.slippage,
    )
    result["data_source"] = req.data_source
    return result


@router.post("/compare")
async def compare_strategies(req: BacktestRequest):
    """Compare all strategies on the same data concurrently."""
    prices_arr = np.array(req.prices)
    strategies = ["sma_crossover", "mean_reversion", "momentum", "rsi"]

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(
            None,
            partial(
                BacktestEngine.run_strategy,
                prices_arr,
                s,
                initial_capital=req.initial_capital,
                commission=req.commission,
                slippage=req.slippage,
            ),
        )
        for s in strategies
    ]
    results_list = await asyncio.gather(*tasks)
    return {"comparison": dict(zip(strategies, results_list, strict=False))}

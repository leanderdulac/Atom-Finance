"""Risk Analysis API endpoints."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.risk import StressTest, ValueAtRisk
from app.models.volatility import EWMAVolatility, GARCHModel, HestonModel

router = APIRouter()


class VaRRequest(BaseModel):
    returns: list[float] = Field(..., min_length=30)
    confidence: float = Field(0.95, ge=0.9, le=0.999)
    portfolio_value: float = Field(1_000_000, gt=0)
    holding_period: int = Field(1, ge=1, le=30)
    method: str = Field("historical", pattern="^(historical|parametric|monte_carlo)$")


class StressTestRequest(BaseModel):
    portfolio: dict[str, float] = Field(..., description="Asset class weights")
    scenario: Optional[str] = None
    portfolio_value: float = Field(1_000_000, gt=0)


class GARCHRequest(BaseModel):
    returns: list[float] = Field(..., min_length=50)
    forecast_horizon: int = Field(30, ge=1, le=252)


class HestonRequest(BaseModel):
    S0: float = Field(100, gt=0)
    v0: float = Field(0.04, gt=0)
    mu: float = 0.05
    kappa: float = Field(2.0, gt=0)
    theta: float = Field(0.04, gt=0)
    xi: float = Field(0.3, gt=0)
    rho: float = Field(-0.7, ge=-1, le=1)
    T: float = Field(1.0, gt=0)
    n_paths: int = Field(10000, ge=100, le=100000)


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.post("/var")
async def calculate_var(req: VaRRequest):
    returns = np.array(req.returns)
    if req.method == "historical":
        return ValueAtRisk.historical(returns, req.confidence, req.portfolio_value, req.holding_period)
    elif req.method == "parametric":
        return ValueAtRisk.parametric(returns, req.confidence, req.portfolio_value, req.holding_period)
    # Monte Carlo is CPU-intensive — run in thread pool
    return await _run_in_thread(
        ValueAtRisk.monte_carlo, returns, req.confidence, req.portfolio_value, req.holding_period
    )


@router.post("/var/all-methods")
async def calculate_var_all(req: VaRRequest):
    returns = np.array(req.returns)
    historical = ValueAtRisk.historical(returns, req.confidence, req.portfolio_value, req.holding_period)
    parametric = ValueAtRisk.parametric(returns, req.confidence, req.portfolio_value, req.holding_period)
    # Run MC concurrently in thread pool
    monte_carlo = await _run_in_thread(
        ValueAtRisk.monte_carlo, returns, req.confidence, req.portfolio_value, req.holding_period
    )
    return {"historical": historical, "parametric": parametric, "monte_carlo": monte_carlo}


@router.post("/stress-test")
async def stress_test(req: StressTestRequest):
    if req.scenario:
        return StressTest.run(req.portfolio, req.scenario, req.portfolio_value)
    return StressTest.run_all(req.portfolio, req.portfolio_value)


@router.post("/garch")
async def fit_garch(req: GARCHRequest):
    returns = np.array(req.returns)

    def _fit_and_forecast():
        model = GARCHModel()
        fit_result = model.fit(returns)
        forecast_result = model.forecast(returns, req.forecast_horizon)
        return {"fit": fit_result, "forecast": forecast_result}

    return await _run_in_thread(_fit_and_forecast)


@router.post("/heston")
async def simulate_heston(req: HestonRequest):
    return await _run_in_thread(
        HestonModel.simulate,
        req.S0, req.v0, req.mu, req.kappa, req.theta, req.xi, req.rho, req.T, req.n_paths,
    )


@router.post("/ewma")
async def ewma_vol(returns: list[float], lambda_: float = 0.94):
    return EWMAVolatility.compute(np.array(returns), lambda_)

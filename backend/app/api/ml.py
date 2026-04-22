"""Machine Learning API endpoints."""

import asyncio
from functools import partial

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.models.ml_models import ARIMAForecast, LSTMPredictor, RandomForestPredictor, TradingDQN

router = APIRouter()


class MLPredictionRequest(BaseModel):
    prices: list[float] = Field(..., min_length=60)
    forecast_days: int = Field(30, ge=1, le=365)
    model: str = Field("lstm", pattern="^(lstm|random_forest|arima|dqn)$")


class ARIMARequest(BaseModel):
    prices: list[float] = Field(..., min_length=30)
    p: int = Field(5, ge=1, le=20)
    d: int = Field(1, ge=0, le=2)
    q: int = Field(0, ge=0, le=5)
    forecast_days: int = Field(30, ge=1, le=365)


async def _run_in_thread(func, *args, **kwargs):
    """Execute a CPU-bound function in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@router.post("/predict")
async def predict(req: MLPredictionRequest):
    prices = np.array(req.prices)
    if req.model == "lstm":
        return await _run_in_thread(LSTMPredictor().predict, prices, req.forecast_days)
    elif req.model == "random_forest":
        return await _run_in_thread(RandomForestPredictor().predict, prices, req.forecast_days)
    elif req.model == "arima":
        return await _run_in_thread(ARIMAForecast.forecast, prices, forecast_days=req.forecast_days)
    elif req.model == "dqn":
        return await _run_in_thread(TradingDQN.generate_signals, prices)


@router.post("/arima")
async def arima_forecast(req: ARIMARequest):
    prices = np.array(req.prices)
    return await _run_in_thread(ARIMAForecast.forecast, prices, req.p, req.d, req.q, req.forecast_days)


@router.post("/trading-signals")
async def trading_signals(prices: list[float]):
    return await _run_in_thread(TradingDQN.generate_signals, np.array(prices))

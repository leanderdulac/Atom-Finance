"""Options Pricing API endpoints."""
import math

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal

from app.models.pricing import (
    BinomialTree,
    BlackScholes,
    FiniteDifference,
    MonteCarlo,
    OptionsStrategies,
    VolatilitySurface,
)

router = APIRouter()


class PricingRequest(BaseModel):
    spot: float = Field(..., description="Current spot price", gt=0)
    strike: float = Field(..., description="Strike price", gt=0)
    maturity: float = Field(..., description="Time to maturity (years)", gt=0)
    rate: float = Field(0.05, description="Risk-free rate")
    sigma: float = Field(0.2, description="Volatility", gt=0)
    option_type: Literal["call", "put"] = "call"
    dividend_yield: float = Field(0.0, description="Continuous dividend yield")


class MonteCarloRequest(PricingRequest):
    n_simulations: int = Field(100000, ge=1000, le=1_000_000)
    n_steps: int = Field(252, ge=10, le=1000)


class BinomialRequest(PricingRequest):
    american: bool = False
    n_steps: int = Field(500, ge=10, le=5000)


class FiniteDiffRequest(PricingRequest):
    american: bool = False
    n_S: int = Field(200, ge=50, le=1000)
    n_t: int = Field(500, ge=50, le=2000)


class IVRequest(BaseModel):
    market_price: float = Field(..., gt=0)
    spot: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    maturity: float = Field(..., gt=0)
    rate: float = 0.05
    option_type: Literal["call", "put"] = "call"


class SurfaceRequest(BaseModel):
    spot: float = Field(..., gt=0)
    rate: float = 0.05
    strikes: list[float] = Field(default_factory=lambda: [80, 85, 90, 95, 100, 105, 110, 115, 120])
    maturities: list[float] = Field(default_factory=lambda: [0.083, 0.25, 0.5, 1.0, 2.0])
    option_type: Literal["call", "put"] = "call"


class StrategyLeg(BaseModel):
    strike: float
    type: Literal["call", "put"]
    position: Literal["long", "short"]
    quantity: int = 1


class StrategyRequest(BaseModel):
    spot: float = Field(..., gt=0)
    sigma: float = 0.2
    rate: float = 0.05
    maturity: float = 0.25
    legs: list[StrategyLeg]


class PresetStrategyRequest(BaseModel):
    spot: float = Field(..., gt=0)
    sigma: float = 0.2
    rate: float = 0.05
    maturity: float = 0.25


@router.post("/black-scholes")
async def price_black_scholes(req: PricingRequest):
    result = BlackScholes.greeks(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, req.dividend_yield)
    return {
        "model": "black_scholes",
        "price": result.price,
        "greeks": {"delta": result.delta, "gamma": result.gamma, "theta": result.theta, "vega": result.vega, "rho": result.rho},
        "inputs": req.model_dump(),
    }


@router.post("/monte-carlo")
async def price_monte_carlo(req: MonteCarloRequest):
    result = MonteCarlo.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, req.n_simulations, req.n_steps, req.dividend_yield)
    return {"model": "monte_carlo", **result, "inputs": req.model_dump()}


@router.post("/binomial")
async def price_binomial(req: BinomialRequest):
    result = BinomialTree.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, req.american, req.n_steps, req.dividend_yield)
    return {"model": "binomial_tree", **result, "inputs": req.model_dump()}


@router.post("/finite-difference")
async def price_finite_difference(req: FiniteDiffRequest):
    result = FiniteDifference.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, req.american, N_S=req.n_S, N_t=req.n_t, q=req.dividend_yield)
    return {"model": "finite_difference", **result, "inputs": req.model_dump()}


@router.post("/implied-volatility")
async def calc_implied_volatility(req: IVRequest):
    iv = BlackScholes.implied_volatility(req.market_price, req.spot, req.strike, req.maturity, req.rate, req.option_type)
    valid = math.isfinite(iv)
    return {
        "implied_volatility": round(iv, 6) if valid else None,
        "iv_pct": round(iv * 100, 2) if valid else None,
        "inputs": req.model_dump(),
    }


@router.post("/volatility-surface")
async def generate_vol_surface(req: SurfaceRequest):
    result = VolatilitySurface.generate(req.spot, req.rate, req.strikes, req.maturities, option_type=req.option_type)
    return result


@router.post("/strategy")
async def analyze_strategy(req: StrategyRequest):
    legs = [leg.model_dump() for leg in req.legs]
    result = OptionsStrategies.analyze_strategy(legs, req.spot, req.sigma, req.rate, req.maturity)
    return {"strategy": "custom", **result}


@router.post("/strategy/straddle")
async def straddle(req: PresetStrategyRequest, strike: float = 100):
    return {"strategy": "straddle", **OptionsStrategies.straddle(req.spot, strike, req.sigma, req.rate, req.maturity)}


@router.post("/strategy/iron-condor")
async def iron_condor(req: PresetStrategyRequest, k1: float = 90, k2: float = 95, k3: float = 105, k4: float = 110):
    return {"strategy": "iron_condor", **OptionsStrategies.iron_condor(req.spot, k1, k2, k3, k4, req.sigma, req.rate, req.maturity)}


@router.post("/strategy/butterfly")
async def butterfly(req: PresetStrategyRequest, k1: float = 90, k2: float = 100, k3: float = 110):
    return {"strategy": "butterfly", **OptionsStrategies.butterfly(req.spot, k1, k2, k3, req.sigma, req.rate, req.maturity)}


@router.post("/compare")
async def compare_models(req: PricingRequest):
    """Compare pricing across all models."""
    bs = BlackScholes.greeks(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, req.dividend_yield)
    mc = MonteCarlo.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, q=req.dividend_yield)
    bt = BinomialTree.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, q=req.dividend_yield)
    fd = FiniteDifference.price(req.spot, req.strike, req.maturity, req.rate, req.sigma, req.option_type, q=req.dividend_yield)

    return {
        "comparison": {
            "black_scholes": bs.price,
            "monte_carlo": mc["price"],
            "binomial_tree": bt["price"],
            "finite_difference": fd["price"],
        },
        "greeks": {"delta": bs.delta, "gamma": bs.gamma, "theta": bs.theta, "vega": bs.vega, "rho": bs.rho},
        "inputs": req.model_dump(),
    }

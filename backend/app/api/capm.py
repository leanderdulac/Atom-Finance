"""CAPM, Kelly Criterion and GBM simulation endpoints."""
import asyncio
from functools import partial
from typing import Optional
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.models.capm import CAPMAnalyzer
from app.models.kelly_derivatives import kelly_derivatives, simular_caminhos_kelly_derivativos

router = APIRouter()


async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


class BetaRequest(BaseModel):
    asset_returns: list[float] = Field(..., min_length=30)
    market_returns: list[float] = Field(..., min_length=30)
    risk_free_rate: float = Field(0.05, ge=0, le=0.2)
    market_premium: float = Field(0.06, ge=0, le=0.2)


class KellyRequest(BaseModel):
    win_rate: float = Field(..., gt=0, lt=1)
    payout_ratio: float = Field(..., gt=0)
    fraction: float = Field(0.5, gt=0, le=1)


class KellyDerivativesRequest(BaseModel):
    win_prob: float = Field(..., gt=0, lt=1, description="Win probability of the options trade")
    payout_ratio: float = Field(..., gt=0, description="Risk/Reward ratio (e.g. 1.5 means winning nets 150% of the premium)")
    bankroll: float = Field(..., gt=0, description="Total capital")
    fraction: float = Field(1.0, gt=0, le=1, description="Full=1.0, Quarter=0.25")


class KellyDerivativesSimRequest(KellyDerivativesRequest):
    num_apostas: int = Field(100, gt=0)
    num_simulacoes: int = Field(10000, gt=0, le=50000)
    seed: Optional[int] = Field(42)


class GBMRequest(BaseModel):
    S0: float = Field(..., gt=0, description="Initial price")
    mu: float = Field(0.08, description="Annual drift (e.g. 0.08 = 8%)")
    sigma: float = Field(0.2, gt=0, description="Annual volatility")
    T: float = Field(1.0, gt=0, description="Time horizon in years")
    n_steps: int = Field(252, ge=10, le=1000)
    n_paths: int = Field(200, ge=10, le=2000)
    seed: Optional[int] = Field(42)


class GBMAsset(BaseModel):
    ticker: str = Field(..., description="Asset ticker (e.g. PETR4)")
    S0: float = Field(..., gt=0, description="Initial price in BRL")
    mu: float = Field(0.10, description="Annual drift")
    sigma: float = Field(0.30, gt=0, description="Annual volatility")


class GBMMultiRequest(BaseModel):
    assets: list[GBMAsset] = Field(..., min_length=1, max_length=10)
    T: float = Field(1.0, gt=0, le=10, description="Horizon in years")
    n_steps: int = Field(252, ge=21, le=1260, description="252=1y, 504=2y …")
    n_paths: int = Field(500, ge=100, le=5000)
    corr_matrix: Optional[list[list[float]]] = Field(
        None, description="d×d correlation matrix. Defaults to identity (independent)."
    )
    seed: Optional[int] = Field(42)


@router.post("/beta")
async def compute_beta(req: BetaRequest):
    result = await _run_in_thread(
        CAPMAnalyzer.compute_beta,
        np.array(req.asset_returns),
        np.array(req.market_returns),
    )
    capm = CAPMAnalyzer.expected_return(result["beta"], req.risk_free_rate, req.market_premium)
    return {**result, "capm": capm}


@router.post("/kelly")
async def kelly_criterion(req: KellyRequest):
    return CAPMAnalyzer.kelly_criterion(req.win_rate, req.payout_ratio, req.fraction)


@router.post("/kelly-derivatives")
async def kelly_deriv_endpoint(req: KellyDerivativesRequest):
    return kelly_derivatives(req.win_prob, req.payout_ratio, req.bankroll, req.fraction)


@router.post("/kelly-derivatives-sim")
async def kelly_deriv_sim_endpoint(req: KellyDerivativesSimRequest):
    return await _run_in_thread(
        simular_caminhos_kelly_derivativos,
        req.win_prob, req.payout_ratio, req.bankroll, req.num_apostas, req.num_simulacoes, req.fraction, req.seed
    )


@router.post("/gbm")
async def gbm_simulation(req: GBMRequest):
    return await _run_in_thread(
        CAPMAnalyzer.gbm_paths,
        req.S0, req.mu, req.sigma, req.T, req.n_steps, req.n_paths, req.seed,
    )


@router.post("/gbm-multi")
async def gbm_multi_simulation(req: GBMMultiRequest):
    """
    **Simulação GBM correlacionada para múltiplos ativos B3.**

    Usa decomposição de Cholesky para gerar trajetórias correlacionadas.
    Retorna média, bandas de confiança (P5/P95) e distribuição terminal por ativo.
    """
    assets = [a.model_dump() for a in req.assets]
    return await _run_in_thread(
        CAPMAnalyzer.gbm_multi_paths,
        assets, req.T, req.n_steps, req.n_paths, req.corr_matrix, req.seed,
    )


@router.get("/gbm-multi/demo")
async def gbm_multi_demo():
    """Demo com ativos B3 pré-configurados: PETR4, VALE3, ITUB4, BBDC4, ABEV3."""
    assets = [
        {"ticker": "PETR4", "S0": 40.0,  "mu": 0.12, "sigma": 0.38},
        {"ticker": "VALE3", "S0": 65.0,  "mu": 0.10, "sigma": 0.32},
        {"ticker": "ITUB4", "S0": 35.0,  "mu": 0.10, "sigma": 0.26},
        {"ticker": "BBDC4", "S0": 15.0,  "mu": 0.08, "sigma": 0.28},
        {"ticker": "ABEV3", "S0": 14.0,  "mu": 0.07, "sigma": 0.22},
    ]
    # Typical B3 cross-asset correlation matrix
    corr = [
        [1.00, 0.45, 0.55, 0.52, 0.30],
        [0.45, 1.00, 0.40, 0.38, 0.25],
        [0.55, 0.40, 1.00, 0.78, 0.35],
        [0.52, 0.38, 0.78, 1.00, 0.32],
        [0.30, 0.25, 0.35, 0.32, 1.00],
    ]
    return await _run_in_thread(
        CAPMAnalyzer.gbm_multi_paths,
        assets, 1.0, 252, 500, corr, 42,
    )


@router.get("/demo")
async def capm_demo():
    """Demo: SPY-like asset vs market benchmark."""
    np.random.seed(99)
    market = np.random.normal(0.0004, 0.012, 252)
    asset = 1.2 * market + np.random.normal(0.0002, 0.008, 252)  # beta ~1.2
    beta_result = CAPMAnalyzer.compute_beta(asset, market)
    capm = CAPMAnalyzer.expected_return(beta_result["beta"])
    kelly = CAPMAnalyzer.kelly_criterion(0.55, 1.8, 0.5)
    gbm = CAPMAnalyzer.gbm_paths(100.0, 0.08, 0.20, 1.0, 252, 100, seed=42)
    return {"beta": beta_result, "capm": capm, "kelly": kelly, "gbm": gbm}

"""
Extreme Value Theory (EVT) API
================================
Endpoints para análise de caudas gordas, VaR/CVaR via GPD/POT e GEV.
"""

import asyncio
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.evt import (
    GeneralizedExtremeValue,
    GeneralizedParetoDistribution,
    compute_evt_risk,
    hill_estimator,
)

router = APIRouter()


# ── Request schemas ───────────────────────────────────────────────────────────

class EVTAnalyzeRequest(BaseModel):
    returns: list[float] = Field(..., description="Série de retornos diários")
    confidence: float = Field(0.99, ge=0.90, le=0.9999)
    threshold_quantile: float = Field(
        0.90, ge=0.80, le=0.99,
        description="Quantil para definir o limiar do POT (ex: 0.90 = top 10% perdas)"
    )
    trading_days_per_year: int = Field(252, ge=200, le=365)


class GEVRequest(BaseModel):
    returns: list[float] = Field(..., description="Série de retornos diários")
    block_size: int = Field(
        63, ge=5, le=252,
        description="Tamanho do bloco em dias (63 ≈ trimestral, 21 ≈ mensal)"
    )


class HillRequest(BaseModel):
    returns: list[float] = Field(..., description="Série de retornos diários")
    k: Optional[int] = Field(None, description="Número de estatísticas de ordem superiores")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def evt_analyze(req: EVTAnalyzeRequest):
    """
    **Análise EVT completa via Peaks Over Threshold (POT / GPD).**

    Retorna VaR e CVaR robustos para distribuições com caudas gordas,
    além de níveis de retorno para horizontes de 10 e 100 anos.
    """
    if len(req.returns) < 50:
        raise HTTPException(status_code=400, detail="Mínimo de 50 observações necessárias.")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                compute_evt_risk,
                np.array(req.returns),
                req.confidence,
                req.threshold_quantile,
                req.trading_days_per_year,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tail_label = (
        "Cauda muito pesada (ξ > 0.5) — risco extremo subestimado pela normal"
        if result.tail_index > 0.5
        else "Cauda moderada (0.2 < ξ ≤ 0.5) — alguma subestimação pelo modelo normal"
        if result.tail_index > 0.2
        else "Cauda leve (ξ ≤ 0.2) — distribuição normal adequada"
    )

    return {
        "method": "GPD / Peaks Over Threshold",
        "confidence": req.confidence,
        "threshold_quantile": req.threshold_quantile,
        "var_evt": round(result.var_evt, 6),
        "cvar_evt": round(result.cvar_evt, 6),
        "normal_var": round(result.normal_var, 6),
        "evt_premium_pct": round(result.evt_premium_pct, 2),
        "tail_index_xi": round(result.tail_index, 4),
        "return_level_10y": round(result.return_level_10y, 6),
        "return_level_100y": round(result.return_level_100y, 6),
        "threshold": round(result.threshold, 6),
        "n_exceedances": result.n_exceedances,
        "exceedance_rate": round(result.exceedance_rate, 4),
        "interpretation": {
            "tail_shape": tail_label,
            "evt_premium": f"EVT-VaR é {result.evt_premium_pct:.1f}% maior que o VaR Normal — risco real de cauda.",
        },
    }


@router.post("/gev")
async def gev_fit(req: GEVRequest):
    """
    **Ajuste GEV via Block Maxima.**

    Divide a série em blocos e ajusta a Distribuição de Valor Extremo
    Generalizada (GEV) aos máximos de cada bloco.
    """
    if len(req.returns) < 100:
        raise HTTPException(status_code=400, detail="Mínimo de 100 observações para Block Maxima.")

    losses = -np.array(req.returns)
    loop = asyncio.get_event_loop()

    try:
        gev = GeneralizedExtremeValue()
        fit = await loop.run_in_executor(None, partial(gev.fit, losses, req.block_size))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Return levels in blocks; convert to years
    trading_days_per_year = 252
    blocks_per_year = trading_days_per_year / req.block_size

    rl_1y = gev.return_level(blocks_per_year)
    rl_5y = gev.return_level(5 * blocks_per_year)
    rl_10y = gev.return_level(10 * blocks_per_year)

    family = (
        "Fréchet (ξ > 0) — caudas pesadas, comum em ações" if fit.xi > 0.05
        else "Gumbel (ξ ≈ 0) — cauda exponencial"
        if abs(fit.xi) <= 0.05
        else "Weibull (ξ < 0) — distribuição com suporte limitado"
    )

    return {
        "method": "GEV / Block Maxima",
        "block_size_days": req.block_size,
        "n_blocks": fit.n_blocks,
        "gev_parameters": {
            "xi_shape": round(fit.xi, 4),
            "mu_location": round(fit.mu, 6),
            "sigma_scale": round(fit.sigma, 6),
        },
        "block_maxima_stats": {
            "mean": round(fit.block_maxima_mean, 6),
            "std": round(fit.block_maxima_std, 6),
        },
        "return_levels": {
            "1y": round(rl_1y, 6),
            "5y": round(rl_5y, 6),
            "10y": round(rl_10y, 6),
        },
        "family": family,
    }


@router.post("/hill")
async def hill_tail_index(req: HillRequest):
    """
    **Estimador de Hill para o índice de cauda.**

    Método não-paramétrico clássico para estimar o expoente da lei de potência
    da cauda (α) e o parâmetro de forma (ξ = 1/α).
    """
    if len(req.returns) < 30:
        raise HTTPException(status_code=400, detail="Mínimo de 30 observações.")

    losses = -np.array(req.returns)
    losses_pos = losses[losses > 0]
    if len(losses_pos) < 10:
        raise HTTPException(status_code=400, detail="Poucas perdas positivas encontradas.")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, partial(hill_estimator, losses_pos, req.k)
    )
    return result


@router.post("/demo")
async def evt_demo():
    """
    **Demo EVT com retornos sintéticos Student-t (caudas gordas).**

    Compara VaR normal vs EVT para evidenciar a subestimação de risco
    em distribuições com fat tails.
    """
    rng = np.random.default_rng(42)
    df = 4                                      # graus de liberdade — caudas muito pesadas
    returns = rng.standard_t(df, size=1000) * 0.01

    result = compute_evt_risk(returns, confidence=0.99, threshold_quantile=0.90)

    return {
        "demo": True,
        "synthetic_distribution": f"Student-t com ν={df} graus de liberdade (caudas pesadas)",
        "n_observations": 1000,
        "results": {
            "evt_var_99pct": round(result.var_evt, 6),
            "normal_var_99pct": round(result.normal_var, 6),
            "evt_premium_pct": round(result.evt_premium_pct, 2),
            "evt_cvar_99pct": round(result.cvar_evt, 6),
            "tail_index_xi": round(result.tail_index, 4),
            "return_level_10y": round(result.return_level_10y, 6),
            "return_level_100y": round(result.return_level_100y, 6),
        },
        "insight": (
            f"O EVT-VaR é {result.evt_premium_pct:.1f}% mais conservador que o VaR Normal, "
            "pois captura o risco real da cauda ignorado pela distribuição gaussiana."
        ),
    }

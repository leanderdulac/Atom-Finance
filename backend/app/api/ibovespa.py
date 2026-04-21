"""
Ibovespa Dashboard API
=======================
Endpoints para simulação GBM + otimização RL (CEM) dos 18 ativos Ibovespa.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.models.ibovespa import (
    IBOVESPA_ASSETS,
    cem_optimize,
    generate_excel_report,
    refresh_ibovespa_params,
    simulate_ibovespa,
)

router = APIRouter()


@router.on_event("startup")
async def startup_event():
    """Update Ibovespa assets on startup (async compatible)."""
    await refresh_ibovespa_params()


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


# ── Request schemas ───────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    n_paths: int = Field(500, ge=100, le=3000)
    T: float = Field(1.0, ge=0.25, le=5.0)
    seed: int | None = Field(42)


class RLRequest(BaseModel):
    profile: Literal["conservador", "agressivo"] = "conservador"
    n_paths: int = Field(500, ge=100, le=3000)
    T: float = Field(1.0, ge=0.25, le=5.0)
    n_iterations: int = Field(60, ge=10, le=200)
    initial_capital: float = Field(100_000.0, gt=0)
    seed: int | None = Field(42)


class ExcelRequest(BaseModel):
    profile: Literal["conservador", "agressivo"] = "conservador"
    n_paths: int = Field(500, ge=100, le=2000)
    T: float = Field(1.0, ge=0.25, le=5.0)
    initial_capital: float = Field(100_000.0, gt=0)
    seed: int | None = Field(42)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/assets")
async def list_assets():
    """Lista os 18 ativos Ibovespa com parâmetros GBM."""
    return {
        "n_assets": len(IBOVESPA_ASSETS),
        "assets": IBOVESPA_ASSETS,
    }


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    """
    **Simulação GBM correlacionada — 18 ativos Ibovespa.**

    Usa matriz de correlação setorial para gerar trajetórias realistas.
    Retorna médias, bandas P5/P95 e distribuição terminal por ativo.
    """
    await refresh_ibovespa_params()   # Background check
    result = await _run(simulate_ibovespa, req.T * 252 // 1, req.n_paths, req.T, req.seed)
    # strip internal numpy array before serialising
    result.pop("_daily_returns", None)
    return result


@router.post("/rl-optimize")
async def rl_optimize(req: RLRequest):
    """
    **Otimização de portfólio por Cross-Entropy Method (CEM / RL).**

    O CEM amostra K portfólios, avalia cada um por uma função de recompensa
    baseada no Sharpe Ratio (penalizada por volatilidade para Conservador ou
    bônus de retorno para Agressivo) e refina a distribuição de busca iterativamente.

    Equivalente a policy-search em RL: o "agente" aprende a distribuição ótima
    de pesos sem gradientes — robusto a funções de recompensa não-diferenciáveis.
    """
    # 1. Ensure latest prices
    await refresh_ibovespa_params()

    # 2. Simulate
    n_steps = int(req.T * 252)
    sim_raw = await _run(simulate_ibovespa, n_steps, req.n_paths, req.T, req.seed)
    daily_returns = sim_raw.pop("_daily_returns")

    # 2. Optimise
    rl: object = await _run(
        cem_optimize,
        daily_returns,
        req.profile,
        req.n_iterations,    # n_iterations
        300,   # n_samples
        0.20,  # elite_fraction
        0.25,  # max_weight per asset
        7,     # seed
    )

    weights_list = rl.weights.tolist()
    allocation = [
        {
            "ticker": rl.tickers[i],
            "sector": IBOVESPA_ASSETS[i]["sector"],
            "weight_pct": round(weights_list[i] * 100, 2),
            "allocation_brl": round(req.initial_capital * weights_list[i], 2),
            "mu_pct": round(IBOVESPA_ASSETS[i]["mu"] * 100, 1),
            "sigma_pct": round(IBOVESPA_ASSETS[i]["sigma"] * 100, 1),
            "expected_return_pct": sim_raw["assets"][i]["terminal"]["expected_return_pct"],
        }
        for i in range(len(rl.tickers))
    ]
    # Sort by weight descending for display
    allocation.sort(key=lambda x: x["weight_pct"], reverse=True)

    sim_raw.pop("_daily_returns", None)

    return {
        "profile": req.profile,
        "initial_capital": req.initial_capital,
        "algorithm": "Cross-Entropy Method (CEM) — RL policy search",
        "iterations": rl.iterations,
        "portfolio_metrics": {
            "expected_return_ann_pct": round(rl.portfolio_return * 100, 2),
            "volatility_ann_pct": round(rl.portfolio_vol * 100, 2),
            "sharpe_ratio": round(rl.sharpe_ratio, 3),
            "expected_terminal_capital": round(req.initial_capital * (1 + rl.portfolio_return), 2),
        },
        "reward_convergence": [round(r, 4) for r in rl.reward_history[::5]],   # every 5 iters
        "allocation": allocation,
        "simulation": sim_raw,
    }


@router.post("/export-excel",
             response_class=Response,
             responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def export_excel(req: ExcelRequest):
    """
    **Gera e baixa relatório Excel completo.**

    3 abas: Portfólio RL (pesos + alocação), Projeções GBM (trajetórias), Métricas de Risco.
    """
    n_steps = int(req.T * 252)
    sim_raw = await _run(simulate_ibovespa, n_steps, req.n_paths, req.T, req.seed)
    daily_returns = sim_raw.pop("_daily_returns")

    rl = await _run(
        cem_optimize, daily_returns, req.profile, 60, 300, 0.20, 0.25, 7,
    )

    xlsx_bytes = await _run(
        generate_excel_report, sim_raw, rl, req.initial_capital, req.profile,
    )

    filename = f"b3_18ativos_{req.profile}_R${int(req.initial_capital)}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/demo")
async def demo():
    """Demo rápido: moderado, 500 simulações, 1 ano."""
    n_steps = 252
    sim_raw = await _run(simulate_ibovespa, n_steps, 300, 1.0, 42)
    daily_returns = sim_raw.pop("_daily_returns")
    rl = await _run(cem_optimize, daily_returns, "conservador", 40, 200, 0.20, 0.25, 7)

    sim_raw.pop("_daily_returns", None)
    return {
        "profile": "conservador",
        "initial_capital": 100_000,
        "portfolio_metrics": {
            "expected_return_ann_pct": round(rl.portfolio_return * 100, 2),
            "volatility_ann_pct": round(rl.portfolio_vol * 100, 2),
            "sharpe_ratio": round(rl.sharpe_ratio, 3),
        },
        "top5_allocation": sorted(
            [{"ticker": t, "weight_pct": round(w * 100, 2)}
             for t, w in zip(rl.tickers, rl.weights)],
            key=lambda x: -x["weight_pct"]
        )[:5],
    }

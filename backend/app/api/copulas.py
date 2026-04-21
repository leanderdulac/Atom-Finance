"""
Copula API
===========
Endpoints para ajuste, simulação e comparação de cópulas multivariadas.
Cópulas isolam a estrutura de dependência dos ativos — essencial para
entender como portfólios colapsam em momentos de crise sistêmica.
"""

import asyncio
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.copulas import (
    ClaytonCopula,
    FrankCopula,
    GaussianCopula,
    GumbelCopula,
    StudentTCopula,
    empirical_copula,
    fit_best_copula,
)

router = APIRouter()

COPULA_MAP = {
    "gaussian": GaussianCopula,
    "student_t": StudentTCopula,
    "clayton": ClaytonCopula,
    "gumbel": GumbelCopula,
    "frank": FrankCopula,
}


# ── Request schemas ───────────────────────────────────────────────────────────

class CopulaFitRequest(BaseModel):
    returns: list[list[float]] = Field(
        ...,
        description="Matriz n×d de retornos (n observações, d ativos). Ex: [[r1_a1, r1_a2], [r2_a1, r2_a2], ...]"
    )
    copula_type: str = Field(
        "auto",
        description="Tipo de cópula: auto | gaussian | student_t | clayton | gumbel | frank"
    )


class CopulaSimulateRequest(BaseModel):
    copula_type: str = Field(..., description="Tipo de cópula a simular")
    parameters: dict = Field(..., description="Parâmetros da cópula (retornados pelo /fit)")
    n_samples: int = Field(1000, ge=100, le=50_000)


class TailDependenceRequest(BaseModel):
    returns: list[list[float]] = Field(..., description="Matriz n×2 de retornos bivariados")
    quantile: float = Field(0.05, ge=0.01, le=0.20, description="Quantil de cauda (ex: 0.05 = 5%)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tail_dependence_empirical(u: np.ndarray, q: float) -> dict:
    """Coeficientes de dependência de cauda empíricos."""
    u1, u2 = u[:, 0], u[:, 1]
    lower = float(np.mean((u1 <= q) & (u2 <= q)) / q)
    upper = float(np.mean((u1 > 1 - q) & (u2 > 1 - q)) / q)
    return {
        "lower_tail_dependence_empirical": round(lower, 4),
        "upper_tail_dependence_empirical": round(upper, 4),
        "quantile_used": q,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/fit")
async def fit_copula(req: CopulaFitRequest):
    """
    **Ajusta cópula(s) a dados multivariados de retornos.**

    Com `copula_type="auto"` testa todos os modelos disponíveis e seleciona
    o melhor por AIC.  Retorna parâmetros, log-verossimilhança, AIC/BIC e
    coeficientes de dependência de cauda (λ_L e λ_U).
    """
    data = np.array(req.returns, dtype=float)
    if data.ndim != 2 or data.shape[1] < 2:
        raise HTTPException(status_code=400, detail="É necessária uma matriz n×d com d ≥ 2 ativos.")
    if data.shape[0] < 50:
        raise HTTPException(status_code=400, detail="Mínimo de 50 observações necessárias.")
    if req.copula_type not in ("auto", *COPULA_MAP):
        raise HTTPException(status_code=400, detail=f"Tipo desconhecido. Use: auto, {', '.join(COPULA_MAP)}.")
    if req.copula_type in ("clayton", "gumbel", "frank") and data.shape[1] != 2:
        raise HTTPException(status_code=400, detail=f"'{req.copula_type}' suporta apenas 2 ativos.")

    u = empirical_copula(data)
    loop = asyncio.get_event_loop()

    try:
        if req.copula_type == "auto":
            results = await loop.run_in_executor(None, partial(fit_best_copula, u))
        else:
            copula = COPULA_MAP[req.copula_type]()
            fit = await loop.run_in_executor(None, partial(copula.fit, u))
            results = {
                req.copula_type: {
                    "parameters": fit.parameters,
                    "log_likelihood": round(fit.log_likelihood, 4),
                    "aic": round(fit.aic, 4),
                    "bic": round(fit.bic, 4),
                    "lower_tail_dependence": round(fit.lower_tail_dependence, 4),
                    "upper_tail_dependence": round(fit.upper_tail_dependence, 4),
                    "interpretation": fit.interpretation,
                },
                "best_copula": req.copula_type,
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Empirical tail dependence (always computed)
    emp_td = {}
    if data.shape[1] == 2:
        emp_td = _tail_dependence_empirical(u, q=0.05)

    return {
        "n_observations": data.shape[0],
        "n_assets": data.shape[1],
        "copula_results": results,
        "empirical_tail_dependence": emp_td,
    }


@router.post("/simulate")
async def simulate_copula(req: CopulaSimulateRequest):
    """
    **Simula amostras a partir de uma cópula parametrizada.**

    Use os parâmetros retornados por `/fit` para gerar cenários correlacionados.
    As amostras estão na escala uniforme (0,1) — aplique a inversa das marginais
    desejadas para obter retornos simulados.
    """
    if req.copula_type not in COPULA_MAP:
        raise HTTPException(status_code=400, detail=f"Tipo desconhecido. Use: {', '.join(COPULA_MAP)}.")

    loop = asyncio.get_event_loop()
    params = req.parameters

    try:
        if req.copula_type == "gaussian":
            corr = np.array(params.get("correlation_matrix", [[1.0, 0.5], [0.5, 1.0]]))
            cop = GaussianCopula()
            cop.corr_matrix = corr
            samples = await loop.run_in_executor(None, partial(cop.simulate, req.n_samples, corr))

        elif req.copula_type == "student_t":
            corr = np.array(params.get("correlation_matrix", [[1.0, 0.5], [0.5, 1.0]]))
            df = float(params.get("df", 5.0))
            cop = StudentTCopula()
            cop.corr_matrix = corr
            cop.df = df
            samples = await loop.run_in_executor(None, partial(cop.simulate, req.n_samples))

        elif req.copula_type == "clayton":
            cop = ClaytonCopula()
            cop.theta = float(params.get("theta", 2.0))
            samples = await loop.run_in_executor(None, partial(cop.simulate, req.n_samples))

        elif req.copula_type == "gumbel":
            cop = GumbelCopula()
            cop.theta = float(params.get("theta", 2.0))
            samples = await loop.run_in_executor(None, partial(cop.simulate, req.n_samples))

        else:  # frank
            cop = FrankCopula()
            cop.theta = float(params.get("theta", 3.0))
            samples = await loop.run_in_executor(None, partial(cop.simulate, req.n_samples))

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    corr_sample = float(np.corrcoef(samples.T)[0, 1]) if samples.shape[1] == 2 else None
    td_emp = _tail_dependence_empirical(samples, q=0.05) if samples.shape[1] == 2 else {}

    return {
        "copula_type": req.copula_type,
        "n_samples": req.n_samples,
        "sample_correlation": corr_sample,
        "empirical_tail_dependence": td_emp,
        "samples": samples.tolist(),
    }


@router.post("/tail-dependence")
async def tail_dependence(req: TailDependenceRequest):
    """
    **Coeficientes de dependência de cauda empíricos (bivariado).**

    Quantifica a probabilidade condicional de colapso conjunto.
    λ_L alto → ativos crasham juntos.  λ_U alto → ativos explodem juntos.
    """
    data = np.array(req.returns, dtype=float)
    if data.shape[1] != 2:
        raise HTTPException(status_code=400, detail="Este endpoint suporta apenas dados bivariados (2 ativos).")
    if data.shape[0] < 30:
        raise HTTPException(status_code=400, detail="Mínimo de 30 observações.")

    u = empirical_copula(data)
    td = _tail_dependence_empirical(u, q=req.quantile)

    lower = td["lower_tail_dependence_empirical"]
    upper = td["upper_tail_dependence_empirical"]

    return {
        **td,
        "interpretation": {
            "lower": (
                f"λ_L = {lower:.3f} — forte correlação em crashes" if lower > 0.30
                else f"λ_L = {lower:.3f} — correlação moderada em quedas"
                if lower > 0.10
                else f"λ_L = {lower:.3f} — baixa dependência em quedas"
            ),
            "upper": (
                f"λ_U = {upper:.3f} — forte correlação em booms" if upper > 0.30
                else f"λ_U = {upper:.3f} — correlação moderada em altas"
                if upper > 0.10
                else f"λ_U = {upper:.3f} — baixa dependência em altas"
            ),
        },
    }


@router.post("/demo")
async def copula_demo():
    """
    **Demo: comparação de cópulas com dados sintéticos correlacionados.**

    Mostra como diferentes cópulas capturam estruturas de dependência
    distintas no mesmo conjunto de dados — e como divergem nas caudas.
    """
    rng = np.random.default_rng(42)
    n = 600
    rho = 0.65

    # Correlated Gaussian returns as base
    corr_mat = np.array([[1.0, rho], [rho, 1.0]])
    L = np.linalg.cholesky(corr_mat)
    z = rng.standard_normal((n, 2))
    x = z @ L.T * 0.01

    u = empirical_copula(x)
    results = fit_best_copula(u)
    td_emp = _tail_dependence_empirical(u, q=0.05)

    # Build comparison table
    comparison = {}
    for name, res in results.items():
        if name == "best_copula":
            continue
        if "error" not in res:
            comparison[name] = {
                "aic": res.get("aic"),
                "lambda_L": res.get("lower_tail_dependence"),
                "lambda_U": res.get("upper_tail_dependence"),
                "interpretation": res.get("interpretation", ""),
            }

    return {
        "demo": True,
        "n_observations": n,
        "n_assets": 2,
        "input_pearson_correlation": rho,
        "best_copula": results.get("best_copula"),
        "copula_comparison": comparison,
        "empirical_tail_dependence": td_emp,
        "insight": (
            "A cópula de Clayton captura crashes simultâneos (λ_L > 0). "
            "A de Gumbel captura booms simultâneos (λ_U > 0). "
            "A Gaussiana e Frank assumem ausência de clustering de cauda. "
            "A Student-t modela AMBAS as caudas — comum em crises financeiras sistêmicas."
        ),
    }

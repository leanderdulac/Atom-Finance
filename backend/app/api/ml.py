"""Evidence-first financial ML research; no unvalidated forecast endpoints."""
import asyncio
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.limiter import limiter
from app.core.quant_doctrine import DOCTRINE_VERSION, TENETS
from app.core.security import get_current_user
from app.db import experiments
from app.models.research_validation import FEATURES, POLICY_VERSION, evaluate_experiment

router = APIRouter(dependencies=[Depends(get_current_user)])
PositivePrice = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    prices: list[PositivePrice] = Field(min_length=400, max_length=5000)
    dates: list[date] = Field(min_length=400, max_length=5000)
    model: Literal['ridge', 'random_forest'] = 'ridge'
    hypothesis: str = Field(min_length=30, max_length=2000)
    data_source: str = Field(min_length=3, max_length=200)
    price_basis: Literal['adjusted', 'unverified'] = 'unverified'
    commission_bps: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    slippage_bps: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    target_volatility: float = Field(default=0.10, gt=0, le=0.50, allow_inf_nan=False)
    max_drawdown: float = Field(default=0.20, gt=0, le=0.50, allow_inf_nan=False)
    n_splits: int = Field(default=4, ge=3, le=6)
    gap_groups: int = Field(default=1, ge=1, le=3)

    @model_validator(mode='after')
    def chronological(self):
        if len(self.prices) != len(self.dates):
            raise ValueError('Datas e preços devem ter o mesmo tamanho.')
        if any(a >= b for a, b in zip(self.dates, self.dates[1:], strict=False)):
            raise ValueError('Datas devem ser únicas e estritamente crescentes.')
        if self.dates[-1] > date.today():
            raise ValueError('Não é permitido enviar observações futuras.')
        return self


@router.get('/policy')
async def policy():
    return {
        'version': POLICY_VERSION,
        'doctrine_version': DOCTRINE_VERSION,
        'features': FEATURES,
        'eligible_for_live_trading': False,
        'tenets': TENETS,
        'rules': [
            'Hipótese econômica antes do modelo.',
            'Treino cronológico com purga e intervalo entre grupos.',
            'Comparação OOS com baselines, custos, turnover e risco.',
            'Dados sintéticos explicitamente identificados.',
            'Revisão independente antes de qualquer promoção.',
            'O aleatório é a base do sinal; desconte a maldição do vencedor.',
            'Backtest pesquisa; evidência é sequencial.',
            'Alvo é retorno ou regime, nunca o print.',
            'Série de preço se vetoriza; for i in range(len(df)) / .iloc[i] vaza e não escala.',
        ],
    }


@router.post('/evaluate')
@limiter.limit('5/minute')
async def evaluate(request: Request, req: ExperimentRequest, owner: str = Depends(get_current_user)):
    inputs = req.model_dump(mode='json')
    run_id = await experiments.begin(owner, inputs)
    try:
        result = await asyncio.to_thread(evaluate_experiment, **inputs)
    except ValueError as exc:
        await experiments.finish(run_id, error=str(exc))
        raise HTTPException(422, str(exc)) from None
    except Exception:
        await experiments.finish(run_id, error='Falha no processamento. Crie uma nova tentativa para repetir.')
        raise HTTPException(500, 'Experimento falhou; tentativa preservada no diário.') from None
    result['run_id'] = run_id
    await experiments.finish(run_id, result=result)
    return result


@router.get('/experiments')
async def history(owner: str = Depends(get_current_user), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return await experiments.history(owner, limit, offset)


@router.get('/experiments/{run_id}')
async def detail(run_id: str, owner: str = Depends(get_current_user)):
    item = await experiments.detail(owner, run_id)
    if item is None: raise HTTPException(404, 'Experimento não encontrado.')
    return item


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    decision: Literal['discard', 'investigate']
    rationale: str = Field(min_length=20, max_length=2000)


@router.post('/experiments/{run_id}/reviews')
async def review(run_id: str, req: ReviewRequest, owner: str = Depends(get_current_user)):
    if not await experiments.review(owner, run_id, req.decision, req.rationale):
        raise HTTPException(404, 'Experimento concluído não encontrado.')
    return await experiments.detail(owner, run_id)


@router.post('/predict')
@router.post('/arima')
@router.post('/trading-signals')
async def legacy_forecast():
    raise HTTPException(410, 'Simulações legadas sem validação foram retiradas. Use /api/ml/evaluate para pesquisa fora da amostra.')

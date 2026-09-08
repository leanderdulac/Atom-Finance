"""Evidence-first financial ML research; no unvalidated forecast endpoints."""
import asyncio
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.limiter import limiter
from app.core.security import get_current_user
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
        if any(a >= b for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError('Datas devem ser únicas e estritamente crescentes.')
        if self.dates[-1] > date.today():
            raise ValueError('Não é permitido enviar observações futuras.')
        return self


@router.get('/policy')
async def policy():
    return {'version': POLICY_VERSION, 'features': FEATURES, 'eligible_for_live_trading': False,
            'rules': ['Hipótese econômica antes do modelo.', 'Treino cronológico com purga e intervalo entre grupos.',
                      'Comparação OOS com baselines, custos, turnover e risco.',
                      'Dados sintéticos explicitamente identificados.', 'Revisão independente antes de qualquer promoção.']}


@router.post('/evaluate')
@limiter.limit('5/minute')
async def evaluate(request: Request, req: ExperimentRequest):
    try:
        return await asyncio.to_thread(evaluate_experiment, **req.model_dump(mode='json'))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/predict')
@router.post('/arima')
@router.post('/trading-signals')
async def legacy_forecast():
    raise HTTPException(410, 'Simulações legadas sem validação foram retiradas. Use /api/ml/evaluate para pesquisa fora da amostra.')

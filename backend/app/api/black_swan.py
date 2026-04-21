"""Black Swan Detection API endpoints."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
import numpy as np
from app.models.black_swan import BlackSwanDetector

router = APIRouter()


class TailRiskRequest(BaseModel):
    returns: list[float] = Field(..., min_length=30)


class NewsAnalysisRequest(BaseModel):
    articles: Optional[list[dict]] = None


class CombinedAnalysisRequest(BaseModel):
    returns: list[float] = Field(..., min_length=30)
    articles: Optional[list[dict]] = None


@router.post("/tail-risk")
async def analyze_tail_risk(req: TailRiskRequest):
    return BlackSwanDetector.analyze_tail_risk(np.array(req.returns))


@router.post("/regime-change")
async def detect_regime_change(req: TailRiskRequest):
    return BlackSwanDetector.detect_regime_change(np.array(req.returns))


@router.post("/news-sentiment")
async def analyze_news(req: NewsAnalysisRequest):
    return BlackSwanDetector.analyze_news_sentiment(req.articles)


@router.post("/full-analysis")
async def full_analysis(req: CombinedAnalysisRequest):
    return BlackSwanDetector.combined_analysis(np.array(req.returns), req.articles)


@router.get("/demo")
async def demo_analysis():
    """Run demo with synthetic data."""
    np.random.seed(42)
    returns = np.random.normal(0.0003, 0.015, 500)
    # Add some fat tails
    returns[100] = -0.08
    returns[250] = -0.06
    returns[400] = 0.07
    return BlackSwanDetector.combined_analysis(returns)

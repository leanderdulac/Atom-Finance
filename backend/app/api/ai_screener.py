from fastapi import APIRouter, HTTPException
from typing import List, Dict
import asyncio
import logging
from datetime import datetime
from app.models.ibovespa import IBOVESPA_ASSETS
from app.api.ai_report import _full_analysis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/screener", tags=["Screener"])

# Cache simple: ticker -> result, timestamp
_SCREENER_CACHE: Dict[str, dict] = {}
_LAST_SCREEN_TIME: datetime | None = None

@router.get("/top-picks")
async def get_top_picks():
    """
    Analyzes the 18 main Ibovespa assets using the Multi-AI 'Dream Team'.
    Ranks them by Bull Score and returns the top 5 high-conviction opportunities.
    """
    global _LAST_SCREEN_TIME, _SCREENER_CACHE
    
    now = datetime.now()
    # Simple 1-hour cache to avoid massive API costs and wait times
    if _LAST_SCREEN_TIME and (now - _LAST_SCREEN_TIME).total_seconds() < 3600:
        logger.info("Returning cached AI Screener results.")
        return sorted(_SCREENER_CACHE.values(), key=lambda x: x["model_scores"]["bull_score"], reverse=True)[:6]

    logger.info("Starting Global AI Screener for 18 B3 assets...")
    
    # We run the 18 analyses in parallel (asynchronously)
    # Caution: This will be very fast but will hit 6 different AI providers simultaneously 18 times.
    # Total of 108 AI calls in a single batch.
    tickers = [asset["ticker"] for asset in IBOVESPA_ASSETS]
    
    tasks = [_full_analysis(ticker) for ticker in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_results = []
    for ticker, res in zip(tickers, results):
        if isinstance(res, Exception):
            logger.error(f"Error screening {ticker}: {res}")
            continue
        
        # Store in cache
        _SCREENER_CACHE[ticker] = res
        valid_results.append(res)
    
    _LAST_SCREEN_TIME = now
    
    # Return Top 6 high conviction picks
    top_picks = sorted(valid_results, key=lambda x: x["model_scores"]["bull_score"], reverse=True)[:6]
    return top_picks

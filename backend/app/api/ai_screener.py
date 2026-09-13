import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.api.ai_report import _full_analysis
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.models.ibovespa import IBOVESPA_ASSETS

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])

# Cache simple: ticker -> result, timestamp
_SCREENER_CACHE: dict[str, dict] = {}
_LAST_SCREEN_TIME: datetime | None = None
# Guards the check-then-refresh below: without it, two requests arriving while
# the cache is stale can each kick off their own 108-call AI batch concurrently.
_SCREEN_LOCK = asyncio.Lock()

@router.get("/top-picks")
@limiter.limit("2/hour")
async def get_top_picks(request: Request, max_tickers: int = 6):
    """
    Screens Ibovespa names with the multi-model report pipeline.
    Default 6 tickers (~36 LLM calls). Cached 1 hour. Hard-capped at 2 runs/hour/user.
    """
    global _LAST_SCREEN_TIME, _SCREENER_CACHE
    max_tickers = max(1, min(max_tickers, 18))

    async with _SCREEN_LOCK:
        now = datetime.now()
        # Simple 1-hour cache to avoid massive API costs and wait times
        if _LAST_SCREEN_TIME and (now - _LAST_SCREEN_TIME).total_seconds() < 3600:
            logger.info("Returning cached AI Screener results.")
            return sorted(_SCREENER_CACHE.values(), key=lambda x: x["model_scores"]["bull_score"], reverse=True)[:6]

        logger.info("Starting Global AI Screener for 18 B3 assets...")

        # We run the 18 analyses in parallel (asynchronously)
        # Caution: This will be very fast but will hit 6 different AI providers simultaneously 18 times.
        # Total of 108 AI calls in a single batch.
        tickers = [asset["ticker"] for asset in IBOVESPA_ASSETS][:max_tickers]

        tasks = [_full_analysis(ticker) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for ticker, res in zip(tickers, results, strict=False):
            if isinstance(res, BaseException):
                logger.error(f"Error screening {ticker}: {res}")
                continue

            # Store in cache
            _SCREENER_CACHE[ticker] = res
            valid_results.append(res)

        _LAST_SCREEN_TIME = now

        # Return Top 6 high conviction picks
        top_picks = sorted(valid_results, key=lambda x: x["model_scores"]["bull_score"], reverse=True)[:6]
        return top_picks

"""
ATOM - Quantitative Finance Platform
Main FastAPI Application
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

load_dotenv()

from app.api import (  # noqa: E402
    ai_proxy_router,
    ai_report_router,
    ai_screener_router,
    auth_router,
    autopilot_router,
    backtesting_router,
    binance_router,
    black_swan_router,
    capm_router,
    copulas_router,
    evt_router,
    ghost_liquidity_router,
    hedge_router,
    ibovespa_router,
    market_data_router,
    ml_router,
    neural_sde_router,
    options_router,
    portfolio_router,
    pricing_router,
    reports_router,
    risk_router,
)
from app.api.research import router as research_router
from app.core.cache import Cache  # noqa: E402
from app.core.limiter import limiter
from app.core.runtime import exclusive_runtime
from app.core.security import get_current_user
from app.db.database import readiness

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Shared rate limiter instance
# (Moved to app.core.limiter to allow router imports)


def _parse_origins() -> list[str]:
    """Support comma-separated ALLOWED_ORIGINS or single FRONTEND_URL."""
    raw = os.getenv("ALLOWED_ORIGINS") or os.getenv("FRONTEND_URL", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174")
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("ATOM Quantitative Finance Platform starting…")
    if Cache.is_redis_available():
        logger.info("Cache backend: Redis")
    else:
        logger.warning("Cache backend: in-memory (Redis not available)")
    with exclusive_runtime():
        yield
    logger.info("ATOM shutting down…")


app = FastAPI(
    title="ATOM - Quantitative Finance Platform",
    description=(
        "Advanced quantitative finance tools: options pricing, risk analysis, "
        "portfolio optimisation, purged walk-forward research, Neural SDE, "
        "ghost liquidity & black swan detection."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ATOM_ENV") == "production" else "/docs",
    redoc_url=None if os.getenv("ATOM_ENV") == "production" else "/redoc",
    openapi_url=None if os.getenv("ATOM_ENV") == "production" else "/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
from slowapi import _rate_limit_exceeded_handler

# This is slowapi's own documented FastAPI integration pattern; the handler's
# signature is narrower than FastAPI's generic ExceptionHandler type.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected = APIRouter(dependencies=[Depends(get_current_user)])
from app.api.market_sources import router as market_sources_router

protected.include_router(market_sources_router, prefix="/api/sources", tags=["Market Sources"])
from app.api.derivatives import router as derivatives_router

protected.include_router(derivatives_router, prefix="/api/derivatives", tags=["Derivatives Planner"])

protected.include_router(research_router, prefix="/api/research", tags=["Research"])

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router,            prefix="/api/auth",          tags=["Authentication"])
protected.include_router(pricing_router,         prefix="/api/pricing",       tags=["Options Pricing"])
protected.include_router(risk_router,            prefix="/api/risk",          tags=["Risk Analysis"])
protected.include_router(hedge_router,           prefix="/api/hedge",         tags=["Dynamic Hedge"])
protected.include_router(portfolio_router,       prefix="/api/portfolio",     tags=["Portfolio Optimisation"])
protected.include_router(ml_router,              prefix="/api/ml",            tags=["Machine Learning"])
protected.include_router(neural_sde_router,      prefix="/api/neural-sde",    tags=["Neural SDE"])
protected.include_router(ghost_liquidity_router, prefix="/api/ghost-liquidity", tags=["Ghost Liquidity"])
protected.include_router(black_swan_router,      prefix="/api/black-swan",    tags=["Black Swan Detection"])
protected.include_router(market_data_router,     prefix="/api/market-data",   tags=["Market Data"])
protected.include_router(ibovespa_router,        prefix="/api/ibovespa",      tags=["Ibovespa Dashboard"])
protected.include_router(options_router,         prefix="/api/ai/options-expert", tags=["AI Options Agent"])
protected.include_router(reports_router,         prefix="/api/reports",       tags=["Reports"])
protected.include_router(backtesting_router,     prefix="/api/backtesting",   tags=["Backtesting"])
protected.include_router(capm_router,            prefix="/api/capm",          tags=["CAPM & Kelly"])
protected.include_router(evt_router,             prefix="/api/evt",           tags=["Extreme Value Theory"])
protected.include_router(copulas_router,         prefix="/api/copulas",       tags=["Copulas"])
protected.include_router(ai_report_router,       prefix="/api/reports",       tags=["AI Analysis"])
protected.include_router(ai_screener_router,     prefix="/api/screener",      tags=["AI Screener"])
protected.include_router(autopilot_router,       prefix="/api/autopilot",     tags=["Autopilot"])
protected.include_router(binance_router,         prefix="/api/binance",       tags=["Binance Crypto"])
protected.include_router(ai_proxy_router,        prefix="/api/ai",            tags=["AI Proxy"])


from app.api.paper_trades import router as paper_trades_router

protected.include_router(paper_trades_router, prefix="/api/paper-trades", tags=["Paper Trading"])
app.include_router(protected)

@app.middleware("http")
async def response_security(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/live")
@limiter.exempt
def live():
    return {"status": "alive"}


@app.get("/api/health")
@limiter.exempt
def health_check():
    try:
        readiness()
    except Exception:
        logger.exception("Database readiness failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "healthy"}

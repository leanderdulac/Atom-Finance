"""
ATOM - Quantitative Finance Platform
Main FastAPI Application
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

from app.api import (  # noqa: E402
    ai_screener_router,
    ai_report_router,
    autopilot_router,
    auth_router,
    binance_router,
    backtesting_router,
    black_swan_router,
    capm_router,
    copulas_router,
    evt_router,
    hedge_router,
    ibovespa_router,
    ghost_liquidity_router,
    market_data_router,
    ml_router,
    neural_sde_router,
    options_router,
    portfolio_router,
    pricing_router,
    reports_router,
    risk_router,
    ai_proxy_router,
)
from app.core.cache import Cache  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate limiter (shared instance imported by routers) ────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


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
    yield
    logger.info("ATOM shutting down…")


app = FastAPI(
    title="ATOM - Quantitative Finance Platform",
    description=(
        "Advanced quantitative finance tools: options pricing, risk analysis, "
        "portfolio optimisation, ML forecasting, Neural SDE, "
        "ghost liquidity & black swan detection."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router,            prefix="/api/auth",          tags=["Authentication"])
app.include_router(pricing_router,         prefix="/api/pricing",       tags=["Options Pricing"])
app.include_router(risk_router,            prefix="/api/risk",          tags=["Risk Analysis"])
app.include_router(hedge_router,           prefix="/api/hedge",         tags=["Dynamic Hedge"])
app.include_router(portfolio_router,       prefix="/api/portfolio",     tags=["Portfolio Optimisation"])
app.include_router(ml_router,              prefix="/api/ml",            tags=["Machine Learning"])
app.include_router(neural_sde_router,      prefix="/api/neural-sde",    tags=["Neural SDE"])
app.include_router(ghost_liquidity_router, prefix="/api/ghost-liquidity", tags=["Ghost Liquidity"])
app.include_router(black_swan_router,      prefix="/api/black-swan",    tags=["Black Swan Detection"])
app.include_router(market_data_router,     prefix="/api/market-data",   tags=["Market Data"])
app.include_router(ibovespa_router,        prefix="/api/ibovespa",      tags=["Ibovespa Dashboard"])
app.include_router(options_router,         prefix="/api/ai/options-expert", tags=["AI Options Agent"])
app.include_router(reports_router,         prefix="/api/reports",       tags=["Reports"])
app.include_router(backtesting_router,     prefix="/api/backtesting",   tags=["Backtesting"])
app.include_router(capm_router,            prefix="/api/capm",          tags=["CAPM & Kelly"])
app.include_router(evt_router,             prefix="/api/evt",           tags=["Extreme Value Theory"])
app.include_router(copulas_router,         prefix="/api/copulas",       tags=["Copulas"])
app.include_router(ai_report_router,       prefix="/api/reports",       tags=["AI Analysis"])
app.include_router(ai_screener_router,     prefix="/api/screener",      tags=["AI Screener"])
app.include_router(autopilot_router,       prefix="/api/autopilot",     tags=["Autopilot"])
app.include_router(binance_router,         prefix="/api/binance",       tags=["Binance Crypto"])
app.include_router(ai_proxy_router,        prefix="/api/ai",            tags=["AI Proxy"])


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": "ATOM",
        "version": "1.0.0",
        "cache": "redis" if Cache.is_redis_available() else "memory",
    }

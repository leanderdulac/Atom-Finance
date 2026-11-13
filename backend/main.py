"""
ATOM - Quantitative Finance Platform
Main FastAPI Application
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

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
from app.core.observability import configure_logging, init_sentry, request_id_middleware
from app.core.runtime import exclusive_runtime
from app.core.security import get_current_user
from app.db.database import readiness
from app.db.postgres import close_pool

configure_logging()
init_sentry()
logger = logging.getLogger(__name__)

# Shared rate limiter instance
# (Moved to app.core.limiter to allow router imports)


def _parse_origins() -> list[str]:
    """Support comma-separated ALLOWED_ORIGINS or single FRONTEND_URL."""
    raw = os.getenv("ALLOWED_ORIGINS") or os.getenv(
        "FRONTEND_URL",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:4173,http://127.0.0.1:4173",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("ATOM Quantitative Finance Platform starting…")
    if Cache.is_redis_available():
        logger.info("Cache backend: Redis")
    else:
        logger.warning("Cache backend: in-memory (Redis not available)")
    job_tasks: list[asyncio.Task] = []
    async with exclusive_runtime():
        from app.services.regime_job import job_enabled
        from app.services.regime_job import loop as regime_loop
        if job_enabled():
            job_tasks.append(asyncio.create_task(regime_loop(), name="regime-job"))
            logger.info("Regime 4h job started")
        from app.services.client_arsenal import job_enabled as client_job_enabled
        from app.services.client_arsenal import loop as client_arsenal_loop
        if client_job_enabled():
            job_tasks.append(asyncio.create_task(client_arsenal_loop(), name="client-arsenal"))
            logger.info("Client arsenal cache job started")
        from app.services.context_job import job_enabled as context_job_enabled
        from app.services.context_job import loop as context_job_loop
        if context_job_enabled():
            job_tasks.append(asyncio.create_task(context_job_loop(), name="context-prewarm"))
            logger.info("Context prewarm job started")
        try:
            yield
        finally:
            for job_task in job_tasks:
                job_task.cancel()
                try:
                    await job_task
                except asyncio.CancelledError:
                    pass
    await close_pool()
    logger.info("ATOM shutting down…")


app = FastAPI(
    title="ATOM - Quantitative Finance Platform",
    description=(
        "Advanced quantitative finance tools: options pricing, risk analysis, "
        "portfolio optimisation, purged walk-forward research, Neural SDE, "
        "tail-risk diagnostics, and from-scratch desk papers "
        "(Heston CF, Engle–Granger, Avellaneda–Stoikov, Fama–French 5, scanners)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ATOM_ENV") == "production" else "/docs",
    redoc_url=None if os.getenv("ATOM_ENV") == "production" else "/redoc",
    openapi_url=None if os.getenv("ATOM_ENV") == "production" else "/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
# Added first so it's outermost (Starlette runs the first-added middleware
# first on the way in, last on the way out): every other layer below —
# SlowAPI, CORS, the request itself — runs with the request id already set,
# so their log lines (and any error Sentry captures) carry it too.
app.middleware("http")(request_id_middleware)
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

# ── Prometheus instrumentação ────────────────────────────────────────────────
# Registered after CORS and before the guard middlewares below so the metrics
# middleware also records 413s — outermost of the function middlewares. Route
# labels are templates (bounded cardinality); /api/metrics fails closed.
from app.api.metrics import metrics_middleware
from app.api.metrics import router as metrics_router

app.middleware("http")(metrics_middleware)
app.include_router(metrics_router, prefix="/api", tags=["Observability"])

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


from app.api.desk import router as desk_router
from app.api.paper_trades import router as paper_trades_router

protected.include_router(paper_trades_router, prefix="/api/paper-trades", tags=["Paper Trading"])
protected.include_router(desk_router, prefix="/api/desk", tags=["Quant Desk"])
from app.api.client import router as client_router

# /api/client/config is public (landing). The remaining client routes still
# declare Depends(get_current_user) on the router in client.py except config.
app.include_router(client_router, prefix="/api/client", tags=["Client"])
app.include_router(protected)

@app.middleware("http")
async def client_mode_guard(request, call_next):
    """When ATOM_CLIENT_MODE is on, non-operators cannot hit the desk APIs."""
    from app.core.client_mode import client_may_access, client_mode_enabled, is_operator_role
    if request.method == "OPTIONS" or not client_mode_enabled():
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") or client_may_access(path):
        return await call_next(request)
    auth = request.headers.get("authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        return await call_next(request)
    from app.core.security import decode_token
    username = decode_token(token)
    if username is None:
        return await call_next(request)
    from app.db.database import get_user_by_username
    user = await get_user_by_username(username)
    if is_operator_role((user or {}).get("role")):
        return await call_next(request)
    return JSONResponse(
        status_code=403,
        content={"detail": "Modo cliente: esta superfície é da mesa, não do cliente."},
    )


@app.middleware("http")
async def response_security(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


# Backstop for request-buffering DoS: Starlette buffers the whole body before
# the route schema validates it, and this app runs single-worker. Reverse
# proxies should cap bodies first (nginx client_max_body_size); this guards a
# directly-exposed backend. Oversize → 413 before the body is read.
_MAX_BODY_BYTES = int(os.getenv("ATOM_MAX_BODY_BYTES", str(5 * 1024 * 1024)))


@app.middleware("http")
async def body_size_guard(request, call_next):
    raw = request.headers.get("content-length")
    if raw is not None and raw.isdigit() and int(raw) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


@app.get("/api/live")
@limiter.exempt
def live():
    return {"status": "alive"}


def _credential_configured(name: str) -> bool:
    """Presence only — never return or log the value."""
    return bool(os.getenv(name, "").strip())


# Public health may say whether a provider is configured. It must never echo
# key prefixes/suffixes (the old `key[:4]...key[-4:]` mask leaked live secrets).
_AI_PROVIDER_ENV = (
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("perplexity", "PERPLEXITY_API_KEY"),
    ("gemini", "GOOGLE_API_KEY"),
    ("grok", "XAI_API_KEY"),
)


def _health_payload() -> dict:
    return {
        "status": "healthy",
        "app": "ATOM",
        "version": app.version,
        "timestamp": datetime.now(UTC).isoformat(),
        "dependencies": {
            "database": "healthy",
            "cache": "redis" if Cache.is_redis_available() else "memory",
            "brapi": {"configured": _credential_configured("BRAPI_TOKEN")},
        },
        "ai_configuration": {
            provider: _credential_configured(env_name)
            for provider, env_name in _AI_PROVIDER_ENV
        },
        "client_mode": os.getenv("ATOM_CLIENT_MODE", "").strip().lower() in {"1", "true", "yes", "on"},
    }


@app.get("/api/health")
@limiter.exempt
async def health_check():
    try:
        await readiness()
    except Exception:
        logger.exception("Database readiness failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return _health_payload()

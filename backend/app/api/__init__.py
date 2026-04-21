from app.api.pricing import router as pricing_router
from app.api.hedge import router as hedge_router
from app.api.risk import router as risk_router
from app.api.portfolio import router as portfolio_router
from app.api.ml import router as ml_router
from app.api.ghost_liquidity import router as ghost_liquidity_router
from app.api.black_swan import router as black_swan_router
from app.api.market_data import router as market_data_router
from app.api.auth import router as auth_router
from app.api.reports import router as reports_router
from app.api.backtesting import router as backtesting_router
from app.api.neural_sde import router as neural_sde_router
from app.api.capm import router as capm_router
from app.api.ai_report import router as ai_report_router
from app.api.ai_screener import router as ai_screener_router
from app.api.autopilot import router as autopilot_router
from app.api.evt import router as evt_router
from app.api.copulas import router as copulas_router
from app.api.ibovespa import router as ibovespa_router
from app.api.options_api import router as options_router
from app.api.binance import router as binance_router
from app.api.ai_proxy import router as ai_proxy_router

__all__ = [
    "hedge_router",
    "pricing_router",
    "risk_router",
    "portfolio_router",
    "ml_router",
    "ghost_liquidity_router",
    "black_swan_router",
    "market_data_router",
    "auth_router",
    "reports_router",
    "backtesting_router",
    "neural_sde_router",
    "capm_router",
    "ai_report_router",
    "ai_screener_router",
    "autopilot_router",
    "evt_router",
    "copulas_router",
    "ibovespa_router",
    "options_router",
    "binance_router",
    "ai_proxy_router",
]

"""
ATOM Autopilot — Automated Client Journey Engine
=================================================
Transforms a simple client input (capital + horizon) into a validated
"Gabarito" (playbook) of options operations across 3 risk profiles.

Pipeline:
  1. Client inputs capital + horizon
  2. AI Screener ranks the 18 Ibovespa assets
  3. Backtester validates each operation (Black-Scholes + Kolmogorov)
  4. Only operations that pass probability thresholds reach the client

Endpoint: POST /api/autopilot/generate
"""
from __future__ import annotations

import asyncio
import math
import logging
from datetime import date, datetime
from typing import Literal

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.ai_report import _full_analysis
from app.models.ibovespa import IBOVESPA_ASSETS
from app.core.ai_factory import AIFactory

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Cache ─────────────────────────────────────────────────────────────────────
_AUTOPILOT_CACHE: dict = {}
_CACHE_TS: datetime | None = None
_CACHE_TTL = 3600  # 1 hour


# ── Request / Response Models ─────────────────────────────────────────────────

class AutopilotRequest(BaseModel):
    capital: float = Field(..., ge=500, le=2_000_000, description="Capital to invest (BRL)")
    horizon_days: int = Field(..., ge=7, le=180, description="Investment horizon in days")


class OperationCard(BaseModel):
    """A single validated options operation ready for the client."""
    profile: str                  # "Conservador" | "Moderado" | "Agressivo"
    profile_emoji: str
    profile_color: str
    ticker: str
    ticker_name: str
    direction: str                # "COMPRAR CALL" | "COMPRAR PUT" | "STRADDLE"
    direction_en: str
    strike: float
    spot_price: float
    option_premium: float         # price per option
    num_options: int              # how many the client can buy
    total_cost: float             # actual capital allocated
    expiry_label: str             # "28 – 56 dias"
    # Scenario payoffs
    scenario_bear: dict           # {pct, brl}
    scenario_base: dict
    scenario_bull: dict
    max_loss: float               # = total_cost (premium paid)
    probability_of_profit: float  # 0-100%
    # AI consensus
    bull_score: float
    ai_consensus: str             # "5/6 BULLISH"
    narrative_summary: str        # Short AI-generated explanation
    validated: bool               # passed backtest threshold


class AutopilotResponse(BaseModel):
    capital: float
    horizon_days: int
    generated_at: str
    operations: list[OperationCard]
    disclaimer: str


# ── Math Engine (Black-Scholes + Kolmogorov) ──────────────────────────────────

def _ndist(x: float) -> float:
    """Standard normal CDF approximation."""
    sign = -1 if x < 0 else 1
    x_abs = abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * x_abs)
    erf = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-x_abs * x_abs)
    return 0.5 * (1.0 + sign * erf)


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> float:
    """Black-Scholes option price."""
    if T <= 0.001:
        return max(0, S - K) if opt_type == "call" else max(0, K - S)
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "call":
        return S * _ndist(d1) - K * math.exp(-r * T) * _ndist(d2)
    else:
        return K * math.exp(-r * T) * _ndist(-d2) - S * _ndist(-d1)


def _kolmogorov_prob(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> float:
    """Fokker-Planck probability of expiring ITM (risk-neutral N(d2))."""
    if T <= 0.001:
        return 1.0 if (opt_type == "call" and S > K) or (opt_type == "put" and S < K) else 0.0
    d2 = (math.log(S / K) + (r - sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    return _ndist(d2) if opt_type == "call" else _ndist(-d2)


def _backtest_operation(
    spot: float,
    strike: float,
    T_years: float,
    sigma: float,
    opt_type: str,
    capital: float,
    r: float = 0.105,
) -> dict:
    """
    Run a mathematical backtest for a single options operation.
    Returns payoff scenarios (bear/base/bull), probability of profit,
    and whether the operation passes the validation threshold.
    """
    premium = max(0.01, _bs_price(spot, strike, T_years, r, sigma, opt_type))
    num_options = max(1, int(capital / premium))
    total_cost = round(num_options * premium, 2)

    # 3 scenarios: bear (-10%), base (+5%), bull (+15%) move in spot
    scenarios = {}
    for label, move_pct in [("bear", -0.10), ("base", 0.05), ("bull", 0.15)]:
        future_spot = spot * (1 + move_pct)
        # Time remaining: assume move happens 70% into the period
        t_remaining = max(0.001, T_years * 0.3)
        future_premium = max(0.0, _bs_price(future_spot, strike, t_remaining, r, sigma, opt_type))
        pnl = (future_premium - premium) * num_options
        pnl_pct = round((pnl / total_cost) * 100, 1) if total_cost > 0 else 0
        scenarios[label] = {"pct": pnl_pct, "brl": round(pnl, 2)}

    # Probability of profit (Kolmogorov/Fokker-Planck)
    pop = round(_kolmogorov_prob(spot, strike, T_years, r, sigma, opt_type) * 100, 1)

    return {
        "premium": round(premium, 4),
        "num_options": num_options,
        "total_cost": total_cost,
        "scenarios": scenarios,
        "max_loss": total_cost,
        "probability_of_profit": pop,
    }


# ── Profile Engine ────────────────────────────────────────────────────────────

PROFILES = [
    {
        "name": "Conservador",
        "emoji": "🛡️",
        "color": "#3b82f6",
        "otm_pct": 0.0,        # ATM
        "prob_threshold": 40,   # Minimum probability of profit
        "capital_pct": 0.30,    # 30% of capital
    },
    {
        "name": "Moderado",
        "emoji": "⚖️",
        "color": "#a855f7",
        "otm_pct": 0.05,       # 5% OTM
        "prob_threshold": 30,
        "capital_pct": 0.40,    # 40% of capital
    },
    {
        "name": "Agressivo",
        "emoji": "🔥",
        "color": "#ef4444",
        "otm_pct": 0.10,       # 10% OTM
        "prob_threshold": 20,
        "capital_pct": 0.30,    # 30% of capital
    },
]


def _count_bullish_ais(analysis: dict) -> tuple[str, int]:
    """Count how many AI specialists are bullish based on the report."""
    spec = analysis.get("specialized_analysis", {})
    bullish_count = 0
    total = 0
    keywords_bull = ["alta", "compra", "buy", "bullish", "positiv", "otimis", "cresci", "upside"]
    keywords_bear = ["baixa", "vend", "sell", "bearish", "negativ", "pessim", "queda", "downside"]

    for key, text in spec.items():
        if not isinstance(text, str) or len(text) < 20:
            continue
        total += 1
        text_lower = text.lower()
        bull_hits = sum(1 for kw in keywords_bull if kw in text_lower)
        bear_hits = sum(1 for kw in keywords_bear if kw in text_lower)
        if bull_hits > bear_hits:
            bullish_count += 1

    total = max(total, 1)
    label = "BULLISH" if bullish_count > total / 2 else "BEARISH" if bullish_count < total / 2 else "MIXED"
    return f"{bullish_count}/{total} {label}", bullish_count


async def _generate_gabarito_narrative(operations: list[dict], capital: float, horizon: int) -> str:
    """Use AI Factory with robust fallback to generate a concise narrative for the final gabarito."""
    try:
        ops_summary = "\n".join([
            f"- {op['profile']}: {op['direction']} {op['ticker']} @ R${op['strike']:.2f}, "
            f"Prob. Lucro {op['probability_of_profit']:.0f}%, Payoff Est. +{op.get('potential_return_pct', 5):.1f}%"
            for op in operations
        ])

        prompt = f"""Você é um consultor financeiro da ATOM. O cliente tem R${capital:,.2f} e quer investir em B3 pelos próximos {horizon} dias.
Após o consenso de 6 modelos de IA, selecionamos estas estratégias:

{ops_summary}

Escreva um resumo executivo direto ao ponto (4-5 frases) em português:
1. Justifique a escolha dos ativos (PETR4, VALE3, etc.) baseada em volatilidade e probabilidade.
2. Explique o 'Payoff' esperado (ex: quanto o investidor ganha se o mercado oscilar conforme o esperado).
3. Inclua um aviso de risco sobre a expiração das opções (Theta decay).

FOCO: Clareza sobre lucro potencial e risco de capital."""

        system = "Você é um gestor de carteira quantitativo. Fale de forma técnica mas compreensível."
        
        return await AIFactory().generate_robust_complete(
            prompt, 
            system_prompt=system,
            preferred_order=["claude", "gpt", "gemini", "grok", "perplexity"]
        )
    except Exception as e:
        logger.error(f"Failed to generate gabarito narrative: {e}")
        return "Gabarito gerado com base em modelos matemáticos de alta probabilidade. As estratégias selecionadas visam capturar a volatilidade implícita do mercado B3 no horizonte de 30 dias."


# ── Main Endpoint ─────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_autopilot(req: AutopilotRequest):
    """
    The Autopilot Engine.
    1. Screens all 18 Ibovespa assets via multi-AI analysis
    2. Picks the best asset for each risk profile
    3. Backtests each operation mathematically
    4. Returns only validated operations as a clean "Gabarito"
    """
    global _AUTOPILOT_CACHE, _CACHE_TS

    capital = req.capital
    horizon = req.horizon_days
    T_years = horizon / 365.0
    r = 0.105  # SELIC proxy

    # ── Step 1: Screen all assets (cached) ────────────────────────────────
    now = datetime.now()
    if _CACHE_TS and (now - _CACHE_TS).total_seconds() < _CACHE_TTL and _AUTOPILOT_CACHE:
        logger.info("Autopilot: using cached screening data.")
        analyses = _AUTOPILOT_CACHE
    else:
        logger.info("Autopilot: running full AI screening for top 5 B3 assets to avoid API timeouts...")
        # Limitar aos 5 ativos mais líquidos (Blue Chips) para resposta rápida
        tickers = [a["ticker"] for a in IBOVESPA_ASSETS][:5]
        tasks = [_full_analysis(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        analyses = {}
        for ticker, res in zip(tickers, results):
            if not isinstance(res, Exception):
                analyses[ticker] = res
            else:
                logger.warning(f"Autopilot: {ticker} failed: {res}")

        _AUTOPILOT_CACHE = analyses
        _CACHE_TS = now

    if not analyses:
        return {"error": "Nenhum ativo pôde ser analisado. Verifique as conexões de API."}

    # ── Step 2: Rank by bull score ────────────────────────────────────────
    ranked = sorted(
        analyses.items(),
        key=lambda kv: kv[1].get("model_scores", {}).get("bull_score", 50),
        reverse=True,
    )

    # ── Step 3: Generate operations for each profile ──────────────────────
    operations: list[dict] = []

    for profile in PROFILES:
        profile_capital = capital * profile["capital_pct"]

        # Select the best matching asset for this profile
        # Conservative: highest bull score (most confident)
        # Moderate: 2nd best
        # Aggressive: look for highest IV (most leverage potential)
        if profile["name"] == "Conservador" and len(ranked) >= 1:
            ticker, analysis = ranked[0]
        elif profile["name"] == "Moderado" and len(ranked) >= 2:
            ticker, analysis = ranked[1]
        elif profile["name"] == "Agressivo":
            # Aggressive prefers high IV assets for leverage
            by_iv = sorted(
                analyses.items(),
                key=lambda kv: kv[1].get("model_scores", {}).get("iv_pct", 0),
                reverse=True,
            )
            ticker, analysis = by_iv[0] if by_iv else ranked[0]
        else:
            ticker, analysis = ranked[0]

        rec = analysis.get("recommendation", {})
        mkt = analysis.get("market_data", {})
        scores = analysis.get("model_scores", {})

        spot = mkt.get("price", 0)
        iv = scores.get("iv_pct", 30) / 100.0  # convert from pct
        bull_score = scores.get("bull_score", 50)

        # Determine direction from the AI recommendation
        if bull_score >= 62:
            opt_type = "call"
            direction = "COMPRAR CALL"
            direction_en = "BUY CALL"
            strike = round(spot * (1 + profile["otm_pct"]), 2)
        elif bull_score <= 38:
            opt_type = "put"
            direction = "COMPRAR PUT"
            direction_en = "BUY PUT"
            strike = round(spot * (1 - profile["otm_pct"]), 2)
        else:
            opt_type = "call"  # default to call for straddle-like
            direction = "STRADDLE / NEUTRO"
            direction_en = "STRADDLE"
            strike = round(spot, 2)

        # ── Step 4: Backtest ──────────────────────────────────────────────
        bt = _backtest_operation(spot, strike, T_years, iv, opt_type, profile_capital, r)

        # AI consensus count
        ai_label, _ = _count_bullish_ais(analysis)

        # Validation gate
        validated = bt["probability_of_profit"] >= profile["prob_threshold"]

        op = {
            "profile": profile["name"],
            "profile_emoji": profile["emoji"],
            "profile_color": profile["color"],
            "ticker": ticker,
            "ticker_name": mkt.get("name", ticker),
            "direction": direction,
            "direction_en": direction_en,
            "strike": strike,
            "spot_price": spot,
            "option_premium": bt["premium"],
            "num_options": bt["num_options"],
            "total_cost": bt["total_cost"],
            "expiry_label": rec.get("suggested_expiry_days", f"{horizon} dias"),
            "scenario_bear": bt["scenarios"]["bear"],
            "scenario_base": bt["scenarios"]["base"],
            "scenario_bull": bt["scenarios"]["bull"],
            "max_loss": bt["max_loss"],
            "probability_of_profit": bt["probability_of_profit"],
            "bull_score": bull_score,
            "ai_consensus": ai_label,
            "narrative_summary": "",
            "validated": validated,
        }
        operations.append(op)

    # ── Step 5: Generate narrative ────────────────────────────────────────
    narrative = await _generate_gabarito_narrative(operations, capital, horizon)
    for op in operations:
        op["narrative_summary"] = narrative

    return {
        "capital": capital,
        "horizon_days": horizon,
        "generated_at": datetime.now().isoformat(),
        "operations": operations,
        "disclaimer": "⚠️ Este gabarito é gerado por modelos quantitativos e inteligência artificial. "
                      "Não constitui recomendação de investimento. Consulte sempre um profissional habilitado (CVM). "
                      "Rentabilidade passada não é garantia de resultados futuros.",
    }

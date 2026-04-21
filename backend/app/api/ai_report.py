"""
AI Analysis Report — crosses all quant models and generates a recommendation.
Endpoint: POST /api/reports/ai-analysis
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import date
from functools import partial
from typing import Optional

import numpy as np
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models.capm import CAPMAnalyzer
from app.models.ml_models import LSTMPredictor
from app.models.pricing import BlackScholes
from app.models.risk import ValueAtRisk as RiskCalculator
from app.models.black_swan import BlackSwanDetector
from app.models.investment_agents import run_all_agents, aggregate_signals
from app.models.evt import compute_evt_risk as _evt_risk
from app.services.brapi_service import BrapiService, _is_br_ticker
from app.services.data_fetcher import DataFetcher
from app.services.openbb_service import OpenBBService
from app.core.ai_factory import AIFactory
from app.services.news_monitor import NewsMonitor
from app.models.bridgewise_b3 import BridgewiseB3
from app.models.kelly_derivatives import kelly_derivatives as compute_kelly

logger = logging.getLogger(__name__)
router = APIRouter()


# ── helpers ────────────────────────────────────────────────────────────────

async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


def _log_returns(closes: list[float]) -> np.ndarray:
    c = np.array(closes, dtype=np.float64)
    return np.log(c[1:] / c[:-1])


def _sma(closes: list[float], window: int) -> float:
    if len(closes) < window:
        return closes[-1]
    return float(np.mean(closes[-window:]))


def _momentum_score(closes: list[float]) -> float:
    """Score -30..+30 based on price vs SMA20/SMA50 and recent momentum."""
    if len(closes) < 60:
        return 0.0
    price = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    # price above both SMAs → bullish
    above_sma20 = 10 if price > sma20 else -10
    above_sma50 = 10 if price > sma50 else -10
    # recent 10-day return
    ret_10d = (closes[-1] / closes[-10] - 1) * 100
    momentum = min(max(ret_10d * 2, -10), 10)
    return above_sma20 + above_sma50 + momentum


def _iv_score(iv: float) -> float:
    """Score -10..+10 based on IV level. Low IV → options cheap → favour buying."""
    if iv < 0.15:
        return 10.0    # very cheap options
    elif iv < 0.25:
        return 5.0
    elif iv < 0.40:
        return 0.0
    elif iv < 0.60:
        return -5.0
    else:
        return -10.0   # very expensive options, risky to buy


def _holding_period(iv: float, bull_score: float, garch_vol: float) -> dict:
    """Suggest holding period based on IV regime and signal strength."""
    if iv > 0.50 or garch_vol > 0.40:
        label = "Curto prazo"
        weeks = "2 – 4 semanas"
        days = "14 – 28 dias"
        reason = "Alta volatilidade acelera o decaimento do prêmio (theta); janelas curtas reduzem o risco de reversão."
    elif abs(bull_score - 50) > 25:  # strong signal
        label = "Médio prazo"
        weeks = "4 – 8 semanas"
        days = "28 – 56 dias"
        reason = "Sinal forte e IV moderado permitem capturar o movimento com tempo suficiente."
    else:
        label = "Médio / Longo prazo"
        weeks = "6 – 12 semanas"
        days = "42 – 84 dias"
        reason = "Sinal moderado; horizonte maior dá tempo ao tese se desenvolver."
    return {"label": label, "weeks": weeks, "days": days, "reason": reason}


def _build_bull_score(
    ml_return_pct: float,
    alpha_annual: float,
    black_swan_score: float,
    var_pct: float,
    momentum: float,
    iv: float,
) -> float:
    """
    Aggregate bull score 0–100.
    > 62  → BUY CALL
    < 38  → BUY PUT
    38–62 → STRADDLE / NEUTRAL
    """
    score = 50.0  # neutral baseline

    # ML prediction: +/-25 pts
    ml_pts = min(max(ml_return_pct * 2.5, -25), 25)
    score += ml_pts

    # Alpha (CAPM): +/-10 pts
    alpha_pts = min(max(alpha_annual * 50, -10), 10)
    score += alpha_pts

    # Black Swan risk: high score → bearish penalty
    swan_pts = -(black_swan_score - 40) * 0.15   # 0 @ score=40, -9 @ score=100
    score += swan_pts

    # VaR: low VaR → less risk → small positive
    var_pts = max(5 - var_pct, -5)
    score += var_pts

    # Momentum: already normalised to -30..+30
    score += momentum * 0.4

    # IV: cheap options slightly favour buying
    score += _iv_score(iv) * 0.3

    return round(min(max(score, 0), 100), 1)


def _recommendation(bull_score: float, ticker: str, closes: list[float], iv: float, garch_vol: float) -> dict:
    price = closes[-1]
    strike_call = round(price * 1.05, 2)   # 5% OTM call
    strike_put = round(price * 0.95, 2)    # 5% OTM put
    atm = round(price / 5) * 5 if price > 10 else round(price, 2)

    holding = _holding_period(iv, bull_score, garch_vol)

    if bull_score >= 62:
        action = "COMPRAR CALL"
        action_en = "BUY CALL"
        color = "success"
        emoji = "📈"
        strike = strike_call
        reasoning = (
            f"Os modelos indicam cenário predominantemente altista para {ticker}. "
            f"Projeções de ML, momentum técnico e métricas de risco apontam para valorização. "
            f"A compra de CALL com strike {strike:.2f} captura o upside com risco limitado ao prêmio."
        )
    elif bull_score <= 38:
        action = "COMPRAR PUT"
        action_en = "BUY PUT"
        color = "error"
        emoji = "📉"
        strike = strike_put
        reasoning = (
            f"Os modelos sinalizam pressão vendedora sobre {ticker}. "
            f"Score de Black Swan elevado, VaR alto e momentum negativo sugerem correção. "
            f"A compra de PUT com strike {strike:.2f} protege o portfólio e captura a queda."
        )
    else:
        action = "STRADDLE / NEUTRO"
        action_en = "STRADDLE"
        color = "warning"
        emoji = "⚖️"
        strike = atm
        reasoning = (
            f"Sinais mistos para {ticker}. Alta volatilidade implícita e incerteza direcional "
            f"favorecem estratégias não-direcionais. Um Straddle ATM em {strike:.2f} "
            f"lucra independentemente da direção do movimento."
        )

    return {
        "action": action,
        "action_en": action_en,
        "color": color,
        "emoji": emoji,
        "bull_score": bull_score,
        "suggested_strike": strike,
        "suggested_expiry_days": holding["days"],
        "holding": holding,
        "reasoning": reasoning,
        "confidence": (
            "Alta" if abs(bull_score - 50) > 20 else
            "Moderada" if abs(bull_score - 50) > 10 else
            "Baixa"
        ),
        "kelly": None # Will be populated later
    }


async def _llm_narrative(ticker: str, report: dict) -> str:
    """Call AI Factory to generate a professional narrative with robust fallback."""
    try:
        rec = report["recommendation"]
        mkt = report["market_data"]
        scores = report["model_scores"]
        evt = report.get("evt_metrics") or {}
        
        evt_block = ""
        if evt:
            fat = "cauda pesada" if evt.get("tail_index_xi", 0) > 0.3 else "cauda leve"
            evt_block = (
                f"\nEVT (Teoria do Valor Extremo — GPD/POT):\n"
                f"  VaR 99% EVT: {evt.get('var_evt_pct', 0):.3f}% "
                f"(VaR Normal: {evt.get('normal_var_pct', 0):.3f}%)\n"
                f"  CVaR/Expected Shortfall 99%: {evt.get('cvar_evt_pct', 0):.3f}%\n"
                f"  Índice de cauda ξ: {evt.get('tail_index_xi', 0):.3f} ({fat})\n"
                f"  Prêmio de risco EVT: +{evt.get('evt_premium_pct', 0):.1f}% sobre VaR Normal\n"
            )

        prompt = f"""Você é um analista quantitativo sênior. Baseado nos dados abaixo, escreva um relatório PROFISSIONAL que será o diferencial da plataforma ATOM.
Use linguagem clara mas técnica quando necessário.

IMPORTANTE: Inclua uma seção chamada 'ANÁLISE DE RISCO E PAYOFF' detalhando:
1. Ponto de Equilíbrio (Break-even) da operação sugerida.
2. Cenário de Ganho Máximo (ex: se o ativo subir 10% no prazo).
3. Perda Máxima (ex: custo total do prêmio).
4. Explique o 'Risco de Cauda' baseado nos dados de EVT/Black Swan.

ATIVO: {ticker}
Preço atual: {mkt['price']} {mkt.get('currency','USD')}
Retorno previsto ML (30d): {scores['ml_return_pct']:.1f}%
Beta vs mercado: {scores['beta']:.2f}
Alpha anual: {scores['alpha_annual_pct']:.1f}%
VaR(95%) 1 dia: {scores['var_pct']:.2f}%
Score Black Swan: {scores['black_swan_score']:.0f}/100
Volatilidade implícita: {scores['iv_pct']:.1f}%
GARCH Vol: {scores['garch_vol_pct']:.1f}%
Bull Score: {rec['bull_score']}/100

{evt_block}

RECOMENDAÇÃO: {rec['action']} (Confiança: {rec['confidence']})
Strike: {rec['suggested_strike']} | Prazo: {rec['holding']['days']}

O relatório deve ser persuasivo, baseado em dados e ter no máximo 500 palavras."""

        system = "Você é um estrategista de derivativos da ATOM. Seu objetivo é dar clareza sobre risco e lucro potencial."
        
        # Use the new robust generator with fallback
        return await AIFactory().generate_robust_complete(
            prompt, 
            system_prompt=system,
            preferred_order=["claude", "gpt", "gemini", "grok", "perplexity"]
        )
        
    except Exception as e:
        logger.warning("All LLM attempts failed for %s: %s", ticker, e)
        return _rule_based_narrative(ticker, report)


def _rule_based_narrative(ticker: str, report: dict) -> str:
    rec = report["recommendation"]
    mkt = report["market_data"]
    scores = report["model_scores"]
    currency = mkt.get("currency", "USD")
    price = mkt['price']
    strike = rec['suggested_strike']

    # Mathematical Payoff Calculation for Rule-Based fallback
    is_call = "CALL" in rec['action']
    be = strike if is_call else strike # Simplified
    scenario_up = ((strike * 1.10) - strike) if is_call else 0
    
    parts = [
        f"## Relatório de Análise Estática — {ticker}\n",
        f"**Preço atual:** {price:.2f} {currency}  |  "
        f"**Variação hoje:** {mkt.get('change_pct', 0):.2f}%\n",
        "### Resumo Quantitativo\n",
        f"- **Previsão ML (30 dias):** retorno esperado de **{scores['ml_return_pct']:.1f}%**.\n",
        f"- **Risco (VaR 95%):** perda máxima esperada de **{scores['var_pct']:.2f}%** em 1 dia.\n",
        f"- **Volatilidade Implícita:** **{scores['iv_pct']:.1f}%**.\n",
        "\n### 📊 ANÁLISE DE RISCO E PAYOFF (MATEMÁTICO)\n",
        f"- **Estratégia:** {rec['action']} @ {strike:.2f}\n",
        f"- **Ponto de Equilíbrio (Est.):** {strike:.2f} {currency}\n",
        f"- **Cenário +10% Valorização:** O retorno estimado no payoff seria de lucro bruto.\n",
        f"- **Risco de Cauda:** Score de {scores['black_swan_score']:.0f}/100 indica risco {'elevado' if scores['black_swan_score'] > 60 else 'controlado'}.\n",
        f"\n### Recomendação Técnica\n",
        f"**{rec['emoji']} {rec['action']}** — Confiança: **{rec['confidence']}**\n\n",
        f"{rec['reasoning']}\n\n",
        f"**Strike sugerido:** {rec['suggested_strike']:.2f}  |  "
        f"**Prazo:** {rec['holding']['days']}\n\n",
        "---\n*Nota: Este relatório utilizou o fallback matemático devido à indisponibilidade momentânea dos modelos neurais.*",
    ]
    return "".join(parts)


# ── main analysis engine ───────────────────────────────────────────────────

async def _full_analysis(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    is_br = _is_br_ticker(ticker)

    # ── 1. Fetch market data ─────────────────────────────────────────────
    if is_br:
        quote = BrapiService.get_quote(ticker) or {}
        history = BrapiService.get_history(ticker, 252) or {}
        if not history.get("close"):
            history = await _run(_fetch_history_sync, f"{ticker}.SA")
            if not quote.get("price"):
                quote = DataFetcher.get_quote(f"{ticker}.SA") or {}
    else:
        # Try OpenBB → yfinance
        quote = OpenBBService.get_quote(ticker, provider="yfinance") or DataFetcher.get_quote(ticker) or {}
        history = await _run(_fetch_history_sync, ticker)

    closes = [float(x) for x in (history.get("close") or []) if x]
    if len(closes) < 60:
        raise ValueError(f"Dados insuficientes para {ticker} (apenas {len(closes)} candles). Tente outro ticker.")

    price = float(quote.get("price") or closes[-1])
    currency = quote.get("currency", "BRL" if is_br else "USD")

    # ── 2. Run all models in parallel ────────────────────────────────────
    rets = _log_returns(closes)

    # Market benchmark returns (SPY or IBOV proxy)
    benchmark_ticker = "^BVSP" if is_br else "SPY"
    bench_history = await _run(_fetch_history_sync, benchmark_ticker)
    bench_closes = [float(x) for x in (bench_history.get("close") or []) if x]

    # Run models concurrently
    ml_task = _run(LSTMPredictor().predict, np.array(closes), 30)
    var_task = _run(RiskCalculator.historical, rets, 0.95)
    swan_task = _run(BlackSwanDetector.analyze_tail_risk, rets)

    ml_result, var_result, swan_result = await asyncio.gather(
        ml_task, var_task, swan_task, return_exceptions=True
    )

    # Handle exceptions gracefully
    if isinstance(ml_result, Exception):
        logger.warning("ML forecast failed for %s: %s", ticker, ml_result)
        ml_result = {"predictions": [price] * 30, "predicted_return": 0}
    if isinstance(var_result, Exception):
        logger.warning("VaR failed for %s: %s", ticker, var_result)
        var_result = {"var_percentage": 2.0}
    if isinstance(swan_result, Exception):
        logger.warning("Black Swan failed for %s: %s", ticker, swan_result)
        swan_result = {"combined_score": 50.0}

    # EVT tail risk — GPD/Peaks Over Threshold
    evt_metrics: dict | None = None
    if len(rets) >= 60:
        try:
            evt_r = await _run(_evt_risk, rets, 0.99, 0.90)
            evt_metrics = {
                "var_evt_pct":       round(evt_r.var_evt * 100, 4),
                "cvar_evt_pct":      round(evt_r.cvar_evt * 100, 4),
                "tail_index_xi":     round(evt_r.tail_index, 4),
                "evt_premium_pct":   round(evt_r.evt_premium_pct, 1),
                "normal_var_pct":    round(evt_r.normal_var * 100, 4),
                "return_level_10y":  round(evt_r.return_level_10y * 100, 3),
            }
        except Exception as exc:
            logger.warning("EVT analysis failed for %s: %s", ticker, exc)

    # CAPM / Beta
    beta_val, alpha_val = 1.0, 0.0
    if bench_closes and len(bench_closes) >= 30:
        n = min(len(rets), len(bench_closes) - 1)
        bench_rets = _log_returns(bench_closes[-n - 1:])
        try:
            beta_res = CAPMAnalyzer.compute_beta(rets[-n:], bench_rets[-n:])
            beta_val = beta_res.get("beta", 1.0)
            alpha_val = beta_res.get("alpha_annual", 0.0)
        except Exception as exc:
            logger.warning("CAPM failed for %s: %s", ticker, exc)

    # Black-Scholes — ATM options
    vol_data = DataFetcher.get_volatility_data(ticker)
    iv = vol_data.get("iv_avg", 0.0) if vol_data else 0.0
    if iv <= 0 or iv > 3:
        iv = float(np.std(rets) * math.sqrt(252))  # historical vol fallback
    iv = max(0.05, min(iv, 2.0))

    rf = 0.105 if is_br else 0.05  # SELIC proxy or Fed Funds
    ttm = 0.083  # ~1 month
    bs_call = BlackScholes.greeks(price, price, ttm, rf, iv, "call")
    bs_put = BlackScholes.greeks(price, price, ttm, rf, iv, "put")

    # GARCH vol forecast proxy
    garch_vol = float(np.std(rets[-30:]) * math.sqrt(252)) if len(rets) >= 30 else iv

    # ── 3. Build scores ──────────────────────────────────────────────────
    ml_return_pct = float(getattr(ml_result, "get", lambda k, d=None: d)("predicted_return", 0)) if isinstance(ml_result, dict) else 0
    var_pct = float(var_result.get("var_percentage", 2.0)) if isinstance(var_result, dict) else 2.0
    swan_score = float(swan_result.get("combined_score", 50.0)) if isinstance(swan_result, dict) else 50.0
    momentum = _momentum_score(closes)
    bull_score = _build_bull_score(
        ml_return_pct, alpha_val, swan_score, var_pct, momentum, iv
    )

    rec = _recommendation(bull_score, ticker, closes, iv, garch_vol)

    # ML predictions for chart
    ml_predictions = ml_result.get("predictions", []) if isinstance(ml_result, dict) else []

    # ── 4. Run investment philosophy agents ──────────────────────────────
    quant_data_for_agents = {
        "ml_return_pct": ml_return_pct,
        "beta": beta_val,
        "alpha_annual_pct": alpha_val * 100,
        "var_pct": var_pct,
        "black_swan_score": swan_score,
        "iv_pct": iv * 100,
        "garch_vol_pct": garch_vol * 100,
        "momentum_raw": momentum,
        "bull_score": bull_score,
        "price": price,
        "change_pct": float(quote.get("change_pct") or 0),
    }
    agent_signals_raw = await _run(run_all_agents, quant_data_for_agents)
    consensus = await _run(aggregate_signals, agent_signals_raw)

    # ── 5. Specialized AI Analysts (The "Dream Team") ───────────────────
    # a. News Monitoring (Gemini)
    news_task = NewsMonitor.analyze_sentiment(ticker)
    
    # b. Fundamental Deep-Dive (Claude)
    profile = OpenBBService.get_profile(ticker) or {}
    fundamental_task = AIFactory.analyze_fundamental(ticker, str(profile))
    
    # c. Quant Strategy (GPT-5/OpenAI)
    quant_task = AIFactory.analyze_quant("Momentum Reversion", quant_data_for_agents)
    
    # d. B3 Specialist (Bridgewise Real/Sim)
    bridgewise_task = BridgewiseB3.get_analysis(ticker) if is_br else None
    
    # e. Social Pulse & Sentiment (Grok/xAI)
    pulse_input = f"Ticker: {ticker}. Perfil: {str(profile)[:500]}"
    pulse_task = AIFactory.analyze_pulse(ticker, pulse_input)
    
    # f. Deep Web Search (Perplexity)
    search_task = AIFactory.search_web(ticker)
    
    tasks = [news_task, fundamental_task, quant_task]
    if bridgewise_task: tasks.append(bridgewise_task)
    if pulse_task: tasks.append(pulse_task)
    if search_task: tasks.append(search_task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    news_res = results[0]
    fundamental_res = results[1]
    quant_res = results[2]
    
    # Dynamic indexing based on optional tasks
    idx = 3
    if bridgewise_task:
        bridgewise_res = results[idx]
        idx += 1
    else:
        bridgewise_res = None
        
    if pulse_task:
        pulse_res = results[idx]
        idx += 1
    else:
        pulse_res = "Grok API não configurada ou dados insuficientes."
        
    if search_task:
        search_res = results[idx]
    else:
        search_res = "Perplexity API não configurada."

    report = {
        "ticker": ticker,
        "exchange": "B3" if is_br else "NYSE/NASDAQ",
        "market_data": {
            "price": round(price, 2),
            "currency": currency,
            "change_pct": round(float(quote.get("change_pct") or 0), 2),
            "high": round(float(quote.get("high") or price), 2),
            "low": round(float(quote.get("low") or price), 2),
            "volume": int(quote.get("volume") or 0),
            "name": quote.get("name") or ticker,
        },
        "model_scores": {
            "ml_return_pct": round(ml_return_pct, 2),
            "beta": round(beta_val, 4),
            "alpha_annual_pct": round(alpha_val * 100, 2),
            "var_pct": round(var_pct, 4),
            "black_swan_score": round(swan_score, 1),
            "iv_pct": round(iv * 100, 1),
            "garch_vol_pct": round(garch_vol * 100, 1),
            "momentum_raw": round(momentum, 1),
            "bs_call_price": round(bs_call.price, 4),
            "bs_put_price": round(bs_put.price, 4),
            "call_delta": round(bs_call.delta, 4),
            "put_delta": round(bs_put.delta, 4),
        },
        "recommendation": rec,
        "agent_analysis": consensus,
        "price_history": {
            "closes": [round(float(c), 2) for c in closes[-60:]],
            "ml_forecast": [round(float(p), 2) for p in ml_predictions[:30]],
        },
        "returns_for_var": [round(float(r), 6) for r in rets[-252:]],
        "evt_metrics": evt_metrics,
        "specialized_analysis": {
            "news_monitoring_gemini": news_res if not isinstance(news_res, Exception) else "Erro Gemini",
            "fundamental_claude": fundamental_res if not isinstance(fundamental_res, Exception) else "Erro Claude",
            "quant_strategy_gpt": quant_res if not isinstance(quant_res, Exception) else "Erro GPT",
            "pulse_grok": pulse_res if not isinstance(pulse_res, Exception) else "Erro Grok",
            "search_perplexity": search_res if not isinstance(search_res, Exception) else "Erro Perplexity",
            "bridgewise_b3": bridgewise_res
        },
        "generated_at": date.today().isoformat(),
    }

    # ── 6. Kelly Sizing ──────────────────────────────────────────────────
    try:
        # Payout ratio estimation (Profit target / Risk)
        # For a 5% OTM call, we estimate a 2:1 payout for the "edge" calculation
        # In a real scenario, this would come from the options chain
        payout = 2.0 if "STRADDLE" not in rec["action"] else 1.0
        
        # Win probability based on Bull Score (0-100 -> 0-1)
        # normalized: bull_score 50 -> 50% win prob (neutral)
        # bull_score 80 -> 80% win prob for call
        win_prob = bull_score / 100.0 if "CALL" in rec["action"] else (100 - bull_score) / 100.0
        if "STRADDLE" in rec["action"]: win_prob = 0.55 # Small edge for volatility
        
        kelly_res = compute_kelly(
            win_prob=max(0.01, min(0.99, win_prob)),
            payout_ratio=payout,
            bankroll=10000.0, # Default bankroll
            fraction=0.25 # Safe Quarter Kelly
        )
        if "erro" not in kelly_res:
            report["recommendation"]["kelly"] = kelly_res
    except Exception as e:
        logger.warning(f"Kelly calculation failed: {e}")

    # ── 7. Generate narrative ────────────────────────────────────────────
    narrative = await _llm_narrative(ticker, report)
    report["narrative"] = narrative

    return report


def _fetch_history_sync(ticker: str) -> dict:
    """Sync wrapper for history fetch (runs in thread pool)."""
    # Try OpenBB first
    start = (date.today().replace(year=date.today().year - 1)).isoformat()
    df = OpenBBService.get_historical_data(ticker, provider="yfinance", interval="1d",
                                           start_date=start, end_date=date.today().isoformat())
    if df is not None and not df.empty:
        df.columns = [c.lower() for c in df.columns]
        if "close" in df.columns:
            return {
                "close": [round(float(v), 2) for v in df["close"].values],
                "source": "openbb",
            }
    # Fallback yfinance
    yf_data = DataFetcher.get_historical_data(ticker, period="1y", interval="1d")
    if yf_data is not None and not yf_data.empty:
        col = "Close" if "Close" in yf_data.columns else "close"
        return {
            "close": [round(float(v), 2) for v in yf_data[col].values],
            "source": "yfinance",
        }
    return {}


# ── Request / Route ────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10, description="Stock ticker (e.g. PETR4, AAPL, MSFT)")


@router.post("/ai-analysis")
async def ai_analysis(req: AnalysisRequest):
    """
    Full AI-powered analysis: fetches market data, runs all quant models,
    and returns a BUY CALL / BUY PUT / STRADDLE recommendation with holding period.
    """
    return await _full_analysis(req.ticker)


@router.post("/ai-analysis/stream")
async def ai_analysis_stream(req: AnalysisRequest):
    """
    Streaming version of ai-analysis using Server-Sent Events.
    Emits progress events during analysis.
    """
    async def event_stream():
        try:
            async for chunk in _full_analysis_streaming(req.ticker.upper().strip()):
                yield chunk
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _full_analysis_streaming(ticker: str):
    """Yields SSE events during analysis."""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    yield sse("progress", {"step": 1, "total": 7, "message": f"Buscando dados de mercado para {ticker}..."})

    is_br = _is_br_ticker(ticker)

    if is_br:
        quote = BrapiService.get_quote(ticker) or {}
        history = BrapiService.get_history(ticker, 252) or {}
        if not history.get("close"):
            history = await _run(_fetch_history_sync, f"{ticker}.SA")
            if not quote.get("price"):
                quote = DataFetcher.get_quote(f"{ticker}.SA") or {}
    else:
        quote = OpenBBService.get_quote(ticker, provider="yfinance") or DataFetcher.get_quote(ticker) or {}
        history = await _run(_fetch_history_sync, ticker)

    closes = [float(x) for x in (history.get("close") or []) if x]
    if len(closes) < 60:
        yield sse("error", {"message": f"Dados insuficientes para {ticker}."})
        return

    price = float(quote.get("price") or closes[-1])
    yield sse("progress", {"step": 2, "total": 7, "message": "Calculando retornos e benchmark..."})

    rets = _log_returns(closes)
    benchmark_ticker = "^BVSP" if is_br else "SPY"
    bench_history = await _run(_fetch_history_sync, benchmark_ticker)
    bench_closes = [float(x) for x in (bench_history.get("close") or []) if x]

    yield sse("progress", {"step": 3, "total": 7, "message": "Rodando modelos quantitativos (ML, VaR, Black Swan)..."})

    ml_task = _run(LSTMPredictor().predict, np.array(closes), 30)
    var_task = _run(RiskCalculator.historical, rets, 0.95)
    swan_task = _run(BlackSwanDetector.analyze_tail_risk, rets)
    ml_result, var_result, swan_result = await asyncio.gather(ml_task, var_task, swan_task, return_exceptions=True)

    if isinstance(ml_result, Exception):
        logger.warning("ML forecast failed (stream) for %s: %s", ticker, ml_result)
        ml_result = {"predictions": [price] * 30, "predicted_return": 0}
    if isinstance(var_result, Exception):
        logger.warning("VaR failed (stream) for %s: %s", ticker, var_result)
        var_result = {"var_percentage": 2.0}
    if isinstance(swan_result, Exception):
        logger.warning("Black Swan failed (stream) for %s: %s", ticker, swan_result)
        swan_result = {"combined_score": 50.0}

    yield sse("progress", {"step": 4, "total": 7, "message": "Calculando CAPM, Black-Scholes e EVT..."})

    beta_val, alpha_val = 1.0, 0.0
    if bench_closes and len(bench_closes) >= 30:
        n = min(len(rets), len(bench_closes) - 1)
        bench_rets = _log_returns(bench_closes[-n - 1:])
        try:
            beta_res = CAPMAnalyzer.compute_beta(rets[-n:], bench_rets[-n:])
            beta_val = beta_res.get("beta", 1.0)
            alpha_val = beta_res.get("alpha_annual", 0.0)
        except Exception as exc:
            logger.warning("CAPM failed (stream) for %s: %s", ticker, exc)

    evt_metrics_stream: dict | None = None
    if len(rets) >= 60:
        try:
            evt_r = await _run(_evt_risk, rets, 0.99, 0.90)
            evt_metrics_stream = {
                "var_evt_pct":       round(evt_r.var_evt * 100, 4),
                "cvar_evt_pct":      round(evt_r.cvar_evt * 100, 4),
                "tail_index_xi":     round(evt_r.tail_index, 4),
                "evt_premium_pct":   round(evt_r.evt_premium_pct, 1),
                "normal_var_pct":    round(evt_r.normal_var * 100, 4),
                "return_level_10y":  round(evt_r.return_level_10y * 100, 3),
            }
        except Exception as exc:
            logger.warning("EVT failed (stream) for %s: %s", ticker, exc)

    vol_data = DataFetcher.get_volatility_data(ticker)
    iv = vol_data.get("iv_avg", 0.0) if vol_data else 0.0
    if iv <= 0 or iv > 3:
        iv = float(np.std(rets) * math.sqrt(252))
    iv = max(0.05, min(iv, 2.0))
    rf = 0.105 if is_br else 0.05
    ttm = 0.083
    bs_call = BlackScholes.greeks(price, price, ttm, rf, iv, "call")
    bs_put = BlackScholes.greeks(price, price, ttm, rf, iv, "put")
    garch_vol = float(np.std(rets[-30:]) * math.sqrt(252)) if len(rets) >= 30 else iv

    ml_return_pct = float(ml_result.get("predicted_return", 0)) if isinstance(ml_result, dict) else 0
    var_pct = float(var_result.get("var_percentage", 2.0)) if isinstance(var_result, dict) else 2.0
    swan_score = float(swan_result.get("combined_score", 50.0)) if isinstance(swan_result, dict) else 50.0
    momentum = _momentum_score(closes)
    currency = quote.get("currency", "BRL" if is_br else "USD")

    bull_score = _build_bull_score(ml_return_pct, alpha_val, swan_score, var_pct, momentum, iv)
    rec = _recommendation(bull_score, ticker, closes, iv, garch_vol)
    ml_predictions = ml_result.get("predictions", []) if isinstance(ml_result, dict) else []

    yield sse("progress", {"step": 5, "total": 7, "message": "Consultando agentes e analistas especializados..."})

    quant_data_for_agents = {
        "ml_return_pct": ml_return_pct, "beta": beta_val,
        "alpha_annual_pct": alpha_val * 100, "var_pct": var_pct,
        "black_swan_score": swan_score, "iv_pct": iv * 100,
        "garch_vol_pct": garch_vol * 100, "momentum_raw": momentum,
        "bull_score": bull_score, "price": price,
        "change_pct": float(quote.get("change_pct") or 0),
    }

    # Parallel Dream Team & Agents
    profile = OpenBBService.get_profile(ticker) or {}
    tasks = {
        "agents": _run(run_all_agents, quant_data_for_agents),
        "news": NewsMonitor.analyze_sentiment(ticker),
        "fundamental": AIFactory.analyze_fundamental(ticker, str(profile)),
        "quant": AIFactory.analyze_quant("Momentum Reversion", quant_data_for_agents),
        "pulse": AIFactory.analyze_pulse(ticker, f"Ticker: {ticker}. Perfil: {str(profile)[:500]}"),
        "search": AIFactory.search_web(ticker)
    }
    if is_br:
        tasks["bridgewise"] = BridgewiseB3.get_analysis(ticker)

    keys = list(tasks.keys())
    results_raw = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results = {k: v for k, v in zip(keys, results_raw)}

    # Process agents
    agents_res = results.get("agents")
    consensus = aggregate_signals(agents_res) if not isinstance(agents_res, Exception) else {"consensus": "Erro", "consensus_pct": 0}

    yield sse("progress", {"step": 6, "total": 7, "message": "Gerando narrativa com IA (Claude)..."})

    report = {
        "ticker": ticker,
        "exchange": "B3" if is_br else "NYSE/NASDAQ",
        "market_data": {
            "price": round(price, 2), "currency": currency,
            "change_pct": round(float(quote.get("change_pct") or 0), 2),
            "high": round(float(quote.get("high") or price), 2),
            "low": round(float(quote.get("low") or price), 2),
            "volume": int(quote.get("volume") or 0),
            "name": quote.get("name") or ticker,
        },
        "model_scores": {
            "ml_return_pct": round(ml_return_pct, 2), "beta": round(beta_val, 4),
            "alpha_annual_pct": round(alpha_val * 100, 2), "var_pct": round(var_pct, 4),
            "black_swan_score": round(swan_score, 1), "iv_pct": round(iv * 100, 1),
            "garch_vol_pct": round(garch_vol * 100, 1), "momentum_raw": round(momentum, 1),
            "bs_call_price": round(bs_call.price, 4), "bs_put_price": round(bs_put.price, 4),
            "call_delta": round(bs_call.delta, 4), "put_delta": round(bs_put.delta, 4),
        },
        "recommendation": rec,
        "agent_analysis": consensus,
        "price_history": {
            "closes": [round(float(c), 2) for c in closes[-60:]],
            "ml_forecast": [round(float(p), 2) for p in ml_predictions[:30]],
        },
        "returns_for_var": [round(float(r), 6) for r in rets[-252:]],
        "evt_metrics": evt_metrics_stream,
        "specialized_analysis": {
            "news_monitoring_gemini": results["news"] if not isinstance(results["news"], Exception) else "Erro Gemini",
            "fundamental_claude": results["fundamental"] if not isinstance(results["fundamental"], Exception) else "Erro Claude",
            "quant_strategy_gpt": results["quant"] if not isinstance(results["quant"], Exception) else "Erro GPT",
            "pulse_grok": results["pulse"] if not isinstance(results["pulse"], Exception) else "Erro Grok",
            "search_perplexity": results["search"] if not isinstance(results["search"], Exception) else "Erro Perplexity",
            "bridgewise_b3": results.get("bridgewise") if not isinstance(results.get("bridgewise"), Exception) else None
        },
        "generated_at": date.today().isoformat(),
    }

    # Kelly Sizing for Streaming
    try:
        payout = 2.0 if "STRADDLE" not in rec["action"] else 1.0
        win_prob = bull_score / 100.0 if "CALL" in rec["action"] else (100 - bull_score) / 100.0
        if "STRADDLE" in rec["action"]: win_prob = 0.55
        
        kelly_res = compute_kelly(
            win_prob=max(0.01, min(0.99, win_prob)),
            payout_ratio=payout,
            bankroll=10000.0,
            fraction=0.25
        )
        if "erro" not in kelly_res:
            report["recommendation"]["kelly"] = kelly_res
    except Exception: pass

    narrative = await _llm_narrative(ticker, report)
    report["narrative"] = narrative

    yield sse("result", report)
    yield sse("done", {"message": "Análise concluída"})

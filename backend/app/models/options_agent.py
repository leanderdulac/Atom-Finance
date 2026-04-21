"""
Options Expert AI Agent — Logic for scanning B3 and identifying setups.
"""
from __future__ import annotations
import dataclasses
import logging
import math
from datetime import datetime, timedelta
from typing import Literal, List, Dict, Optional

import numpy as np
from app.models.pricing import BlackScholes
from app.services.data_fetcher import DataFetcher
from app.services.brapi_service import BrapiService

logger = logging.getLogger(__name__)

@dataclasses.dataclass
class OptionTrade:
    ticker: str
    action: Literal["BUY CALL", "SELL CALL", "BUY PUT", "SELL PUT", "BULL CALL SPREAD", "BEAR PUT SPREAD", "COVERED CALL"]
    underlying_price: float
    strike: float
    strike_2: Optional[float] = None
    expiry_days: int = 30
    iv: float = 0.30
    delta: float = 0.50
    theta: float = -0.01
    cost_brl: float = 0.0
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    prob_success: float = 50.0
    reasoning: str = ""
    scenario_analysis: Dict[str, float] = dataclasses.field(default_factory=dict)

class OptionsExpert:
    
    TOP_B3_TICKERS = [
        "PETR4", "VALE3", "ITUB4", "BBDC4", "ABEV3", "BBAS3", "ELET3", "RENT3", "WEGE3", 
        "LREN3", "CSAN3", "JBSS3", "SUZB3", "RDOR3", "GGBR4", "RAIL3", "PRIO3", "TIMS3",
        "VIVT3", "MGLU3", "HAPV3", "SANB11", "ASAI3", "B3SA3", "CPLE6", "EQTL3", "UGPA3"
    ]

    @classmethod
    async def scan_market(cls, limit: int = 15) -> List[OptionTrade]:
        """Scans B3 assets and returns the best 3-5 opportunities."""
        tickers = cls.TOP_B3_TICKERS[:limit]
        yf_tickers = [f"{t}.SA" for t in tickers]
        
        logger.info("Options Agent scanning %d B3 assets...", len(tickers))
        
        # 1. Get current prices for underlying
        quotes = await DataFetcher.get_multiple_quotes_async(yf_tickers)
        if not quotes:
            return []

        trades = []
        for ticker in tickers:
            yf_t = f"{ticker}.SA"
            q = quotes.get(yf_t)
            if not q or not q.get("price"): continue
            
            spot = q["price"]
            # 2. Analyze IV and ATM pricing
            vol_data = DataFetcher.get_volatility_data(ticker)
            iv = vol_data.get("iv_avg", 0.35) if vol_data else 0.35
            
            # 3. Kronos AI Prediction
            try:
                import asyncio
                from app.models.kronos_agent import KronosAgent
                kronos_pred = await asyncio.to_thread(KronosAgent.predict, yf_t, 30)
                kronos_trend = kronos_pred["trend"] if kronos_pred else "NEUTRAL"
                kronos_return = kronos_pred["predicted_return_pct"] if kronos_pred else 0.0
            except Exception as e:
                logger.error(f"Kronos prediction failed for {ticker}: {e}")
                kronos_trend = "NEUTRAL"
                kronos_return = 0.0

            change = q.get("change_pct", 0)
            
            if kronos_trend == "BULLISH" and iv < 0.45:
                trade = cls._recommend_bullish(ticker, spot, iv)
                trade.reasoning = f"Modelo Kronos prevê alta de {kronos_return:.1f}% em 30 dias. Volatilidade baixa ({iv*100:.1f}%) favorece a compra de estrutura."
                trades.append(trade)
            elif kronos_trend == "BEARISH" and iv < 0.45:
                trade = cls._recommend_bearish(ticker, spot, iv)
                trade.reasoning = f"Modelo Kronos prevê queda de {abs(kronos_return):.1f}% em 30 dias. IV moderado permite montagem de trava de baixa."
                trades.append(trade)
            elif iv > 0.45:
                trade = cls._recommend_income(ticker, spot, iv)
                trade.reasoning = f"Mesmo com previsão de {kronos_trend} ({kronos_return:.1f}%), a volatilidade implícita de {iv*100:.1f}% está muito alta. Recomenda-se venda coberta."
                trades.append(trade)
            else:
                trade = cls._recommend_bullish(ticker, spot, iv)
                trade.reasoning = f"Previsão neutra ou sem sinal forte ({kronos_return:.1f}%). Sugerimos alocação conservadora."
                trades.append(trade)

        # Sort by 'probability' or 'edge' and return top 5
        trades.sort(key=lambda x: x.prob_success, reverse=True)
        return trades[:5]

    @classmethod
    def _recommend_bullish(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        strike = round(spot * 1.05, 2) # 5% OTM
        cost = spot * 0.03 # generic premium estimate
        
        # Scenario
        scenario = {
            "p10_gain": spot * 0.10 * 100, # crude estimate
            "p5_gain": spot * 0.05 * 100,
            "m5_loss": -cost * 100
        }
        
        return OptionTrade(
            ticker=ticker,
            action="BULL CALL SPREAD",
            underlying_price=spot,
            strike=strike,
            strike_2=round(strike * 1.05, 2),
            cost_brl=cost,
            iv=iv,
            prob_success=58.0,
            reasoning=f"Tendência de alta confirmada em {ticker}. Volatilidade baixa ({iv*100:.1f}%) favorece a compra de estrutura. Trava de alta reduz o custo e protege contra queda moderada.",
            scenario_analysis=scenario
        )

    @classmethod
    def _recommend_bearish(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        strike = round(spot * 0.95, 2)
        cost = spot * 0.03
        return OptionTrade(
            ticker=ticker,
            action="BEAR PUT SPREAD",
            underlying_price=spot,
            strike=strike,
            strike_2=round(strike * 0.95, 2),
            cost_brl=cost,
            iv=iv,
            prob_success=62.0,
            reasoning=f"Sinais de correção para {ticker}. IV moderado permite montagem de trava de baixa com bom custo/benefício.",
            scenario_analysis={}
        )

    @classmethod
    def _recommend_income(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        strike = round(spot * 1.08, 2)
        premium = spot * 0.05
        return OptionTrade(
            ticker=ticker,
            action="COVERED CALL",
            underlying_price=spot,
            strike=strike,
            cost_brl=-premium, # credit
            iv=iv,
            prob_success=75.0,
            reasoning=f"Volatilidade implícita de {iv*100:.1f}% em {ticker} está muito acima da média. Venda de CALL (Lançamento Coberto) permite rentabilizar a carteira com prêmio gordo.",
            scenario_analysis={}
        )

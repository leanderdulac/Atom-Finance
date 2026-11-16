"""
Options Expert AI Agent — Logic for scanning B3 and identifying setups.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Literal

from app.models.pricing import BlackScholes
from app.services.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

# Horizon shared by every recommendation below (30 calendar days) and the
# BRL risk-free proxy used to price them. Wire the DI curve when available.
_HORIZON_T = 30.0 / 365.0
_SELIC_PROXY = 0.10

@dataclasses.dataclass
class OptionTrade:
    ticker: str
    action: Literal["BUY CALL", "SELL CALL", "BUY PUT", "SELL PUT", "BULL CALL SPREAD", "BEAR PUT SPREAD", "COVERED CALL"]
    underlying_price: float
    strike: float
    strike_2: float | None = None
    expiry_days: int = 30
    iv: float = 0.30
    delta: float = 0.50
    theta: float = -0.01
    cost_brl: float = 0.0
    max_profit: float | None = None
    max_loss: float | None = None
    prob_success: float = 50.0
    reasoning: str = ""
    scenario_analysis: dict[str, float] = dataclasses.field(default_factory=dict)

class OptionsExpert:
    
    TOP_B3_TICKERS = [
        "PETR4", "VALE3", "ITUB4", "BBDC4", "ABEV3", "BBAS3", "ELET3", "RENT3", "WEGE3", 
        "LREN3", "CSAN3", "JBSS32", "SUZB3", "RDOR3", "GGBR4", "RAIL3", "PRIO3", "TIMS3",
        "VIVT3", "MGLU3", "HAPV3", "SANB11", "ASAI3", "B3SA3", "CPLE6", "EQTL3", "UGPA3"
    ]

    @classmethod
    async def scan_market(cls, limit: int = 15) -> list[OptionTrade]:
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
                logger.error("Kronos prediction failed for %s: %s", ticker, e)
                kronos_trend = "NEUTRAL"
                kronos_return = 0.0

            # q["change_pct"] (today's move) is intentionally not used for routing:
            # the trade direction is driven by Kronos's 30-day forecast, and a
            # single day's print is noise relative to that horizon.

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
    def _bs_call(cls, spot: float, strike: float, iv: float):
        return BlackScholes.greeks(spot, strike, _HORIZON_T, _SELIC_PROXY, iv, "call")

    @classmethod
    def _bs_put(cls, spot: float, strike: float, iv: float):
        return BlackScholes.greeks(spot, strike, _HORIZON_T, _SELIC_PROXY, iv, "put")

    @classmethod
    def _recommend_bullish(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        from scipy.stats import norm as _norm

        k1 = round(spot * 1.05, 2)  # 5% OTM long leg
        k2 = round(k1 * 1.05, 2)  # short leg caps the upside
        long_leg, short_leg = cls._bs_call(spot, k1, iv), cls._bs_call(spot, k2, iv)
        debit = long_leg.price - short_leg.price
        max_profit = (k2 - k1) - debit
        # First-order P(expiring above K1): risk-neutral N(d2) of the long leg.
        d2 = BlackScholes.d2(spot, k1, _HORIZON_T, _SELIC_PROXY, iv)
        prob = float(_norm.cdf(d2) * 100.0)

        return OptionTrade(
            ticker=ticker,
            action="BULL CALL SPREAD",
            underlying_price=spot,
            strike=k1,
            strike_2=k2,
            cost_brl=round(debit, 2),
            iv=iv,
            delta=round(long_leg.delta - short_leg.delta, 4),
            theta=round(long_leg.theta - short_leg.theta, 6),
            max_profit=round(max_profit, 2),
            max_loss=round(-debit, 2),
            prob_success=round(prob, 1),
            reasoning=f"Tendência de alta em {ticker}. Trava {k1}/{k2} precificada a R${debit:.2f} (BS 30d, IV {iv*100:.1f}%).",
            scenario_analysis={
                "p10_gain": round((k2 - k1 - debit) * 100, 2),
                "p5_gain": round(max(spot * 1.05 - k1, 0.0) * 100 - debit * 100, 2),
                "m5_loss": round(-debit * 100, 2),
            },
        )

    @classmethod
    def _recommend_bearish(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        from scipy.stats import norm as _norm

        k1 = round(spot * 0.95, 2)  # long put, 5% OTM-down
        k2 = round(k1 * 0.95, 2)  # short put funds it
        long_leg, short_leg = cls._bs_put(spot, k1, iv), cls._bs_put(spot, k2, iv)
        debit = long_leg.price - short_leg.price
        max_profit = (k1 - k2) - debit
        d2 = BlackScholes.d2(spot, k1, _HORIZON_T, _SELIC_PROXY, iv)
        prob = float(_norm.cdf(-d2) * 100.0)

        return OptionTrade(
            ticker=ticker,
            action="BEAR PUT SPREAD",
            underlying_price=spot,
            strike=k1,
            strike_2=k2,
            cost_brl=round(debit, 2),
            iv=iv,
            delta=round(long_leg.delta - short_leg.delta, 4),
            theta=round(long_leg.theta - short_leg.theta, 6),
            max_profit=round(max_profit, 2),
            max_loss=round(-debit, 2),
            prob_success=round(prob, 1),
            reasoning=f"Sinais de correção para {ticker}. Trava {k2}/{k1} precificada a R${debit:.2f} (BS 30d, IV {iv*100:.1f}%).",
            scenario_analysis={
                "m10_gain": round((k1 - k2 - debit) * 100, 2),
                "m5_gain": round(max(k1 - spot * 0.95, 0.0) * 100 - debit * 100, 2),
                "p5_loss": round(-debit * 100, 2),
            },
        )

    @classmethod
    def _recommend_income(cls, ticker: str, spot: float, iv: float) -> OptionTrade:
        from scipy.stats import norm as _norm

        strike = round(spot * 1.08, 2)
        leg = cls._bs_call(spot, strike, iv)
        premium = leg.price
        d2 = BlackScholes.d2(spot, strike, _HORIZON_T, _SELIC_PROXY, iv)
        prob = float(_norm.cdf(-d2) * 100.0)  # expire below K: keep it all
        return OptionTrade(
            ticker=ticker,
            action="COVERED CALL",
            underlying_price=spot,
            strike=strike,
            cost_brl=-round(premium, 2),  # credit
            iv=iv,
            delta=round(1.0 - leg.delta, 4),  # long stock + short call
            theta=round(-leg.theta, 6),
            max_profit=round(premium, 2),
            max_loss=round(premium - spot, 2),
            prob_success=round(prob, 1),
            reasoning=f"IV de {iv*100:.1f}% em {ticker} sustenta lançamento coberto {strike} por R${premium:.2f} (BS 30d).",
            scenario_analysis={
                "flat_keep": round(premium * 100, 2),
                "up8_capped": round((strike - spot + premium) * 100, 2),
            },
        )

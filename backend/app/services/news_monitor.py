"""
News Monitor Service — Uses Gemini 1.5 Pro to analyze market news 
fetched from Yahoo Finance or other sources.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any

from app.core.ai_factory import AIFactory
from app.services.data_fetcher import _get_yfinance

logger = logging.getLogger(__name__)

class NewsMonitor:
    
    @staticmethod
    async def get_latest_news(ticker: str) -> List[Dict[str, Any]]:
        """Fetch news from Yahoo Finance for a given ticker."""
        yf = _get_yfinance()
        if not yf: return []
        
        try:
            # Handle B3 suffix
            if len(ticker) >= 5 and ticker[:4].isalpha():
                if not ticker.endswith(".SA"):
                    ticker = f"{ticker}.SA"
            
            t = yf.Ticker(ticker)
            news = t.news
            return news if news else []
        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {e}")
            return []

    @classmethod
    async def analyze_sentiment(cls, ticker: str) -> Dict[str, Any]:
        """
        Fetches latest news and uses Gemini to analyze impact and sentiment.
        """
        news_items = await cls.get_latest_news(ticker)
        if not news_items:
            return {
                "ticker": ticker,
                "sentiment": "Neutro",
                "score": 50,
                "summary": "Nenhuma notícia recente encontrada para este ativo.",
                "highlights": []
            }

        # Consolidate news for Gemini
        news_text = "\n---\n".join([
            f"Título: {item.get('title')}\nLink: {item.get('link')}\nPublicado: {item.get('publisher')}"
            for item in news_items[:5] # Analyze top 5
        ])

        analysis = await AIFactory.monitor_news(ticker, news_text)
        
        # Simple heuristic to extract score/sentiment from Gemini's text 
        # (Ideal: prompt Gemini to return JSON, but for now we use the raw narrative)
        return {
            "ticker": ticker,
            "news_count": len(news_items),
            "ai_analysis": analysis,
            "provider": "Google Gemini 1.5 Pro"
        }

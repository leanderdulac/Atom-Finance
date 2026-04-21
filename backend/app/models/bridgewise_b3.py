"""
Bridgewise B3 Specialist — Real Integration with Bridgewise API 
(rest.bridgewise.com) for B3 assets.
"""
from __future__ import annotations
import os
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class BridgewiseB3:
    """
    Integrates with Bridgewise Companies API:
    - Identifier search (Ticker -> company_id)
    - Fundamental Analysis
    - Fundamental Paragraphs (AI Report)
    """
    BASE_URL = os.getenv("BRIDGEWISE_BASE_URL", "https://rest.bridgewise.com")
    TOKEN = os.getenv("BRIDGEWISE_TOKEN")

    @classmethod
    async def _get_headers(cls) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {cls.TOKEN}",
            "Content-Type": "application/json"
        }

    @classmethod
    async def get_company_id(cls, ticker: str) -> Optional[int]:
        """Search for the Bridgewise company_id using the ticker."""
        if not cls.TOKEN: return None
        
        try:
            async with httpx.AsyncClient() as client:
                # Bridgewise often requires .SA for Brazilian stocks in search
                query = f"{ticker}.SA" if len(ticker) <= 5 and not ticker.endswith(".SA") else ticker
                params = {"query": query}
                response = await client.get(
                    f"{cls.BASE_URL}/identifier-search", 
                    headers=await cls._get_headers(),
                    params=params
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        return data[0].get("companyid") or data[0].get("company_id")
                
                logger.warning(f"Bridgewise: Company ID not found for {ticker}. Status: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Bridgewise identifier-search error: {e}")
            return None

    @classmethod
    async def get_analysis(cls, ticker: str) -> Dict[str, Any]:
        """
        Fetches real scoring and narrative from Bridgewise.
        """
        if not cls.TOKEN:
            return {"error": "BRIDGEWISE_TOKEN não configurado.", "details": "Utilizando simulação quantitativa."}

        company_id = await cls.get_company_id(ticker)
        if not company_id:
            return {"error": f"Ativo {ticker} não encontrado na base Bridgewise."}

        try:
            async with httpx.AsyncClient() as client:
                # 1. Fundamental Analysis (Scores)
                analysis_task = client.get(
                    f"{cls.BASE_URL}/companies/{company_id}/fundamental-analysis",
                    headers=await cls._get_headers()
                )
                
                # 2. Fundamental Paragraphs (Narrative in Portuguese)
                paragraphs_task = client.get(
                    f"{cls.BASE_URL}/companies/{company_id}/fundamental-paragraphs",
                    headers=await cls._get_headers(),
                    params={"language": "pt-BR"}
                )
                
                responses = await asyncio.gather(analysis_task, paragraphs_task)
                
                analysis_data = responses[0].json() if responses[0].status_code == 200 else {}
                paragraphs_data = responses[1].json() if responses[1].status_code == 200 else {}
                
                # Normalize response for ATOM UI
                # Bridgewise usually returns 'overall_score' (0-100) or 0-10
                overall_grade = analysis_data.get("overall_score", 0) / 10 if analysis_data.get("overall_score", 0) > 10 else analysis_data.get("overall_score", 0)

                return {
                    "ticker": ticker,
                    "company_id": company_id,
                    "overall_grade": round(float(overall_grade), 1),
                    "fundamental_score": analysis_data.get("fundamental_score"),
                    "technical_score": analysis_data.get("technical_score"),
                    "peer_rank": analysis_data.get("peer_rank_label", "Médio"),
                    "recommendation": analysis_data.get("recommendation_label", "NEUTRO"),
                    "paragraphs": paragraphs_data.get("paragraphs", []),
                    "bridgewise_narrative": paragraphs_data.get("summary", "Análise real Bridgewise processada."),
                    "is_real_data": True
                }

        except Exception as e:
            logger.error(f"Bridgewise total analysis error: {e}")
            return {"error": "Falha na comunicação com Bridgewise API."}

# Necessary for gathering. We'll import it where used or add here.
import asyncio

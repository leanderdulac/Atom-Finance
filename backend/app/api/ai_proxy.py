"""
AI Proxy — Routes AI calls through the backend so API keys never leave the server.
Supports Perplexity code refinement used by PaperCrawler & SPYIntraday pages.
"""

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.limiter import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

_ALLOWED_MODELS = frozenset({"sonar-pro", "sonar", "sonar-reasoning"})
_PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"


class RefineRequest(BaseModel):
    code: str = Field(max_length=20_000)
    instruction: str = Field(
        default=(
            "Implemente melhorias profissionais e vetorizadas. "
            "Retorne apenas o código Python puro, sem tags markdown."
        ),
        max_length=2_000,
    )
    model: str = "sonar-pro"


class RefineResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    refined_code: str
    model_used: str
    tokens_used: int = 0


@router.post("/perplexity/refine", response_model=RefineResponse)
@limiter.limit("10/hour")
async def perplexity_refine(request: Request, req: RefineRequest):
    """
    Proxy Perplexity API for code refinement.
    The PERPLEXITY_API_KEY is read from the server environment — never exposed to clients.
    """
    if req.model not in _ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported model")
    if not _PERPLEXITY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Perplexity API key not configured on the server. "
                   "Set PERPLEXITY_API_KEY in the backend .env file.",
        )

    payload = {
        "model": req.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Você é um Quantitative Researcher Senior especializado em Python para "
                    "finanças quantitativas (B3 e mercados globais). "
                    "Forneça APENAS o código Python puro, sem nenhuma marcação markdown."
                ),
            },
            {
                "role": "user",
                "content": f"{req.instruction}\n\nCódigo atual:\n{req.code}",
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                _PERPLEXITY_URL,
                headers={
                    "Authorization": f"Bearer {_PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        raw_text: str = data["choices"][0]["message"]["content"]
        # Strip markdown code fences if Perplexity adds them despite instructions
        cleaned = raw_text.replace("```python", "").replace("```", "").strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)

        return RefineResponse(refined_code=cleaned, model_used=req.model, tokens_used=tokens)

    except httpx.HTTPStatusError as exc:
        logger.error("Perplexity API error: %s — %s", exc.response.status_code, exc.response.text)
        raise HTTPException(status_code=502, detail=f"Perplexity API error: {exc.response.status_code}") from exc
    except Exception as exc:
        logger.error("Perplexity proxy unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Upstream AI provider failed") from exc

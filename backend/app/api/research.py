"""Authenticated gateway to the isolated QuantMind research worker."""

import os
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.core.security import get_current_user

router = APIRouter()


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["text", "arxiv"]
    content: str = Field(min_length=1, max_length=80000)


async def call_worker(method, path, **kwargs):
    token = os.getenv("QUANTMIND_SERVICE_TOKEN", "")
    if not token:
        raise HTTPException(503, "O serviço QuantMind ainda não foi configurado.")
    url = os.getenv("QUANTMIND_URL", "http://127.0.0.1:8010").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=195) as client:
            response = await client.request(
                method,
                url + path,
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        if response.is_error:
            if response.status_code in (404, 422, 502, 503, 504):
                detail = response.json().get("detail", "Falha no serviço de pesquisa.")
                raise HTTPException(response.status_code, detail)
            raise HTTPException(502, "Falha na comunicação com o serviço de pesquisa.")
        return response.json()
    except httpx.TimeoutException:
        raise HTTPException(
            504, "Tempo limite do serviço de pesquisa excedido."
        ) from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Serviço de pesquisa indisponível.") from None


@router.get("/health")
async def health(user: str = Depends(get_current_user)):
    return await call_worker("GET", "/health")


@router.post("/papers", status_code=201)
async def extract(req: ExtractRequest, user: str = Depends(get_current_user)):
    return await call_worker(
        "POST", "/papers", json={**req.model_dump(), "owner": user}
    )


@router.get("/papers")
async def papers(user: str = Depends(get_current_user)):
    return await call_worker("GET", "/papers", params={"owner": user})


@router.get("/papers/{paper_id}")
async def paper(paper_id: UUID, user: str = Depends(get_current_user)):
    return await call_worker("GET", f"/papers/{paper_id}", params={"owner": user})

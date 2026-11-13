"""Structured JSON from local agents. Invalid or sourceless news is discarded."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Severity = Literal["baixa", "media", "alta"]
Recommendation = Literal["manter", "reduzir", "recusar"]


class SourceRef(BaseModel):
    titulo: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=8, max_length=500)
    data: str = ""

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        raw = value.strip()
        if not raw.startswith(("http://", "https://")):
            raise ValueError("url precisa ser http(s)")
        return raw


class EventoProximo(BaseModel):
    nome: str
    data: str
    tipo: Literal["macro", "empresa", "crypto", "binary"] = "macro"
    impacto: Literal["baixo", "medio", "alto"] = "medio"


class NewsBrief(BaseModel):
    eventos_proximos: list[EventoProximo] = Field(default_factory=list)
    sentimento: float = Field(ge=-1.0, le=1.0)
    riscos: list[str] = Field(default_factory=list)
    fontes: list[SourceRef]
    xai_sentimento: float | None = None
    openai_sentimento: float | None = None
    source_disagreement: bool = False
    providers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_sources(self) -> NewsBrief:
        if not self.fontes:
            raise ValueError("news brief sem fontes")
        return self


class RiskBrief(BaseModel):
    objecoes: list[str] = Field(default_factory=list)
    severidade: Severity
    recomendacao: Recommendation

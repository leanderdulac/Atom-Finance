"""Private QuantMind worker, isolated from the numerical backend dependencies."""

import asyncio
import json
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from quantmind.configs import PaperFlowCfg
from quantmind.configs.paper import ArxivIdentifier, RawText
from quantmind.flows import paper_flow

logger = logging.getLogger(__name__)


def authorize(authorization: str = Header(default="")):
    token = os.getenv("QUANTMIND_SERVICE_TOKEN", "")
    if not token or not secrets.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(401, "Invalid service credentials")


app = FastAPI(title="ATOM Research", dependencies=[Depends(authorize)])


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    owner: str = Field(min_length=1, max_length=200)
    kind: Literal["text", "arxiv"]
    content: str = Field(min_length=1, max_length=80000)

    @model_validator(mode="after")
    def check_arxiv(self):
        """Accept identifiers only, never arbitrary URLs or server paths."""
        import re

        if self.kind == "arxiv" and not re.fullmatch(
            r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", self.content
        ):
            raise ValueError("Use an arXiv identifier, for example 2401.12345")
        return self


@contextmanager
def connect():
    """Open the persistent research store and initialize its schema."""
    path = Path(os.getenv("QUANTMIND_DB_PATH", "data/research.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS papers_owner ON papers(owner, created_at)")
    try:
        with db:
            yield db
    finally:
        db.close()


@app.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT 1")
    return {"status": "healthy", "configured": bool(os.getenv("OPENAI_API_KEY"))}


@app.post("/papers", status_code=201)
async def extract(req: ExtractRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Configure OPENAI_API_KEY no serviço de pesquisa.")
    inp = (
        ArxivIdentifier(id=req.content)
        if req.kind == "arxiv"
        else RawText(text=req.content)
    )
    cfg = PaperFlowCfg(
        model=os.getenv("QUANTMIND_MODEL", "gpt-4o-mini"),
        max_turns=3,
        tracing_disabled=True,
        trace_include_sensitive_data=False,
    )
    try:
        paper = await asyncio.wait_for(paper_flow(inp, cfg=cfg, extra_instructions=(
                "In the methodology and limitations sections, explicitly report the economic hypothesis, "
                "feature availability at decision time, point-in-time data and look-ahead risks, "
                "chronological out-of-sample validation, label purging/embargo, simple baselines, "
                "net transaction costs and turnover, volatility control, maximum drawdown and regime stability. "
                "Price is not a modelling target: prefer returns and regimes; the print is typically I(1). "
                "Evidence is sequential (signal at t uses only information ≤ t). "
                "Ask how many candidates a reported Sharpe beat (winner's curse / Deflated Sharpe). "
                "Shuffled K-Fold is invalid for financial series; require purged/embargoed temporal CV. "
                "For each absent item say not reported; never infer that an unreported check passed. "
                "Model complexity or training fit is not evidence of tradable alpha. "
                "Preserve supporting citations and distinguish author claims from demonstrated results."
            )), timeout=180)
        title = paper.root().title
    except asyncio.TimeoutError:
        raise HTTPException(
            504, "A extração excedeu o limite de três minutos."
        ) from None
    except Exception:
        logger.exception("Paper extraction failed")
        raise HTTPException(
            502, "Falha na extração. Verifique a fonte e a configuração do serviço."
        ) from None
    payload = paper.model_dump(mode="json")

    def save():
        with connect() as db:
            db.execute(
                "INSERT INTO papers VALUES (?, ?, ?, ?, ?)",
                (
                    str(paper.id),
                    req.owner,
                    title,
                    paper.created_at.isoformat(),
                    json.dumps(payload),
                ),
            )

    await asyncio.to_thread(save)
    return payload


@app.get("/papers")
def list_papers(owner: str, limit: int = 30):
    with connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT id, title, created_at FROM papers WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                (owner, max(1, min(limit, 100))),
            )
        ]


@app.get("/papers/{paper_id}")
def get_paper(paper_id: UUID, owner: str):
    with connect() as db:
        row = db.execute(
            "SELECT payload FROM papers WHERE id=? AND owner=?", (str(paper_id), owner)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Artigo não encontrado.")
    return json.loads(row["payload"])

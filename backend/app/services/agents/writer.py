"""Client-facing Portuguese: cite sources (title, url, date). No jargon."""
from __future__ import annotations

from app.services.agents.schemas import NewsBrief, SourceRef


def cite_sources(why: str, news: NewsBrief | None) -> str:
    body = (why or "").strip()
    fontes: list[SourceRef] = list(news.fontes) if news else []
    if not fontes:
        return body
    lines = [body, "", "Fontes consultadas (título, data, link):"]
    for src in fontes[:8]:
        date = f", {src.data}" if src.data else ""
        lines.append(f"• {src.titulo}{date} — {src.url}")
    return "\n".join(lines)

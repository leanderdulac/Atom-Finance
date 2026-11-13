"""Market thermometer: directional sentiment as a low-weight arsenal factor.

The LLM may summarise sources; it never picks entry, stop or target.
Score lives in [-1, +1]. Weight starts at ATOM_SENTIMENT_WEIGHT (default 0.2)
and only the evidence report may recommend raising it.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.services.agents.schemas import NewsBrief

_POS = (
    "alta", "sobe", "subiu", "rally", "bull", "recorde", "otimista", "surpresa positiva",
    "compra", "dispar", "valoriz", "green", "surge", "jump",
)
_NEG = (
    "queda", "desaba", "caiu", "crash", "bear", "pessimista", "crise", "recuo",
    "venda", "derrete", "tombo", "selloff", "plunge", "drop",
)
_CONF_ORDER = ("baixa", "média", "moderada")


def configured_weight() -> float:
    try:
        raw = float(os.getenv("ATOM_SENTIMENT_WEIGHT", "0.2"))
    except ValueError:
        raw = 0.2
    return float(min(max(raw, 0.0), 0.5))


def effective_weight(evidence: dict[str, Any] | None) -> float:
    """Default 0.2. A higher ATOM_SENTIMENT_WEIGHT only applies with evidence."""
    cap = configured_weight()
    if evidence and evidence.get("allows_raise"):
        return cap
    return min(cap, 0.2)


def climate_of(score: float) -> str:
    if score > 0.15:
        return "otimista"
    if score < -0.15:
        return "pessimista"
    return "neutro"


def climate_label(ticker: str, score: float) -> str:
    return f"Clima do mercado para {ticker}: {climate_of(score)}"


def lexical_score(titles: list[str]) -> float:
    if not titles:
        return 0.0
    acc = 0.0
    for title in titles:
        blob = (title or "").lower()
        acc += sum(1 for w in _POS if w in blob)
        acc -= sum(1 for w in _NEG if w in blob)
    return float(np.clip(acc / max(len(titles), 1), -1.0, 1.0))


def build_signal(
    ticker: str,
    horizon: str,
    *,
    news: NewsBrief | None,
    history: list[dict[str, Any]] | None = None,
    price: float | None = None,
    price_mom: float | None = None,
    holding_days: int = 21,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """None when there is no sourced brief — never invent a climate."""
    if news is None or not news.fontes:
        return None
    now = now or datetime.now(UTC)
    titles = [s.titulo for s in news.fontes]
    lex = lexical_score(titles)
    brief_s = float(news.sentimento)
    if abs(brief_s) < 1e-9:
        score = lex
    else:
        score = float(np.clip(0.7 * brief_s + 0.3 * lex, -1.0, 1.0))
    n_mentions = len(news.fontes)
    hist = list(history or [])
    avg_n = float(np.mean([int(r.get("n_mentions") or 0) for r in hist])) if hist else 0.0
    intensity = n_mentions / avg_n if avg_n >= 1 else 1.0
    prev = float(hist[-1]["score"]) if hist and hist[-1].get("score") is not None else score
    momentum = float(score - prev)
    if price_mom is None or abs(score) < 0.05 or abs(price_mom) < 1e-12:
        divergence = 0.0
    else:
        divergence = float(np.sign(score) * np.sign(price_mom))  # -1 = vs preço
    headlines = [
        {"title": s.titulo, "url": s.url, "date": s.data or now.date().isoformat()}
        for s in news.fontes[:3]
    ]
    sources = [{"title": s.titulo, "url": s.url, "date": s.data} for s in news.fontes]
    tone = climate_of(score)
    return {
        "ticker": ticker,
        "horizon": horizon,
        "score": round(score, 4),
        "intensity": round(float(intensity), 4),
        "momentum": round(momentum, 4),
        "price": price,
        "price_divergence": round(divergence, 4),
        "n_mentions": n_mentions,
        "holding_days": holding_days,
        "as_of": now.isoformat(),
        "headlines": headlines,
        "sources": sources,
        "climate": tone,
        "label": climate_label(ticker, score),
        "xai_sentimento": news.xai_sentimento,
        "openai_sentimento": news.openai_sentimento,
        "gemini_sentimento": news.gemini_sentimento,
        "dispersion": news.dispersion,
        "source_disagreement": bool(news.source_disagreement),
        "providers": list(news.providers or []),
        "eligible_for_live_trading": False,
    }


def thermometer_view(signal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not signal:
        return None
    return {
        "label": signal.get("label") or climate_label(str(signal.get("ticker") or ""), float(signal.get("score") or 0)),
        "tone": signal.get("climate") or climate_of(float(signal.get("score") or 0)),
        "score": signal.get("score"),
        "headlines": (signal.get("headlines") or [])[:3],
    }


def quant_score(local: str, z_score: float, mom: float, horizon_vol: float) -> float:
    if local == "mean_reverting":
        if z_score > 0.5:
            return -1.0
        if z_score < -0.5:
            return 1.0
        return 0.0
    noise = 0.15 * max(horizon_vol, 1e-9)
    if abs(mom) < noise:
        return 0.0
    return float(np.clip(mom / max(horizon_vol, 1e-9), -1.0, 1.0))


def blend_direction(
    q: float,
    s: float,
    weight: float,
) -> tuple[str | None, str, float]:
    """Return (direction or None, relation, combined). LLM does not vote here."""
    w = float(min(max(weight, 0.0), 0.5))
    combined = (1.0 - w) * q + w * s
    disagree = q != 0 and s != 0 and (q * s) < 0
    agree = q != 0 and s != 0 and (q * s) > 0
    if abs(combined) < 0.12:
        return None, "neutro", combined
    if disagree and abs(combined) < 0.25:
        return None, "desacordo", combined
    direction = "bullish" if combined > 0 else "bearish"
    relation = "acordo" if agree else ("desacordo" if disagree else "neutro")
    return direction, relation, combined


def adjust_confidence(base: str, relation: str) -> str:
    if base not in _CONF_ORDER:
        base = "baixa"
    idx = _CONF_ORDER.index(base)
    if relation == "acordo":
        idx = min(idx + 1, len(_CONF_ORDER) - 1)
    elif relation == "desacordo":
        idx = 0
    return _CONF_ORDER[idx]

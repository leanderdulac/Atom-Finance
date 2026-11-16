"""Honest skill of the thermometer vs future returns. Weight does not auto-rise."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
from datetime import timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MIN_PAIRS = 20
HIT_FLOOR = 0.52
CORR_FLOOR = 0.05


def evaluate_pairs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Each row needs created_at, score, price, holding_days.

    Future return = first later print at least holding_days later, if priced.
    """
    ordered = sorted(
        (r for r in rows if r.get("created_at") is not None),
        key=lambda r: r["created_at"],
    )
    xs: list[float] = []
    ys: list[float] = []
    hits = 0
    for i, row in enumerate(ordered):
        price = row.get("price")
        score = row.get("score")
        if price in (None, 0) or score is None:
            continue
        hold = int(row.get("holding_days") or 21)
        created = row.get("created_at")
        later_price = None
        for nxt in ordered[i + 1 :]:
            nxt_t = nxt.get("created_at")
            nxt_p = nxt.get("price")
            if nxt_p in (None, 0) or created is None or nxt_t is None:
                continue
            if nxt_t - created >= timedelta(days=max(hold - 1, 1)):
                later_price = float(nxt_p)
                break
        if later_price is None:
            continue
        fut = later_price / float(price) - 1.0
        xs.append(float(score))
        ys.append(fut)
        if abs(float(score)) >= 0.05 and abs(fut) >= 1e-12:
            if (float(score) > 0) == (fut > 0):
                hits += 1
    n = len(xs)
    if n < 2:
        return {
            "n": n,
            "correlation": None,
            "hit_rate": None,
            "allows_raise": False,
            "assessment": "insufficient_evidence",
            "note": "Ainda não há pares sinal→retorno futuro suficientes para um teste honesto.",
            "recommended_weight": 0.2,
            "eligible_for_live_trading": False,
        }
    corr = float(np.corrcoef(xs, ys)[0, 1]) if n >= 3 else None
    if corr is not None and (math.isnan(corr) or math.isinf(corr)):
        corr = None
    signed = sum(1 for x, y in zip(xs, ys, strict=True) if abs(x) >= 0.05 and abs(y) >= 1e-12)
    hit_rate = (hits / signed) if signed else None
    allows = (
        n >= MIN_PAIRS
        and hit_rate is not None and hit_rate > HIT_FLOOR
        and corr is not None and corr > CORR_FLOOR
    )
    note = (
        "Correlação e acerto do clima vs retorno posterior no horizonte. "
        "O peso do termômetro só sobe com este relatório — não com um print isolado."
    )
    if not allows:
        note += f" Evidência insuficiente (n={n}, mínimo {MIN_PAIRS}; acerto > {HIT_FLOOR}, correlação > {CORR_FLOOR})."
    return {
        "n": n,
        "correlation": None if corr is None else round(corr, 4),
        "hit_rate": None if hit_rate is None else round(hit_rate, 4),
        "allows_raise": allows,
        "assessment": "candidate" if allows else "insufficient_evidence",
        "note": note,
        "recommended_weight": 0.2 if not allows else 0.3,
        "eligible_for_live_trading": False,
    }


async def evaluate_ticker(ticker: str, horizon: str) -> dict[str, Any]:
    from app.db.sentiment import list_snapshots

    rows = await list_snapshots(ticker, horizon, limit=2000)
    report = evaluate_pairs(rows)
    report.update({"ticker": ticker, "horizon": horizon})
    return report


async def record_diary(owner: str, report: dict[str, Any]) -> str | None:
    from app.db import experiments

    hypothesis = (
        f"O termômetro de sentimento de {report.get('ticker')} no horizonte "
        f"{report.get('horizon')} prevê o sinal do retorno futuro melhor que o acaso, "
        "sem autorizar capital real e sem o LLM escolher preço."
    )
    run_id = await experiments.begin(owner, {
        "hypothesis": hypothesis,
        "data_source": "sentiment_snapshots+public_news_xsearch",
        "model": "thermometer-hitrate",
        "ticker": report.get("ticker"),
        "horizon": report.get("horizon"),
        "n": report.get("n"),
    })
    await experiments.finish(run_id, result={
        "assessment": report.get("assessment"),
        "results": {"thermometer": {
            "net_return_pct": 0,
            "sharpe_net": 0,
            "max_drawdown_pct": 0,
            "cost_paid_pct_initial": 0,
            "correlation": report.get("correlation"),
            "hit_rate": report.get("hit_rate"),
            "n": report.get("n"),
        }},
        "config": {"model": "thermometer"},
        "reasons": [report.get("note")],
        "limitations": [
            "Paper only. Correlação não é causalidade. Peso não sobe sozinho.",
            "Sem N de pares suficiente o relatório recusa evidência.",
        ],
        "eligible_for_live_trading": False,
    })
    return run_id


async def _cli(ticker: str, horizon: str) -> None:
    report = await evaluate_ticker(ticker, horizon)
    print(json.dumps(report, default=str, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Poder preditivo do termômetro (paper).")
    parser.add_argument("--ticker", default="BTC")
    parser.add_argument("--horizon", default="weeks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_cli(args.ticker, args.horizon))


if __name__ == "__main__":
    main()

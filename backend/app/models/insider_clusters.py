"""
Insider-cluster detector inspired by Cohen, Malloy & Pomorski (2012).

The paper's usable idea: routine (calendar-predictable) insider trades are less
informative than opportunistic, clustered ones. We do not fetch SEC EDGAR here.
Pass Form-4-like events: ticker, insider_id, side (buy/sell), shares, date
(YYYY-MM-DD). A cluster is ≥ min_insiders distinct insiders in the same ticker
and direction inside a window of `window_days`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta


def _parse(date: str) -> datetime:
    return datetime.strptime(date[:10], "%Y-%m-%d")


def detect(
    events: list[dict],
    window_days: int = 7,
    min_insiders: int = 3,
) -> dict:
    if window_days < 1 or min_insiders < 2:
        raise ValueError("window_days ≥ 1 and min_insiders ≥ 2")
    parsed = []
    for e in events:
        side = str(e.get("side", "")).lower()
        if side not in {"buy", "sell"}:
            raise ValueError("Each event needs side='buy' or 'sell'")
        shares = float(e["shares"])
        if shares <= 0:
            raise ValueError("shares must be positive")
        parsed.append({
            "ticker": str(e["ticker"]).upper(),
            "insider_id": str(e["insider_id"]),
            "side": side,
            "shares": shares,
            "date": _parse(str(e["date"])),
            "notional": float(e.get("notional", shares)),
        })
    parsed.sort(key=lambda r: (r["ticker"], r["date"]))

    clusters: list[dict] = []
    by_ticker: dict[str, list] = defaultdict(list)
    for row in parsed:
        by_ticker[row["ticker"]].append(row)

    for ticker, rows in by_ticker.items():
        n = len(rows)
        i = 0
        while i < n:
            start = rows[i]["date"]
            end = start + timedelta(days=window_days)
            j = i
            bucket = []
            while j < n and rows[j]["date"] <= end:
                bucket.append(rows[j])
                j += 1
            for side in ("buy", "sell"):
                subset = [r for r in bucket if r["side"] == side]
                insiders = {r["insider_id"] for r in subset}
                if len(insiders) >= min_insiders:
                    shares = sum(r["shares"] for r in subset)
                    notional = sum(r["notional"] for r in subset)
                    clusters.append({
                        "ticker": ticker,
                        "side": side,
                        "window_start": start.date().isoformat(),
                        "window_end": min(end, rows[j - 1]["date"]).date().isoformat(),
                        "n_insiders": len(insiders),
                        "n_trades": len(subset),
                        "shares": round(shares, 2),
                        "notional": round(notional, 2),
                        "cluster_score": round(len(insiders) * math.log1p(notional), 4),
                    })
            i += 1 if j == i else max(1, (j - i) // 2)

    # De-duplicate overlapping windows by keeping the highest score per ticker/side/day.
    best: dict[tuple, dict] = {}
    for c in clusters:
        key = (c["ticker"], c["side"], c["window_start"])
        if key not in best or c["cluster_score"] > best[key]["cluster_score"]:
            best[key] = c
    ranked = sorted(best.values(), key=lambda c: c["cluster_score"], reverse=True)
    return {
        "n_events": len(parsed),
        "n_tickers": len(by_ticker),
        "n_clusters": len(ranked),
        "clusters": ranked[:50],
        "window_days": window_days,
        "min_insiders": min_insiders,
        "math": (
            "Opportunistic cluster ≈ several distinct insiders, same name, same direction, "
            "inside a short window. Routine isolated Form-4s are ignored."
        ),
        "eligible_for_live_trading": False,
        "what_broke": [
            "No EDGAR pull unless you call /desk/insider-clusters/edgar with ATOM_SEC_USER_AGENT.",
            "Share counts without price/notional overweight penny-stock grants.",
            "Overlapping windows still double-count a burst that lasts longer than `window_days`.",
            "Publicly clustered buys can be already in the price by the time the filing hits.",
        ],
    }

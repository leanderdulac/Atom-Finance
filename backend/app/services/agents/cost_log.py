"""Shared estimated-USD diary for paid context providers. Not a bill."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.cache import Cache

COST_KEY = "atom:context:costs"
LEGACY_OPENAI_KEY = "atom:openai:costs"
COST_TTL = 7 * 24 * 3600
COST_MAX = 200


def log_cost(entry: dict[str, Any]) -> dict[str, Any]:
    row = {
        **entry,
        "at": datetime.now(UTC).isoformat(),
        "eligible_for_live_trading": False,
        "estimate": True,
    }
    rows = Cache.get(COST_KEY)
    if not isinstance(rows, list):
        rows = []
    rows.insert(0, row)
    Cache.set(COST_KEY, rows[:COST_MAX], ex=COST_TTL)
    return row


def recent_costs(limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (COST_KEY, LEGACY_OPENAI_KEY):
        got = Cache.get(key)
        if isinstance(got, list):
            rows.extend(r for r in got if isinstance(r, dict))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        stamp = f"{row.get('at')}|{row.get('provider')}|{row.get('kind')}|{row.get('ticker')}"
        if stamp in seen:
            continue
        seen.add(stamp)
        out.append(row)
    return out[: max(1, min(limit, COST_MAX))]

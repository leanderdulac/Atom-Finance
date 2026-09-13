"""4-hour regime snapshot job. Disabled when ATOM_ENV=test or ATOM_REGIME_JOB!=1."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from app.models.regime import evaluate
from app.services.regime_context import write_context
from app.services.regime_feeds import fetch_live_payload

logger = logging.getLogger(__name__)

_LAST: dict[str, Any] | None = None


def last_snapshot() -> dict[str, Any] | None:
    return _LAST


def job_enabled() -> bool:
    if os.getenv("ATOM_ENV") == "test":
        return False
    return os.getenv("ATOM_REGIME_JOB", "0") == "1"


def job_interval_seconds() -> int:
    raw = os.getenv("ATOM_REGIME_JOB_SECONDS", "14400")
    try:
        return max(60, int(raw))
    except ValueError:
        return 14400


def run_snapshot(*, fetch=fetch_live_payload) -> dict[str, Any]:
    payload = fetch()
    extra = {k: payload.pop(k) for k in ("live_books", "sources", "n_obs", "as_of_session") if k in payload}
    result = evaluate(**payload, as_of=extra.get("as_of_session"))
    result.update(extra)
    dest = os.getenv("ATOM_STRATEGY_CONTEXT_DIR", "").strip()
    if dest:
        path = Path(dest).expanduser()
        if path.is_absolute():
            write_context(path, result)
            result["context_dir"] = str(path)
    global _LAST
    _LAST = result
    return result


async def maybe_flatten_operator(result: dict[str, Any]) -> dict[str, Any] | None:
    if not result.get("kill_switch", {}).get("armed"):
        return None
    owner = os.getenv("ATOM_REGIME_KILL_OWNER", "").strip()
    if not owner:
        return None
    from app.api.paper_trades import flatten_open_trades

    return await flatten_open_trades(owner, reason="regime_job_crisis")


async def loop() -> None:
    interval = job_interval_seconds()
    logger.info("Regime job armed every %ss", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            result = await asyncio.to_thread(run_snapshot)
            flat = await maybe_flatten_operator(result)
            if flat:
                logger.warning("Paper flatten for %s: %s", os.getenv("ATOM_REGIME_KILL_OWNER"), flat)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Regime job tick failed")

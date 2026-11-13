"""Pre-warm public context for the assets the client screen uses most.

Does not write the research diary — that happens on assemble, with the
operation. ATOM_ENV=test and ATOM_CONTEXT_JOB=0 disable the loop.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

WARM = (
    ("PETR4", "weeks", "equity_br"),
    ("VALE3", "weeks", "equity_br"),
    ("ITUB4", "weeks", "equity_br"),
    ("BTC", "weeks", "crypto"),
    ("ETH", "weeks", "crypto"),
)


def job_enabled() -> bool:
    if os.getenv("ATOM_ENV") == "test":
        return False
    return os.getenv("ATOM_CONTEXT_JOB", "0").strip() == "1"


def interval_seconds() -> int:
    try:
        return max(60, int(os.getenv("ATOM_CONTEXT_JOB_SECONDS", "300")))
    except ValueError:
        return 300


async def warm_once() -> None:
    from app.services.context.gather import gather_context

    for ticker, horizon, asset_class in WARM:
        try:
            await asyncio.to_thread(gather_context, ticker, horizon, asset_class=asset_class)
        except Exception as exc:
            logger.info("Context prewarm %s failed (%s)", ticker, type(exc).__name__)


async def loop() -> None:
    delay = interval_seconds()
    logger.info("Context prewarm every %ss", delay)
    while True:
        await warm_once()
        await asyncio.sleep(delay)

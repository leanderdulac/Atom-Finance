"""Pre-warm public context and persist the thermometer series.

Does not write the research diary on every tick — that happens when an
operator asks for the skill report. ATOM_ENV=test and ATOM_CONTEXT_JOB=0
disable the loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

from app.models.ready_operation import Horizon

logger = logging.getLogger(__name__)

WARM: tuple[tuple[str, Horizon, Literal["equity_br", "crypto"]], ...] = (
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
    from app.api.client import _load_sentiment, _persist_signal
    from app.services.agents.news import run_news_agent
    from app.services.client_arsenal import load_market
    from app.services.context.gather import gather_context

    for ticker, horizon, asset_class in WARM:
        try:
            await asyncio.to_thread(gather_context, ticker, horizon, asset_class=asset_class)
            news = await run_news_agent(ticker, horizon, asset_class=asset_class)
            market = await asyncio.to_thread(load_market, ticker)
            signal, _weight = await _load_sentiment(ticker, horizon, news, market)
            await _persist_signal(signal)
        except Exception as exc:
            logger.info("Context prewarm %s failed (%s)", ticker, type(exc).__name__)


async def loop() -> None:
    delay = interval_seconds()
    logger.info("Context prewarm every %ss", delay)
    while True:
        await warm_once()
        await asyncio.sleep(delay)

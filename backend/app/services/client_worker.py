"""Standalone scheduler for launchd: regime + client arsenal cache.

    python -m app.services.client_worker

Disabled when ATOM_ENV=test. The FastAPI process can run the same loops;
use ATOM_CLIENT_JOB=0 / ATOM_REGIME_JOB=0 on uvicorn when this worker is
the one holding the timers (see ops/macos).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / "backend" / ".env", override=False)

logging.basicConfig(
    level=os.getenv("ATOM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("atom.worker")


async def main() -> None:
    if os.getenv("ATOM_ENV") == "test":
        logger.info("ATOM_ENV=test — worker not started")
        return
    from app.core.cache import Cache
    from app.db.postgres import close_pool, get_pool
    from app.services.client_arsenal import job_enabled as client_on
    from app.services.client_arsenal import loop as client_loop
    from app.services.regime_job import job_enabled as regime_on
    from app.services.regime_job import loop as regime_loop

    await get_pool()
    Cache.is_redis_available()
    tasks = []
    if regime_on() or os.getenv("ATOM_WORKER_REGIME", "1") == "1":
        tasks.append(asyncio.create_task(regime_loop(), name="regime-job"))
    if client_on() or os.getenv("ATOM_WORKER_CLIENT", "1") == "1":
        tasks.append(asyncio.create_task(client_loop(), name="client-arsenal"))
    if not tasks:
        logger.error("No jobs enabled — set ATOM_REGIME_JOB=1 and/or ATOM_CLIENT_JOB=1")
        sys.exit(1)
    logger.info("Worker running %s", [t.get_name() for t in tasks])
    try:
        await asyncio.gather(*tasks)
    finally:
        await close_pool()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped")

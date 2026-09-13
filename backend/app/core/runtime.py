"""Startup readiness check and crash recovery.

The old SQLite runtime held an fcntl file lock for the process's lifetime
because SQLite can't safely take concurrent writers from multiple processes
("ATOM SQLite requires one process per database"). Postgres has no such
constraint — that's a large part of why this migration exists — so the lock
is gone.

CAUTION for whoever implements Fase 4 (scaling the app tier / multiple
workers or replicas): the crash-recovery UPDATE below marks every orphaned
'running' experiment as failed on startup. That's correct for a single
process today. With more than one worker/replica, a worker starting up
would incorrectly fail another worker's in-flight experiment. This needs a
per-worker or per-run recovery scope (e.g. a worker/lease id on the row)
before Fase 4 ships — don't just remove this comment and add --workers.
"""
from contextlib import asynccontextmanager

from app.db import database
from app.db.postgres import get_pool


@asynccontextmanager
async def exclusive_runtime():
    await database.readiness()
    pool = await get_pool()
    await pool.execute(
        "UPDATE experiments SET status='failed', error=$1 WHERE status='running'",
        'Process interrupted; create a new experiment to retry.',
    )
    yield

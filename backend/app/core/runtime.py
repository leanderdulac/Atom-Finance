"""Single-process SQLite pilot runtime: exclusive lock and crash recovery."""
import fcntl
from contextlib import contextmanager

from app.db import database, experiments


@contextmanager
def exclusive_runtime():
    # Hold throughout lifespan. A second worker/replica sharing this DB fails closed.
    with open(database._DB_PATH + '.runtime.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('ATOM SQLite requires one process per database') from exc
        try:
            with database._get_conn() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
            database.readiness()
            with database._get_conn() as conn:
                experiments.setup(conn)
                conn.execute("UPDATE experiments SET status='failed', error=? WHERE status='running'",
                             ('Process interrupted; create a new experiment to retry.',))
                conn.commit()
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

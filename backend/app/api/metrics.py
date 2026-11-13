"""Prometheus observability for ATOM.

One text endpoint, fail-closed by default: /api/metrics requires a JWT unless
ATOM_METRICS_PUBLIC=true is explicitly set (then it must sit behind a trusted
network — in the prod compose the backend is internal-only). Request labels use
the matched endpoint handler name (bounded cardinality — never query strings,
resource ids, or ambiguous module-relative paths).

Route registration follows CONTRIBUTING.md: registered in main.py.
"""
from __future__ import annotations

import os
import time

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    Security,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

_bearer = HTTPBearer(auto_error=False)

router = APIRouter()

HTTP_REQUESTS = Counter(
    "atom_http_requests_total",
    "HTTP responses by method, endpoint handler and status",
    ("method", "handler", "status"),
)
HTTP_DURATION = Histogram(
    "atom_http_request_duration_seconds",
    "Request duration in seconds by method and endpoint handler",
    ("method", "handler"),
    buckets=(0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 120.0),
)
DB_POOL_SIZE = Gauge("atom_db_pool_size", "asyncpg pool connections", ("state",))


def _metrics_public() -> bool:
    return os.getenv("ATOM_METRICS_PUBLIC", "").strip().lower() in ("1", "true", "yes")


async def _metrics_access(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Dependency: JWT required unless ATOM_METRICS_PUBLIC is explicitly set."""
    if _metrics_public():
        return
    if credentials is None:
        raise HTTPException(401, "Metrics require a token (or ATOM_METRICS_PUBLIC=true on a trusted network)")
    from app.core.security import decode_token

    if decode_token(credentials.credentials) is None:
        raise HTTPException(401, "Invalid or expired token")


def _handler_label(request: Request) -> str:
    """Bounded cardinality: the matched endpoint function name.

    (This FastAPI keeps include_router prefixes in nested routers, so
    scope["route"].path is module-relative and would both lose the /api
    prefix and collide labels across routers — /export exists in more than
    one. The endpoint handler is unique per route and never contains ids.)
    """
    endpoint = request.scope.get("endpoint")
    name = getattr(endpoint, "__qualname__", None)
    return name if isinstance(name, str) and name else "unmatched"


async def metrics_middleware(request: Request, call_next):
    """Handler instrumentation: one counter + one histogram per request."""
    start = time.perf_counter()
    response = await call_next(request)
    try:
        handler = _handler_label(request)
        HTTP_REQUESTS.labels(method=request.method, handler=handler, status=str(response.status_code)).inc()
        HTTP_DURATION.labels(method=request.method, handler=handler).observe(time.perf_counter() - start)
    except Exception:  # pragma: no cover — instrumentation must never break a response
        pass
    return response


def _update_pool_gauges() -> None:
    """Read the existing asyncpg pool without creating one (a scrape must not
    open connections). No pool → all states zero.

    Reads postgres._pool directly instead of get_pool(): get_pool() would
    create a pool on scrape, and pools are bound to the creating event loop.
    """
    from app.db import postgres as db_postgres

    pool = getattr(db_postgres, "_pool", None)
    total = idle = 0
    if pool is not None:
        try:
            total = pool.get_size()
            idle = pool.get_idle_size()
        except Exception:  # pragma: no cover — pool closed concurrently
            total = idle = 0
    DB_POOL_SIZE.labels(state="total").set(total)
    DB_POOL_SIZE.labels(state="idle").set(idle)
    DB_POOL_SIZE.labels(state="used").set(total - idle)


@router.get("/metrics", dependencies=[Depends(_metrics_access)])
async def metrics(request: Request) -> Response:
    """Prometheus text exposition (default 200/min limiter applies)."""
    _update_pool_gauges()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

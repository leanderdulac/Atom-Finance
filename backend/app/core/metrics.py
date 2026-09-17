"""Opt-in Prometheus metrics for the ATOM API.

Gated behind ATOM_ENABLE_METRICS=1 (like ATOM_REGIME_JOB) so local dev and CI
behave exactly as before unless a deployment opts in. When disabled the
/metrics route and the measuring middleware are simply not registered; the
metric objects still exist (cheap, pure-python) which keeps the types simple.

Cardinality is bounded on purpose: labels are method + a coarse route group
(the first two path segments, e.g. `api/reports`, `api/market-data`) + status,
never the raw path, so a /api/market-data/history/{ticker} can't explode the
label space. Request-id correlation stays in the structured logs.
"""
from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

ENABLED = os.getenv("ATOM_ENABLE_METRICS", "").strip().lower() in ("1", "true", "yes")

_registry = CollectorRegistry()
_HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "route_grp", "status"],
    registry=_registry,
)
_HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route_grp"],
    registry=_registry,
)
_HTTP_IN_FLIGHT = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being processed",
    ["method"],
    registry=_registry,
)
_APP_STARTED = Gauge(
    "app_started_at_time",
    "Unix timestamp when this app process started",
    registry=_registry,
)
_APP_STARTED.set(time.time())


def _route_group(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return "/".join(parts[:2]) if parts else "root"


async def middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Instruments one request against the Prometheus registry."""
    method = request.method or "GET"
    grp = _route_group(request.url.path)
    _HTTP_IN_FLIGHT.labels(method).inc()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # an unhandled exception still needs a status label; the framework
        # turns it into a 500 after the middleware returns, so emit it here.
        _HTTP_REQUESTS.labels(method, grp, "500").inc()
        _HTTP_DURATION.labels(method, grp).observe(time.perf_counter() - start)
        raise
    finally:
        _HTTP_IN_FLIGHT.labels(method).dec()
    status = str(response.status_code)
    _HTTP_REQUESTS.labels(method, grp, status).inc()
    _HTTP_DURATION.labels(method, grp).observe(time.perf_counter() - start)
    return response


def metrics_response(request: Request) -> Response:
    """Renders the Prometheus exposition format."""
    return Response(generate_latest(_registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

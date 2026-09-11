"""Request-id log correlation and optional Sentry error tracking.

Both are safe no-ops when unconfigured: the request-id middleware and log
filter work with or without Sentry (correlation is useful on its own, e.g.
for grepping one request's log lines across a busy server); `init_sentry()`
does nothing unless `SENTRY_DSN` is set, so every environment without it
(local dev, CI) behaves exactly as before this module existed.
"""
import contextvars
import logging
import os
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIDLogFilter(logging.Filter):
    """Injects the current request's id into every log record's `request_id` field.

    Attach to handlers (not loggers) so it applies regardless of which
    module's logger emitted the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Correlates one request's logs and gives clients an id to report back.

    Trusts an inbound X-Request-ID so a reverse proxy or the frontend can
    thread its own trace through, but always generates one if absent —
    never leaves a request uncorrelated.
    """
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_var.set(req_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = req_id
    return response


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  [%(request_id)s] — %(message)s",
    )
    request_id_filter = RequestIDLogFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(request_id_filter)


def init_sentry() -> None:
    """Wires up Sentry if SENTRY_DSN is set; otherwise a deliberate no-op.

    Kept separate from configure_logging() so a deployment can adopt one
    without the other (e.g. request-id log correlation without an external
    error-tracking account yet).
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        logging.getLogger(__name__).info("SENTRY_DSN not set — Sentry error tracking disabled.")
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ATOM_ENV", "development"),
        # Tracing is opt-in and off by default: a pilot-scale deployment doesn't
        # need per-request performance traces, just error capture. Bump via env
        # once there's a reason to pay for the extra Sentry event volume.
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    logging.getLogger(__name__).info("Sentry error tracking enabled.")

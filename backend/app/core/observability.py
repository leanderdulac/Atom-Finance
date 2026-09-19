"""
Request-id log correlation, structured logging, and optional Sentry error tracking.

All are safe no-ops when unconfigured: the request-id middleware and log
filter work with or without Sentry; `init_sentry()` does nothing unless
`SENTRY_DSN` is set; and structured JSON logging is a single formatter swap
chosen by `ATOM_LOG_FORMAT=json` (default: readable text for local dev/CI).
"""
import contextvars
import json
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


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, machine-parseable for log shippers.

    Includes the correlated request_id and any structured extra fields a
    caller attaches (user, ticker, status, ...), so a single request's story
    can be grepped across a busy server or shipped to a collector.
    """

    # Fields that add signal when present on a record; ignore the rest to avoid
    # leaking unrelated internal state into logs.
    _EXTRA_FIELDS = ("user", "owner", "ticker", "method", "path", "status", "attempt")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for key in self._EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = str(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _install_root_handler(formatter: logging.Formatter) -> None:
    """Attaches formatter + request-id filter to the root handler(s)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RequestIDLogFilter())


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
    """Configures the root logger with request-id correlation and (optionally)
    JSON structured output.

    `ATOM_LOG_FORMAT=json` emits one JSON object per line — the mode a
    deployment stands up before shipping logs to a collector. The default text
    format keeps local dev and CI readable.
    """
    fmt = os.getenv("ATOM_LOG_FORMAT", "text").strip().lower()
    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  [%(request_id)s] — %(message)s"
        )
    _install_root_handler(formatter)


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

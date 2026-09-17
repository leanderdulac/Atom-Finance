"""Pure tests for the observability helpers (structured logging + Prometheus)."""
import json
import logging

from app.core.metrics import _route_group, metrics_response
from app.core.observability import JsonFormatter


def test_json_formatter_emits_valid_json_with_request_id():
    rec = logging.LogRecord("app.core.observability", logging.INFO, __file__, 0,
                            "hello {name}", (), None)
    rec.request_id = "req-abc"
    rec.ticker = "PETR4"
    rec.method = "POST"
    payload = json.loads(JsonFormatter().format(rec))
    assert payload["request_id"] == "req-abc"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.core.observability"
    assert payload["message"] == "hello {name}"
    assert payload["ticker"] == "PETR4"
    assert payload["method"] == "POST"


def test_json_formatter_defaults_request_id():
    rec = logging.LogRecord("x", logging.WARNING, __file__, 0, "bare", (), None)
    payload = json.loads(JsonFormatter().format(rec))
    assert payload["request_id"] == "-"  # contextvar default
    assert "exc" not in payload


def test_route_group_is_bounded():
    assert _route_group("/api/market-data/history/PETR4") == "api/market-data"
    assert _route_group("/api/auth/login") == "api/auth"
    assert _route_group("/metrics") == "metrics"
    assert _route_group("/") == "root"


def test_metrics_exposition_contains_http_metrics():
    # metrics_response ignores the request object; the registry is module-level.
    body = metrics_response(None).body.decode("utf-8")
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "http_requests_in_progress" in body

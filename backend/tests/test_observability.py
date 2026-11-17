"""Pure tests for the JSON log formatter (metrics live in app/api/metrics.py)."""
import json
import logging

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

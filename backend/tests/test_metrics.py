"""Observability: /api/metrics fail-closed, bounded route-label cardinality."""
import re

import pytest
from fastapi.testclient import TestClient

import main
from app.core.security import create_access_token

TOKEN = {"Authorization": "Bearer " + create_access_token("anyone")}


@pytest.fixture(autouse=True)
def _metrics_private(monkeypatch):
    monkeypatch.delenv("ATOM_METRICS_PUBLIC", raising=False)
    yield
    monkeypatch.delenv("ATOM_METRICS_PUBLIC", raising=False)


def test_metrics_fail_closed_without_token():
    response = TestClient(main.app).get("/api/metrics")
    assert response.status_code == 401


def test_metrics_reject_invalid_token():
    response = TestClient(main.app).get(
        "/api/metrics", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


def test_metrics_requires_bearer_with_token():
    response = TestClient(main.app).get("/api/metrics", headers=TOKEN)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "atom_http_requests_total" in body
    assert "atom_http_request_duration_seconds" in body
    assert "atom_db_pool_size" in body


def test_metrics_handler_labels_are_bounded(monkeypatch):
    monkeypatch.setenv("ATOM_METRICS_PUBLIC", "true")
    client = TestClient(main.app)
    body = client.get("/api/metrics").text
    # endpoint handler é o label — query strings e ids de recurso nunca entram
    assert 'handler="metrics"' in body
    assert not re.search(r'handler="[^"]*\d', body)
    assert "atom_db_pool_size{state=\"total\"" in body



def test_metrics_open_with_atom_metrics_public():
    # autouse fixture deleted the env; re-set explicitly for clarity of the case
    import os
    os.environ["ATOM_METRICS_PUBLIC"] = "true"
    try:
        response = TestClient(main.app).get("/api/metrics")
        assert response.status_code == 200
    finally:
        del os.environ["ATOM_METRICS_PUBLIC"]

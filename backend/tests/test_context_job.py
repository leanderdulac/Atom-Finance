"""Context prewarm job stays off in tests and honors ATOM_CONTEXT_JOB."""
from __future__ import annotations

from app.services.context_job import interval_seconds, job_enabled


def test_job_disabled_in_test_env():
    assert job_enabled() is False


def test_interval_seconds(monkeypatch):
    monkeypatch.setenv("ATOM_CONTEXT_JOB_SECONDS", "90")
    assert interval_seconds() == 90
    monkeypatch.setenv("ATOM_CONTEXT_JOB_SECONDS", "nope")
    assert interval_seconds() == 300

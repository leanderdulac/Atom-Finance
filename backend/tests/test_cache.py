"""Tests for cache layer (in-memory backend)."""
import time

import pytest

from app.core.cache import Cache, _MemStore, _redact_url


@pytest.fixture(autouse=True)
def clear_store():
    _MemStore.clear()
    yield
    _MemStore.clear()


class TestMemoryCache:
    def test_set_and_get(self):
        Cache.set("k", {"value": 42}, ex=60)
        result = Cache.get("k")
        assert result == {"value": 42}

    def test_missing_key_returns_none(self):
        assert Cache.get("nonexistent") is None

    def test_delete_removes_key(self):
        Cache.set("to_delete", "hello", ex=60)
        Cache.delete("to_delete")
        assert Cache.get("to_delete") is None

    def test_ttl_expiry(self):
        _MemStore.set("expiring", '{"x": 1}', ex=1)
        assert _MemStore.get("expiring") is not None
        time.sleep(1.05)
        assert _MemStore.get("expiring") is None

    def test_overwrite(self):
        Cache.set("key", "first", ex=60)
        Cache.set("key", "second", ex=60)
        assert Cache.get("key") == "second"

    def test_complex_value(self):
        val = {"list": [1, 2, 3], "nested": {"a": True}}
        Cache.set("complex", val, ex=60)
        assert Cache.get("complex") == val


class TestRedactUrl:
    def test_strips_password_and_keeps_host(self):
        assert _redact_url("redis://user:super-secret@localhost:6379/0") == "redis://user:***@localhost:6379/0"

    def test_password_only_userinfo(self):
        assert _redact_url("redis://:hunter2@cache.internal:6379/1") == "redis://:***@cache.internal:6379/1"

    def test_leaves_urls_without_password_unchanged(self):
        assert _redact_url("redis://localhost:6379/0") == "redis://localhost:6379/0"

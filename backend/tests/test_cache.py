"""Tests for cache layer (in-memory backend)."""
import time
import pytest

from app.core.cache import Cache, _MemStore


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

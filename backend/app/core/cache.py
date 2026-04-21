"""Unified cache layer — Redis when available, in-memory TTL dict otherwise."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_redis_client = None
_redis_unavailable = False  # avoid hammering a down Redis on every request


def _get_redis():
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        logger.info("Redis connected at %s", url)
        return _redis_client
    except Exception as exc:
        _redis_unavailable = True
        logger.warning("Redis unavailable — using in-memory cache: %s", exc)
        return None


class _MemStore:
    """Thread-unsafe but sufficient for single-process FastAPI demo usage."""

    _store: dict[str, tuple[str, float]] = {}

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        entry = cls._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if time.monotonic() > expire_at:
            cls._store.pop(key, None)
            return None
        return value

    @classmethod
    def set(cls, key: str, value: str, ex: int) -> None:
        cls._store[key] = (value, time.monotonic() + ex)

    @classmethod
    def delete(cls, key: str) -> None:
        cls._store.pop(key, None)

    @classmethod
    def clear(cls) -> None:
        cls._store.clear()


class Cache:
    """Public cache interface: Redis or in-memory fallback.

    Values are automatically JSON-serialised / deserialised.
    """

    @staticmethod
    def get(key: str) -> Optional[Any]:
        r = _get_redis()
        if r:
            try:
                raw = r.get(key)
                return json.loads(raw) if raw is not None else None
            except Exception as exc:
                logger.debug("Redis GET error for %s: %s", key, exc)

        raw = _MemStore.get(key)
        return json.loads(raw) if raw is not None else None

    @staticmethod
    def set(key: str, value: Any, ex: int = 60) -> None:
        serialised = json.dumps(value, default=str)
        r = _get_redis()
        if r:
            try:
                r.setex(key, ex, serialised)
                return
            except Exception as exc:
                logger.debug("Redis SET error for %s: %s", key, exc)

        _MemStore.set(key, serialised, ex)

    @staticmethod
    def delete(key: str) -> None:
        r = _get_redis()
        if r:
            try:
                r.delete(key)
            except Exception:
                pass
        _MemStore.delete(key)

    @staticmethod
    def is_redis_available() -> bool:
        return _get_redis() is not None

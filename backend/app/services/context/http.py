"""Short-timeout HTTP with Redis/memory cache. Failures return None — never invent."""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx

from app.core.cache import Cache

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = float(os.getenv("ATOM_CONTEXT_TIMEOUT", "4"))
DEFAULT_TTL = int(os.getenv("ATOM_CONTEXT_TTL", "300"))


def _key(prefix: str, url: str, extra: str = "") -> str:
    digest = hashlib.sha256(f"{url}|{extra}".encode()).hexdigest()[:20]
    return f"ctx:{prefix}:{digest}"


def cached_get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    ttl: int | None = None,
    prefix: str = "http",
) -> Any | None:
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    ttl = DEFAULT_TTL if ttl is None else ttl
    cache_key = _key(prefix, url, repr(sorted((params or {}).items())))
    hit = Cache.get(cache_key)
    if hit is not None:
        return hit
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.info("Context GET %s failed (%s)", url, type(exc).__name__)
        return None
    Cache.set(cache_key, payload, ex=ttl)
    return payload


def cached_get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    ttl: int | None = None,
    prefix: str = "http-text",
) -> str | None:
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    ttl = DEFAULT_TTL if ttl is None else ttl
    cache_key = _key(prefix, url, repr(sorted((params or {}).items())))
    hit = Cache.get(cache_key)
    if isinstance(hit, str):
        return hit
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            text = response.text
    except Exception as exc:
        logger.info("Context GET text %s failed (%s)", url, type(exc).__name__)
        return None
    Cache.set(cache_key, text, ex=ttl)
    return text


def cached_post_json(
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    ttl: int | None = None,
    prefix: str = "http-post",
) -> Any | None:
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    ttl = DEFAULT_TTL if ttl is None else ttl
    cache_key = _key(prefix, url, repr(sorted(json_body.items())))
    hit = Cache.get(cache_key)
    if hit is not None:
        return hit
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, json=json_body, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.info("Context POST %s failed (%s)", url, type(exc).__name__)
        return None
    Cache.set(cache_key, payload, ex=ttl)
    return payload

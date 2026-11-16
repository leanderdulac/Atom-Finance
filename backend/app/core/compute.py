"""Process/thread pools and torch device — sized by env, not hardcoded.

The Mac that serves the public tunnel (M-series, Metal/MPS) can run Heston/GARCH
and cache warming in parallel. Uvicorn stays single-worker (see runtime.py);
parallelism is inside the process. Override with ATOM_COMPUTE_WORKERS,
ATOM_TORCH_DEVICE, ATOM_DB_POOL_MIN/MAX.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from functools import lru_cache

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, *, lo: int = 1, hi: int = 64) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return default


def cpu_count() -> int:
    return os.cpu_count() or 4


def compute_workers() -> int:
    """Default: half the cores, capped. The other half stays for uvicorn/Redis/Postgres."""
    default = max(2, min(8, cpu_count() // 2 or 2))
    return _env_int("ATOM_COMPUTE_WORKERS", default, lo=1, hi=32)


def io_workers() -> int:
    default = max(4, min(16, cpu_count()))
    return _env_int("ATOM_IO_WORKERS", default, lo=1, hi=32)


def db_pool_min() -> int:
    return _env_int("ATOM_DB_POOL_MIN", 1, lo=1, hi=32)


def db_pool_max() -> int:
    return max(db_pool_min(), _env_int("ATOM_DB_POOL_MAX", 10, lo=1, hi=64))


@lru_cache(maxsize=1)
def torch_device() -> str:
    """mps when available (Apple GPU), else cpu. ATOM_TORCH_DEVICE overrides."""
    override = os.getenv("ATOM_TORCH_DEVICE", "").strip().lower()
    if override in {"cpu", "mps", "cuda"}:
        if override == "mps" and not _mps_available():
            logger.warning("ATOM_TORCH_DEVICE=mps but torch.backends.mps is unavailable — using cpu")
            return "cpu"
        return override
    if _mps_available():
        return "mps"
    return "cpu"


def _mps_available() -> bool:
    try:
        import torch
        return bool(torch.backends.mps.is_available())
    except Exception:
        return False


def parallel_map[T, R](fn: Callable[[T], R], items: Iterable[T], *, kind: str = "thread") -> list[R]:
    """Map fn over items. kind=thread for I/O; process for CPU-bound numpy fits."""
    seq = list(items)
    if not seq:
        return []
    if len(seq) == 1 or os.getenv("ATOM_ENV") == "test":
        return [fn(item) for item in seq]
    workers = io_workers() if kind == "thread" else compute_workers()
    pool_cls = ThreadPoolExecutor if kind == "thread" else ProcessPoolExecutor
    ordered: list[R] = [None] * len(seq)  # type: ignore[list-item]
    with pool_cls(max_workers=min(workers, len(seq))) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(seq)}
        for fut in as_completed(futures):
            ordered[futures[fut]] = fut.result()
    return ordered

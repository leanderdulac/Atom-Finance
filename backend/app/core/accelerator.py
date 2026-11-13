"""Hardware accelerator detection and dispatch for Apple Silicon (MPS), NVIDIA (CUDA), and CPU."""
from __future__ import annotations

import logging
import os
import platform
from typing import Any

import torch

logger = logging.getLogger(__name__)

_VALID_DEVICES = frozenset({"auto", "cpu", "cuda", "mps"})


def is_mps_available() -> bool:
    """Return True when Apple Silicon Metal Performance Shaders (MPS) is available."""
    return bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())


def is_cuda_available() -> bool:
    """Return True when NVIDIA CUDA is available."""
    return bool(torch.cuda.is_available())


def preferred_accelerator() -> str:
    """Return the best available hardware accelerator ('cuda', 'mps', or 'cpu')."""
    override = os.getenv("ATOM_DEVICE", "auto").strip().lower()
    if override in _VALID_DEVICES and override != "auto":
        if override == "cuda" and is_cuda_available():
            return "cuda"
        if override == "mps" and is_mps_available():
            return "mps"
        if override == "cpu":
            return "cpu"
        logger.warning("Requested ATOM_DEVICE=%s is unavailable; falling back to auto.", override)

    if is_cuda_available():
        return "cuda"
    if is_mps_available():
        return "mps"
    return "cpu"


def select_torch_device(
    batch_size: int = 1,
    *,
    min_gpu_batch: int = 128,
    requested: str | None = None,
) -> torch.device:
    """Select optimal torch.device considering kernel launch overhead for small batches.

    On Apple Silicon (M-series Max) and discrete GPUs, small sequential loops with tiny
    batch sizes run faster on CPU (Apple Accelerate / AMX) than on GPU due to dispatch
    overhead. Once batch_size >= min_gpu_batch, GPU/MPS parallelism dominates.
    """
    choice = (requested or os.getenv("ATOM_DEVICE", "auto")).strip().lower()
    if choice == "cpu":
        return torch.device("cpu")
    if choice == "cuda" and is_cuda_available():
        return torch.device("cuda")
    if choice == "mps" and is_mps_available():
        return torch.device("mps")

    # Auto mode: use GPU/MPS when batch is large enough to amortize dispatch overhead
    if batch_size >= min_gpu_batch:
        return torch.device(preferred_accelerator())
    return torch.device("cpu")


def device_info() -> dict[str, Any]:
    """Return hardware acceleration telemetry for diagnostics and status endpoints."""
    accel = preferred_accelerator()
    gpu_name: str | None = None
    if is_cuda_available():
        try:
            gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            gpu_name = "NVIDIA CUDA GPU"
    elif is_mps_available():
        gpu_name = f"Apple Silicon Metal ({platform.processor() or platform.machine()})"

    return {
        "preferred_device": accel,
        "cuda_available": is_cuda_available(),
        "mps_available": is_mps_available(),
        "gpu_name": gpu_name,
        "cpu_arch": platform.machine(),
        "cpu_count": os.cpu_count() or 1,
        "torch_version": torch.__version__,
    }

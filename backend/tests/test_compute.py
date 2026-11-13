"""Compute helpers: env sizing and sequential map in tests."""
from app.core.compute import compute_workers, parallel_map, torch_device


def test_parallel_map_is_sequential_in_test_env():
    assert parallel_map(lambda x: x * 2, [1, 2, 3]) == [2, 4, 6]
    assert parallel_map(lambda x: x, []) == []


def test_workers_and_device_are_bounded(monkeypatch):
    monkeypatch.setenv("ATOM_COMPUTE_WORKERS", "4")
    # compute_workers reads env each call (not cached except torch_device).
    assert compute_workers() == 4
    monkeypatch.setenv("ATOM_TORCH_DEVICE", "cpu")
    torch_device.cache_clear()
    assert torch_device() == "cpu"
    torch_device.cache_clear()

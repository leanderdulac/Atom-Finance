"""Bit-exact prefix checks for causal research tools."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


def assert_same_bits(left: np.ndarray, right: np.ndarray) -> None:
    a = np.asarray(left)
    b = np.asarray(right)
    assert a.shape == b.shape
    if a.dtype == bool or np.issubdtype(a.dtype, np.integer):
        np.testing.assert_array_equal(a, b)
        return
    af = np.asarray(a, dtype=np.float64)
    bf = np.asarray(b, dtype=np.float64)
    nan_a = np.isnan(af)
    nan_b = np.isnan(bf)
    np.testing.assert_array_equal(nan_a, nan_b)
    np.testing.assert_array_equal(af[~nan_a], bf[~nan_b])


def perturb(values: np.ndarray, t: int, kind: str, seed: int = 0) -> np.ndarray:
    out = np.array(values, dtype=np.float64, copy=True)
    if kind == "nan":
        out[t + 1 :] = np.nan
    else:
        rng = np.random.default_rng(seed)
        out[t + 1 :] = out[t + 1 :] + rng.normal(0.0, 5.0, size=out[t + 1 :].shape)
    return out


def _leaves(obj: object) -> Iterator[np.ndarray]:
    if isinstance(obj, np.ndarray):
        yield obj
        return
    if isinstance(obj, tuple | list):
        for item in obj:
            yield from _leaves(item)
        return
    fields = getattr(obj, "__dataclass_fields__", None)
    if fields:
        for name in fields:
            value = getattr(obj, name)
            if isinstance(value, np.ndarray):
                yield value


def assert_causal_prefix(original: object, perturbed: object, t: int) -> None:
    left = list(_leaves(original))
    right = list(_leaves(perturbed))
    assert left and len(left) == len(right)
    for a, b in zip(left, right, strict=True):
        assert_same_bits(a[: t + 1], b[: t + 1])

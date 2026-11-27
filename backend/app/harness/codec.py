"""Canonical JSON and content hashes for audit records and memory keys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(payload: object) -> str:
    """Stable JSON. NaN and Infinity are rejected so hashes stay reproducible."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(payload: object) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def hypothesis_fingerprint(
    *,
    family: str,
    statement: str,
    feature_names: tuple[str, ...],
    feature_formulas: tuple[str, ...],
    lag: int,
    commission_bps: float,
    slippage_bps: float,
    half_spread_bps: float,
) -> str:
    features = sorted(
        zip((name.strip().lower() for name in feature_names), (_norm(f) for f in feature_formulas), strict=True)
    )
    return fingerprint(
        {
            "family": family.strip().lower(),
            "statement": _norm(statement),
            "features": features,
            "lag": int(lag),
            "commission_bps": float(commission_bps),
            "slippage_bps": float(slippage_bps),
            "half_spread_bps": float(half_spread_bps),
        }
    )


def feature_fingerprint(name: str, formula: str) -> str:
    return fingerprint({"name": name.strip().lower(), "formula": _norm(formula)})


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def as_json(payload: Mapping[str, Any]) -> str:
    return canonical(dict(payload))

"""Rejected B3 Graham net-net trials, recorded so later DSR counts include them.

The backtest itself is not in this module. The 32 variations and their
published metrics live in ``docs/reports/net-net-b3.json``. ``TrialRegistry``
loads them once into family ``b3_graham_net_net`` with status ``rejected``.
``eligible_for_live_trading`` stays false. This is a negative result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FAMILY_ID = "b3_graham_net_net"
STATUS_REJECTED = "rejected"
RECORDED_AT = "2026-11-20T00:00:00Z"
SOURCE = "docs/reports/net-net-b3.json"

_REPO = Path(__file__).resolve().parents[3]
REPORT_PATH = _REPO / "docs" / "reports" / "net-net-b3.json"

_CATALOG: list[dict[str, Any]] | None = None


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} is not a list")
    return value


def catalog() -> list[dict[str, Any]]:
    """The 32 published variations. Identity fields plus the recorded metrics."""
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    report = _as_object(json.loads(REPORT_PATH.read_text(encoding="utf-8")), "net-net report")
    sample = _as_object(report.get("sample"), "sample")
    rows = _as_list(report.get("trials"), "trials")
    if len(rows) != 32:
        raise ValueError(f"expected 32 net-net trials, found {len(rows)}")
    first_phase0 = _first_phase0_signal(report)
    built: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        row = _as_object(raw, "trial")
        key = _record_key(row)
        if key in seen:
            raise ValueError(f"duplicate net-net trial {key}")
        seen.add(key)
        sharpe = row.get("sharpe_net")
        n_obs = row.get("n_obs_months")
        if not isinstance(sharpe, int | float) or isinstance(sharpe, bool):
            raise ValueError(f"{key} is missing sharpe_net")
        if not isinstance(n_obs, int) or isinstance(n_obs, bool):
            raise ValueError(f"{key} is missing n_obs_months")
        built.append(
            {
                "record_key": key,
                "status": STATUS_REJECTED,
                "block": row.get("block"),
                "filter": row.get("filter"),
                "yield_proxy": row.get("yield_proxy"),
                "lag_days": row.get("lag_days"),
                "phase": row.get("phase"),
                "aum_brl": row.get("aum_brl"),
                "sharpe": float(sharpe),
                "psr": row.get("psr"),
                "dsr": row.get("dsr"),
                "min_trl_months": row.get("min_trl_months"),
                "min_trl_infinite": bool(row.get("min_trl_infinite")),
                "cagr_gross": row.get("cagr_gross"),
                "cagr_net": row.get("cagr_net"),
                "n_obs_months": n_obs,
                "n_trials_at_record": row.get("n_trials"),
                "sample_first_session": sample.get("first_session"),
                "sample_last_session": sample.get("last_session"),
                "sample_first_signal_on_or_after": sample.get("first_signal_on_or_after"),
                "sample_first_phase0_signal": first_phase0,
                "eligible_for_live_trading": False,
                "source": SOURCE,
            }
        )
    _CATALOG = built
    return built


def rejected_ledger_count() -> int:
    return len(catalog())


def record_rejected_net_nets(registry: Any) -> int:
    """Insert any missing rejected trials. A second call does not duplicate them.

    Returns the family count after the call.
    """
    existing: set[str] = set()
    for trial in registry.trials(FAMILY_ID):
        params = trial.params if isinstance(trial.params, dict) else {}
        key = params.get("record_key")
        if isinstance(key, str):
            existing.add(key)
    for params in catalog():
        key = params["record_key"]
        if not isinstance(key, str) or key in existing:
            continue
        sharpe = params["sharpe"]
        n_obs = params["n_obs_months"]
        registry.register(
            FAMILY_ID,
            params,
            sharpe=float(sharpe) if isinstance(sharpe, int | float) and not isinstance(sharpe, bool) else None,
            n_obs=int(n_obs) if isinstance(n_obs, int) and not isinstance(n_obs, bool) else None,
            costs_included=True,
            periods_per_year=12.0,
            notes="rejected",
            status=STATUS_REJECTED,
            timestamp=RECORDED_AT,
        )
        existing.add(key)
    return registry.count(FAMILY_ID)


def _record_key(row: dict[str, Any]) -> str:
    parts = (
        row.get("block"),
        row.get("filter"),
        row.get("yield_proxy"),
        row.get("lag_days"),
        row.get("phase"),
        row.get("aum_brl"),
    )
    if any(part is None for part in parts):
        raise ValueError("net-net trial is missing an identity field")
    return "|".join(str(part) for part in parts)


def _first_phase0_signal(report: dict[str, Any]) -> str | None:
    census = report.get("screen_census")
    if not isinstance(census, dict):
        return None
    per_signal = census.get("per_signal")
    if not isinstance(per_signal, list) or not per_signal:
        return None
    first = per_signal[0]
    if not isinstance(first, dict):
        return None
    signal = first.get("signal")
    return signal if isinstance(signal, str) else None

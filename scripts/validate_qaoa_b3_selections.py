"""Score QAOA B3 selections on the equal-weight simulator.

Reads an optional selections parquet. Fills any classical solver the file does
not already contain. Does not run ``qaoa_aer``. Does not open a socket and
does not send an order.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.afml.trials import TrialRegistry  # noqa: E402
from app.models.qaoa_b3 import (  # noqa: E402
    ELIGIBLE_FOR_LIVE_TRADING,
    inconclusive_report,
    prior_ledger,
    run_study,
    validate_selection,
)
from app.models.qaoa_b3_io import load_research_inputs, read_selections, read_table, universe_from_rows  # noqa: E402


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str | int | bool) or value is None:
        return value
    return str(value)


def _selection_check(snapshot_dir: Path, selection_path: Path) -> dict:
    universes: dict = {}
    for path in sorted(snapshot_dir.glob("*.parquet")):
        day, tickers, digest = universe_from_rows(read_table(path))
        universes[day] = (tickers, digest)
    selections = read_selections(selection_path)
    for sel in selections:
        if sel.rebalance not in universes:
            raise ValueError(f"{sel.rebalance.isoformat()} is not a snapshot date")
        validate_selection(sel, tuple(sorted(universes[sel.rebalance][0])))
    return {
        "accepted": True,
        "n_snapshot_dates": len(universes),
        "n_rows": len(selections),
        "solvers": sorted({sel.solver for sel in selections}),
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate QAOA B3 selections. Paper only.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--events", type=Path, default=Path("data/equal-weight/yahoo"))
    parser.add_argument("--snapshots", type=Path, default=Path("docs/reports/qaoa-b3/snapshots"))
    parser.add_argument("--selections", type=Path, default=None)
    parser.add_argument("--registry", type=Path, default=Path("data/qaoa-b3/trials.sqlite"))
    parser.add_argument("--json", type=Path, default=Path("docs/reports/qaoa-b3/phase1.json"))
    args = parser.parse_args()
    cache_ready = (args.cache / "cad_cia_aberta.csv").exists()
    if cache_ready:
        loaded = load_research_inputs(args.cache, args.events)
        external = read_selections(args.selections) if args.selections else None
        report = run_study(
            loaded["companies"],
            loaded["tapes"],
            loaded["sessions"],
            loaded["events"],
            loaded["cdi_ords"],
            loaded["cdi_rates"],
            args.registry,
            loaded["listings"],
            selections=external,
        )
        report["sample"] = {
            "first_session": str(loaded["sessions"][0]) if loaded["sessions"] else None,
            "last_session": str(loaded["sessions"][-1]) if loaded["sessions"] else None,
            "n_sessions": len(loaded["sessions"]),
            "confirmed_splits_on_strategy_tapes": loaded["n_splits"],
        }
    else:
        report = inconclusive_report(
            "The COTAHIST cache is not available, so no 2012–2026 path was scored. "
            "Classical baselines are implemented. qaoa_aer selections were not scored."
        )
        with tempfile.TemporaryDirectory() as tmp:
            with TrialRegistry(Path(tmp) / "trials.sqlite") as registry:
                report["priors"] = prior_ledger(registry)
                report["n_trials_decision_before_new_trials"] = report["priors"]["n_decision"]
        if args.selections and args.snapshots.exists():
            report["selection_check"] = _selection_check(args.snapshots, args.selections)
    report["eligible_for_live_trading"] = False
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["verdict"], args.json, flush=True)


if __name__ == "__main__":
    main()

"""Refresh the net-net report and run the long-horizon factor grid.

Reads the cache from ``scripts/fetch_net_net_b3.py``. Does not download.
Paper research only: both reports keep ``eligible_for_live_trading`` false.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.long_horizon import run_study as run_factors
from app.models.net_net import run_study as run_net_net
from app.models.net_net_io import load_bundle

FIRST_SIGNAL = date(2012, 5, 2)


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="B3 net-net audit and long-horizon factor study.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--net-net-report", type=Path, default=Path("docs/reports/net-net-b3.json"))
    parser.add_argument("--factor-report", type=Path, default=Path("docs/reports/long-horizon-factors.json"))
    parser.add_argument("--skip-net-net", action="store_true")
    args = parser.parse_args()
    bundle = load_bundle(args.cache)
    if not args.skip_net_net:
        registry = args.cache / "trials.sqlite"
        if registry.exists():
            registry.unlink()
        first = max(FIRST_SIGNAL.toordinal(), bundle["sessions"][0] if bundle["sessions"] else FIRST_SIGNAL.toordinal())
        net = run_net_net(
            bundle["companies"],
            bundle["tapes"],
            bundle["sessions"],
            bundle["yields"],
            bundle["ibov_ords"],
            bundle["ibov_close"],
            registry_path=str(registry),
            first_ord=first,
        )
        net["n_split_adjustments"] = bundle["n_split_adjustments"]
        net["n_priced_tickers"] = bundle["n_priced_tickers"]
        net["n_share_points_rescaled"] = bundle["n_share_points_rescaled"]
        _write(args.net_net_report, net)
        print(json.dumps({"net_net_verdict": net["verdict"], "audit_primary": net["audit"]["primary"]}, ensure_ascii=False, indent=2))
    factor_registry = args.cache / "factor-trials.sqlite"
    if factor_registry.exists():
        factor_registry.unlink()
    factors = run_factors(
        bundle["companies"],
        bundle["tapes"],
        bundle["sessions"],
        bundle["ibov_ords"],
        bundle["ibov_close"],
        bundle["cdi_ords"],
        bundle["cdi_rates"],
        registry_path=str(factor_registry),
    )
    _write(args.factor_report, factors)
    print(json.dumps({"factor_verdict": factors["verdict"], "oos": factors["oos_split"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

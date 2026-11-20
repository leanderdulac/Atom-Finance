"""Run the pre-specified Graham net-net grid and write the report JSON.

Reads the cache from ``scripts/fetch_net_net_b3.py``. Does not download.
Paper research only: the report's ``eligible_for_live_trading`` is false.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.net_net import run_study
from app.models.net_net_io import load_bundle

# First signal on or after this date so a 2011 filing can already be a trailing year.
FIRST_SIGNAL = date(2012, 5, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="B3 Graham net-net study.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--report", type=Path, default=Path("docs/reports/net-net-b3.json"))
    parser.add_argument("--registry", type=Path, default=Path("data/net-net/trials.sqlite"))
    args = parser.parse_args()
    bundle = load_bundle(args.cache)
    first = max(FIRST_SIGNAL.toordinal(), bundle["sessions"][0] if bundle["sessions"] else FIRST_SIGNAL.toordinal())
    if args.registry.exists():
        args.registry.unlink()
    report = run_study(
        bundle["companies"],
        bundle["tapes"],
        bundle["sessions"],
        bundle["yields"],
        bundle["ibov_ords"],
        bundle["ibov_close"],
        registry_path=str(args.registry),
        first_ord=first,
    )
    report["n_split_adjustments"] = bundle["n_split_adjustments"]
    report["n_priced_tickers"] = bundle["n_priced_tickers"]
    report["n_share_points_rescaled"] = bundle["n_share_points_rescaled"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "coverage": report["coverage"], "primary": report["primary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

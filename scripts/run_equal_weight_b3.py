"""Run the equal-weight B3 study and write the report.

Reads the cache from ``scripts/fetch_net_net_b3.py`` and the cash events from
``scripts/fetch_equal_weight_dividends.py``. Does not open a socket.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.equal_weight import render_report, run_study  # noqa: E402
from app.models.equal_weight_io import (  # noqa: E402
    Listing,
    listings_from_tapes,
    load_cash_events,
    load_listings,
    load_strategy_tapes,
    share_events_from_companies,
)
from app.models.net_net_io import load_bundle, session_calendar  # noqa: E402


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _listings_with_on_fallback(listings: list[Listing], companies: list) -> list[Listing]:
    known = {(item.cnpj, item.ticker) for item in listings}
    extra: list[Listing] = []
    for company in companies:
        for ticker, start, end in company.tickers:
            key = (company.cnpj, ticker)
            if key in known:
                continue
            known.add(key)
            extra.append(Listing(company.cnpj, ticker, int(start), None if end is None else int(end), "on"))
    return listings + extra


def main() -> None:
    parser = argparse.ArgumentParser(description="Equal-weight B3 study. Paper only.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--events", type=Path, default=Path("data/equal-weight/yahoo"))
    parser.add_argument("--json", type=Path, default=Path("docs/reports/equal-weight-b3.json"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/EQUAL-WEIGHT-B3.md"))
    parser.add_argument("--registry", type=Path, default=Path("data/equal-weight/trials.sqlite"))
    args = parser.parse_args()
    bundle = load_bundle(args.cache)
    filed = _listings_with_on_fallback(load_listings(args.cache), bundle["companies"])
    share_events = share_events_from_companies(bundle["companies"], filed)
    tapes, trades, n_splits = load_strategy_tapes(args.cache, None, share_events)
    sessions = session_calendar(tapes)
    listings = listings_from_tapes(tapes, filed, int(sessions[-1]) if sessions else 0)
    events = load_cash_events(args.events)
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    if args.registry.exists():
        args.registry.unlink()
    report = run_study(
        bundle["companies"],
        tapes,
        sessions,
        events,
        bundle["ibov_ords"],
        bundle["ibov_close"],
        bundle["cdi_ords"],
        bundle["cdi_rates"],
        str(args.registry),
        listings,
        published_tapes=bundle["tapes"],
        trades=trades,
        audit_sessions=bundle["sessions"],
    )
    report["sample"]["confirmed_splits_on_strategy_tapes"] = n_splits
    report["sample"]["cash_event_files"] = len(events)
    payload = _jsonable(report)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(render_report(report), encoding="utf-8")
    print(report["verdict"], args.json, args.markdown, flush=True)


if __name__ == "__main__":
    main()

"""Write causal QAOA B3 snapshots. Reads a cache. Does not open a socket.

The versioned schema example is written with ``--fixture-only``. A full sample
is written only when the COTAHIST cache from the equal-weight study is present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.qaoa_b3 import build_snapshots, holdout_points, schema_fixture_world  # noqa: E402
from app.models.qaoa_b3_io import load_research_inputs, write_holdout, write_snapshot  # noqa: E402


def _write(directory: Path, book: dict, taxed: dict, snaps: list, sessions: list, tapes: dict) -> int:
    hold = directory / "holdout"
    for index, snap in enumerate(snaps):
        write_snapshot(directory, snap)
        nxt_ord = None if index + 1 == len(snaps) else snaps[index + 1].rebalance_ordinal
        nxt_day = None if index + 1 == len(snaps) else snaps[index + 1].rebalance
        _last, points = holdout_points(
            snap.rebalance_ordinal,
            nxt_ord,
            sessions,
            book.get(snap.rebalance_ordinal, []),
            tapes,
            taxed,
        )
        write_holdout(hold, snap, nxt_day, points)
    return len(snaps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export causal QAOA B3 snapshots. Paper only.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--events", type=Path, default=Path("data/equal-weight/yahoo"))
    parser.add_argument("--out", type=Path, default=Path("docs/reports/qaoa-b3/snapshots"))
    parser.add_argument("--fixture-dir", type=Path, default=Path("docs/reports/qaoa-b3/fixtures"))
    parser.add_argument("--fixture-only", action="store_true")
    args = parser.parse_args()
    if args.fixture_only:
        world = schema_fixture_world()
        book, taxed, snaps = build_snapshots(
            world["companies"], world["listings"], world["tapes"], world["sessions"], world["events"]
        )
        n = _write(args.fixture_dir, book, taxed, snaps, world["sessions"], world["tapes"])
        print(f"fixture {n} rebalance dates -> {args.fixture_dir}", flush=True)
        return
    marker = args.cache / "cad_cia_aberta.csv"
    if not marker.exists():
        print(
            "COTAHIST cache is not available. No market snapshot was written. "
            f"Point --cache at the equal-weight cache, or pass --fixture-only to refresh {args.fixture_dir}.",
            flush=True,
        )
        return
    loaded = load_research_inputs(args.cache, args.events)
    book, taxed, snaps = build_snapshots(
        loaded["companies"], loaded["listings"], loaded["tapes"], loaded["sessions"], loaded["events"]
    )
    n = _write(args.out, book, taxed, snaps, loaded["sessions"], loaded["tapes"])
    print(f"wrote {n} rebalance dates -> {args.out}", flush=True)


if __name__ == "__main__":
    main()

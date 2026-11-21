"""Download public cash-distribution events for the equal-weight study.

Writes one JSON file per listing ticker. The chart feed does not label
interest on equity separately from dividends, so every row is kind
``unknown``. Amounts are reais per share on the ex-date, after undoing
splits the same feed reports strictly after that date.

A name that returns no events, or that the feed does not know, is recorded
in ``_manifest.json``. No cash is invented for a missing name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.equal_weight_io import (  # noqa: E402
    load_listings,
    parse_cotahist_print,
    parse_yahoo_events,
    parse_yahoo_splits,
)

CHART = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA"
    "?interval=1d&events=div%7Csplit&period1={period1}&period2={period2}"
)
UA = "Mozilla/5.0 (compatible; atom-finance-research/1.0)"


def _fetch(ticker: str, period1: int, period2: int) -> tuple[str, dict | None, str | None]:
    url = CHART.format(ticker=ticker, period1=period1, period2=period2)
    last = "no response"
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return ticker, payload, None
        except urllib.error.HTTPError as exc:
            last = f"http {exc.code}"
            if exc.code in (404, 400):
                return ticker, None, last
            if exc.code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = str(exc)
        time.sleep(0.4 * (attempt + 1))
    return ticker, None, last


def _cotahist_tickers(cache: Path) -> set[str]:
    """Every standard-lot cash ticker in the cached COTAHIST files."""
    found: set[str] = set()
    folder = cache / "cotahist"
    if not folder.exists():
        return found
    paths = {path.resolve() for path in folder.iterdir() if path.suffix.lower() == ".zip"}
    for path in sorted(paths):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if not names:
                continue
            with archive.open(names[0]) as handle:
                for raw in handle:
                    parsed = parse_cotahist_print(raw.decode("latin-1", errors="replace"))
                    if parsed is not None:
                        found.add(str(parsed["ticker"]))
        print(f"tickers {path.name} {len(found)}", flush=True)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Download B3 cash distributions from the public chart feed.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--out", type=Path, default=Path("data/equal-weight/yahoo"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--refresh-splits",
        action="store_true",
        help="Refetch a ticker whose file has no splits key, so the ex-date calendar is stored.",
    )
    args = parser.parse_args()
    raw_tickers = set(_cotahist_tickers(args.cache)) | {item.ticker for item in load_listings(args.cache)}
    tickers = sorted(ticker for ticker in raw_tickers if re.fullmatch(r"[A-Z0-9]{4,12}", ticker))
    args.out.mkdir(parents=True, exist_ok=True)
    period1 = int(datetime(2009, 1, 1, tzinfo=UTC).timestamp())
    period2 = int(datetime.now(UTC).timestamp()) + 86400
    def _pending(ticker: str) -> bool:
        path = args.out / f"{ticker}.json"
        if not path.exists():
            return True
        if not args.refresh_splits:
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return True
        return "splits" not in payload

    pending = [ticker for ticker in tickers if _pending(ticker)]
    print(f"listings {len(tickers)} pending {len(pending)}", flush=True)
    failures: dict[str, str] = {}
    written = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(_fetch, ticker, period1, period2) for ticker in pending]
        for done, future in enumerate(as_completed(futures), start=1):
            ticker, payload, error = future.result()
            events = []
            splits = []
            if payload is not None:
                events = [
                    {"ordinal": event.ordinal, "amount": event.amount, "kind": event.kind}
                    for event in parse_yahoo_events(payload, ticker)
                ]
                splits = [
                    {"ordinal": ordinal, "share_factor": ratio} for ordinal, ratio in parse_yahoo_splits(payload)
                ]
            elif error:
                failures[ticker] = error
                if not error.startswith("http 404") and not error.startswith("http 400"):
                    continue
            (args.out / f"{ticker}.json").write_text(
                json.dumps({"ticker": ticker, "events": events, "splits": splits, "error": error}, ensure_ascii=False),
                encoding="utf-8",
            )
            written += 1
            if done % 200 == 0 or done == len(pending):
                print(f"fetched {done}/{len(pending)}", flush=True)
    manifest = {
        "source": CHART.split("?")[0],
        "period1": period1,
        "tickers": len(tickers),
        "files_written_this_run": written,
        "failures": failures,
        "note": (
            "Amounts are gross reais per share on the ex-date. The feed does not label "
            "interest on equity, so kind is unknown. A file with an empty events list was "
            "fetched and had no cash distribution. A failure is a name the feed did not return."
        ),
    }
    (args.out / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out.resolve()} failures {len(failures)}", flush=True)


if __name__ == "__main__":
    main()

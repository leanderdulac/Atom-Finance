"""Run the B3 forward paper books. Research only. No order is sent.

Commands:
  --init              append the genesis and the frozen target
  --mark-to-market    mark sessions that already have a close, in order
  --monthly-report    write the Markdown and JSON report
  --status            print the current paper state
  --freeze-book       one-time selection through 2026-11-19; refuses to overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.b3_paper_forward import (  # noqa: E402
    ENTRY_SESSION,
    SIGNAL_SESSION,
    LedgerTimeError,
    PaperDataError,
    PaperError,
    commit_mark,
    initialize,
    load_book,
    paper_root,
    preregistration_path,
    public_state,
    select_small_book,
    write_monthly_report,
    write_preregistration,
)
from app.models.corporate_actions import (  # noqa: E402
    adjust_prints,
    load_chart_splits,
    load_official_events,
    merge_official,
)
from app.models.equal_weight_io import (  # noqa: E402
    Listing,
    load_cash_events,
    load_listings,
    parse_cotahist_print,
    parse_yahoo_events,
    parse_yahoo_splits,
    share_events_from_companies,
)
from app.models.net_net import Tape  # noqa: E402
from app.models.net_net_io import load_bundle, parse_sgs_cdi, parse_yahoo_chart  # noqa: E402

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
UA = "Mozilla/5.0 (compatible; atom-finance-research/1.0)"
COTAHIST_A = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
COTAHIST_D = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{stamp}.ZIP"
CDI_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={start}&dataFinal={end}"
IBOV_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&period1={period1}&period2={period2}"
CHART = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA"
    "?interval=1d&events=div%7Csplit&period1={period1}&period2={period2}"
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fresh(path: Path, hours: float = 18.0) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    return (time.time() - path.stat().st_mtime) < hours * 3600.0


def _download(url: str, dest: Path, *, refresh: bool) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return True
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    if not payload:
        return False
    temporary = dest.with_suffix(dest.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(dest)
    return True


def _ensure_research(research: Path, today: date) -> None:
    """Filings for a quarterly membership. Existing past years are kept. The current year is refreshed."""
    cad = research / "cad_cia_aberta.csv"
    if not _download(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv", cad, refresh=True):
        raise PaperDataError("company registry download failed")
    for year in range(2018, today.year + 1):
        refresh = year == today.year
        for kind in ("dfp", "itr", "fca", "fre"):
            dest = research / kind / f"{kind}_{year}.zip"
            url = f"{CVM}/DOC/{kind.upper()}/DADOS/{kind}_cia_aberta_{year}.zip"
            _download(url, dest, refresh=refresh)


def _ensure_market_files(cache: Path, today: date) -> None:
    cotahist = cache / "cotahist"
    _download(COTAHIST_A.format(year=today.year), cotahist / f"COTAHIST_A{today.year}.ZIP", refresh=not _fresh(cotahist / f"COTAHIST_A{today.year}.ZIP"))
    if today.month <= 2:
        previous = today.year - 1
        _download(COTAHIST_A.format(year=previous), cotahist / f"COTAHIST_A{previous}.ZIP", refresh=False)
    stamp = today.strftime("%d%m%Y")
    _download(COTAHIST_D.format(stamp=stamp), cotahist / f"COTAHIST_D{stamp}.ZIP", refresh=not _fresh(cotahist / f"COTAHIST_D{stamp}.ZIP", hours=6))
    cdi_path = cache / "cdi.json"
    if not _fresh(cdi_path, hours=12):
        start = date(today.year, 1, 1).strftime("%d/%m/%Y")
        end = today.strftime("%d/%m/%Y")
        _download(CDI_URL.format(start=start, end=end), cdi_path, refresh=True)
    ibov_path = cache / "ibov.json"
    if not _fresh(ibov_path, hours=12):
        period1 = int(datetime(today.year, 1, 1, tzinfo=UTC).timestamp())
        period2 = int(datetime.now(UTC).timestamp()) + 86400
        _download(IBOV_URL.format(period1=period1, period2=period2), ibov_path, refresh=True)


def _prints(cache: Path, wanted: set[str] | None) -> dict[str, dict[int, tuple[float, float, float, float, float]]]:
    folder = cache / "cotahist"
    prints: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    if not folder.exists():
        return prints
    paths = sorted({path.resolve() for path in folder.iterdir() if path.suffix.lower() == ".zip"})
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if not names:
                continue
            with archive.open(names[0]) as handle:
                for raw in handle:
                    parsed = parse_cotahist_print(raw.decode("latin-1", errors="replace"))
                    if parsed is None:
                        continue
                    ticker = str(parsed["ticker"])
                    if wanted is not None and ticker not in wanted:
                        continue
                    prints.setdefault(ticker, {})[int(parsed["date"])] = (
                        float(parsed["close"]),
                        float(parsed["bid"]),
                        float(parsed["ask"]),
                        float(parsed["qty"]),
                        float(parsed["vol"]),
                    )
    return prints


def _tapes_from_prints(
    prints: dict[str, dict[int, tuple[float, float, float, float, float]]],
    share_events: dict[str, tuple[list[int], list[float]]] | None,
    official: dict | None = None,
) -> dict[str, Tape]:
    """Build tapes with the point-in-time corporate-action rule.

    ``share_events`` is unused. A FRE receipt is not an ex-date, and a filing
    after the print does not rewrite the mark. Factors apply on the session
    being marked, which is the prospective path of an already opened book.
    """
    del share_events
    events = {} if official is None else official
    tapes: dict[str, Tape] = {}
    for ticker, by_day in prints.items():
        ords = sorted(by_day)
        if not ords:
            continue
        close = np.array([by_day[day][0] for day in ords], dtype=np.float64)
        bid = np.array([by_day[day][1] for day in ords], dtype=np.float64)
        ask = np.array([by_day[day][2] for day in ords], dtype=np.float64)
        qty = np.array([by_day[day][3] for day in ords], dtype=np.float64)
        vol = np.array([by_day[day][4] for day in ords], dtype=np.float64)
        dates = np.array(ords, dtype=np.int64)
        adjusted = adjust_prints(dates, close, bid, ask, qty, vol, ticker=ticker, official=events.get(ticker, []))
        tapes[ticker] = Tape(
            dates,
            adjusted.close,
            adjusted.bid,
            adjusted.ask,
            adjusted.qty,
            adjusted.vol,
            adjusted.share_factor,
            adjusted.source,
            adjusted.heuristic_cash_scale,
        )
    return tapes


def _official_for(research: Path, cache: Path) -> dict:
    official = load_official_events(research) if research.exists() else {}
    return merge_official(official, load_chart_splits(cache / "events"))


def _series_map(ords: np.ndarray, values: np.ndarray) -> dict[int, float]:
    return {int(day): float(value) for day, value in zip(ords, values, strict=False)}


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


def _load_universe(research: Path):
    bundle = load_bundle(research)
    filed = _listings_with_on_fallback(load_listings(research), bundle["companies"])
    events = share_events_from_companies(bundle["companies"], filed)
    return bundle["companies"], filed, events


def _refresh_events(cache: Path, tickers: set[str]) -> None:
    folder = cache / "events"
    folder.mkdir(parents=True, exist_ok=True)
    period1 = int(datetime(2009, 1, 1, tzinfo=UTC).timestamp())
    period2 = int(datetime.now(UTC).timestamp()) + 86400
    for ticker in sorted(tickers):
        dest = folder / f"{ticker}.json"
        if _fresh(dest, hours=18):
            continue
        url = CHART.format(ticker=ticker, period1=period1, period2=period2)
        request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        error = None
        payload = None
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 400):
                raise PaperDataError(f"cash-event feed failed for {ticker}: http {exc.code}") from exc
            error = f"http {exc.code}"
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PaperDataError(f"cash-event feed failed for {ticker}") from exc
        rows = []
        splits = []
        if payload is not None:
            rows = [
                {"ordinal": event.ordinal, "amount": event.amount, "kind": event.kind}
                for event in parse_yahoo_events(payload, ticker)
            ]
            splits = [{"ordinal": ordinal, "share_factor": ratio} for ordinal, ratio in parse_yahoo_splits(payload)]
        dest.write_text(
            json.dumps({"ticker": ticker, "events": rows, "splits": splits, "error": error}),
            encoding="utf-8",
        )


def _wanted(snapshot: dict) -> set[str]:
    names = {str(row["ticker"]) for row in snapshot.get("frozen_b_targets") or []}
    names.update(str(row["ticker"]) for row in snapshot["b"]["net_positions"])
    names.add("BOVA11")
    return names


def _quarter_ahead(last: date | None, sessions: list[date]) -> bool:
    prev = last
    for session in sessions:
        if prev is not None and prev.month in (3, 6, 9, 12) and (session.year, session.month) > (prev.year, prev.month):
            return True
        prev = session
    return False


def _status(root: Path) -> int:
    try:
        payload = public_state(root)
    except FileNotFoundError:
        print("not initialized")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _freeze(research: Path, root: Path, today: date) -> int:
    if today >= ENTRY_SESSION:
        raise SystemExit("the signal window is closed; the frozen book is not recomputed")
    path = preregistration_path(root)
    if path.exists():
        raise SystemExit(f"preregistration already frozen at {path}")
    companies, listings, _events = _load_universe(research)
    prints = _prints(research, None)
    tapes = _tapes_from_prints(prints, None, _official_for(research, research))
    book = select_small_book(companies, listings, tapes, SIGNAL_SESSION)
    digest = write_preregistration(path, book, frozen_on=today.isoformat())
    print(json.dumps({"sha256": digest, "n": book["n"], "cash": book["cash"], "path": str(path)}, ensure_ascii=False))
    return 0


def _mark(root: Path, cache: Path, research: Path, today: date) -> int:
    if today < ENTRY_SESSION:
        print(f"nothing to mark before {ENTRY_SESSION.isoformat()}")
        return 0
    loaded = load_book(root)
    snapshot = loaded["snapshot"]
    _ensure_market_files(cache, today)
    cdi_ords, cdi_rates = parse_sgs_cdi((cache / "cdi.json").read_text(encoding="utf-8"))
    ibov_ords, ibov_close = parse_yahoo_chart((cache / "ibov.json").read_text(encoding="utf-8"))
    cdi = _series_map(cdi_ords, cdi_rates)
    ibov = _series_map(ibov_ords, ibov_close)
    held = _wanted(snapshot)
    # The annual file is parsed once. A quarterly boundary needs every listing, not only the names already held.
    probe = _prints(cache, {"BOVA11"})
    bova_days = sorted(probe.get("BOVA11", {}))
    last = snapshot.get("last_session")
    last_day = date.fromisoformat(last) if last else None
    sessions = [
        date.fromordinal(day)
        for day in bova_days
        if date.fromordinal(day) >= ENTRY_SESSION and date.fromordinal(day) <= today and (last_day is None or date.fromordinal(day) > last_day)
    ]
    if not sessions:
        print("no new session with a BOVA11 close")
        return 0
    full_universe = _quarter_ahead(last_day, sessions)
    share_events = None
    companies = None
    listings = None
    if full_universe:
        _ensure_research(research, today)
        if not (research / "cad_cia_aberta.csv").exists():
            raise PaperDataError("quarterly rebalance needs the research cache")
        companies, listings, share_events = _load_universe(research)
        prints = _prints(cache, None)
    else:
        prints = _prints(cache, held)
    tapes = _tapes_from_prints(prints, share_events, _official_for(research, cache))
    _refresh_events(cache, held)
    events = load_cash_events(cache / "events")
    for session in sessions:
        try:
            result = commit_mark(
                root,
                session,
                tapes,
                cdi.get(session.toordinal()),
                ibov.get(session.toordinal()),
                events,
                companies,
                listings,
                today=today,
                timestamp=_now(),
            )
        except LedgerTimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(session.isoformat(), result["ledger_head"], flush=True)
        # Holdings can change, so later sessions in this run must see the new names' history.
        loaded = load_book(root)
        extra = _wanted(loaded["snapshot"]) - set(tapes)
        if extra and not full_universe:
            tapes.update(_tapes_from_prints(_prints(cache, extra), None, _official_for(research, cache)))
            _refresh_events(cache, extra)
            events = load_cash_events(cache / "events")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="B3 forward paper books. No live orders.")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--mark-to-market", action="store_true")
    parser.add_argument("--monthly-report", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--freeze-book", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=Path("data/b3-paper-cache"))
    parser.add_argument("--research", type=Path, default=Path("data/net-net"))
    parser.add_argument("--as-of", type=str, default=None)
    parser.add_argument("--month", type=str, default=None)
    args = parser.parse_args()
    commands = [args.init, args.mark_to_market, args.monthly_report, args.status, args.freeze_book]
    if sum(bool(item) for item in commands) != 1:
        parser.error("choose one of --init, --mark-to-market, --monthly-report, --status, --freeze-book")
    root = args.root or paper_root()
    today = date.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC).date()
    try:
        if args.status:
            raise SystemExit(_status(root))
        if args.freeze_book:
            raise SystemExit(_freeze(args.research, root, today))
        if args.init:
            result = initialize(root, timestamp=_now())
            print(json.dumps(result, ensure_ascii=False))
            return
        if args.mark_to_market:
            raise SystemExit(_mark(root, args.cache, args.research, today))
        try:
            report = write_monthly_report(root, args.month)
        except PaperDataError as exc:
            if args.month is None and "no session" in str(exc):
                print(str(exc))
                return
            raise
        print(report["month"], "eligible_for_live_trading", report["eligible_for_live_trading"])
    except (PaperError, PaperDataError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()

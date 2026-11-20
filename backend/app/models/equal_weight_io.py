"""Public B3 files for the equal-weight study. This module only reads a cache.

COTAHIST prints, Formulário Cadastral tickers and Yahoo chart events are
read from a cache directory. The download scripts are the only code that
opens a network connection. Cash distributions are stored gross, in reais
per share on the ex-date. The tax rule lives in ``equal_weight``.
"""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.models.net_net import Tape, confirmed_split_factors
from app.models.net_net_io import _date_ord, _idx, _rows

SHARE_CLASS = {
    "ações ordinárias": "on",
    "acoes ordinarias": "on",
    "ações preferenciais": "pn",
    "acoes preferenciais": "pn",
    "units": "unit",
}


@dataclass(frozen=True)
class Listing:
    cnpj: str
    ticker: str
    start: int
    end: int | None
    share_class: str


@dataclass(frozen=True)
class CashEvent:
    """Gross reais per share on the ex-date, before the withholding rule."""

    ordinal: int
    amount: float
    kind: str  # dividendo, jcp, unknown


def share_class_of(label: str) -> str | None:
    key = (label or "").strip().lower()
    return SHARE_CLASS.get(key)


def parse_fca_equity(text: str) -> list[tuple[str, str, int, int | None, str]]:
    """Bolsa listings of ordinary shares, preferred shares and units.

    Returns ``(cnpj, ticker, start, end, share_class)``. An empty end date
    means the filing left the listing open. OTC rows are not listings.
    """
    out: list[tuple[str, str, int, int | None, str]] = []
    cached: tuple[int | None, ...] | None = None
    for header, row in _rows(text):
        if cached is None:
            cached = (
                _idx(header, "cnpj_companhia", "cnpj_cia", "cnpj"),
                _idx(header, "codigo_negociacao", "cod_negociacao"),
                _idx(header, "valor_mobiliario"),
                _idx(header, "mercado"),
                _idx(header, "data_inicio_negociacao"),
                _idx(header, "data_fim_negociacao"),
            )
            if cached[0] is None or cached[1] is None or cached[2] is None:
                return out
        i_cnpj, i_tic, i_val, i_mkt, i_ini, i_fim = cached
        if i_cnpj is None or i_tic is None or i_val is None:
            return out
        if max(i_cnpj, i_tic, i_val) >= len(row):
            continue
        share_class = share_class_of(row[i_val])
        if share_class is None:
            continue
        if i_mkt is not None and i_mkt < len(row) and row[i_mkt].strip() not in ("", "Bolsa"):
            continue
        ticker = row[i_tic].strip().upper()
        if not ticker or len(ticker) > 12:
            continue
        start = _date_ord(row[i_ini]) if i_ini is not None and i_ini < len(row) else None
        end = _date_ord(row[i_fim]) if i_fim is not None and i_fim < len(row) else None
        if start is None:
            continue
        out.append((row[i_cnpj].strip(), ticker, start, end, share_class))
    return out


def merge_listings(rows: list[tuple[str, str, int, int | None, str]]) -> list[Listing]:
    """One interval per issuer and ticker. A blank end date in any vintage keeps it open."""
    spans: dict[tuple[str, str], list[tuple[int, int | None, str]]] = defaultdict(list)
    for cnpj, ticker, start, end, share_class in rows:
        spans[(cnpj, ticker)].append((start, end, share_class))
    merged: list[Listing] = []
    for (cnpj, ticker), intervals in spans.items():
        start = min(item[0] for item in intervals)
        if any(item[1] is None for item in intervals):
            end: int | None = None
        else:
            closed = [item[1] for item in intervals if item[1] is not None]
            end = max(closed) if closed else None
        share_class = intervals[-1][2]
        merged.append(Listing(cnpj, ticker, start, end, share_class))
    merged.sort(key=lambda item: (item.cnpj, item.ticker))
    return merged


def load_listings(cache: Path) -> list[Listing]:
    rows: list[tuple[str, str, int, int | None, str]] = []
    folder = Path(cache) / "fca"
    if not folder.exists():
        return []
    for path in sorted(folder.glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if "valor_mobiliario" not in name.lower():
                    continue
                text = archive.read(name).decode("latin-1", errors="replace")
                rows.extend(parse_fca_equity(text))
    return merge_listings(rows)


def parse_cotahist_print(line: str) -> dict[str, Any] | None:
    """One standard-lot cash print, including the trade count (TOTNEG)."""
    raw = line.rstrip("\r\n")
    if len(raw) < 245 or raw[0:2] != "01":
        return None
    if raw[10:12] != "02" or raw[24:27] != "010":
        return None
    try:
        ordinal = datetime.strptime(raw[2:10], "%Y%m%d").date().toordinal()
        close = int(raw[108:121]) / 100.0
        bid = int(raw[121:134]) / 100.0
        ask = int(raw[134:147]) / 100.0
        trades_txt = raw[147:152].strip()
        trades = int(trades_txt) if trades_txt else 0
        qty = int(raw[152:170])
        vol = int(raw[170:188]) / 100.0
    except ValueError:
        return None
    ticker = raw[12:24].strip().upper()
    if not ticker or close <= 0:
        return None
    return {
        "date": ordinal,
        "ticker": ticker,
        "close": close,
        "bid": bid,
        "ask": ask,
        "qty": float(qty),
        "vol": vol,
        "trades": float(trades),
    }


def yahoo_nominal_amount(adjusted: float, ex_ordinal: int, splits: list[tuple[int, float]]) -> float:
    """Undo Yahoo's later split adjustment. A split on the ex-date itself is left in the amount.

    Yahoo stores the cash amount in shares after subsequent splits. Multiplying
    by those later ratios recovers reais per share as of the ex-date. The
    same-day split is not applied here: the share count is adjusted first, and
    the amount is already in the new share.
    """
    if not np.isfinite(adjusted) or adjusted <= 0:
        return 0.0
    factor = 1.0
    for split_ord, ratio in splits:
        if split_ord > ex_ordinal and np.isfinite(ratio) and ratio > 0:
            factor *= float(ratio)
    return float(adjusted) * factor


def parse_yahoo_events(payload: dict[str, Any], ticker: str) -> list[CashEvent]:
    """Chart-event dividends. The feed does not label JCP, so the kind is ``unknown``."""
    chart = payload.get("chart") or {}
    result = chart.get("result") or []
    if not result:
        return []
    events = result[0].get("events") or {}
    raw_splits = events.get("splits") or {}
    splits: list[tuple[int, float]] = []
    for item in raw_splits.values():
        if not isinstance(item, dict):
            continue
        stamp = item.get("date")
        ratio = item.get("splitRatio")
        if ratio is None and item.get("numerator") and item.get("denominator"):
            ratio = float(item["numerator"]) / float(item["denominator"])
        if stamp is None or ratio is None:
            continue
        try:
            ordinal = datetime.fromtimestamp(int(stamp), UTC).date().toordinal()
            splits.append((ordinal, float(ratio)))
        except (TypeError, ValueError, OSError):
            continue
    out: list[CashEvent] = []
    for item in (events.get("dividends") or {}).values():
        if not isinstance(item, dict):
            continue
        try:
            ordinal = datetime.fromtimestamp(int(item["date"]), UTC).date().toordinal()
            amount = yahoo_nominal_amount(float(item["amount"]), ordinal, splits)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if amount <= 0 or not np.isfinite(amount):
            continue
        out.append(CashEvent(ordinal, amount, "unknown"))
    out.sort(key=lambda event: (event.ordinal, event.amount))
    return out


def load_cash_events(directory: Path) -> dict[str, list[CashEvent]]:
    """Read ``{ticker}.json`` files written by the dividend fetch script."""
    folder = Path(directory)
    events: dict[str, list[CashEvent]] = {}
    if not folder.exists():
        return events
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ticker = str(payload.get("ticker") or path.stem).upper()
        rows: list[CashEvent] = []
        for item in payload.get("events") or []:
            try:
                ordinal = int(item["ordinal"])
                amount = float(item["amount"])
            except (KeyError, TypeError, ValueError):
                continue
            kind = str(item.get("kind") or "unknown")
            if amount <= 0 or not np.isfinite(amount):
                continue
            rows.append(CashEvent(ordinal, amount, kind))
        rows.sort(key=lambda event: (event.ordinal, event.kind, event.amount))
        if rows:
            events[ticker] = rows
    return events


def share_events_from_companies(companies: Sequence[Any], listings: Sequence[Listing]) -> dict[str, tuple[list[int], list[float]]]:
    """Common-share counts by receipt date, used to confirm a split on every class of the issuer."""
    by_cnpj = {company.cnpj: company for company in companies}
    events: dict[str, tuple[list[int], list[float]]] = {}
    for item in listings:
        company = by_cnpj.get(item.cnpj)
        if company is None:
            continue
        collapsed: dict[int, Any] = {}
        for point in company.shares:
            prev = collapsed.get(point.received)
            if prev is None or point.period_end > prev.period_end:
                collapsed[point.received] = point
        points = [collapsed[key] for key in sorted(collapsed)]
        if len(points) < 2:
            continue
        events[item.ticker] = (
            [int(point.received) for point in points],
            [float(point.on_out) for point in points],
        )
    return events


def share_class_of_ticker(ticker: str) -> str:
    """B3 cash-equity suffix. ``11`` is a unit, ``3`` is ordinary, the rest is preferred."""
    if ticker.endswith("11"):
        return "unit"
    if ticker.endswith("3"):
        return "on"
    return "pn"


def listings_from_tapes(
    tapes: dict[str, Tape],
    known: Sequence[Listing],
    last_session: int,
) -> list[Listing]:
    """Add every COTAHIST name the cadastral form did not carry.

    Forms before 2018 leave the ticker blank, so a name that stopped trading
    before a later form named it would otherwise disappear. The tape is the
    listing. A 4-letter root that already has a company identifier keeps that
    identifier, so the preferred line joins the ordinary line. A root with no
    filing gets a synthetic identifier and cannot enter the small-cap book,
    because there is no share count to capitalise.
    """
    by_ticker = {item.ticker: item for item in known}
    root_cnpj: dict[str, str] = {}
    for item in known:
        root_cnpj.setdefault(item.ticker[:4], item.cnpj)
    extra: list[Listing] = []
    for ticker, tape in tapes.items():
        if ticker in by_ticker or len(tape.dates) == 0:
            continue
        root = ticker[:4]
        start = int(tape.dates[0])
        last = int(tape.dates[-1])
        end: int | None = None if last_session - last <= 15 else last
        extra.append(Listing(root_cnpj.get(root, f"ROOT:{root}"), ticker, start, end, share_class_of_ticker(ticker)))
    extra.sort(key=lambda item: (item.cnpj, item.ticker))
    return list(known) + extra


def load_strategy_tapes(
    cache: Path,
    listings: list[Listing] | None,
    share_events: dict[str, tuple[list[int], list[float]]],
) -> tuple[dict[str, Tape], dict[str, np.ndarray], int]:
    """COTAHIST tapes for the listing set, plus a trade-count array aligned to each tape.

    ``share_events`` maps a ticker to ``(receipt ordinals, common shares)``. A
    round price gap is a split only when that series confirms it. The trade
    count is COTAHIST's TOTNEG and is not on the shared ``Tape`` type.
    """
    wanted = None if listings is None else {item.ticker for item in listings}
    prints: dict[str, dict[int, tuple[float, float, float, float, float, float]]] = defaultdict(dict)
    folder = Path(cache) / "cotahist"
    if folder.exists():
        paths = {path.resolve() for path in folder.iterdir() if path.suffix.lower() == ".zip"}
        for path in sorted(paths):
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                if not names:
                    continue
                with archive.open(names[0]) as handle:
                    for raw in handle:
                        parsed = parse_cotahist_print(raw.decode("latin-1", errors="replace"))
                        if parsed is None or (wanted is not None and parsed["ticker"] not in wanted):
                            continue
                        prints[parsed["ticker"]][int(parsed["date"])] = (
                            float(parsed["close"]),
                            float(parsed["bid"]),
                            float(parsed["ask"]),
                            float(parsed["qty"]),
                            float(parsed["vol"]),
                            float(parsed["trades"]),
                        )
    tapes: dict[str, Tape] = {}
    trades: dict[str, np.ndarray] = {}
    n_splits = 0
    for ticker, by_day in prints.items():
        ords = sorted(by_day)
        if len(ords) < 2:
            continue
        close = np.array([by_day[day][0] for day in ords], dtype=np.float64)
        bid = np.array([by_day[day][1] for day in ords], dtype=np.float64)
        ask = np.array([by_day[day][2] for day in ords], dtype=np.float64)
        qty = np.array([by_day[day][3] for day in ords], dtype=np.float64)
        vol = np.array([by_day[day][4] for day in ords], dtype=np.float64)
        trade = np.array([by_day[day][5] for day in ords], dtype=np.float64)
        dates = np.array(ords, dtype=np.int64)
        events = share_events.get(ticker)
        if events is None:
            split = np.ones(len(dates), dtype=np.float64)
        else:
            split = confirmed_split_factors(dates, close, events[0], events[1])
        n_splits += int(np.sum(np.abs(split - 1.0) > 1e-8))
        tapes[ticker] = Tape(dates, close, bid, ask, qty, vol, split)
        trades[ticker] = trade
    return tapes, trades, n_splits

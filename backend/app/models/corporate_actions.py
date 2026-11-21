"""Point-in-time B3 corporate-action adjustment.

Research and paper marks only. Nothing here sends an order.
``eligible_for_live_trading`` stays false on every study that consumes the tapes.

The rule below was fixed before the v2 equal-weight path was read. Do not
retune the tolerances against that path.

A price jump is not a return when it is a grupamento, a desdobramento or a
bonificação whose ex-date was already known, or when the same session shows
the pre-registered price-and-volume pattern. A document filed after the print
does not justify the jump. The previous window of 250 days after the print
was removed.

Order, on each print:

1. Official B3 or CVM event whose knowledge date is on or before the ex-date,
   and whose share factor explains the same-session price ratio within
   ``OFFICIAL_RESIDUAL_TOL``. The factor and the ex-date come from the record.
2. Else a reversal pair: two jumps, each near an integer or ``1/n``, that undo
   each other within ``REVERT_SESSIONS`` prints. Those prints are bad data.
   The close is carried forward and the share volume is dropped from ADV.
3. Else the heuristic: the price ratio is within ``PRICE_INTEGER_REL_TOL`` of
   an integer ``n`` or of ``1/n``, with ``2 <= n <= MAX_HEURISTIC_FACTOR``, and
   the share volume moves the other way by a log-factor within
   ``VOLUME_LOG_REL_TOL``. Same session only.
4. Else the jump stays in the return. Source ``unadjusted``.

``share_factor`` is new shares over old shares. A grupamento of 80-for-1 has
share factor ``1/80``. Position quantity is multiplied by that factor. The
adjusted return on the print is ``price_ratio * share_factor - 1``.
"""

from __future__ import annotations

import csv
import json
import math
import re
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

# Locked before the v2 result. Quoted by docs/EQUAL-WEIGHT-B3.md.
RULE_VERSION = "b3-corporate-actions-v2"
JUMP_RATIO = 1.45
PRICE_INTEGER_REL_TOL = 0.03
MAX_HEURISTIC_FACTOR = 100
VOLUME_LOG_REL_TOL = 0.40
MIN_SHARE_QTY = 100.0
REVERT_SESSIONS = 5
REVERT_NET_REL_TOL = 0.08
OFFICIAL_RESIDUAL_TOL = 0.25
OFFICIAL_SESSION_SLACK_DAYS = 7

_SOURCES = ("b3", "cvm", "heuristic", "unadjusted", "bad_print")
_DATE_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RATIO_WORDS = re.compile(r"(\d+)\s*(?:para|:|/)\s*(\d+)", re.IGNORECASE)
_EX_DATE = re.compile(
    r"data[\s\-]*ex\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_BONUS_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


@dataclass(frozen=True)
class OfficialEvent:
    """One corporate action whose factor is applied on the ex-date.

    ``knowledge_ordinal`` is the announcement or the protocol date. An event
    with ``knowledge_ordinal > ex_ordinal`` is ignored. ``share_factor`` is
    new shares / old shares. ``source`` is ``b3`` or ``cvm``.
    """

    ticker: str
    ex_ordinal: int
    share_factor: float
    knowledge_ordinal: int
    source: str
    kind: str = ""

    @property
    def usable(self) -> bool:
        return (
            self.source in ("b3", "cvm")
            and self.knowledge_ordinal <= self.ex_ordinal
            and math.isfinite(self.share_factor)
            and self.share_factor > 0.0
            and abs(self.share_factor - 1.0) > 1e-12
        )


@dataclass(frozen=True)
class Adjustment:
    close: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    qty: np.ndarray
    vol: np.ndarray
    share_factor: np.ndarray
    source: np.ndarray
    heuristic_cash_scale: np.ndarray
    audit: tuple[dict[str, Any], ...]


def is_jump(price_ratio: float) -> bool:
    if not math.isfinite(price_ratio) or price_ratio <= 0.0:
        return False
    return price_ratio >= JUMP_RATIO or price_ratio <= 1.0 / JUMP_RATIO


def match_share_factor(price_ratio: float) -> float | None:
    """Share factor implied by a price ratio near ``n`` or ``1/n``.

    Returns new/old shares, or ``None`` when the ratio is not that shape.
    """
    if not math.isfinite(price_ratio) or price_ratio <= 0.0:
        return None
    if price_ratio >= JUMP_RATIO:
        n = int(round(price_ratio))
        if n < 2 or n > MAX_HEURISTIC_FACTOR:
            return None
        if abs(price_ratio - n) / n > PRICE_INTEGER_REL_TOL:
            return None
        return 1.0 / n
    if price_ratio <= 1.0 / JUMP_RATIO:
        inv = 1.0 / price_ratio
        n = int(round(inv))
        if n < 2 or n > MAX_HEURISTIC_FACTOR:
            return None
        if abs(inv - n) / n > PRICE_INTEGER_REL_TOL:
            return None
        return float(n)
    return None


def volume_confirms(price_ratio: float, qty_prev: float, qty_today: float) -> bool:
    """Share volume moves with the corporate-action factor on the same print.

    For a price rise the share volume must fall, and the log of that fall must
    sit within ``VOLUME_LOG_REL_TOL`` of the log of the price ratio. A split is
    the mirror image. A price jump with unchanged share volume fails.
    """
    if not all(math.isfinite(x) for x in (price_ratio, qty_prev, qty_today)):
        return False
    if qty_prev < MIN_SHARE_QTY or qty_today < MIN_SHARE_QTY or price_ratio <= 0.0:
        return False
    if price_ratio >= JUMP_RATIO:
        fallen = qty_prev / qty_today
        if fallen <= 1.0:
            return False
        return abs(math.log(fallen) - math.log(price_ratio)) / math.log(price_ratio) <= VOLUME_LOG_REL_TOL
    if price_ratio <= 1.0 / JUMP_RATIO:
        risen = qty_today / qty_prev
        target = 1.0 / price_ratio
        if risen <= 1.0 or target <= 1.0:
            return False
        return abs(math.log(risen) - math.log(target)) / math.log(target) <= VOLUME_LOG_REL_TOL
    return False


def official_matches(price_ratio: float, share_factor: float) -> bool:
    """The official factor removes the print, up to a same-day residual."""
    if not math.isfinite(price_ratio) or not math.isfinite(share_factor):
        return False
    if price_ratio <= 0.0 or share_factor <= 0.0:
        return False
    return abs(price_ratio * share_factor - 1.0) <= OFFICIAL_RESIDUAL_TOL


def adj_return(close: np.ndarray, share_factor: np.ndarray) -> np.ndarray:
    """Point-in-time simple return. The print's share factor is in the numerator.

    ``r_t = close_t / close_{t-1} * share_factor_t - 1``. A grupamento whose
    price ratio is ``n`` and whose share factor is ``1/n`` has return 0 before
    the residual move. Bad prints are already carried forward in ``close``.
    """
    close = np.asarray(close, dtype=np.float64)
    factor = np.asarray(share_factor, dtype=np.float64)
    out = np.full(len(close), np.nan, dtype=np.float64)
    if len(close) < 2:
        return out
    prev = close[:-1]
    px = close[1:]
    f = factor[1:]
    valid = (prev > 0.0) & (px > 0.0) & (f > 0.0) & np.isfinite(prev) & np.isfinite(px) & np.isfinite(f)
    ret = np.full(len(prev), np.nan, dtype=np.float64)
    ret[valid] = px[valid] / prev[valid] * f[valid] - 1.0
    out[1:] = ret
    return out


def adjusted_close(close: np.ndarray, share_factor: np.ndarray) -> np.ndarray:
    """Price in the first print's share unit. Later factors do not restate earlier days."""
    close = np.asarray(close, dtype=np.float64)
    factor = np.asarray(share_factor, dtype=np.float64)
    step = np.where(np.isfinite(factor) & (factor > 0.0), factor, 1.0)
    return close * np.cumprod(step)


def filing_price_multiplier(
    dates: np.ndarray,
    share_factor: np.ndarray,
    filing_received: int,
    asof: int,
) -> float:
    """Scale a raw close back into the share unit of a filing already received.

    Factors dated after ``filing_received`` and on or before ``asof`` are the
    ones the filing cannot yet contain. Multiplying the raw price by their
    product keeps market cap = price × filed shares continuous across the event.
    """
    dates = np.asarray(dates, dtype=np.int64)
    factor = np.asarray(share_factor, dtype=np.float64)
    mask = (dates > int(filing_received)) & (dates <= int(asof)) & np.isfinite(factor) & (factor > 0.0)
    if not np.any(mask):
        return 1.0
    return float(np.prod(factor[mask]))


def cash_scale_at(tape: Any, ordinal: int) -> float:
    """Reais per current share / reais per share quoted before heuristic factors.

    Official factors are assumed to already be in the cash amount. Heuristic
    factors are not, so the amount is scaled by the inverse of those factors
    up through ``ordinal``.
    """
    series = getattr(tape, "heuristic_cash_scale", None)
    if series is None or len(series) == 0:
        return 1.0
    idx = tape.index_on_or_before(int(ordinal))
    if idx is None or int(tape.dates[idx]) > int(ordinal):
        return 1.0
    value = float(series[idx])
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    return value


def heuristic_cash_scale(share_factor: np.ndarray, source: np.ndarray) -> np.ndarray:
    step = np.ones(len(share_factor), dtype=np.float64)
    heuristic = np.asarray(source) == "heuristic"
    factor = np.asarray(share_factor, dtype=np.float64)
    good = heuristic & np.isfinite(factor) & (factor > 0.0)
    step[good] = factor[good]
    return np.cumprod(1.0 / step)


def events_from_chart_splits(ticker: str, splits: Sequence[tuple[int, float]]) -> list[OfficialEvent]:
    """Chart-feed ex-dates. Knowledge date is the ex-date itself, not a later protocol.

    The cash-event fetch already reads this calendar. A split ratio is new/old
    shares. Rows are labeled ``b3`` because they are the exchange ex-date, and
    ``kind`` stays ``chart_ex_date`` so the audit can count them apart from a
    B3 file.
    """
    out: list[OfficialEvent] = []
    for ordinal, ratio in splits:
        try:
            ex = int(ordinal)
            factor = float(ratio)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(factor) or factor <= 0.0 or abs(factor - 1.0) <= 1e-12:
            continue
        out.append(OfficialEvent(ticker.upper(), ex, factor, ex, "b3", "chart_ex_date"))
    return out


def _parse_date(text: str) -> int | None:
    raw = text.strip()
    iso = _DATE_ISO.search(raw)
    if iso and iso.group(0) == raw[:10]:
        try:
            return datetime.strptime(iso.group(0), "%Y-%m-%d").date().toordinal()
        except ValueError:
            return None
    if iso and len(raw) >= 10 and raw[4] == "-":
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date().toordinal()
        except ValueError:
            return None
    slash = _DATE_SLASH.search(raw)
    if slash:
        day, month, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
        try:
            return date(year, month, day).toordinal()
        except ValueError:
            return None
    return None


def _event_from_mapping(row: Mapping[str, Any]) -> OfficialEvent | None:
    try:
        ticker = str(row.get("ticker") or "").upper().strip()
        factor = float(row["share_factor"])
        source = str(row.get("source") or "").lower().strip()
    except (KeyError, TypeError, ValueError):
        return None
    ex = row.get("ex_ordinal", row.get("ex_date"))
    knowledge = row.get("knowledge_ordinal", row.get("knowledge_date"))
    ex_ord = int(ex) if isinstance(ex, int) and not isinstance(ex, bool) else _parse_date(str(ex or ""))
    know_ord = (
        int(knowledge)
        if isinstance(knowledge, int) and not isinstance(knowledge, bool)
        else _parse_date(str(knowledge or ""))
    )
    if not ticker or ex_ord is None or know_ord is None:
        return None
    if source not in ("b3", "cvm"):
        return None
    return OfficialEvent(ticker, ex_ord, factor, know_ord, source, str(row.get("kind") or ""))


def parse_official_records(payload: Any) -> list[OfficialEvent]:
    """JSON list, or a map of ticker to lists. Unknown rows are dropped."""
    rows: list[Any]
    if isinstance(payload, dict):
        rows = []
        for ticker, items in payload.items():
            if str(ticker).startswith("_"):
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and "ticker" not in item:
                    item = {**item, "ticker": ticker}
                rows.append(item)
    elif isinstance(payload, list):
        rows = payload
    else:
        return []
    out: list[OfficialEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event = _event_from_mapping(row)
        if event is not None:
            out.append(event)
    return out


def parse_official_csv(text: str) -> list[OfficialEvent]:
    """Columns ``ticker,ex_date,share_factor,knowledge_date,source,kind``."""
    out: list[OfficialEvent] = []
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        lowered = {str(key).strip().lower(): value for key, value in row.items() if key}
        event = _event_from_mapping(lowered)
        if event is not None:
            out.append(event)
    return out


def parse_cvm_ipe_text(text: str) -> list[OfficialEvent]:
    """CVM IPE rows that state both a factor and an ex-date in the subject.

    A row whose delivery date is after the ex-date is returned with that later
    knowledge date so the caller can drop it. The factor is not guessed when
    the subject has no ratio and no ex-date.
    """
    sample = text.lstrip("\ufeff")
    if not sample.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(sample[:2048], delimiters=";\t,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(sample.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        return []
    fields = {name.lower(): name for name in reader.fieldnames if name}
    cnpj_key = fields.get("cnpj_companhia") or fields.get("cnpj_cia")
    subject_key = fields.get("assunto")
    delivery_key = fields.get("data_entrega") or fields.get("dt_receb")
    ticker_key = fields.get("codigo_negociacao") or fields.get("ticker")
    if subject_key is None or delivery_key is None:
        return []
    out: list[OfficialEvent] = []
    for row in reader:
        subject = str(row.get(subject_key) or "")
        factor, kind = _factor_from_subject(subject)
        ex_match = _EX_DATE.search(subject)
        if factor is None or ex_match is None:
            continue
        ex_ord = _parse_date(ex_match.group(1))
        know_ord = _parse_date(str(row.get(delivery_key) or ""))
        if ex_ord is None or know_ord is None:
            continue
        ticker = str(row.get(ticker_key) or "").upper().strip() if ticker_key else ""
        if not ticker:
            ticker = _ticker_in_subject(subject) or ""
        if not ticker and cnpj_key:
            continue
        if not ticker:
            continue
        out.append(OfficialEvent(ticker, ex_ord, factor, know_ord, "cvm", kind))
    return out


def _ticker_in_subject(subject: str) -> str | None:
    match = re.search(r"\b([A-Z]{4}\d{1,2})\b", subject.upper())
    return None if match is None else match.group(1)


def _factor_from_subject(subject: str) -> tuple[float | None, str]:
    """``A para B`` means A old shares become B new shares."""
    lowered = subject.lower()
    kind = ""
    if "grupamento" in lowered:
        kind = "grupamento"
    elif "desdobramento" in lowered:
        kind = "desdobramento"
    elif "bonifica" in lowered:
        kind = "bonificacao"
    ratio = _RATIO_WORDS.search(subject)
    if ratio and kind:
        old, new = int(ratio.group(1)), int(ratio.group(2))
        if old <= 0 or new <= 0:
            return None, kind
        return new / old, kind
    if kind == "bonificacao":
        bonus = _BONUS_PCT.search(subject)
        if bonus:
            pct = float(bonus.group(1).replace(",", "."))
            if pct > 0.0:
                return 1.0 + pct / 100.0, kind
    return None, kind


def merge_official(
    primary: Mapping[str, Sequence[OfficialEvent]],
    extra: Mapping[str, Sequence[OfficialEvent]],
) -> dict[str, list[OfficialEvent]]:
    """File events win over a chart ex-date on the same ticker and ex-date."""
    out: dict[str, list[OfficialEvent]] = {key: list(rows) for key, rows in primary.items()}
    for ticker, rows in extra.items():
        held = out.setdefault(ticker, [])
        taken = {int(event.ex_ordinal) for event in held}
        for event in rows:
            if int(event.ex_ordinal) in taken:
                continue
            held.append(event)
            taken.add(int(event.ex_ordinal))
    return out


def load_official_events(cache: Path) -> dict[str, list[OfficialEvent]]:
    """B3 CSV/JSON plus CVM IPE zips under the research cache. No network."""
    folder = Path(cache)
    found: list[OfficialEvent] = []
    json_path = folder / "corporate-actions.json"
    if json_path.exists():
        found.extend(parse_official_records(json.loads(json_path.read_text(encoding="utf-8"))))
    csv_path = folder / "corporate-actions.csv"
    if csv_path.exists():
        found.extend(parse_official_csv(csv_path.read_text(encoding="utf-8")))
    extra_dir = folder / "corporate-actions"
    if extra_dir.exists():
        for path in sorted(extra_dir.glob("*.json")):
            found.extend(parse_official_records(json.loads(path.read_text(encoding="utf-8"))))
    ipe = folder / "ipe"
    if ipe.exists():
        for path in sorted(ipe.glob("*.zip")):
            found.extend(_ipe_zip(path))
    grouped: dict[str, list[OfficialEvent]] = {}
    for event in found:
        grouped.setdefault(event.ticker, []).append(event)
    return grouped


def _ipe_zip(path: Path) -> list[OfficialEvent]:
    out: list[OfficialEvent] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = archive.read(name).decode("latin-1", errors="replace")
            out.extend(parse_cvm_ipe_text(text))
    return out


def load_chart_splits(directory: Path) -> dict[str, list[OfficialEvent]]:
    """``splits`` saved next to the cash events. Missing key means no ex-date record."""
    folder = Path(directory)
    out: dict[str, list[OfficialEvent]] = {}
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        ticker = str(payload.get("ticker") or path.stem).upper()
        splits: list[tuple[int, float]] = []
        for item in payload.get("splits") or []:
            try:
                splits.append((int(item["ordinal"]), float(item["share_factor"])))
            except (KeyError, TypeError, ValueError):
                continue
        events = events_from_chart_splits(ticker, splits)
        if events:
            out[ticker] = events
    return out


def adjust_prints(
    dates: np.ndarray,
    close: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    qty: np.ndarray,
    vol: np.ndarray,
    *,
    ticker: str,
    official: Sequence[OfficialEvent] = (),
) -> Adjustment:
    """Clean one tape and return the share factor, the source and the jump log."""
    dates = np.asarray(dates, dtype=np.int64)
    raw_close = np.asarray(close, dtype=np.float64)
    raw_bid = np.asarray(bid, dtype=np.float64)
    raw_ask = np.asarray(ask, dtype=np.float64)
    raw_qty = np.asarray(qty, dtype=np.float64)
    raw_vol = np.asarray(vol, dtype=np.float64)
    n = len(dates)
    if not (len(raw_close) == len(raw_bid) == len(raw_ask) == len(raw_qty) == len(raw_vol) == n):
        raise ValueError("tape arrays must share one length")
    out_close = raw_close.copy()
    out_bid = raw_bid.copy()
    out_ask = raw_ask.copy()
    out_qty = raw_qty.copy()
    out_vol = raw_vol.copy()
    factor = np.ones(n, dtype=np.float64)
    source = np.array(["unadjusted"] * n, dtype=object)
    if n < 2:
        scale = heuristic_cash_scale(factor, source)
        return Adjustment(out_close, out_bid, out_ask, out_qty, out_vol, factor, source, scale, ())

    jumps = _jump_indices(raw_close)
    usable, late = _split_official(official)
    applied, rejected = _apply_official(dates, raw_close, usable)
    reversible = np.asarray([index for index in jumps if int(index) not in applied], dtype=np.int64)
    bad = _reversal_mask(dates, raw_close, reversible)
    for index, event in applied.items():
        factor[index] = float(event.share_factor)
        source[index] = event.source

    for index in np.flatnonzero(bad):
        i = int(index)
        out_close[i] = out_close[i - 1]
        out_bid[i] = out_bid[i - 1]
        out_ask[i] = out_ask[i - 1]
        out_qty[i] = np.nan
        out_vol[i] = np.nan
        factor[i] = 1.0
        source[i] = "bad_print"

    for index in jumps:
        i = int(index)
        if source[i] != "unadjusted":
            continue
        ratio = _ratio(raw_close, i)
        share = None if ratio is None else match_share_factor(ratio)
        if share is None or not _qty_confirms(raw_qty, i, ratio):
            continue
        factor[i] = float(share)
        source[i] = "heuristic"

    audit = _audit_rows(
        ticker,
        dates,
        raw_close,
        raw_qty,
        jumps,
        source,
        factor,
        late,
        rejected,
        applied,
    )
    scale = heuristic_cash_scale(factor, source)
    return Adjustment(out_close, out_bid, out_ask, out_qty, out_vol, factor, source, scale, tuple(audit))


def summarize_audit(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts for jumps of at least 45%, by source. Sub-threshold events stay out."""
    jumps = [row for row in rows if is_jump(float(row.get("price_ratio") or 0.0))]
    counts: Counter[str] = Counter(str(row.get("source") or "unadjusted") for row in jumps)
    chart = sum(1 for row in jumps if "chart_ex_date" in str(row.get("reason") or ""))
    late = sum(1 for row in jumps if "late_filing_ignored" in str(row.get("reason") or ""))
    by_source = {name: int(counts.get(name, 0)) for name in _SOURCES}
    return {
        "rule": RULE_VERSION,
        "n_jumps": len(jumps),
        "by_source": by_source,
        "b3_chart_ex_date": chart,
        "late_filings_ignored": late,
        "eligible_for_live_trading": False,
    }


def _jump_indices(close: np.ndarray) -> np.ndarray:
    prev = close[:-1]
    px = close[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = px / prev
    jump = (prev > 0.0) & (px > 0.0) & np.isfinite(ratio) & ((ratio >= JUMP_RATIO) | (ratio <= 1.0 / JUMP_RATIO))
    return np.flatnonzero(jump) + 1


def _ratio(close: np.ndarray, index: int) -> float | None:
    prev = float(close[index - 1])
    px = float(close[index])
    if prev <= 0.0 or px <= 0.0 or not math.isfinite(prev) or not math.isfinite(px):
        return None
    return px / prev


def _qty_confirms(qty: np.ndarray, index: int, ratio: float | None) -> bool:
    if ratio is None or index < 1:
        return False
    return volume_confirms(ratio, float(qty[index - 1]), float(qty[index]))


def _reversal_mask(dates: np.ndarray, close: np.ndarray, jumps: np.ndarray) -> np.ndarray:
    bad = np.zeros(len(close), dtype=bool)
    jump_set = {int(index) for index in jumps}
    for index in jumps:
        i = int(index)
        if bad[i]:
            continue
        ratio = _ratio(close, i)
        if ratio is None or match_share_factor(ratio) is None:
            continue
        last = min(len(close) - 1, i + REVERT_SESSIONS)
        for j in range(i + 1, last + 1):
            if j - i > REVERT_SESSIONS or j not in jump_set:
                continue
            if int(dates[j]) < int(dates[i]):
                continue
            inv = _ratio(close, j)
            if inv is None or match_share_factor(inv) is None:
                continue
            if abs(ratio * inv - 1.0) > REVERT_NET_REL_TOL:
                continue
            if abs(close[j] / close[i - 1] - 1.0) > REVERT_NET_REL_TOL:
                continue
            bad[i] = True
            bad[j] = True
            break
    return bad


def _split_official(
    official: Sequence[OfficialEvent],
) -> tuple[list[OfficialEvent], list[OfficialEvent]]:
    usable: list[OfficialEvent] = []
    late: list[OfficialEvent] = []
    for event in official:
        if event.knowledge_ordinal > event.ex_ordinal:
            late.append(event)
        elif event.usable:
            usable.append(event)
    return usable, late


def _session_index(dates: np.ndarray, ex_ordinal: int) -> int | None:
    index = int(np.searchsorted(dates, int(ex_ordinal), side="left"))
    if index >= len(dates):
        return None
    if int(dates[index]) - int(ex_ordinal) > OFFICIAL_SESSION_SLACK_DAYS:
        return None
    return index


def _apply_official(
    dates: np.ndarray,
    close: np.ndarray,
    events: Sequence[OfficialEvent],
) -> tuple[dict[int, OfficialEvent], dict[int, str]]:
    grouped: dict[int, list[OfficialEvent]] = {}
    for event in events:
        index = _session_index(dates, event.ex_ordinal)
        if index is None or index == 0:
            continue
        grouped.setdefault(index, []).append(event)
    applied: dict[int, OfficialEvent] = {}
    rejected: dict[int, str] = {}
    for index, rows in grouped.items():
        ratio = _ratio(close, index)
        if ratio is None:
            continue
        combined = 1.0
        for event in rows:
            combined *= float(event.share_factor)
        if not official_matches(ratio, combined):
            rejected[index] = "official_residual_too_large"
            continue
        source = "b3" if any(event.source == "b3" for event in rows) else "cvm"
        kind = "+".join(event.kind or event.source for event in rows)
        applied[index] = OfficialEvent(rows[0].ticker, int(dates[index]), combined, rows[0].knowledge_ordinal, source, kind)
    return applied, rejected


def _volume_ratio(qty: np.ndarray, index: int) -> float | None:
    prev = float(qty[index - 1])
    today = float(qty[index])
    if prev <= 0.0 or today <= 0.0 or not math.isfinite(prev) or not math.isfinite(today):
        return None
    return today / prev


def _audit_rows(
    ticker: str,
    dates: np.ndarray,
    close: np.ndarray,
    qty: np.ndarray,
    jumps: np.ndarray,
    source: np.ndarray,
    factor: np.ndarray,
    late: Sequence[OfficialEvent],
    rejected: Mapping[int, str],
    applied: Mapping[int, OfficialEvent],
) -> list[dict[str, Any]]:
    late_at: dict[int, int] = {}
    for event in late:
        index = _session_index(dates, event.ex_ordinal)
        if index is not None:
            late_at[index] = int(event.knowledge_ordinal)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index in list(jumps) + [i for i in applied if int(i) not in set(map(int, jumps))]:
        i = int(index)
        if i in seen or i <= 0:
            continue
        seen.add(i)
        ratio = _ratio(close, i)
        if ratio is None:
            continue
        reason = _reason(i, str(source[i]), applied.get(i), i in late_at, rejected.get(i))
        rows.append(
            {
                "ticker": ticker,
                "date": date.fromordinal(int(dates[i])).isoformat(),
                "ordinal": int(dates[i]),
                "price_ratio": float(ratio),
                "share_volume_ratio": _volume_ratio(qty, i),
                "source": str(source[i]),
                "share_factor": float(factor[i]),
                "reason": reason,
            }
        )
    rows.sort(key=lambda row: (str(row["ticker"]), int(row["ordinal"])))
    return rows


def _reason(
    index: int,
    source: str,
    event: OfficialEvent | None,
    late: bool,
    rejected: str | None,
) -> str:
    del index
    parts: list[str] = []
    if source == "bad_print":
        parts.append("bad_print_reversal")
    elif source == "heuristic":
        parts.append("heuristic_price_and_volume")
    elif source in ("b3", "cvm") and event is not None:
        parts.append("official_ex_date")
        if event.kind:
            parts.append(event.kind)
    else:
        parts.append("no_official_event")
    if late:
        parts.append("late_filing_ignored")
    if rejected:
        parts.append(rejected)
    return ":".join(parts)

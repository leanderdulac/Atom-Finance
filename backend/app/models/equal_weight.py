"""Equal-weight B3 portfolio. Research and paper simulation only.

The sleeve is chosen on month-ends through 2018-12-31. The later path is not
used to pick the rule and is not a reason to send an order.
``eligible_for_live_trading`` stays false.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.models.afml.gate import gate
from app.models.afml.trials import TrialRegistry
from app.models.equal_weight_io import CashEvent, Listing
from app.models.net_net import (
    DELIST_STALE_SESSIONS,
    PRICE_STALE_SESSIONS,
    SMALL_CAP_QUANTILE,
    Company,
    FillStats,
    NameRow,
    SharePoint,
    Tape,
    _ibov_stats,
    build_signal_rows,
    execution_book,
    match_share_multiplier,
    monthly_simple_returns,
    performance,
    price_fill,
    rebalance_signals,
    small_cap_names,
    trailing_adv,
)
from app.models.net_net import (
    simulate as vendored_simulate,
)
from app.models.net_net_io import cdi_growth
from app.models.rejected_net_net import rejected_ledger_count
from app.models.trading_costs import cash_delta

FAMILY_ID = "b3_equal_weight"
ELIGIBLE_FOR_LIVE_TRADING = False
PERIODS_PER_YEAR = 12.0
DESIGN_END = date(2018, 12, 31)
EVAL_START = date(2019, 1, 1)
SELECTION_AUM = 1_000_000.0
PUBLISHED_FIRST_SIGNAL = date(2012, 5, 2)
JCP_WITHHOLDING = 0.15
UNKNOWN_WITHHOLDING = 0.15
ADV_WINDOW = 60
ADV_MIN_OBS = 20
LIQUID_MIN_NAMES = 20
SMALL_MIN_NAMES = 15
PARTICIPATION_CAP = 0.10
LONG_HORIZON_TRIALS = 24
AUMS = (100_000.0, 1_000_000.0, 10_000_000.0)

# Locked before any out-of-sample result of this study was read.
# Eight sleeves at the selection wealth, two further wealth levels that are
# counted and cannot be chosen.
_SLEEVES: tuple[tuple[str, float], ...] = (
    ("liquid", 1_000_000.0),
    ("liquid", 5_000_000.0),
    ("small", 50_000.0),
    ("small", 200_000.0),
)
_FREQUENCIES = ("monthly", "quarterly")


@dataclass(frozen=True)
class Target:
    cnpj: str
    ticker: str
    adv_brl: float
    adv_shares: float
    mcap: float | None = None


@dataclass
class Position:
    cnpj: str
    ticker: str
    shares: float
    entry_px: float
    entry_ord: int


@dataclass
class Ledger:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)


def production_grid() -> list[dict[str, Any]]:
    """Every wealth/sleeve pair of the pre-specified total-return rule."""
    rows: list[dict[str, Any]] = []
    for universe, floor in _SLEEVES:
        for frequency in _FREQUENCIES:
            for aum in AUMS:
                rows.append(
                    {
                        "universe": universe,
                        "adv_floor": float(floor),
                        "frequency": frequency,
                        "aum": float(aum),
                        "selection_candidate": float(aum) == SELECTION_AUM,
                    }
                )
    return rows


def signal_ordinals(sessions: Sequence[int], frequency: str) -> list[int]:
    """Last session of each month, or of March, June, September and December."""
    if frequency not in _FREQUENCIES:
        raise ValueError("frequency must be monthly or quarterly")
    last: dict[tuple[int, int], int] = {}
    for ordinal in sessions:
        day = date.fromordinal(int(ordinal))
        if frequency == "quarterly" and day.month not in (3, 6, 9, 12):
            continue
        last[(day.year, day.month)] = int(ordinal)
    return [last[key] for key in sorted(last)]


def shares_asof(points: Sequence[SharePoint], asof: int) -> SharePoint | None:
    """Latest share count whose receipt date is on or before ``asof``."""
    best: SharePoint | None = None
    for point in points:
        if point.received > asof:
            continue
        if best is None or point.period_end > best.period_end or (
            point.period_end == best.period_end and point.received > best.received
        ):
            best = point
    return best


def issuer_mcap(company: Company, asof: int, class_px: dict[str, float]) -> float | None:
    """Price times shares of each class that has both a count and a price.

    A missing class price makes the capitalisation unknown. Using one class
    to price the other class would push dual-class names into the small book.
    """
    point = shares_asof(company.shares, asof)
    if point is None:
        return None
    prices = dict(class_px)
    if point.on_out > 0 and "on" not in prices and "unit" in prices and point.pn_out <= 0:
        prices["on"] = prices["unit"]
    mcap = 0.0
    if point.on_out > 0:
        px = prices.get("on")
        if px is None or px <= 0:
            return None
        mcap += float(px) * float(point.on_out)
    if point.pn_out > 0:
        px = prices.get("pn")
        if px is None or px <= 0:
            return None
        mcap += float(px) * float(point.pn_out)
    if mcap <= 0:
        return None
    return mcap


def _close_on(tape: Tape, ordinal: int, max_stale: int) -> tuple[float | None, int | None, bool]:
    idx = tape.index_on_or_before(ordinal)
    if idx is None:
        return None, None, True
    age = ordinal - int(tape.dates[idx])
    px = float(tape.close[idx])
    if not math.isfinite(px) or px <= 0:
        return None, idx, True
    return px, idx, age > max_stale


def build_signal_book(
    companies: Sequence[Company],
    listings: Sequence[Listing],
    tapes: dict[str, Tape],
    signals: Sequence[int],
    universe: str,
    adv_floor: float,
    *,
    min_names: int | None = None,
    adv_window: int = ADV_WINDOW,
) -> dict[int, list[Target]]:
    """One listing per issuer. Membership uses only information known on the signal date."""
    if universe not in ("liquid", "small"):
        raise ValueError("universe must be liquid or small")
    floor_n = LIQUID_MIN_NAMES if universe == "liquid" else SMALL_MIN_NAMES
    if min_names is not None:
        floor_n = int(min_names)
    by_cnpj = {company.cnpj: company for company in companies}
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for item in listings:
        grouped[item.cnpj].append(item)
    book: dict[int, list[Target]] = {}
    for ordinal in signals:
        rows: list[Target] = []
        for cnpj, group in grouped.items():
            company = by_cnpj.get(cnpj)
            if company is None:
                if universe == "small":
                    continue
            elif universe == "small" and company.financial:
                continue
            class_best: dict[str, tuple[float, float]] = {}
            priced: list[tuple[float, float, Listing, float]] = []
            for item in group:
                if ordinal < item.start or (item.end is not None and ordinal > item.end):
                    continue
                tape = tapes.get(item.ticker)
                if tape is None:
                    continue
                px, idx, stale = _close_on(tape, int(ordinal), PRICE_STALE_SESSIONS)
                if px is None or idx is None or stale or idx < ADV_MIN_OBS:
                    continue
                adv_brl, adv_sh = trailing_adv(tape, idx, adv_window)
                if adv_brl < adv_floor:
                    continue
                priced.append((adv_brl, adv_sh, item, px))
                prev = class_best.get(item.share_class)
                if prev is None or adv_brl > prev[0]:
                    class_best[item.share_class] = (adv_brl, px)
            if not priced:
                continue
            priced.sort(key=lambda item: (-item[0], item[2].ticker))
            adv_brl, adv_sh, best, _px = priced[0]
            class_px = {key: value[1] for key, value in class_best.items()}
            mcap = None if company is None else issuer_mcap(company, int(ordinal), class_px)
            rows.append(Target(cnpj, best.ticker, adv_brl, adv_sh, mcap))
        if universe == "small":
            sized = [row for row in rows if row.mcap is not None and row.mcap > 0]
            if not sized:
                rows = []
            else:
                cut = float(np.quantile(np.array([row.mcap for row in sized], dtype=np.float64), SMALL_CAP_QUANTILE))
                rows = [row for row in sized if row.mcap is not None and row.mcap <= cut]
        if len(rows) < floor_n:
            rows = []
        book[int(ordinal)] = rows
    return book


def _apply_splits(ledger: Ledger, tapes: dict[str, Tape], ordinal: int, enabled: bool) -> None:
    if not enabled:
        return
    for pos in ledger.positions.values():
        tape = tapes.get(pos.ticker)
        if tape is None:
            continue
        idx = tape.index_on_or_before(ordinal)
        if idx is None or int(tape.dates[idx]) != ordinal:
            continue
        factor = float(tape.split[idx])
        if factor > 0 and abs(factor - 1.0) > 1e-8:
            pos.shares *= factor
            pos.entry_px /= factor


def _credit(
    net: Ledger,
    gross: Ledger,
    events: dict[str, tuple[np.ndarray, np.ndarray]] | None,
    prev: int | None,
    ordinal: int,
) -> tuple[float, int]:
    """Cash to holders of the previous close. Buying today does not collect today's distribution."""
    if prev is None or not events:
        return 0.0, 0
    cash = 0.0
    count = 0
    for pos in net.positions.values():
        series = events.get(pos.ticker)
        if series is None or pos.shares <= 0:
            continue
        dates, amounts = series
        lo = int(np.searchsorted(dates, prev, side="right"))
        hi = int(np.searchsorted(dates, ordinal, side="right"))
        if hi <= lo:
            continue
        paid = float(np.sum(amounts[lo:hi])) * pos.shares
        if paid == 0:
            continue
        cash += paid
        count += hi - lo
    net.cash += cash
    gross.cash += cash
    return cash, count


def _execution(tape: Tape, ordinal: int, px: float, idx: int) -> tuple[Any, str]:
    adv_brl, adv_sh = trailing_adv(tape, idx)
    return execution_book(px, float(tape.bid[idx]), float(tape.ask[idx]), adv_brl, adv_sh)


def _drop(net: Ledger, gross: Ledger, ticker: str) -> None:
    net.positions.pop(ticker, None)
    gross.positions.pop(ticker, None)


def _sell(
    net: Ledger,
    gross: Ledger,
    ticker: str,
    tapes: dict[str, Tape],
    ordinal: int,
    stats: FillStats,
    haircut: float,
    qty: float | None = None,
) -> str | None:
    pos = net.positions.get(ticker)
    if pos is None or pos.shares <= 0:
        _drop(net, gross, ticker)
        return None
    tape = tapes.get(ticker)
    if tape is None:
        _drop(net, gross, ticker)
        return "delist"
    px, idx, _stale = _close_on(tape, ordinal, 10**9)
    if px is None or idx is None:
        _drop(net, gross, ticker)
        return "delist"
    age = ordinal - int(tape.dates[idx])
    stale = age > DELIST_STALE_SESSIONS
    sell_qty = pos.shares if qty is None else min(qty, pos.shares)
    if stale and haircut >= 1.0:
        pos.shares -= sell_qty
        gpos = gross.positions.get(ticker)
        if gpos is not None:
            gpos.shares -= sell_qty
            if gpos.shares <= 1e-8:
                gross.positions.pop(ticker, None)
        if pos.shares <= 1e-8:
            net.positions.pop(ticker, None)
        return "worthless"
    if stale and haircut > 0:
        px = px * (1.0 - haircut)
    if px <= 0:
        _drop(net, gross, ticker)
        return "worthless"
    book, source = _execution(tape, ordinal, px, idx)
    fill, capped = price_fill("sell", sell_qty, px, book)
    stats.add(fill, source, capped)
    net.cash += cash_delta(fill)
    pos.shares -= sell_qty
    gpos = gross.positions.get(ticker)
    if gpos is not None:
        gross.cash += sell_qty * px
        gpos.shares -= sell_qty
        if gpos.shares <= 1e-8:
            gross.positions.pop(ticker, None)
    if pos.shares <= 1e-8:
        net.positions.pop(ticker, None)
    return "delist" if stale else "trade"


def _buy_qty(cash: float, qty: float, mid: float, book: Any) -> float:
    if qty <= 0 or cash <= 0:
        return 0.0
    fill, _capped = price_fill("buy", qty, mid, book)
    if -cash_delta(fill) <= cash + 1e-6:
        return qty
    lo, hi = 0.0, qty
    for _ in range(24):
        mid_q = (lo + hi) / 2.0
        if mid_q <= 0:
            break
        trial, _capped = price_fill("buy", mid_q, mid, book)
        if -cash_delta(trial) <= cash:
            lo = mid_q
        else:
            hi = mid_q
    return lo


def _buy(
    net: Ledger,
    gross: Ledger,
    row: Target,
    px: float,
    idx: int,
    qty: float,
    tapes: dict[str, Tape],
    ordinal: int,
    stats: FillStats,
) -> None:
    tape = tapes[row.ticker]
    book, source = _execution(tape, ordinal, px, idx)
    qty = _buy_qty(net.cash, qty, px, book)
    if qty <= 1e-8:
        return
    fill, capped = price_fill("buy", qty, px, book)
    spent = -cash_delta(fill)
    if spent > net.cash + 1e-4:
        return
    stats.add(fill, source, capped)
    net.cash -= spent
    pos = net.positions.get(row.ticker)
    if pos is None:
        net.positions[row.ticker] = Position(row.cnpj, row.ticker, qty, px, ordinal)
    else:
        pos.shares += qty
    gross.cash -= qty * px
    gpos = gross.positions.get(row.ticker)
    if gpos is None:
        gross.positions[row.ticker] = Position(row.cnpj, row.ticker, qty, px, ordinal)
    else:
        gpos.shares += qty


def _rebalance(
    net: Ledger,
    gross: Ledger,
    targets: list[Target],
    tapes: dict[str, Tape],
    ordinal: int,
    stats: FillStats,
    *,
    round_trip: bool,
    haircut: float,
) -> tuple[int, int]:
    priced: list[tuple[Target, float, int]] = []
    seen: set[str] = set()
    for row in targets:
        if row.ticker in seen:
            continue
        tape = tapes.get(row.ticker)
        if tape is None:
            continue
        px, idx, stale = _close_on(tape, ordinal, PRICE_STALE_SESSIONS)
        if px is None or idx is None or stale:
            continue
        seen.add(row.ticker)
        priced.append((row, px, idx))
    keep = {row.ticker for row, _px, _idx in priced}
    stale_sells = 0
    worthless = 0
    if round_trip:
        for ticker in list(net.positions):
            reason = _sell(net, gross, ticker, tapes, ordinal, stats, haircut)
            if reason == "delist":
                stale_sells += 1
            elif reason == "worthless":
                worthless += 1
    else:
        for ticker in list(net.positions):
            if ticker not in keep:
                reason = _sell(net, gross, ticker, tapes, ordinal, stats, haircut)
                if reason == "delist":
                    stale_sells += 1
                elif reason == "worthless":
                    worthless += 1
    if not priced:
        return stale_sells, worthless
    equity = net.cash
    for row, px, _idx in priced:
        pos = net.positions.get(row.ticker)
        if pos is not None:
            equity += pos.shares * px
    target_value = equity / len(priced)
    if round_trip:
        buys = [(row, target_value / px, px, idx) for row, px, idx in priced]
        sells: list[tuple[str, float]] = []
    else:
        sells = []
        buys = []
        for row, px, idx in priced:
            pos = net.positions.get(row.ticker)
            current = 0.0 if pos is None else pos.shares
            delta = target_value / px - current
            if delta < -1e-8 and pos is not None:
                sells.append((row.ticker, -delta))
            elif delta > 1e-8:
                buys.append((row, delta, px, idx))
    for ticker, qty in sells:
        reason = _sell(net, gross, ticker, tapes, ordinal, stats, haircut, qty=qty)
        if reason == "delist":
            stale_sells += 1
        elif reason == "worthless":
            worthless += 1
    for row, qty, px, idx in buys:
        _buy(net, gross, row, px, idx, qty, tapes, ordinal, stats)
    return stale_sells, worthless


def simulate_book(
    sessions: Sequence[int],
    tapes: dict[str, Tape],
    signal_book: dict[int, list[Target]],
    aum: float,
    events: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
    *,
    round_trip: bool = False,
    apply_splits: bool = True,
    haircut: float = 0.0,
    flatten: bool = True,
    exit_when_stale: bool = True,
) -> dict[str, Any]:
    """Paper book. Names that remain are resized, unless ``round_trip`` repeats the old bug.

    A distribution is credited to shares held at the previous close, after the
    same-day split factor and before the rebalance trade. ``haircut`` of 1
    marks a stale exit as worthless. Idle cash earns nothing.
    """
    if aum <= 0:
        raise ValueError("aum must be positive")
    net = Ledger(cash=float(aum))
    gross = Ledger(cash=float(aum))
    stats = FillStats()
    pending: int | None = None
    prev: int | None = None
    dividend_cash = 0.0
    dividend_events = 0
    stale_sells = 0
    worthless = 0
    logs: list[dict[str, Any]] = []
    curve_ord: list[int] = []
    curve_net: list[float] = []
    curve_gross: list[float] = []
    signal_set = set(signal_book)
    ordered = [int(day) for day in sessions]

    def _equity(ledger: Ledger) -> float:
        total = ledger.cash
        for pos in ledger.positions.values():
            tape = tapes.get(pos.ticker)
            if tape is None:
                continue
            px, _idx, _stale = _close_on(tape, ordinal, 10**9)
            if px is not None:
                total += pos.shares * px
        return total

    for ordinal in ordered:
        _apply_splits(net, tapes, ordinal, apply_splits)
        _apply_splits(gross, tapes, ordinal, apply_splits)
        paid, n_paid = _credit(net, gross, events, prev, ordinal)
        dividend_cash += paid
        dividend_events += n_paid
        if exit_when_stale:
            for ticker in list(net.positions):
                tape = tapes.get(ticker)
                dark = tape is None
                if tape is not None:
                    _px, idx, _stale = _close_on(tape, ordinal, 10**9)
                    dark = idx is None or ordinal - int(tape.dates[idx]) > DELIST_STALE_SESSIONS
                if not dark:
                    continue
                reason = _sell(net, gross, ticker, tapes, ordinal, stats, haircut)
                if reason == "delist":
                    stale_sells += 1
                elif reason == "worthless":
                    worthless += 1
        if pending is not None:
            targets = signal_book.get(pending, [])
            stale_n, dead_n = _rebalance(
                net, gross, targets, tapes, ordinal, stats, round_trip=round_trip, haircut=haircut
            )
            stale_sells += stale_n
            worthless += dead_n
            advs = [row.adv_brl for row in targets if row.adv_brl > 0]
            logs.append(
                {
                    "signal": int(pending),
                    "trade": int(ordinal),
                    "n_pass": len(targets),
                    "n_held": len(net.positions),
                    "median_adv": float(np.median(advs)) if advs else 0.0,
                    "min_adv": float(min(advs)) if advs else 0.0,
                }
            )
            pending = None
        if ordinal in signal_set:
            pending = ordinal
        curve_ord.append(ordinal)
        curve_net.append(_equity(net))
        curve_gross.append(_equity(gross))
        prev = ordinal
    if flatten and ordered:
        last = ordered[-1]
        for ticker in list(net.positions):
            reason = _sell(net, gross, ticker, tapes, last, stats, haircut)
            if reason == "delist":
                stale_sells += 1
            elif reason == "worthless":
                worthless += 1
        if curve_net:
            curve_net[-1] = net.cash
            curve_gross[-1] = gross.cash
    return {
        "ords": curve_ord,
        "net": curve_net,
        "gross": curve_gross,
        "logs": logs,
        "stats": stats,
        "dividend_cash": dividend_cash,
        "dividend_events": dividend_events,
        "stale_sells": stale_sells,
        "worthless_exits": worthless,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


_CASH_WITHOUT_PRICE_CAP = 10_000.0


def plausible_cash(
    events: dict[str, list[CashEvent]] | None,
    tapes: dict[str, Tape],
) -> tuple[dict[str, list[CashEvent]], dict[str, Any]]:
    """Drop a per-share amount that exceeds the previous close.

    A holder cannot receive more cash than the share was worth and still keep
    the share. The public chart feed sometimes stores a figure that is not a
    per-share dividend (PDGR3 is hundreds of millions of reais per share).
    When the tape has no prior close, an amount above R$ 10,000 is dropped on
    the same ground. Nothing is put in its place.
    """
    kept: dict[str, list[CashEvent]] = {}
    dropped: list[dict[str, Any]] = []
    for ticker, rows in (events or {}).items():
        tape = tapes.get(ticker)
        accepted: list[CashEvent] = []
        for event in rows:
            prev = _previous_close(tape, int(event.ordinal))
            if prev is not None and float(event.amount) > prev:
                dropped.append(
                    {"ticker": ticker, "ordinal": int(event.ordinal), "amount": float(event.amount), "previous_close": prev}
                )
                continue
            if prev is None and float(event.amount) > _CASH_WITHOUT_PRICE_CAP:
                dropped.append(
                    {"ticker": ticker, "ordinal": int(event.ordinal), "amount": float(event.amount), "previous_close": None}
                )
                continue
            accepted.append(event)
        if accepted:
            kept[ticker] = accepted
    dropped.sort(key=lambda row: row["amount"], reverse=True)
    return kept, {
        "dropped": len(dropped),
        "largest": [
            {
                "ticker": row["ticker"],
                "date": date.fromordinal(int(row["ordinal"])).isoformat(),
                "amount": round(float(row["amount"]), 2),
                "previous_close": None if row["previous_close"] is None else round(float(row["previous_close"]), 4),
            }
            for row in dropped[:8]
        ],
    }


def _previous_close(tape: Tape | None, ordinal: int) -> float | None:
    if tape is None:
        return None
    idx = tape.index_on_or_before(ordinal - 1)
    if idx is None:
        return None
    px = float(tape.close[idx])
    if not math.isfinite(px) or px <= 0:
        return None
    return px


def event_arrays(
    events: dict[str, list[CashEvent]] | None,
    unknown_rate: float,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """After-tax reais per share. Labeled dividends stay exempt. Labeled JCP stays at 15%."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for ticker, rows in (events or {}).items():
        dates: list[int] = []
        amounts: list[float] = []
        for event in rows:
            if event.kind == "dividendo":
                rate = 0.0
            elif event.kind == "jcp":
                rate = JCP_WITHHOLDING
            else:
                rate = unknown_rate
            net = float(event.amount) * (1.0 - rate)
            if net <= 0:
                continue
            dates.append(int(event.ordinal))
            amounts.append(net)
        if dates:
            order = np.argsort(np.asarray(dates, dtype=np.int64), kind="mergesort")
            out[ticker] = (
                np.asarray(dates, dtype=np.int64)[order],
                np.asarray(amounts, dtype=np.float64)[order],
            )
    return out


def one_way_turnover(book: dict[int, list[Target]]) -> float:
    """Mean one-way turnover after the initial build. The first investment from cash is excluded."""
    prev: dict[str, float] | None = None
    turns: list[float] = []
    for ordinal in sorted(book):
        names = [row.ticker for row in book[ordinal]]
        weights = {ticker: 1.0 / len(names) for ticker in names} if names else {}
        if prev is not None:
            keys = set(prev) | set(weights)
            turns.append(0.5 * sum(abs(weights.get(key, 0.0) - prev.get(key, 0.0)) for key in keys))
        prev = weights
    return float(np.mean(turns)) if turns else 0.0


def capacity_of(book: dict[int, list[Target]]) -> dict[str, float]:
    typical: list[float] = []
    thin: list[float] = []
    counts: list[int] = []
    for rows in book.values():
        counts.append(len(rows))
        advs = [row.adv_brl for row in rows if row.adv_brl > 0]
        if not advs:
            continue
        n = len(rows)
        typical.append(PARTICIPATION_CAP * float(np.median(advs)) * n)
        thin.append(PARTICIPATION_CAP * float(min(advs)) * n)
    return {
        "median_names": float(np.median(counts)) if counts else 0.0,
        "fraction_rebalances_in_cash": float(np.mean([count == 0 for count in counts])) if counts else 1.0,
        "capacity_typical_10pct_adv": float(np.median(typical)) if typical else 0.0,
        "capacity_thin_10pct_adv": float(np.median(thin)) if thin else 0.0,
        "n_rebalances": float(len(counts)),
    }


def slice_performance(result: dict[str, Any], which: str, start_ord: int | None, end_ord: int | None) -> dict[str, Any]:
    ords = [int(day) for day in result["ords"]]
    equity = result[which]
    if not ords:
        return performance([], [], [])
    lo = 0 if start_ord is None else int(np.searchsorted(np.asarray(ords), start_ord, side="left"))
    hi = len(ords) if end_ord is None else int(np.searchsorted(np.asarray(ords), end_ord, side="right"))
    if start_ord is not None and lo > 0:
        lo -= 1
    if hi - lo < 2:
        return performance([], [], [])
    _m_ords, monthly = monthly_simple_returns(ords[lo:hi], equity[lo:hi])
    return performance(ords[lo:hi], equity[lo:hi], monthly)


def choose_specification(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest design-window net Sharpe among selection candidates.

    Ties break toward higher design CAGR, lower turnover, monthly, a higher
    liquidity floor, then the liquid universe. Out-of-sample fields are not read.
    """
    usable = [
        row
        for row in rows
        if row.get("selection_candidate")
        and row.get("design_sharpe") is not None
        and int(row.get("n_design") or 0) >= 36
    ]
    if not usable:
        return None

    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        cagr = row.get("design_cagr")
        turnover = row.get("design_turnover")
        return (
            -float(row["design_sharpe"]),
            -(float(cagr) if cagr is not None else -1e9),
            float(turnover) if turnover is not None else 1e9,
            0 if row.get("frequency") == "monthly" else 1,
            -float(row.get("adv_floor") or 0.0),
            0 if row.get("universe") == "liquid" else 1,
        )

    return dict(sorted(usable, key=sort_key)[0])


def _cdi_cagr(ords: np.ndarray, rates: np.ndarray, start_ord: int, end_ord: int) -> float | None:
    if len(ords) == 0 or end_ord <= start_ord:
        return None
    growth = cdi_growth(ords, rates, start_ord, end_ord)
    years = (end_ord - start_ord) / 365.25
    if years <= 0.05 or growth <= 0:
        return None
    return float(growth ** (1.0 / years) - 1.0)


def calendar_table(
    month_ords: Sequence[int],
    month_rets: Sequence[float],
    cdi_ords: np.ndarray,
    cdi_rates: np.ndarray,
    anchor: int | None,
) -> list[dict[str, Any]]:
    """Calendar-year compound of the month-end returns, next to CDI over the same span."""
    if not month_ords:
        return []
    rows: list[dict[str, Any]] = []
    by_year: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    previous = anchor
    for ordinal, ret in zip(month_ords, month_rets, strict=False):
        year = date.fromordinal(int(ordinal)).year
        opened = int(previous) if previous is not None else int(ordinal)
        by_year[year].append((int(ordinal), float(ret), opened))
        previous = int(ordinal)
    for year in sorted(by_year):
        pairs = by_year[year]
        growth = 1.0
        for _ordinal, ret, _opened in pairs:
            growth *= 1.0 + ret
        start = min(item[2] for item in pairs)
        end = pairs[-1][0]
        cdi = _cdi_cagr(cdi_ords, cdi_rates, start, end)
        total = growth - 1.0
        rows.append(
            {
                "year": year,
                "total_return": total,
                "cdi": cdi,
                "excess_over_cdi": None if cdi is None else total - cdi,
                "bad_year": total < 0,
                "n_months": len(pairs),
            }
        )
    return rows


def jump_census(tapes: dict[str, Tape], tickers: Sequence[str]) -> dict[str, Any]:
    """Price gaps of at least 45%. A confirmed split is the share-count factor on the tape."""
    confirmed = 0
    unconfirmed = 0
    round_unconfirmed = 0
    worst: list[tuple[float, str, str, float]] = []
    for ticker in sorted(set(tickers)):
        tape = tapes.get(ticker)
        if tape is None or len(tape.close) < 2:
            continue
        for i in range(1, len(tape.close)):
            prev = float(tape.close[i - 1])
            px = float(tape.close[i])
            if prev <= 0 or px <= 0:
                continue
            ratio = px / prev
            if 1 / 1.45 < ratio < 1.45:
                continue
            if abs(float(tape.split[i]) - 1.0) > 1e-8:
                confirmed += 1
                continue
            unconfirmed += 1
            if match_share_multiplier(ratio) is not None:
                round_unconfirmed += 1
            worst.append((abs(math.log(ratio)), ticker, date.fromordinal(int(tape.dates[i])).isoformat(), ratio))
    worst.sort(reverse=True)
    return {
        "confirmed_split_prints": confirmed,
        "unconfirmed_gaps": unconfirmed,
        "unconfirmed_round_gaps": round_unconfirmed,
        "largest_unconfirmed": [
            {"ticker": ticker, "date": day, "price_ratio": round(ratio, 4)}
            for _score, ticker, day, ratio in worst[:15]
        ],
    }


def trade_census(trades: dict[str, np.ndarray] | None, tapes: dict[str, Tape], tickers: Sequence[str]) -> dict[str, Any]:
    if not trades:
        return {"available": False}
    medians: list[float] = []
    one_trade = 0
    prints = 0
    for ticker in set(tickers):
        series = trades.get(ticker)
        tape = tapes.get(ticker)
        if series is None or tape is None or len(series) == 0:
            continue
        medians.append(float(np.median(series)))
        one_trade += int(np.sum(series <= 1.0))
        prints += int(len(series))
    return {
        "available": True,
        "n_names": len(medians),
        "median_of_median_trades": float(np.median(medians)) if medians else None,
        "fraction_prints_at_most_one_trade": (one_trade / prints) if prints else None,
    }


def _round(value: Any, ndigits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, ndigits)
    return value


def _judge(returns: Sequence[float], n_trials: float) -> dict[str, Any] | None:
    if len(returns) < 3 or n_trials < 2:
        return None
    judged = gate(
        costs_included=True,
        returns=list(returns),
        n_trials=float(n_trials),
        periods_per_year=PERIODS_PER_YEAR,
        n_eff=None,
    )
    min_trl = judged.min_trl
    infinite = min_trl is not None and not math.isfinite(min_trl)
    return {
        "psr": judged.psr,
        "dsr": judged.dsr,
        "sr_star": judged.sr_star,
        "min_trl_months": None if min_trl is None or infinite else min_trl,
        "min_trl_infinite": infinite,
        "n_obs_months": judged.n_obs,
        "n_trials": n_trials,
        "sharpe": judged.observed_sharpe,
        "approved_for_paper_dsr": bool(judged.approved),
    }


def _fill_public(stats: FillStats) -> dict[str, Any]:
    return {
        "n": stats.n,
        "n_book": stats.n_book,
        "n_estimate": stats.n_estimate,
        "n_capped": stats.n_capped,
        "fee": round(stats.fee, 2),
        "half_spread": round(stats.half_spread, 2),
        "slippage": round(stats.slippage, 2),
        "mean_half_spread_bps": round(stats.half_spread_bps_sum / stats.n, 4) if stats.n else None,
    }


def _targets_from_rows(rows: Sequence[NameRow]) -> list[Target]:
    return [Target(row.cnpj, row.ticker, row.adv_brl, row.adv_shares, row.mcap) for row in rows]


def published_small_audit(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    taxed_events: dict[str, tuple[np.ndarray, np.ndarray]],
    trades: dict[str, np.ndarray] | None,
) -> dict[str, Any]:
    """Replay the published small-cap equal-weight path and the artifact variants.

    The base path is the vendored simulator: bottom 30% by market cap of the
    fundamental universe, phase-0 calendar, price return, resize, R$ 1 million.
    It is an audit. It is not a sleeve the design window can choose.
    """
    if len(sessions) < 30:
        return {"available": False, "reason": "session calendar is too short", "eligible_for_live_trading": False}
    first = max(PUBLISHED_FIRST_SIGNAL.toordinal(), int(sessions[0]))
    last = int(sessions[-1]) - 10
    signals = rebalance_signals(sessions, 0, first, last)
    table = build_signal_rows(companies, tapes, signals, 0)
    selected = {int(ordinal): small_cap_names(rows) for ordinal, rows in table.items()}
    book = {ordinal: _targets_from_rows(rows) for ordinal, rows in selected.items()}
    names = [row.ticker for rows in selected.values() for row in rows]
    advs = [row.adv_brl for rows in selected.values() for row in rows if row.adv_brl > 0]

    def _selector(_sig: int, rows: list[NameRow], _pos: dict[str, Any]) -> list[NameRow]:
        return small_cap_names(rows)

    exact = vendored_simulate(sessions, tapes, table, _selector, SELECTION_AUM, False)
    exact_net_ords, exact_monthly = monthly_simple_returns(exact["ords"], exact["net"])
    _exact_gross_ords, exact_gross = monthly_simple_returns(exact["ords"], exact["gross"])
    base = simulate_book(sessions, tapes, book, SELECTION_AUM, None, exit_when_stale=False)
    bug = simulate_book(sessions, tapes, book, SELECTION_AUM, None, round_trip=True, exit_when_stale=False)
    no_split = simulate_book(sessions, tapes, book, SELECTION_AUM, None, apply_splits=False, exit_when_stale=False)
    with_div = simulate_book(sessions, tapes, book, SELECTION_AUM, taxed_events, exit_when_stale=False)
    dead = simulate_book(sessions, tapes, book, SELECTION_AUM, None, haircut=1.0, exit_when_stale=False)

    def pack(run: dict[str, Any]) -> dict[str, Any]:
        _o, monthly = monthly_simple_returns(run["ords"], run["net"])
        _g, monthly_g = monthly_simple_returns(run["ords"], run["gross"])
        net = performance(run["ords"], run["net"], monthly)
        gross = performance(run["ords"], run["gross"], monthly_g)
        stats: FillStats = run["stats"]
        return {
            "cagr_net": _round(net.get("cagr")),
            "cagr_gross": _round(gross.get("cagr")),
            "sharpe_net": _round(net.get("sharpe")),
            "max_drawdown_net": _round(net.get("max_drawdown")),
            "max_drawdown_gross": _round(gross.get("max_drawdown")),
            "stale_sells": run.get("stale_sells"),
            "worthless_exits": run.get("worthless_exits"),
            "dividend_cash": _round(run.get("dividend_cash"), 2),
            "fills": _fill_public(stats),
            "monthly_net": [round(float(value), 8) for value in monthly],
        }

    exact_net = performance(exact["ords"], exact["net"], exact_monthly)
    exact_gross_perf = performance(exact["ords"], exact["gross"], exact_gross)
    stats = exact["stats"]
    n_slots = sum(len(rows) for rows in selected.values())
    return {
        "available": True,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "definition": (
            "Non-financial issuers with a point-in-time balance sheet, one ordinary listing, "
            "the most liquid line, bottom 30% by market capitalisation, phase-0 calendar "
            "(first session of every fourth month) from 2012-05-02, price return, "
            "R$ 1 million, resize rather than a round trip. This is the published path."
        ),
        "n_signals": len(signals),
        "median_universe": float(np.median([len(rows) for rows in table.values()])) if table else 0.0,
        "median_small_names": float(np.median([len(rows) for rows in selected.values()])) if selected else 0.0,
        "adv_brl": {
            "median": float(np.median(advs)) if advs else None,
            "p10": float(np.quantile(advs, 0.10)) if advs else None,
            "fraction_below_10k": float(np.mean(np.asarray(advs) < 10_000.0)) if advs else None,
            "fraction_below_100k": float(np.mean(np.asarray(advs) < 100_000.0)) if advs else None,
            "n_name_slots": n_slots,
        },
        "vendored_resize_price": {
            "cagr_net": _round(exact_net.get("cagr")),
            "cagr_gross": _round(exact_gross_perf.get("cagr")),
            "sharpe_net": _round(exact_net.get("sharpe")),
            "max_drawdown_net": _round(exact_net.get("max_drawdown")),
            "max_drawdown_gross": _round(exact_gross_perf.get("max_drawdown")),
            "delist_exits_counter": exact["delist_exits"],
            "fills": _fill_public(stats),
            "monthly_net_n": len(exact_net_ords),
            "monthly_net": [round(float(value), 8) for value in exact_monthly],
        },
        "resize_price": pack(base),
        "round_trip_bug": pack(bug),
        "no_split": pack(no_split),
        "with_taxed_distributions": pack(with_div),
        "worthless_stale_exit": pack(dead),
        "jumps": jump_census(tapes, names),
        "trades": trade_census(trades, tapes, names),
        "held_names": len(set(names)),
    }


def dividend_coverage(
    listings: Sequence[Listing],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    events: dict[str, list[CashEvent]] | None,
) -> dict[str, Any]:
    """How much of the listing set has a cash-distribution record, split by names that stopped trading."""
    if not sessions:
        return {"listings": 0}
    last = int(sessions[-1])
    tickers = {item.ticker for item in listings}
    ended = {item.ticker for item in listings if item.end is not None and item.end < last}
    dark: set[str] = set()
    for ticker in tickers:
        tape = tapes.get(ticker)
        if tape is None or len(tape.dates) == 0:
            dark.add(ticker)
            continue
        if int(tape.dates[-1]) < last - 40:
            dark.add(ticker)
    stopped = ended | dark
    covered = {ticker for ticker, rows in (events or {}).items() if rows}
    kinds: dict[str, int] = defaultdict(int)
    for rows in (events or {}).values():
        for event in rows:
            kinds[event.kind] += 1
    stopped_n = len(stopped & tickers)
    return {
        "listings": len(tickers),
        "with_any_cash_event": len(covered & tickers),
        "fraction_with_any_cash_event": (len(covered & tickers) / len(tickers)) if tickers else None,
        "stopped_trading": stopped_n,
        "stopped_with_any_cash_event": len(stopped & covered),
        "stopped_without_cash_event": len((stopped & tickers) - covered),
        "events_by_kind": dict(kinds),
        "source": (
            "Yahoo Finance chart events, grossed up by splits that the same feed reports after the ex-date. "
            "The feed does not label interest on equity separately from dividends, so those rows are kind=unknown."
        ),
        "gap": (
            "A name that stopped trading and has no event understates the total return if it paid cash "
            "before it left. No cash is invented for that gap. The price-only rows are the lower bound "
            "that ignores every distribution."
        ),
    }


def _per_year(frequency: str) -> float:
    return 12.0 if frequency == "monthly" else 4.0


def run_study(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    events: dict[str, list[CashEvent]] | None,
    ibov_ords: np.ndarray,
    ibov_close: np.ndarray,
    cdi_ords: np.ndarray,
    cdi_rates: np.ndarray,
    registry_path: str,
    listings: Sequence[Listing],
    *,
    published_tapes: dict[str, Tape] | None = None,
    trades: dict[str, np.ndarray] | None = None,
    min_names: int | None = None,
    audit_sessions: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Run the locked grid, register every variation, then score the held-out window.

    Out-of-sample returns are not an input to ``choose_specification``.
    """
    if len(sessions) < 30:
        raise ValueError("need a session calendar")
    design_end = DESIGN_END.toordinal()
    eval_start = EVAL_START.toordinal()
    events, cash_filter = plausible_cash(events, tapes)
    taxed = event_arrays(events, UNKNOWN_WITHHOLDING)
    exempt = event_arrays(events, 0.0)
    books: dict[tuple[str, float, str], dict[int, list[Target]]] = {}
    for universe, floor in _SLEEVES:
        for frequency in _FREQUENCIES:
            signals = signal_ordinals(sessions, frequency)
            books[(universe, float(floor), frequency)] = build_signal_book(
                companies, listings, tapes, signals, universe, float(floor), min_names=min_names
            )

    jobs: list[dict[str, Any]] = []
    for spec in production_grid():
        jobs.append(
            {
                **spec,
                "role": "grid",
            "events": taxed,
            "round_trip": False,
            "apply_splits": True,
            "haircut": 0.0,
            "exit_when_stale": True,
            "book_key": (spec["universe"], float(spec["adv_floor"]), spec["frequency"]),
        }
    )
    for universe, floor in _SLEEVES:
        for frequency in _FREQUENCIES:
            base = {
                "universe": universe,
                "adv_floor": float(floor),
                "frequency": frequency,
                "aum": SELECTION_AUM,
                "selection_candidate": False,
                "book_key": (universe, float(floor), frequency),
                "round_trip": False,
                "apply_splits": True,
                "exit_when_stale": True,
            }
            jobs.append({**base, "role": "price_only", "events": None, "haircut": 0.0})
            jobs.append({**base, "role": "tax_exempt_unknown", "events": exempt, "haircut": 0.0})
            jobs.append({**base, "role": "delist_worthless", "events": taxed, "haircut": 1.0})

    on_listings = [
        Listing(company.cnpj, ticker, start, end, "on")
        for company in companies
        for ticker, start, end in company.tickers
    ]
    on_signals = signal_ordinals(sessions, "monthly")
    on_book = build_signal_book(
        companies,
        on_listings,
        tapes,
        on_signals,
        "liquid",
        1_000_000.0,
        min_names=1,
        adv_window=ADV_WINDOW,
    )
    jobs.append(
        {
            "role": "liquid_on_price",
            "universe": "liquid_on",
            "adv_floor": 1_000_000.0,
            "frequency": "monthly",
            "aum": SELECTION_AUM,
            "selection_candidate": False,
            "events": None,
            "round_trip": False,
            "apply_splits": True,
            "haircut": 0.0,
            "exit_when_stale": True,
            "book": on_book,
        }
    )

    audit = published_small_audit(
        companies,
        published_tapes or tapes,
        audit_sessions or sessions,
        taxed,
        trades,
    )
    audit_series: list[tuple[str, list[float]]] = []
    if audit.get("available"):
        audit_series = [
            ("published_small_vendored_price", list(audit["vendored_resize_price"]["monthly_net"])),
            ("published_small_resize_price", list(audit["resize_price"]["monthly_net"])),
            ("published_small_round_trip", list(audit["round_trip_bug"]["monthly_net"])),
            ("published_small_no_split", list(audit["no_split"]["monthly_net"])),
            ("published_small_taxed_distributions", list(audit["with_taxed_distributions"]["monthly_net"])),
            ("published_small_worthless_exit", list(audit["worthless_stale_exit"]["monthly_net"])),
        ]

    results: list[dict[str, Any]] = []
    with TrialRegistry(registry_path) as registry:
        for job in jobs:
            book = job["book"] if "book" in job else books[job["book_key"]]
            run = simulate_book(
                sessions,
                tapes,
                book,
                float(job["aum"]),
                job["events"],
                round_trip=bool(job["round_trip"]),
                apply_splits=bool(job["apply_splits"]),
                haircut=float(job["haircut"]),
                exit_when_stale=bool(job.get("exit_when_stale", True)),
            )
            m_ords, monthly = monthly_simple_returns(run["ords"], run["net"])
            params = {
                "family": FAMILY_ID,
                "role": job["role"],
                "universe": job["universe"],
                "adv_floor": job["adv_floor"],
                "frequency": job["frequency"],
                "aum_brl": job["aum"],
                "unknown_withholding": None
                if job["events"] is None
                else (0.0 if job["role"] == "tax_exempt_unknown" else UNKNOWN_WITHHOLDING),
                "round_trip": job["round_trip"],
                "apply_splits": job["apply_splits"],
                "delist_haircut": job["haircut"],
                "oos_split": "design_through_2018-12-31_eval_from_2019-01-01",
            }
            if len(monthly) >= 3:
                registry.register(
                    FAMILY_ID,
                    params,
                    returns=monthly,
                    costs_included=True,
                    periods_per_year=PERIODS_PER_YEAR,
                    notes=str(job["role"]),
                    status="audit" if job["role"] != "grid" else "grid",
                )
            results.append({"job": job, "run": run, "book": book, "monthly_ords": m_ords, "monthly": monthly, "params": params})
        for role, monthly in audit_series:
            if len(monthly) < 3:
                continue
            registry.register(
                FAMILY_ID,
                {
                    "family": FAMILY_ID,
                    "role": role,
                    "universe": "published_small",
                    "adv_floor": 0.0,
                    "frequency": "phase0",
                    "aum_brl": SELECTION_AUM,
                    "selection_candidate": False,
                    "oos_split": "not_a_selection_sleeve",
                },
                returns=monthly,
                costs_included=True,
                periods_per_year=PERIODS_PER_YEAR,
                notes=role,
                status="audit",
            )
        n_family = registry.count(FAMILY_ID)
        try:
            eff = registry.effective_n_trials(FAMILY_ID)
        except ValueError:
            eff = {"n_eff": None, "mean_corr": None, "n": 0}

    n_rejected = rejected_ledger_count()
    n_decision = float(n_family + n_rejected)
    n_with_factors = n_decision + LONG_HORIZON_TRIALS
    per_cache: dict[tuple[Any, ...], float] = {}
    public: list[dict[str, Any]] = []
    for item in results:
        job = item["job"]
        run = item["run"]
        book = item["book"]
        _g_ords, monthly_g = monthly_simple_returns(run["ords"], run["gross"])
        full_net = performance(run["ords"], run["net"], item["monthly"])
        full_gross = performance(run["ords"], run["gross"], monthly_g)
        design = slice_performance(run, "net", None, design_end)
        oos_net = slice_performance(run, "net", eval_start, None)
        oos_gross = slice_performance(run, "gross", eval_start, None)
        design_rets = [ret for ordinal, ret in zip(item["monthly_ords"], item["monthly"], strict=False) if int(ordinal) <= design_end]
        oos_rets = [ret for ordinal, ret in zip(item["monthly_ords"], item["monthly"], strict=False) if int(ordinal) >= eval_start]
        key = (job["universe"], job["adv_floor"], job["frequency"], job["role"])
        if key not in per_cache:
            design_book = {int(ordinal): rows for ordinal, rows in book.items() if int(ordinal) <= design_end}
            per_cache[key] = one_way_turnover(design_book) * _per_year(job["frequency"])
        turnover = one_way_turnover(book) * _per_year(job["frequency"])
        cap = capacity_of(book)
        judged = _judge(item["monthly"], n_decision)
        oos_judged = _judge(oos_rets, n_decision)
        oos_factors = _judge(oos_rets, n_with_factors)
        base_marks = [int(day) for day in run["ords"] if int(day) <= design_end]
        cdi_start = base_marks[-1] if base_marks else int(run["ords"][0])
        cdi_end = int(run["ords"][-1]) if run["ords"] else cdi_start
        oos_cdi = _cdi_cagr(cdi_ords, cdi_rates, cdi_start, cdi_end)
        oos_cagr = oos_net.get("cagr")
        excess = None if oos_cagr is None or oos_cdi is None else float(oos_cagr) - float(oos_cdi)
        stats: FillStats = run["stats"]
        public.append(
            {
                "role": job["role"],
                "universe": job["universe"],
                "adv_floor": job["adv_floor"],
                "frequency": job["frequency"],
                "aum_brl": job["aum"],
                "selection_candidate": bool(job["selection_candidate"]),
                "cagr_gross": _round(full_gross.get("cagr")),
                "cagr_net": _round(full_net.get("cagr")),
                "sharpe_net": _round(full_net.get("sharpe")),
                "max_drawdown_gross": _round(full_gross.get("max_drawdown")),
                "max_drawdown_net": _round(full_net.get("max_drawdown")),
                "design_sharpe": _round(design.get("sharpe")),
                "design_cagr": _round(design.get("cagr")),
                "design_max_drawdown": _round(design.get("max_drawdown")),
                "n_design": len(design_rets),
                "design_turnover": _round(per_cache[key], 4),
                "turnover_one_way_annual": _round(turnover, 4),
                "oos_cagr_gross": _round(oos_gross.get("cagr")),
                "oos_cagr_net": _round(oos_cagr),
                "oos_sharpe": _round(oos_net.get("sharpe")),
                "oos_max_drawdown_net": _round(oos_net.get("max_drawdown")),
                "oos_cagr_cdi": _round(oos_cdi),
                "oos_excess_cagr_over_cdi": _round(excess),
                "oos_n_months": len(oos_rets),
                "psr": None if judged is None else _round(judged["psr"]),
                "dsr": None if judged is None else _round(judged["dsr"]),
                "min_trl_months": None if judged is None else _round(judged["min_trl_months"], 2),
                "min_trl_infinite": bool(judged and judged["min_trl_infinite"]),
                "oos_psr": None if oos_judged is None else _round(oos_judged["psr"]),
                "oos_dsr": None if oos_judged is None else _round(oos_judged["dsr"]),
                "oos_min_trl_months": None if oos_judged is None else _round(oos_judged["min_trl_months"], 2),
                "oos_min_trl_infinite": bool(oos_judged and oos_judged["min_trl_infinite"]),
                "oos_dsr_with_factor_trials": None if oos_factors is None else _round(oos_factors["dsr"]),
                "oos_psr_with_factor_trials": None if oos_factors is None else _round(oos_factors["psr"]),
                "oos_min_trl_with_factor_trials": None if oos_factors is None else _round(oos_factors["min_trl_months"], 2),
                "oos_min_trl_with_factor_trials_infinite": bool(oos_factors and oos_factors["min_trl_infinite"]),
                "capacity_typical_10pct_adv": _round(cap["capacity_typical_10pct_adv"], 2),
                "capacity_thin_10pct_adv": _round(cap["capacity_thin_10pct_adv"], 2),
                "median_names": cap["median_names"],
                "fraction_rebalances_in_cash": _round(cap["fraction_rebalances_in_cash"], 4),
                "fills": _fill_public(stats),
                "dividend_cash": _round(run["dividend_cash"], 2),
                "dividend_events": run["dividend_events"],
                "stale_sells": run["stale_sells"],
                "worthless_exits": run["worthless_exits"],
                "month_ends": [date.fromordinal(int(day)).isoformat() for day in item["monthly_ords"]],
                "monthly_net": [round(float(value), 8) for value in item["monthly"]],
                "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
            }
        )

    chosen = choose_specification(public)
    chosen_row = None
    if chosen is not None:
        for row in public:
            if (
                row["selection_candidate"]
                and row["universe"] == chosen["universe"]
                and row["frequency"] == chosen["frequency"]
                and row["adv_floor"] == chosen["adv_floor"]
                and row["aum_brl"] == SELECTION_AUM
            ):
                chosen_row = row
                break
    criterion = False
    if chosen_row is not None:
        dsr = chosen_row.get("oos_dsr")
        excess = chosen_row.get("oos_excess_cagr_over_cdi")
        criterion = bool(dsr is not None and dsr >= 0.95 and excess is not None and excess > 0)
    anchor = int(sessions[0])
    annual: list[dict[str, Any]] = []
    if chosen_row is not None:
        match = [
            item
            for item in results
            if item["job"]["role"] == "grid"
            and item["job"]["universe"] == chosen_row["universe"]
            and item["job"]["frequency"] == chosen_row["frequency"]
            and item["job"]["adv_floor"] == chosen_row["adv_floor"]
            and item["job"]["aum"] == SELECTION_AUM
        ]
        if match:
            annual = calendar_table(match[0]["monthly_ords"], match[0]["monthly"], cdi_ords, cdi_rates, anchor)
    wealth_rows = []
    if chosen_row is not None:
        wealth_rows = [
            row
            for row in public
            if row["role"] == "grid"
            and row["universe"] == chosen_row["universe"]
            and row["frequency"] == chosen_row["frequency"]
            and row["adv_floor"] == chosen_row["adv_floor"]
        ]
    cdi_full = _cdi_cagr(cdi_ords, cdi_rates, int(sessions[0]), int(sessions[-1]))
    ibov = _ibov_stats(ibov_ords, ibov_close, sessions)
    oos_sessions = [int(day) for day in sessions if int(day) >= eval_start]
    ibov_oos = _ibov_stats(ibov_ords, ibov_close, oos_sessions) if oos_sessions else {"available": False}
    return {
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "verdict": "aprovado" if criterion else "reprovado",
        "n_trials": n_family,
        "n_rejected_net_net": n_rejected,
        "n_trials_decision": n_decision,
        "n_long_horizon_factor_trials": LONG_HORIZON_TRIALS,
        "n_trials_with_factor_trials": n_with_factors,
        "n_eff": None if eff.get("n_eff") is None else round(float(eff["n_eff"]), 4),
        "mean_pairwise_corr": None if eff.get("mean_corr") is None else round(float(eff["mean_corr"]), 4),
        "dsr_n": "family_plus_rejected_net_net",
        "dsr_n_transparency": "family_plus_rejected_net_net_plus_24_long_horizon_factor_trials",
        "periods_per_year": PERIODS_PER_YEAR,
        "sample": {
            "first_session": date.fromordinal(int(sessions[0])).isoformat(),
            "last_session": date.fromordinal(int(sessions[-1])).isoformat(),
            "n_sessions": len(sessions),
            "n_listings": len({item.ticker for item in listings}),
            "n_tapes": len(tapes),
        },
        "method": {
            "portfolio": "equal weight of one listing per issuer, the listing with the highest trailing ADV",
            "universes": "liquid: every issuer above the ADV floor; small: bottom 30% by point-in-time market cap, financials excluded, after the ADV floor",
            "liquidity": f"{ADV_WINDOW}-session median BRL volume, at least {ADV_MIN_OBS} prints, a print within {PRICE_STALE_SESSIONS} sessions",
            "min_names": {
                "liquid": LIQUID_MIN_NAMES if min_names is None else min_names,
                "small": SMALL_MIN_NAMES if min_names is None else min_names,
            },
            "rebalance": "signal at the month-end or quarter-end close, fill at the next session",
            "costs": "B3 taker fee, half-spread and participation slippage from trading_costs.quote_fill, cap 5000 bps",
            "cash": "idle cash earns 0; CDI is a benchmark, not a credit inside the book",
            "dividends": (
                "Cash credited to shares held at the previous close. Labeled dividends are untaxed. "
                "Labeled interest on equity is withheld at 15%. Unlabeled events, which are the public chart feed, "
                "are withheld at 15% on the selection path. A registered sensitivity withholds nothing on unlabeled events. "
                "An amount larger than the previous close is dropped. The feed is not a per-share dividend at that size."
            ),
            "splits": "A round gap of at least 45% changes the share count only when a later capital filing confirms the inverse change",
            "delist": "A name with no print for 10 sessions is sold at the last trade on the base path. A registered sensitivity marks that exit worthless",
            "survivorship": (
                "The cadastral form names a ticker only from the 2018 vintage onward, and that row can carry an earlier start date. "
                "Every standard-lot COTAHIST name missing from the form is still listed, from its first print to its last. "
                "A 4-letter root already tied to a company keeps that company. A root with no filing has no share count, so it can enter the liquid book and cannot enter the small-cap book. "
                "No cash distribution is invented when the chart feed has no event for a name that stopped trading."
            ),
        },
        "dividend_coverage": {**dividend_coverage(listings, tapes, sessions, events), "implausible": cash_filter},
        "oos_split": {
            "design_end": DESIGN_END.isoformat(),
            "eval_start": EVAL_START.isoformat(),
            "selection_aum_brl": SELECTION_AUM,
            "rule": (
                "Among the eight sleeves at R$ 1 million (liquid or small, two ADV floors, "
                "monthly or quarterly), choose the highest net Sharpe on month-ends through "
                "2018-12-31, with at least 36 months. Ties break to higher design CAGR, lower "
                "turnover, monthly, a higher ADV floor, then liquid. Wealth variants and audit "
                "variants are registered and counted in N, and cannot be chosen. The path is "
                "not flattened at the split."
            ),
            "selected": None
            if chosen_row is None
            else {
                "universe": chosen_row["universe"],
                "adv_floor": chosen_row["adv_floor"],
                "frequency": chosen_row["frequency"],
                "aum_brl": chosen_row["aum_brl"],
                "design_sharpe": chosen_row["design_sharpe"],
                "design_cagr": chosen_row["design_cagr"],
                "n_design": chosen_row["n_design"],
            },
            "criterion": "DSR >= 0.95 on the out-of-sample net monthly returns, N = this family plus the 32 rejected net-net trials, AND out-of-sample net CAGR minus CDI CAGR > 0",
            "criterion_met": criterion,
            "verdict": "aprovado" if criterion else "reprovado",
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        },
        "chosen_annual": [
            {
                **row,
                "total_return": _round(row["total_return"]),
                "cdi": _round(row["cdi"]),
                "excess_over_cdi": _round(row["excess_over_cdi"]),
            }
            for row in annual
        ],
        "chosen_wealth": wealth_rows,
        "trials": public,
        "published_small_cap_audit": audit,
        "benchmark_ibov": ibov,
        "benchmark_ibov_oos": ibov_oos,
        "benchmark_cdi": {
            "series": "BCB SGS 12",
            "unit": "daily percent converted to a decimal, compounded on (start, end]",
            "cagr_full_sample": _round(cdi_full),
            "note": "CDI is the opportunity cost. The book does not earn it on idle cash.",
        },
    }


def _pct(value: Any, digits: int = 1) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    text = f"{number * 100:.{digits}f}"
    return text.replace(".", ",") + "%"


def _num(value: Any, digits: int = 2) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:.{digits}f}".replace(".", ",")


def _brl(value: Any) -> str:
    if value is None:
        return "—"
    number = float(value)
    if abs(number) >= 1_000_000:
        return "R$ " + _num(number / 1_000_000, 1) + " mi"
    if abs(number) >= 1_000:
        return "R$ " + _num(number / 1_000, 0) + " mil"
    return "R$ " + _num(number, 0)


def render_report(report: dict[str, Any]) -> str:
    """Portuguese write-up of a ``run_study`` payload. Numbers come from the payload."""
    split = report["oos_split"]
    selected = split.get("selected") or {}
    verdict = report["verdict"]
    chosen = None
    for row in report["trials"]:
        if (
            selected
            and row["selection_candidate"]
            and row["universe"] == selected.get("universe")
            and row["frequency"] == selected.get("frequency")
            and row["adv_floor"] == selected.get("adv_floor")
        ):
            chosen = row
            break
    lines: list[str] = []
    lines.append("# Carteira de peso igual na B3 (paper)")
    lines.append("")
    lines.append("Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`.")
    lines.append("")
    lines.append(
        "Pergunta: uma carteira de peso igual, com o universo, o piso de liquidez e o calendário "
        "escolhidos só na janela de desenho, sobrevive a custo, a provento com a regra fiscal travada, "
        "ao deflacionamento por todas as variações e a um excesso líquido sobre o CDI fora da amostra?"
    )
    lines.append("")
    if chosen is None:
        lines.append(f"Resposta deste estudo: **{verdict}**. Nenhuma manga teve 36 meses de desenho.")
    else:
        lines.append(
            f"Resposta deste estudo: **{verdict}**. A manga escolhida na janela de desenho foi "
            f"`{chosen['universe']}` com piso de ADV de {_brl(chosen['adv_floor'])}, rebalanceamento "
            f"{chosen['frequency']}, patrimônio de R$ 1 milhão. Fora da amostra o DSR é "
            f"{_num(chosen.get('oos_dsr'), 2)} (o corte é 0,95, com N = {_num(report['n_trials_decision'], 0)}) "
            f"e o excesso de CAGR líquido sobre o CDI é {_pct(chosen.get('oos_excess_cagr_over_cdi'))}."
        )
    lines.append("")
    lines.append("O critério é DSR ≥ 0,95 e excesso líquido sobre o CDI > 0 no período fora da amostra. Passar ainda seria paper. Não autoriza capital.")
    lines.append("")
    lines.append("## Regra, fixada antes de ler o resultado fora da amostra")
    lines.append("")
    lines.append(split["rule"])
    lines.append("")
    lines.append("| Universo | Piso de ADV | O que entra |")
    lines.append("|---|---:|---|")
    lines.append("| `liquid` | R$ 1 milhão e R$ 5 milhões | todo emissor acima do piso, inclusive financeiro |")
    lines.append("| `small` | R$ 50 mil e R$ 200 mil | 30% menor por valor de mercado point-in-time, financeiro de fora |")
    lines.append("")
    lines.append(
        "Um papel por emissor, o de maior ADV. Classes ordinária, preferencial e unit. "
        "Sinal no fechamento do fim do mês, ou do fim do trimestre. Fill no pregão seguinte. "
        "Caixa parado rende zero. Menos de 20 nomes no líquido, ou menos de 15 no small, e o livro fica em caixa."
    )
    lines.append("")
    lines.append("## Proventos, desdobramento e quem saiu da bolsa")
    lines.append("")
    lines.append(
        "O caixa do provento entra para quem tinha o papel no fechamento anterior. Dividendo com rótulo não paga imposto. "
        "JCP com rótulo retém 15%. O feed público não separa os dois, então o evento sem rótulo retém 15% na manga escolhida. "
        "Uma sensibilidade registrada não retém nada no evento sem rótulo. Valor por ação maior que o fechamento anterior é descartado."
    )
    lines.append("")
    lines.append(
        "Salto de preço de pelo menos 45% com razão redonda só muda a quantidade quando um protocolo de capital posterior confirma a variação inversa das ações."
    )
    lines.append("")
    lines.append(
        "Papel sem negócio por 10 pregões é vendido no último preço no caminho base. Uma sensibilidade registrada marca essa saída como perda total."
    )
    lines.append("")
    lines.append(
        "O formulário cadastral só traz o ticker a partir da safra de 2018, e a linha pode ter início anterior. "
        "Todo lote padrão do COTAHIST que o formulário não nomeia continua no universo, do primeiro ao último negócio. "
        "Raiz de 4 letras já ligada a uma companhia herda essa companhia. Raiz sem protocolo não tem quantidade de ações: entra no líquido e não entra no small. "
        "Não se inventa provento para quem parou de negociar e não tem evento."
    )
    lines.append("")
    cover = report["dividend_coverage"]
    lines.append(
        f"Cobertura de proventos: {cover.get('with_any_cash_event')} de {cover.get('listings')} papéis "
        f"têm ao menos um evento ({_pct(cover.get('fraction_with_any_cash_event'))}). "
        f"Papéis que pararam de negociar: {cover.get('stopped_trading')}, dos quais "
        f"{cover.get('stopped_without_cash_event')} não têm evento. {cover.get('gap')}"
    )
    implausible = cover.get("implausible") or {}
    if implausible.get("dropped"):
        lines.append("")
        lines.append(
            f"Eventos descartados porque o valor por ação superava o fechamento anterior, "
            f"ou R$ 10 mil quando não havia fechamento: {implausible.get('dropped')}."
        )
        for item in implausible.get("largest") or []:
            lines.append(
                f"- {item['ticker']} em {item['date']}: {_brl(item['amount'])} contra fechamento {_num(item['previous_close'], 2)}"
            )
    lines.append("")
    lines.append(str(cover.get("source")))
    lines.append("")
    lines.append("## Resultado a R$ 1 milhão, regra de seleção")
    lines.append("")
    lines.append("| Universo | Piso | Calendário | CAGR bruto | CAGR líq. | Sharpe | Max DD | Desenho Sharpe | OOS CAGR líq. | OOS DSR | OOS − CDI | Giro | Cap. tênue |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report["trials"]:
        if row["role"] != "grid" or row["aum_brl"] != SELECTION_AUM:
            continue
        lines.append(
            "| {universe} | {floor} | {freq} | {gross} | {net} | {sharpe} | {dd} | {dsharpe} | {oos} | {dsr} | {excess} | {turn} | {thin} |".format(
                universe=row["universe"],
                floor=_brl(row["adv_floor"]),
                freq=row["frequency"],
                gross=_pct(row["cagr_gross"]),
                net=_pct(row["cagr_net"]),
                sharpe=_num(row["sharpe_net"], 2),
                dd=_pct(row["max_drawdown_net"]),
                dsharpe=_num(row["design_sharpe"], 2),
                oos=_pct(row["oos_cagr_net"]),
                dsr=_num(row["oos_dsr"], 2),
                excess=_pct(row["oos_excess_cagr_over_cdi"]),
                turn=_num(row["turnover_one_way_annual"], 2),
                thin=_brl(row["capacity_thin_10pct_adv"]),
            )
        )
    lines.append("")
    lines.append("## Patrimônio da manga escolhida")
    lines.append("")
    lines.append("| Patrimônio | CAGR líq. | OOS CAGR líq. | OOS − CDI | OOS DSR | Fills no teto | Sharpe | Max DD | Max DD OOS |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report.get("chosen_wealth") or []:
        fills = row["fills"]
        lines.append(
            f"| {_brl(row['aum_brl'])} | {_pct(row['cagr_net'])} | {_pct(row['oos_cagr_net'])} | "
            f"{_pct(row['oos_excess_cagr_over_cdi'])} | {_num(row['oos_dsr'], 2)} | "
            f"{fills['n_capped']}/{fills['n']} | {_num(row['sharpe_net'], 2)} | "
            f"{_pct(row['max_drawdown_net'])} | {_pct(row['oos_max_drawdown_net'])} |"
        )
    lines.append("")
    if chosen is not None:
        lines.append(
            f"Giro de mão única da manga escolhida: {_num(chosen['turnover_one_way_annual'], 2)} ao ano. "
            f"Capacidade típica a 10% do ADV mediano: {_brl(chosen['capacity_typical_10pct_adv'])}. "
            f"Capacidade limitada pelo papel menos líquido: {_brl(chosen['capacity_thin_10pct_adv'])}. "
            f"Mediana de nomes: {_num(chosen['median_names'], 0)}."
        )
        lines.append("")
    lines.append("## Anos da manga escolhida")
    lines.append("")
    lines.append("| Ano | Retorno líquido | CDI | Excesso | Ano ruim |")
    lines.append("|---:|---:|---:|---:|---|")
    bad = []
    for row in report.get("chosen_annual") or []:
        flag = "sim" if row["bad_year"] else ""
        if row["bad_year"]:
            bad.append(str(row["year"]))
        lines.append(
            f"| {row['year']} | {_pct(row['total_return'])} | {_pct(row['cdi'])} | {_pct(row['excess_over_cdi'])} | {flag} |"
        )
    lines.append("")
    lines.append("Anos com retorno líquido negativo: " + (", ".join(bad) if bad else "nenhum na série escolhida") + ".")
    lines.append("")
    lines.append(
        "Um mês acima de 100% num livro de cerca de 37 nomes tem o tamanho de um grupamento não confirmado por protocolo de capital. "
        "Em 29/05/2025, AMOB3 foi de R$ 0,24 para R$ 13,42, e o ADV mediano dos 60 pregões anteriores era R$ 2,2 milhões, acima do piso da manga escolhida. "
        "Esse salto fica no retorno enquanto o protocolo não confirma a quantidade. O excesso fora da amostra convive com saltos dessa classe."
    )
    lines.append("")
    lines.append("## Benchmarks")
    lines.append("")
    cdi = report["benchmark_cdi"]
    ibov = report["benchmark_ibov"]
    lines.append(f"CDI, amostra cheia (SGS 12): {_pct(cdi.get('cagr_full_sample'))}. {cdi.get('note')}")
    lines.append("")
    if ibov.get("available"):
        lines.append(
            f"Ibovespa, retorno total oficial, sem custo de investidor: CAGR {_pct(ibov.get('cagr'))}, "
            f"Sharpe {_num(ibov.get('sharpe'), 2)}, max DD {_pct(ibov.get('max_drawdown'))}."
        )
    else:
        lines.append("Ibovespa: série diária indisponível nesta corrida. " + str(ibov.get("note") or ""))
    lines.append("")
    lines.append("## DSR, PSR e MinTRL")
    lines.append("")
    lines.append(
        f"Trials desta família: {report['n_trials']}. Trials rejeitados do net-net, já no registro: "
        f"{report['n_rejected_net_net']}. N da decisão: {_num(report['n_trials_decision'], 0)}. "
        f"N de transparência, somando os {report['n_long_horizon_factor_trials']} trials de fatores de horizonte longo: "
        f"{_num(report['n_trials_with_factor_trials'], 0)}. N efetivo da família, por correlação, fica em "
        f"{_num(report.get('n_eff'), 2)} e não é o N do DSR."
    )
    lines.append("")
    if chosen is not None:
        lines.append(
            f"Fora da amostra, na manga escolhida: PSR {_num(chosen.get('oos_psr'), 2)}, "
            f"DSR {_num(chosen.get('oos_dsr'), 2)}, MinTRL {_num(chosen.get('oos_min_trl_months'), 0)}"
            f"{' (infinito)' if chosen.get('oos_min_trl_infinite') else ''}. "
            f"Com os 24 trials de fatores no N: DSR {_num(chosen.get('oos_dsr_with_factor_trials'), 2)}, "
            f"PSR {_num(chosen.get('oos_psr_with_factor_trials'), 2)}, "
            f"MinTRL {_num(chosen.get('oos_min_trl_with_factor_trials'), 0)}"
            f"{' (infinito)' if chosen.get('oos_min_trl_with_factor_trials_infinite') else ''}."
        )
        lines.append("")
        lines.append(
            f"Amostra cheia da mesma manga: Sharpe {_num(chosen.get('sharpe_net'), 2)}, "
            f"PSR {_num(chosen.get('psr'), 2)}, DSR {_num(chosen.get('dsr'), 2)}, "
            f"max DD {_pct(chosen.get('max_drawdown_net'))} (líquido) e {_pct(chosen.get('max_drawdown_gross'))} (bruto). "
            f"Max DD fora da amostra: {_pct(chosen.get('oos_max_drawdown_net'))}."
        )
    lines.append("")
    lines.append("## Auditoria do 17,5% ao ano das small caps")
    lines.append("")
    audit = report.get("published_small_cap_audit") or {}
    if not audit.get("available"):
        lines.append("A reprodução do caminho publicado não rodou nesta amostra. " + str(audit.get("reason") or ""))
    else:
        vendored = audit["vendored_resize_price"]
        resize = audit["resize_price"]
        bug = audit["round_trip_bug"]
        plain = audit["no_split"]
        cash = audit["with_taxed_distributions"]
        dead = audit["worthless_stale_exit"]
        adv = audit["adv_brl"]
        jumps = audit["jumps"]
        trade = audit["trades"]
        fills = vendored["fills"]
        capped = fills["n_capped"]
        n_fills = fills["n"]
        lines.append(audit["definition"])
        lines.append("")
        lines.append(
            f"O simulador publicado, só preço, imprime CAGR bruto {_pct(vendored['cagr_gross'])} e líquido "
            f"{_pct(vendored['cagr_net'])}. Max DD bruto {_pct(vendored['max_drawdown_gross'])}, "
            f"líquido {_pct(vendored['max_drawdown_net'])}. "
            f"O mesmo livro neste simulador, com resize, imprime líquido {_pct(resize['cagr_net'])} "
            f"e bruto {_pct(resize['cagr_gross'])}."
        )
        lines.append("")
        lines.append(
            f"Vender e recomprar quem ficou no livro muda o líquido para {_pct(bug['cagr_net'])} "
            f"e o bruto para {_pct(bug['cagr_gross'])}. A correção de resize é o caminho base. "
            f"O bug não é a origem do {_pct(vendored['cagr_net'])} líquido: esse número já é o caminho corrigido."
        )
        lines.append("")
        lines.append(
            f"Sem o ajuste de desdobramento confirmado por protocolo de capital, o líquido vai a "
            f"{_pct(plain['cagr_net'])} e o bruto a {_pct(plain['cagr_gross'])}. "
            f"Saltos confirmados como split: {jumps['confirmed_split_prints']}. "
            f"Saltos de pelo menos 45% sem confirmação: {jumps['unconfirmed_gaps']}, "
            f"dos quais {jumps['unconfirmed_round_gaps']} têm razão redonda de grupamento ou desdobramento. "
            "Salto sem protocolo continua no retorno."
        )
        lines.append("")
        lines.append(
            f"Com provento tributado na regra travada, o líquido vai a {_pct(cash['cagr_net'])} "
            f"e o caixa de provento somado é {_brl(cash['dividend_cash'])}."
        )
        lines.append("")
        lines.append(
            f"Marcar a saída sem negócio recente como perda total leva o líquido a {_pct(dead['cagr_net'])}. "
            f"O contador de saída do simulador publicado, que só incrementa no modo de carregar até o dobro, "
            f"fica em {vendored['delist_exits_counter']}. A saída de quem para de negociar, neste livro de substituição, "
            f"acontece no rebalanceamento, no último negócio. Neste simulador isso aparece como "
            f"{resize['stale_sells']} vendas com preço velho."
        )
        lines.append("")
        lines.append(
            f"Liquidez do livro publicado: mediana de nomes small { _num(audit['median_small_names'], 0) }, "
            f"ADV mediano {_brl(adv.get('median'))}, percentil 10 {_brl(adv.get('p10'))}, "
            f"fração de vagas com ADV abaixo de R$ 10 mil {_pct(adv.get('fraction_below_10k'))}, "
            f"abaixo de R$ 100 mil {_pct(adv.get('fraction_below_100k'))}. "
            f"Fills no teto de 5.000 bps: {capped} de {n_fills}. "
            f"Slippage {_brl(fills['slippage'])} dentro de taxa {_brl(fills['fee'])} e meio spread {_brl(fills['half_spread'])}."
        )
        if trade.get("available"):
            lines.append("")
            lines.append(
                f"Negócios por dia, nos papéis que passaram pelo livro: mediana das medianas "
                f"{_num(trade.get('median_of_median_trades'), 1)}, fração de pregões com no máximo um negócio "
                f"{_pct(trade.get('fraction_prints_at_most_one_trade'))}."
            )
        largest = jumps.get("largest_unconfirmed") or []
        if largest:
            lines.append("")
            lines.append("Maiores saltos sem confirmação de capital, preço final sobre preço anterior:")
            lines.append("")
            for item in largest[:8]:
                lines.append(f"- {item['ticker']} em {item['date']}: razão {_num(item['price_ratio'], 2)}")
        lines.append("")
        net_pub = vendored["cagr_net"]
        gross_pub = vendored["cagr_gross"]
        lines.append(
            "Leitura: o 17,5% líquido e o 32,8% bruto publicados são o par preço-apenas depois da correção "
            "de não vender quem continua na carteira. "
            f"Esta corrida mede {_pct(gross_pub)} bruto e {_pct(net_pub)} líquido nesse desenho. "
            "A distância entre bruto e líquido é custo, e o slippage no teto é a maior peça quando o ADV "
            "do nome é pequeno diante da fatia igual do patrimônio. "
            "Desdobramento não confirmado e saída no último negócio empurram o bruto para cima se o salto "
            "ou o último negócio não são econômicos. Os números das variantes acima são o tamanho desse efeito, "
            "não um segundo estudo para escolher regra."
        )
    lines.append("")
    lines.append("## Limites")
    lines.append("")
    lines.append(
        "O N da decisão soma esta família e os 32 trials rejeitados do net-net. "
        "Os 24 trials de fatores entram só na coluna de transparência, porque esse bloco não está neste registro. "
        "N efetivo não substitui o N. `eligible_for_live_trading` é false."
    )
    lines.append("")
    lines.append("Números completos, inclusive a série mensal de cada trial: `docs/reports/equal-weight-b3.json`.")
    lines.append("")
    return "\n".join(lines)

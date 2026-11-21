"""Graham net-net screen on B3. Research and paper simulation only.

The liquidation value and the four filters follow Greenblatt, Pzena and
Newberg, "How the small investor can beat the market", Journal of Portfolio
Management (1981). Nothing here sends an order. ``eligible_for_live_trading``
is false on every report this module builds.

Point-in-time rule: a filing is visible only when ``received <= as-of``.
The price that enters P/LV and P/E is the signal-day close. The fill is the
next session, priced by ``trading_costs.quote_fill``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.models.afml.gate import gate
from app.models.afml.trials import TrialRegistry
from app.models.trading_costs import BookTop, cash_delta, quote_fill

FAMILY_ID = "b3_graham_net_net"
ELIGIBLE_FOR_LIVE_TRADING = False
PERIODS_PER_YEAR = 12.0

# Greenblatt, Pzena & Newberg: an 8% AAA yield maps to a P/E cap of about 6.25,
# i.e. earnings yield at least twice the bond yield, P/E <= 1 / (2 * y).
PAPER_AAA_EXAMPLE = 0.08
PAPER_PE_AT_8PCT = 6.25

# Liquidity assumptions. The book is COTAHIST's daily best bid/ask when that
# quote is usable. Depth is not in the file: the displayed touch is taken as
# 1% of trailing median share volume, and the desk impact (10 bps when the
# order equals that touch) then scales slippage with participation.
# The spread fallback is used only when the bid/ask is missing or absurd.
# full_spread_bps = clip(250_000 / sqrt(ADV_BRL), 10, 500):
#   ADV R$100m -> 25 bps, ADV R$1m -> 250 bps, ADV R$100k -> 500 bps cap.
TOUCH_FRACTION_OF_ADV = 0.01
IMPACT_BPS = 10.0
SPREAD_NUMERATOR = 250_000.0
SPREAD_FLOOR_BPS = 10.0
SPREAD_CAP_BPS = 500.0
SLIPPAGE_CAP_BPS = 5_000.0
NO_DEPTH_SLIPPAGE_BPS = 200.0
ADV_WINDOW = 20
PRICE_STALE_SESSIONS = 5
DELIST_STALE_SESSIONS = 10
HOLD_DAYS = 730
DOUBLE = 2.0
SMALL_CAP_QUANTILE = 0.30
PARTICIPATION_CAP = 0.10
YIELD_STALE_DAYS = 40

FINANCIAL_SETORES = frozenset(
    {
        "Bancos",
        "Seguradoras e Corretoras",
        "Arrendamento Mercantil",
        "Intermediação Financeira",
        "Securitização de Recebíveis",
        "Emp. Adm. Part. - Intermediação Financeira",
        "Emp. Adm. Part. - Seguradoras e Corretoras",
        "Crédito Imobiliário",
        "Emp. Adm. Part. - Crédito Imobiliário",
        "Bolsas de Valores/Mercadorias e Futuros",
        "Emp. Adm. Part.-Bolsas de Valores/Mercadorias e Futuros",
        "Factoring",
        "Emp. Adm. Part. - Arrendamento Mercantil",
        "Emp. Adm. Part. - Securitização de Recebíveis",
        "Emp. Adm. Part. - Bancos",
    }
)

FILTERS: tuple[tuple[str, float, str], ...] = (
    ("plv1_ey", 1.0, "ey"),
    ("plv085_ey", 0.85, "ey"),
    ("plv1_pe5", 1.0, "pe5"),
    ("plv085_pe5", 0.85, "pe5"),
)


def is_financial_setor(setor: str | None) -> bool:
    return (setor or "").strip() in FINANCIAL_SETORES


def pe_cap_from_yield(bond_yield: float) -> float:
    """P/E cap. ``bond_yield`` is a decimal (0.08 -> 6.25)."""
    if not math.isfinite(bond_yield) or bond_yield <= 0:
        raise ValueError("bond yield must be a positive finite decimal")
    return 1.0 / (2.0 * float(bond_yield))


def fallback_full_spread_bps(adv_brl: float) -> float:
    if not math.isfinite(adv_brl) or adv_brl <= 0:
        return SPREAD_CAP_BPS
    raw = SPREAD_NUMERATOR / math.sqrt(float(adv_brl))
    return float(min(max(raw, SPREAD_FLOOR_BPS), SPREAD_CAP_BPS))


def liquidation_per_share(
    ca: float,
    cl: float,
    ltl: float,
    capital: float | None,
    on_out: float,
    pn_integrated: float,
    total_integrated: float,
) -> float | None:
    """Liquidation value per common share, in BRL.

    LV = current assets − current liabilities − long-term liabilities
    − preferred at book. Book preferred, under Lei 6.404/76, is not a
    liability line: preferred shares sit in equity. The claim taken here is
    capital social realizado times the preferred fraction of subscribed
    capital (par, or the no-par capital allocated by share count).

    Returns None when the preferred claim cannot be measured, when a
    liability line is negative, or when there is no common share outstanding.
    A negative result is a real LV (the name is not a net-net); callers
    reject it. None means the input is not usable.
    """
    if min(ca, cl, ltl) < 0 or not all(map(math.isfinite, (ca, cl, ltl))):
        return None
    if not math.isfinite(on_out) or on_out <= 0:
        return None
    if not math.isfinite(pn_integrated) or pn_integrated < 0:
        return None
    if not math.isfinite(total_integrated) or total_integrated <= 0:
        return None
    if pn_integrated - total_integrated > 1.0:
        return None
    if pn_integrated == 0:
        preferred = 0.0
    else:
        if capital is None or not math.isfinite(capital) or capital <= 0:
            return None
        preferred = float(capital) * (float(pn_integrated) / float(total_integrated))
    return (float(ca) - float(cl) - float(ltl) - preferred) / float(on_out)


@dataclass(frozen=True)
class BsPoint:
    period_end: int
    received: int
    ca: float
    cl: float
    ltl: float
    capital: float | None
    assets: float | None = None
    equity: float | None = None
    cash: float | None = None
    debt_st: float | None = None
    debt_lt: float | None = None


@dataclass(frozen=True)
class SharePoint:
    period_end: int
    received: int
    on_out: float
    pn_subscribed: float
    total_subscribed: float
    pn_out: float


@dataclass(frozen=True)
class EarnRow:
    start: int
    end: int
    received: int
    ni: float
    eps: float | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    ebit: float | None = None
    ebt: float | None = None


@dataclass(frozen=True)
class Fundamentals:
    bs_received: int
    bs_period_end: int
    lv_per_share: float
    on_out: float
    pn_out_integrated: float
    total_out: float
    ttm_ni: float | None
    ttm_source: str
    earnings_received: int | None


def _latest(points: Sequence[Any], asof: int) -> Any | None:
    best = None
    for point in points:
        if point.received > asof:
            continue
        if best is None or point.period_end > best.period_end or (
            point.period_end == best.period_end and point.received > best.received
        ):
            best = point
    return best


def _source_pair(con: Sequence[Any], ind: Sequence[Any], asof: int) -> Sequence[Any]:
    """Prefer whichever statement has the newer published period. Tie goes to consolidated."""
    latest_con = _latest(con, asof)
    latest_ind = _latest(ind, asof)
    if latest_con is None and latest_ind is None:
        return ()
    if latest_con is None:
        return ind
    if latest_ind is None:
        return con
    if latest_ind.period_end > latest_con.period_end:
        return ind
    return con


def _earn_source(con: Sequence[EarnRow], ind: Sequence[EarnRow], asof: int) -> Sequence[EarnRow]:
    def newest(rows: Sequence[EarnRow]) -> EarnRow | None:
        best = None
        for row in rows:
            if row.received > asof:
                continue
            if best is None or row.end > best.end or (row.end == best.end and row.received >= best.received):
                best = row
        return best

    latest_con = newest(con)
    latest_ind = newest(ind)
    if latest_con is None and latest_ind is None:
        return ()
    if latest_con is None:
        return ind
    if latest_ind is None:
        return con
    if latest_ind.end > latest_con.end:
        return ind
    return con


def _collapse_earnings(rows: Sequence[EarnRow], asof: int) -> list[EarnRow]:
    best: dict[tuple[int, int], EarnRow] = {}
    for row in rows:
        if row.received > asof:
            continue
        key = (row.start, row.end)
        prev = best.get(key)
        if prev is None or row.received >= prev.received:
            best[key] = row
    return list(best.values())


def _derive_quarters(rows: Sequence[EarnRow]) -> tuple[list[EarnRow], list[EarnRow]]:
    """Explicit quarters, plus quarters implied by YTD and by annual minus 9M.

    A derived quarter is known only once every input row is known. Callers
    pass rows already restricted to ``received <= as-of``.
    """
    quarters: list[EarnRow] = []
    annuals: list[EarnRow] = []
    ytds: list[EarnRow] = []
    for row in rows:
        dur = row.end - row.start
        if 70 <= dur <= 110:
            quarters.append(row)
        elif 300 <= dur <= 380:
            annuals.append(row)
        elif 111 <= dur <= 299:
            ytds.append(row)
    have_end = {row.end for row in quarters}
    for ytd in sorted(ytds, key=lambda row: (row.start, row.end)):
        inside = [row for row in quarters if ytd.start <= row.start and row.end <= ytd.end]
        inside.sort(key=lambda row: row.end)
        cursor = ytd.start
        covered = 0.0
        tiled = True
        for row in inside:
            if row.start != cursor:
                tiled = False
                break
            covered += row.ni
            cursor = row.end + 1
        if not tiled or cursor > ytd.end or ytd.end in have_end:
            continue
        tail = ytd.end - cursor
        if not 70 <= tail <= 110:
            continue
        quarters.append(EarnRow(cursor, ytd.end, ytd.received, ytd.ni - covered))
        have_end.add(ytd.end)
    for annual in annuals:
        cands = [row for row in ytds if row.start == annual.start and row.end < annual.end]
        if not cands:
            continue
        ytd = max(cands, key=lambda row: row.end)
        if not (200 <= ytd.end - ytd.start <= 299):
            continue
        if annual.end in have_end:
            continue
        quarters.append(
            EarnRow(
                ytd.end + 1,
                annual.end,
                max(annual.received, ytd.received),
                annual.ni - ytd.ni,
            )
        )
        have_end.add(annual.end)
    return quarters, annuals


def trailing_earnings(
    rows: Sequence[EarnRow], asof: int
) -> tuple[float | None, str, int | None]:
    """TTM net income from four consecutive published quarters, else the latest annual.

    The annual fallback is used only when its period ended within 450 days of
    ``asof``. Missing earnings stay missing: they are not treated as a profit.
    """
    collapsed = _collapse_earnings(rows, asof)
    quarters, annuals = _derive_quarters(collapsed)
    quarters = [row for row in quarters if row.end <= asof and row.received <= asof]
    quarters.sort(key=lambda row: (row.end, row.received))
    # one row per period end: the latest restatement already in ``collapsed``
    by_end: dict[int, EarnRow] = {}
    for row in quarters:
        by_end[row.end] = row
    ordered = [by_end[key] for key in sorted(by_end)]
    if len(ordered) >= 4:
        last4 = ordered[-4:]
        gaps = [last4[i].end - last4[i - 1].end for i in range(1, 4)]
        if all(70 <= gap <= 120 for gap in gaps) and asof - last4[-1].end <= 200:
            received = max(row.received for row in last4)
            return float(sum(row.ni for row in last4)), "quarters", received
    fresh = [
        row
        for row in annuals
        if row.end <= asof and row.received <= asof and asof - row.end <= 450
    ]
    if fresh:
        annual = max(fresh, key=lambda row: (row.end, row.received))
        return float(annual.ni), "annual", annual.received
    return None, "missing", None


def fundamentals_asof(
    bs_con: Sequence[BsPoint],
    bs_ind: Sequence[BsPoint],
    shares: Sequence[SharePoint],
    er_con: Sequence[EarnRow],
    er_ind: Sequence[EarnRow],
    asof: int,
) -> Fundamentals | None:
    bs_src = _source_pair(bs_con, bs_ind, asof)
    bs = _latest(bs_src, asof)
    share = _latest(shares, asof)
    if bs is None or share is None:
        return None
    lv = liquidation_per_share(
        bs.ca, bs.cl, bs.ltl, bs.capital, share.on_out, share.pn_subscribed, share.total_subscribed
    )
    if lv is None:
        return None
    er_src = _earn_source(er_con, er_ind, asof)
    ttm, source, earned = trailing_earnings(er_src, asof)
    total_out = share.on_out + max(share.pn_out, 0.0)
    return Fundamentals(
        bs_received=bs.received,
        bs_period_end=bs.period_end,
        lv_per_share=lv,
        on_out=share.on_out,
        pn_out_integrated=share.pn_subscribed,
        total_out=total_out,
        ttm_ni=ttm,
        ttm_source=source,
        earnings_received=earned,
    )


def earnings_per_share(ttm_ni: float | None, on_out: float) -> float | None:
    if ttm_ni is None or not math.isfinite(ttm_ni) or on_out <= 0:
        return None
    return float(ttm_ni) / float(on_out)


def passes_screen(
    price: float,
    lv_per_share: float | None,
    eps: float | None,
    plv_max: float,
    pe_mode: str,
    bond_yield: float | None,
) -> bool:
    """One name, one signal date. Losses and non-positive LV never pass."""
    if not math.isfinite(price) or price <= 0 or lv_per_share is None or lv_per_share <= 0:
        return False
    if eps is None or not math.isfinite(eps) or eps <= 0:
        return False
    if price / lv_per_share > plv_max + 1e-12:
        return False
    if pe_mode == "pe5":
        cap = 5.0
    elif pe_mode == "ey":
        if bond_yield is None:
            return False
        cap = pe_cap_from_yield(bond_yield)
    else:
        raise ValueError("pe_mode must be 'pe5' or 'ey'")
    return (price / eps) <= cap + 1e-12


@dataclass
class Tape:
    dates: np.ndarray
    close: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    qty: np.ndarray
    vol: np.ndarray
    split: np.ndarray
    # Per-print label from corporate_actions.adjust_prints. None means the
    # factor was supplied by a test or an older builder and is not a heuristic.
    split_source: np.ndarray | None = None
    # Cumulative reais-per-share multiplier for heuristic factors through each print.
    heuristic_cash_scale: np.ndarray | None = None

    def index_on_or_before(self, ordinal: int) -> int | None:
        if len(self.dates) == 0:
            return None
        idx = int(np.searchsorted(self.dates, ordinal, side="right") - 1)
        if idx < 0:
            return None
        return idx


def trailing_adv(tape: Tape, idx: int, window: int = ADV_WINDOW) -> tuple[float, float]:
    """Median BRL volume and share volume over the prior ``window`` prints, excluding ``idx``.

    Share volume is restated in the share unit of ``idx``. A print is multiplied
    by the product of split factors strictly after it and through ``idx``, so a
    grupamento does not leave the old share count inside the depth estimate.
    BRL volume is the notional that traded and is not rescaled.
    """
    start = max(0, idx - window)
    if idx - start < 1:
        return 0.0, 0.0
    vol = np.asarray(tape.vol[start:idx], dtype=np.float64)
    qty = np.asarray(tape.qty[start:idx], dtype=np.float64)
    span = np.asarray(tape.split[start : idx + 1], dtype=np.float64)
    positive = np.where(np.isfinite(span) & (span > 0.0), span, 1.0)
    if len(span) > 1:
        rev = np.cumprod(positive[::-1])[::-1]
        qty = qty * rev[1 : 1 + len(qty)]
    vol = vol[np.isfinite(vol)]
    qty = qty[np.isfinite(qty)]
    if len(vol) == 0:
        return 0.0, 0.0
    return float(np.median(vol)), float(np.median(qty)) if len(qty) else 0.0


def execution_book(
    mid: float, bid: float, ask: float, adv_brl: float, adv_shares: float
) -> tuple[BookTop, str]:
    depth = adv_shares * TOUCH_FRACTION_OF_ADV if adv_shares > 0 else None
    if (
        math.isfinite(bid)
        and math.isfinite(ask)
        and math.isfinite(mid)
        and mid > 0
        and bid > 0
        and ask >= bid
    ):
        width = (ask - bid) / mid * 10_000.0
        if 0 <= width <= 2_000:
            return (
                BookTop(
                    bid=float(bid),
                    ask=float(ask),
                    bid_size=depth,
                    ask_size=depth,
                    mid=float(mid),
                    volume=adv_brl if adv_brl > 0 else None,
                    estimated=False,
                ),
                "book",
            )
    half = fallback_full_spread_bps(adv_brl) / 2.0
    bump = mid * half / 10_000.0 if mid > 0 else 0.0
    return (
        BookTop(
            bid=mid - bump if mid > bump else None,
            ask=mid + bump if mid > 0 else None,
            bid_size=depth,
            ask_size=depth,
            mid=mid if mid > 0 else None,
            volume=adv_brl if adv_brl > 0 else None,
            estimated=True,
        ),
        "estimate",
    )


def _capped_book(book: BookTop, side: str, qty: float) -> tuple[BookTop, bool]:
    depth = book.ask_size if side == "buy" else book.bid_size
    if depth is None or depth <= 0 or qty <= 0:
        return book, False
    raw = IMPACT_BPS * qty / depth
    if raw <= SLIPPAGE_CAP_BPS:
        return book, False
    capped_depth = IMPACT_BPS * qty / SLIPPAGE_CAP_BPS
    if side == "buy":
        return (
            BookTop(
                bid=book.bid,
                ask=book.ask,
                bid_size=book.bid_size,
                ask_size=capped_depth,
                mid=book.mid,
                volume=book.volume,
                estimated=book.estimated,
            ),
            True,
        )
    return (
        BookTop(
            bid=book.bid,
            ask=book.ask,
            bid_size=capped_depth,
            ask_size=book.ask_size,
            mid=book.mid,
            volume=book.volume,
            estimated=book.estimated,
        ),
        True,
    )


@dataclass
class FillStats:
    n: int = 0
    n_book: int = 0
    n_estimate: int = 0
    n_capped: int = 0
    fee: float = 0.0
    half_spread: float = 0.0
    slippage: float = 0.0
    half_spread_bps_sum: float = 0.0

    def add(self, fill, source: str, capped: bool) -> None:
        self.n += 1
        self.n_book += int(source == "book")
        self.n_estimate += int(source != "book")
        self.n_capped += int(capped)
        self.fee += fill.fee
        self.half_spread += fill.half_spread
        self.slippage += fill.slippage
        self.half_spread_bps_sum += fill.half_spread_bps


def price_fill(side: str, qty: float, mid: float, book: BookTop) -> tuple[Any, bool]:
    if qty <= 0 or not math.isfinite(mid) or mid <= 0:
        raise ValueError("qty and mid must be positive")
    book, capped = _capped_book(book, side, qty)
    depth = book.ask_size if side == "buy" else book.bid_size
    fallback = 0.0 if depth is not None and depth > 0 else NO_DEPTH_SLIPPAGE_BPS
    fill = quote_fill(
        side=side,
        qty=qty,
        mid=mid,
        venue="b3",
        liquidity="taker",
        book=book,
        impact_bps=IMPACT_BPS,
        fallback_slippage_bps=fallback,
    )
    return fill, capped


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


def _apply_splits(ledger: Ledger, tapes: dict[str, Tape], ordinal: int) -> None:
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


def _close_on(tape: Tape, ordinal: int, max_stale: int) -> tuple[float | None, int | None, bool]:
    idx = tape.index_on_or_before(ordinal)
    if idx is None:
        return None, None, True
    age = ordinal - int(tape.dates[idx])
    stale = age > max_stale
    px = float(tape.close[idx])
    if not math.isfinite(px) or px <= 0:
        return None, idx, True
    return px, idx, stale


@dataclass(frozen=True)
class NameRow:
    cnpj: str
    ticker: str
    price: float
    lv_per_share: float | None
    eps: float | None
    adv_brl: float
    adv_shares: float
    mcap: float | None
    idx: int


def match_share_multiplier(price_ratio: float) -> float | None:
    """Share multiplier implied by a round price jump of at least 45%.

    Price becoming ``a/b`` (a, b <= 20) maps to a share multiplier ``b/a``.
    Ordinary gaps are not matches. Used only together with a confirming
    change in shares outstanding.
    """
    if not math.isfinite(price_ratio) or price_ratio <= 0:
        return None
    best: float | None = None
    best_err = 0.03
    for num in range(1, 21):
        for den in range(1, 21):
            if num == den:
                continue
            target = num / den
            if 1 / 1.45 < target < 1.45:
                continue
            err = abs(price_ratio - target) / target
            if err < best_err:
                best_err = err
                best = den / num
    return best


def confirmed_split_factors(
    dates: np.ndarray,
    close: np.ndarray,
    share_ords: Sequence[int],
    share_counts: Sequence[float],
    confirm_days: int = 250,
    qty: np.ndarray | None = None,
    official: Sequence[Any] | None = None,
) -> np.ndarray:
    """Share multiplier applied to a position at the start of each print.

    The 250-day look-ahead is gone. ``confirm_days``, ``share_ords`` and
    ``share_counts`` are accepted so older callers still import, and they are
    not used: a capital filing received after the print is not an ex-date.
    Pass ``qty`` and official events to get the point-in-time factor. The
    cleaned price series lives on ``corporate_actions.adjust_prints``.
    """
    del confirm_days, share_ords, share_counts
    from app.models.corporate_actions import adjust_prints

    n = len(dates)
    if qty is None:
        qty_arr = np.ones(n, dtype=np.float64)
    else:
        qty_arr = np.asarray(qty, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    adj = adjust_prints(
        np.asarray(dates, dtype=np.int64),
        close_arr,
        close_arr,
        close_arr,
        qty_arr,
        np.ones(n, dtype=np.float64),
        ticker="",
        official=() if official is None else official,
    )
    return adj.share_factor


def month_ends(session_ords: Sequence[int]) -> list[int]:
    last: dict[tuple[int, int], int] = {}
    for ordinal in session_ords:
        day = date.fromordinal(int(ordinal))
        last[(day.year, day.month)] = int(ordinal)
    return [last[key] for key in sorted(last)]


def first_sessions_by_month(session_ords: Sequence[int]) -> dict[tuple[int, int], int]:
    first: dict[tuple[int, int], int] = {}
    for ordinal in session_ords:
        day = date.fromordinal(int(ordinal))
        key = (day.year, day.month)
        if key not in first:
            first[key] = int(ordinal)
    return first


def rebalance_signals(session_ords: Sequence[int], phase: int, first_ord: int, last_ord: int) -> list[int]:
    """First session of each month whose ``year*12+month`` modulo 4 equals ``phase``."""
    signals = []
    for (year, month), ordinal in first_sessions_by_month(session_ords).items():
        if (year * 12 + month) % 4 != phase:
            continue
        if ordinal < first_ord or ordinal > last_ord:
            continue
        signals.append(ordinal)
    return signals


def yield_asof(dates: np.ndarray, values: np.ndarray, ordinal: int, max_stale: int = YIELD_STALE_DAYS) -> float | None:
    if len(dates) == 0:
        return None
    idx = int(np.searchsorted(dates, ordinal, side="right") - 1)
    if idx < 0:
        return None
    if ordinal - int(dates[idx]) > max_stale:
        return None
    value = float(values[idx])
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _mirror_gross(gross: Ledger, ticker: str, qty: float, mid: float, side: str, template: Position | None) -> None:
    """Same shares as the net book. Gross cash moves at the mid, with no fee."""
    if side == "sell":
        gross.cash += qty * mid
        gpos = gross.positions.get(ticker)
        if gpos is None:
            return
        gpos.shares -= qty
        if gpos.shares <= 1e-8:
            gross.positions.pop(ticker, None)
        return
    gross.cash -= qty * mid
    gpos = gross.positions.get(ticker)
    if gpos is None and template is not None:
        gross.positions[ticker] = Position(template.cnpj, template.ticker, qty, template.entry_px, template.entry_ord)
    elif gpos is not None:
        gpos.shares += qty


def _sell(
    ledger: Ledger,
    gross: Ledger,
    ticker: str,
    tapes: dict[str, Tape],
    ordinal: int,
    stats: FillStats,
) -> None:
    pos = ledger.positions.get(ticker)
    if pos is None or pos.shares <= 0:
        gross.positions.pop(ticker, None)
        ledger.positions.pop(ticker, None)
        return
    tape = tapes[ticker]
    px, idx, _stale = _close_on(tape, ordinal, max_stale=10**9)
    if px is None or idx is None:
        return
    qty = pos.shares
    adv_brl, adv_sh = trailing_adv(tape, idx)
    book, source = execution_book(px, float(tape.bid[idx]), float(tape.ask[idx]), adv_brl, adv_sh)
    fill, capped = price_fill("sell", qty, px, book)
    stats.add(fill, source, capped)
    ledger.cash += cash_delta(fill)
    _mirror_gross(gross, ticker, qty, px, "sell", None)
    ledger.positions.pop(ticker, None)


def _buy_qty(cash: float, qty: float, mid: float, book: BookTop) -> float:
    if qty <= 0 or cash <= 0:
        return 0.0
    fill, _capped = price_fill("buy", qty, mid, book)
    if -cash_delta(fill) <= cash + 1e-6:
        return qty
    lo, hi = 0.0, qty
    for _ in range(20):
        mid_q = (lo + hi) / 2.0
        if mid_q <= 0:
            break
        trial, _capped = price_fill("buy", mid_q, mid, book)
        if -cash_delta(trial) <= cash:
            lo = mid_q
        else:
            hi = mid_q
    return lo


def _rebalance(
    ledger: Ledger,
    gross: Ledger,
    targets: list[NameRow],
    tapes: dict[str, Tape],
    ordinal: int,
    stats: FillStats,
) -> None:
    priced: list[tuple[NameRow, float, int]] = []
    for row in targets:
        tape = tapes.get(row.ticker)
        if tape is None:
            continue
        px, idx, stale = _close_on(tape, ordinal, PRICE_STALE_SESSIONS)
        if px is None or idx is None or stale:
            continue
        priced.append((row, px, idx))
    # Drop anything we cannot price today, then size off the net equity.
    keep = {row.ticker for row, _px, _idx in priced}
    for ticker in list(ledger.positions):
        if ticker not in keep:
            _sell(ledger, gross, ticker, tapes, ordinal, stats)
    if not priced:
        return
    equity = ledger.cash
    for _row, px, _idx in priced:
        pos = ledger.positions.get(_row.ticker)
        if pos is not None:
            equity += pos.shares * px
    target_value = equity / len(priced)
    sells: list[tuple[str, float]] = []
    buys: list[tuple[NameRow, float, float, int]] = []
    for row, px, idx in priced:
        pos = ledger.positions.get(row.ticker)
        current = 0.0 if pos is None else pos.shares
        desired = target_value / px
        delta = desired - current
        if delta < -1e-8:
            sells.append((row.ticker, -delta))
        elif delta > 1e-8:
            buys.append((row, delta, px, idx))
    for ticker, qty in sells:
        pos = ledger.positions[ticker]
        # Partial sell. Entry price stays the original mid.
        tape = tapes[ticker]
        px, idx, _stale = _close_on(tape, ordinal, 10**9)
        if px is None or idx is None:
            continue
        qty = min(qty, pos.shares)
        adv_brl, adv_sh = trailing_adv(tape, idx)
        book, source = execution_book(px, float(tape.bid[idx]), float(tape.ask[idx]), adv_brl, adv_sh)
        fill, capped = price_fill("sell", qty, px, book)
        stats.add(fill, source, capped)
        ledger.cash += cash_delta(fill)
        pos.shares -= qty
        _mirror_gross(gross, ticker, qty, px, "sell", None)
        if pos.shares <= 1e-8:
            ledger.positions.pop(ticker, None)
    for row, qty, px, idx in buys:
        tape = tapes[row.ticker]
        adv_brl, adv_sh = trailing_adv(tape, idx)
        book, source = execution_book(px, float(tape.bid[idx]), float(tape.ask[idx]), adv_brl, adv_sh)
        qty = _buy_qty(ledger.cash, qty, px, book)
        if qty <= 1e-8:
            continue
        fill, capped = price_fill("buy", qty, px, book)
        spent = -cash_delta(fill)
        if spent > ledger.cash + 1e-4:
            continue
        stats.add(fill, source, capped)
        ledger.cash -= spent
        pos = ledger.positions.get(row.ticker)
        if pos is None:
            pos = Position(row.cnpj, row.ticker, qty, px, ordinal)
            ledger.positions[row.ticker] = pos
        else:
            pos.shares += qty
        _mirror_gross(gross, row.ticker, qty, px, "buy", pos)


def _should_exit(pos: Position, px: float, ordinal: int, stale: bool) -> bool:
    if stale:
        return True
    if px / pos.entry_px >= DOUBLE:
        return True
    if ordinal - pos.entry_ord >= HOLD_DAYS:
        return True
    return False


def _equity(ledger: Ledger, tapes: dict[str, Tape], ordinal: int) -> float:
    total = ledger.cash
    for pos in ledger.positions.values():
        tape = tapes.get(pos.ticker)
        if tape is None:
            continue
        px, _idx, _stale = _close_on(tape, ordinal, 10**9)
        if px is not None:
            total += pos.shares * px
    return total


def simulate(
    sessions: Sequence[int],
    tapes: dict[str, Tape],
    signal_rows: dict[int, list[NameRow]],
    selector,
    aum: float,
    hold_until_exit: bool,
) -> dict[str, Any]:
    """Path-dependent paper book.

    ``selector(signal_ordinal, rows, positions) -> target NameRows``.
    When ``hold_until_exit`` is true, names already held are kept until they
    double, reach two years, or go stale, and the selector's new names are
    added at the rebalance. When false, membership is replaced by the selector
    (the small-cap benchmark). Names that remain are resized, not sold and
    bought again: a full round trip on an unchanged book would charge the
    spread and the participation slippage twice per rebalance.
    """
    if aum <= 0:
        raise ValueError("aum must be positive")
    ledger = Ledger(cash=float(aum))
    gross = Ledger(cash=float(aum))
    stats = FillStats()
    pending_signal: int | None = None
    pending_exits: dict[str, str] = {}
    delist_exits = 0
    double_exits = 0
    time_exits = 0
    logs: list[dict[str, Any]] = []
    curve_ord: list[int] = []
    curve_net: list[float] = []
    curve_gross: list[float] = []
    signal_set = set(signal_rows)
    ordered = list(sessions)

    def _count(reason: str) -> None:
        nonlocal delist_exits, double_exits, time_exits
        if reason == "delist":
            delist_exits += 1
        elif reason == "double":
            double_exits += 1
        else:
            time_exits += 1

    for ordinal in ordered:
        _apply_splits(ledger, tapes, ordinal)
        _apply_splits(gross, tapes, ordinal)
        for ticker, reason in pending_exits.items():
            if ticker in ledger.positions:
                _count(reason)
                _sell(ledger, gross, ticker, tapes, ordinal, stats)
        pending_exits = {}
        if pending_signal is not None:
            rows = signal_rows.get(pending_signal, [])
            chosen = list(selector(pending_signal, rows, ledger.positions))
            if hold_until_exit:
                chosen_ids = {row.ticker for row in chosen}
                kept: list[NameRow] = []
                exiting: list[str] = []
                for ticker, pos in list(ledger.positions.items()):
                    tape = tapes.get(ticker)
                    px, _idx, stale = (None, None, True) if tape is None else _close_on(tape, pending_signal, DELIST_STALE_SESSIONS)
                    if px is None or _should_exit(pos, px, pending_signal, stale):
                        exiting.append(ticker)
                        if px is None or stale:
                            _count("delist")
                        elif px / pos.entry_px >= DOUBLE:
                            _count("double")
                        else:
                            _count("time")
                    elif ticker not in chosen_ids:
                        kept.append(
                            NameRow(pos.cnpj, ticker, px, None, None, 0.0, 0.0, None, -1)
                        )
                for ticker in exiting:
                    _sell(ledger, gross, ticker, tapes, ordinal, stats)
                targets = chosen + kept
            else:
                # Do not liquidate names that are still targets. ``_rebalance``
                # sells anything that dropped out and trades only the weight delta.
                targets = chosen
            before = set(ledger.positions)
            _rebalance(ledger, gross, targets, tapes, ordinal, stats)
            after = set(ledger.positions)
            advs = [row.adv_brl for row in chosen if row.adv_brl > 0]
            logs.append(
                {
                    "signal": int(pending_signal),
                    "trade": int(ordinal),
                    "n_pass": len(chosen),
                    "n_held": len(after),
                    "n_new": len(after - before),
                    "median_adv": float(np.median(advs)) if advs else 0.0,
                    "min_adv": float(min(advs)) if advs else 0.0,
                }
            )
            pending_signal = None
        if ordinal in signal_set:
            pending_signal = ordinal
        elif hold_until_exit:
            for ticker, pos in ledger.positions.items():
                tape = tapes.get(ticker)
                if tape is None:
                    pending_exits[ticker] = "delist"
                    continue
                px, _idx, stale = _close_on(tape, ordinal, DELIST_STALE_SESSIONS)
                if px is None or stale:
                    pending_exits[ticker] = "delist"
                elif px / pos.entry_px >= DOUBLE:
                    pending_exits[ticker] = "double"
                elif ordinal - pos.entry_ord >= HOLD_DAYS:
                    pending_exits[ticker] = "time"
        curve_ord.append(ordinal)
        curve_net.append(_equity(ledger, tapes, ordinal))
        curve_gross.append(_equity(gross, tapes, ordinal))
    # Flatten anything still open at the last mark. Paper only.
    if ordered:
        last = ordered[-1]
        for ticker in list(ledger.positions):
            _sell(ledger, gross, ticker, tapes, last, stats)
        if curve_net:
            curve_net[-1] = ledger.cash
            curve_gross[-1] = gross.cash
    return {
        "ords": curve_ord,
        "net": curve_net,
        "gross": curve_gross,
        "logs": logs,
        "stats": stats,
        "delist_exits": delist_exits,
        "double_exits": double_exits,
        "time_exits": time_exits,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def monthly_simple_returns(ords: Sequence[int], equity: Sequence[float]) -> tuple[list[int], list[float]]:
    if not ords:
        return [], []
    ends = set(month_ends(ords))
    marks: list[tuple[int, float]] = []
    for ordinal, value in zip(ords, equity, strict=False):
        if int(ordinal) in ends:
            marks.append((int(ordinal), float(value)))
    if not marks:
        return [], []
    out_ords: list[int] = []
    out_rets: list[float] = []
    prev = marks[0][1]
    # Each ordinal is the month-end that closes that return. When the curve
    # starts inside the first month, the first return runs from the initial
    # equity to that month-end. When the curve starts on a month-end, that
    # mark is only a level and the first return ends at the next month-end.
    initial = float(equity[0])
    if marks[0][0] != int(ords[0]) and initial > 0:
        out_rets.append(marks[0][1] / initial - 1.0)
        out_ords.append(marks[0][0])
    for ordinal, value in marks[1:]:
        if prev > 0 and math.isfinite(value):
            out_rets.append(value / prev - 1.0)
            out_ords.append(ordinal)
        prev = value
    return out_ords, out_rets


def performance(ords: Sequence[int], equity: Sequence[float], monthly: Sequence[float]) -> dict[str, Any]:
    eq = np.asarray(equity, dtype=np.float64)
    if len(eq) < 2 or eq[0] <= 0:
        return {"cagr": None, "max_drawdown": None, "sharpe": None, "total": None, "years": None}
    years = (int(ords[-1]) - int(ords[0])) / 365.25
    total = float(eq[-1] / eq[0] - 1.0)
    cagr = float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0) if years > 0.05 else None
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq / peak - 1.0))
    rets = np.asarray(list(monthly), dtype=np.float64)
    rets = rets[np.isfinite(rets)]
    sharpe = None
    if len(rets) >= 3 and float(np.std(rets, ddof=1)) > 1e-16:
        sharpe = float(np.sqrt(PERIODS_PER_YEAR) * np.mean(rets) / np.std(rets, ddof=1))
    return {
        "cagr": cagr,
        "max_drawdown": dd,
        "sharpe": sharpe,
        "total": total,
        "years": years,
        "n_months": int(len(rets)),
    }


def capacity_from_logs(logs: Sequence[dict[str, Any]], aum: float) -> dict[str, Any]:
    """AUM at which equal-weight participation hits 10% of ADV.

    ``thin`` uses the least liquid name that passed that rebalance.
    ``typical`` uses the median name. Both are medians across rebalances
    that had at least one passing name.
    """
    thin, typical, names = [], [], []
    for row in logs:
        n = int(row["n_pass"])
        names.append(n)
        if n <= 0 or row["median_adv"] <= 0:
            continue
        typical.append(PARTICIPATION_CAP * float(row["median_adv"]) * n)
        if row["min_adv"] > 0:
            thin.append(PARTICIPATION_CAP * float(row["min_adv"]) * n)
    return {
        "aum": aum,
        "median_names": float(np.median(names)) if names else 0.0,
        "min_names": int(min(names)) if names else 0,
        "max_names": int(max(names)) if names else 0,
        "n_rebalances": len(logs),
        "n_rebalances_with_names": int(sum(n > 0 for n in names)),
        "capacity_typical_10pct_adv": float(np.median(typical)) if typical else 0.0,
        "capacity_thin_10pct_adv": float(np.median(thin)) if thin else 0.0,
    }


def screen_names(
    rows: Sequence[NameRow],
    plv_max: float,
    pe_mode: str,
    bond_yield: float | None,
) -> list[NameRow]:
    return [
        row
        for row in rows
        if passes_screen(row.price, row.lv_per_share, row.eps, plv_max, pe_mode, bond_yield)
    ]


def small_cap_names(rows: Sequence[NameRow], quantile: float = SMALL_CAP_QUANTILE) -> list[NameRow]:
    sized = [row for row in rows if row.mcap is not None and row.mcap > 0 and row.price > 0]
    if not sized:
        return []
    caps = np.array([row.mcap for row in sized], dtype=np.float64)
    cut = float(np.quantile(caps, quantile))
    return [row for row in sized if row.mcap is not None and row.mcap <= cut]


def active_ticker(tickers: Sequence[tuple[str, int, int | None]], ordinal: int) -> list[str]:
    out = []
    for ticker, start, end in tickers:
        if ordinal < start:
            continue
        if end is not None and ordinal > end:
            continue
        out.append(ticker)
    return out


@dataclass
class Company:
    cnpj: str
    denom: str
    setor: str
    sit: str
    bs_con: list[BsPoint]
    bs_ind: list[BsPoint]
    shares: list[SharePoint]
    er_con: list[EarnRow]
    er_ind: list[EarnRow]
    tickers: list[tuple[str, int, int | None]]

    @property
    def financial(self) -> bool:
        return is_financial_setor(self.setor)

    @property
    def cancelled(self) -> bool:
        return self.sit == "CANCELADA"


def build_signal_rows(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    signal_ords: Sequence[int],
    extra_lag_days: int,
) -> dict[int, list[NameRow]]:
    """Fundamentals as of ``signal - extra_lag_days``. Price is the signal close."""
    table: dict[int, list[NameRow]] = {}
    for ordinal in signal_ords:
        asof = ordinal - int(extra_lag_days)
        rows: list[NameRow] = []
        for company in companies:
            if company.financial or not company.tickers:
                continue
            facts = fundamentals_asof(
                company.bs_con, company.bs_ind, company.shares, company.er_con, company.er_ind, asof
            )
            if facts is None:
                continue
            best: tuple[float, str, float, int] | None = None
            best_adv_sh = 0.0
            for ticker in active_ticker(company.tickers, ordinal):
                tape = tapes.get(ticker)
                if tape is None:
                    continue
                px, idx, stale = _close_on(tape, ordinal, PRICE_STALE_SESSIONS)
                if px is None or idx is None or stale:
                    continue
                adv_brl, adv_sh = trailing_adv(tape, idx)
                if best is None or adv_brl > best[0]:
                    best = (adv_brl, ticker, px, idx)
                    best_adv_sh = adv_sh
            if best is None:
                continue
            adv_brl, ticker, px, idx = best
            eps = earnings_per_share(facts.ttm_ni, facts.on_out)
            mcap = px * facts.total_out if facts.total_out > 0 else None
            rows.append(
                NameRow(
                    cnpj=company.cnpj,
                    ticker=ticker,
                    price=px,
                    lv_per_share=facts.lv_per_share,
                    eps=eps,
                    adv_brl=adv_brl,
                    adv_shares=best_adv_sh,
                    mcap=mcap,
                    idx=idx,
                )
            )
        table[int(ordinal)] = rows
    return table


def coverage_report(companies: Sequence[Company], tapes: dict[str, Tape]) -> dict[str, Any]:
    n = len(companies)
    financial = [c for c in companies if c.financial]
    operating = [c for c in companies if not c.financial]
    with_bs = [
        c
        for c in operating
        if c.bs_con or c.bs_ind
    ]
    with_ticker = [c for c in with_bs if c.tickers]
    with_price = [c for c in with_ticker if any(t in tapes and len(tapes[t].dates) for t, _s, _e in c.tickers)]
    no_price = [c for c in with_ticker if c not in with_price]
    no_ticker = [c for c in with_bs if not c.tickers]
    def _n_can(rows: Sequence[Company]) -> int:
        return sum(1 for c in rows if c.cancelled)
    return {
        "n_registrants": n,
        "n_cancelada": sum(1 for c in companies if c.cancelled),
        "n_financial_excluded": len(financial),
        "n_operating": len(operating),
        "n_operating_with_balance_sheet": len(with_bs),
        "n_with_on_ticker": len(with_ticker),
        "n_with_on_ticker_and_price": len(with_price),
        "n_ticker_without_price": len(no_price),
        "n_ticker_without_price_cancelada": _n_can(no_price),
        "n_ticker_without_price_active": sum(1 for c in no_price if c.sit == "ATIVO"),
        "n_balance_sheet_without_ticker": len(no_ticker),
        "n_balance_sheet_without_ticker_cancelada": _n_can(no_ticker),
    }


def _round(value: Any, ndigits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, ndigits)
    return value


def _stats_block(result: dict[str, Any]) -> dict[str, Any]:
    _m_ords, monthly = monthly_simple_returns(result["ords"], result["net"])
    _g_ords, monthly_g = monthly_simple_returns(result["ords"], result["gross"])
    net = performance(result["ords"], result["net"], monthly)
    gross = performance(result["ords"], result["gross"], monthly_g)
    stats: FillStats = result["stats"]
    return {
        "net": {k: _round(v, 6) for k, v in net.items()},
        "gross": {k: _round(v, 6) for k, v in gross.items()},
        "monthly_net": [round(float(x), 8) for x in monthly],
        "monthly_gross": [round(float(x), 8) for x in monthly_g],
        "delist_exits": result["delist_exits"],
        "double_exits": result["double_exits"],
        "time_exits": result["time_exits"],
        "fills": {
            "n": stats.n,
            "n_book": stats.n_book,
            "n_estimate": stats.n_estimate,
            "n_capped": stats.n_capped,
            "fee": round(stats.fee, 2),
            "half_spread": round(stats.half_spread, 2),
            "slippage": round(stats.slippage, 2),
            "mean_half_spread_bps": round(stats.half_spread_bps_sum / stats.n, 4) if stats.n else None,
        },
        "terminal_gap_brl": None
        if not result["gross"] or not result["net"]
        else round(float(result["gross"][-1]) - float(result["net"][-1]), 2),
        "cost_components_brl": round(stats.fee + stats.half_spread + stats.slippage, 2),
    }


def production_grid() -> list[dict[str, Any]]:
    """Every variation that will be registered. Fixed before any result is read."""
    specs: list[dict[str, Any]] = []

    def add(block: str, yield_name: str, lag: int, phase: int, aum: float) -> None:
        for name, plv, mode in FILTERS:
            specs.append(
                {
                    "block": block,
                    "filter": name,
                    "plv_max": plv,
                    "pe_mode": mode,
                    "yield": yield_name,
                    "lag_days": lag,
                    "phase": phase,
                    "aum": aum,
                }
            )

    add("primary", "pre_5y", 0, 0, 1_000_000.0)
    add("yield", "pre_long", 0, 0, 1_000_000.0)
    add("lag", "pre_5y", 63, 0, 1_000_000.0)
    for phase in (1, 2, 3):
        add("phase", "pre_5y", 0, phase, 1_000_000.0)
    for aum in (10_000_000.0, 50_000_000.0):
        add("capacity", "pre_5y", 0, 0, aum)
    return specs


def _selector_factory(spec: dict[str, Any], yields: dict[str, tuple[np.ndarray, np.ndarray]]):
    dates, values = yields[spec["yield"]]

    def selector(signal_ord: int, rows: list[NameRow], _positions: dict[str, Position]) -> list[NameRow]:
        yld = yield_asof(dates, values, signal_ord) if spec["pe_mode"] == "ey" else None
        return screen_names(rows, spec["plv_max"], spec["pe_mode"], yld)

    return selector


def run_study(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    yields: dict[str, tuple[np.ndarray, np.ndarray]],
    ibov_ords: np.ndarray,
    ibov_close: np.ndarray,
    registry_path: str,
    first_ord: int | None = None,
    grid: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the pre-specified grid, register every net path, then deflate by that N."""
    grid = grid if grid is not None else production_grid()
    if len(sessions) < 10:
        raise ValueError("need a session calendar")
    first = int(sessions[0] if first_ord is None else first_ord)
    last = int(sessions[-1]) - 10
    # Cache signal tables by (phase, lag).
    tables: dict[tuple[int, int], dict[int, list[NameRow]]] = {}
    for spec in grid:
        key = (int(spec["phase"]), int(spec["lag_days"]))
        if key in tables:
            continue
        signals = rebalance_signals(sessions, int(spec["phase"]), first, last)
        print(f"signals phase={key[0]} lag={key[1]} n={len(signals)}", flush=True)
        tables[key] = build_signal_rows(companies, tapes, signals, int(spec["lag_days"]))
    # Small-cap benchmark uses the primary calendar (phase 0, no extra lag).
    bench_table = tables.get((0, 0))
    if bench_table is None:
        signals = rebalance_signals(sessions, 0, first, last)
        bench_table = build_signal_rows(companies, tapes, signals, 0)
        tables[(0, 0)] = bench_table

    def bench_selector(_sig: int, rows: list[NameRow], _pos: dict[str, Position]) -> list[NameRow]:
        return small_cap_names(rows)

    census = _screen_census(bench_table, yields)
    benchmark = simulate(sessions, tapes, bench_table, bench_selector, 1_000_000.0, hold_until_exit=False)
    bench_block = _stats_block(benchmark)
    ibov = _ibov_stats(ibov_ords, ibov_close, benchmark["ords"])

    results: list[dict[str, Any]] = []
    with TrialRegistry(registry_path) as registry:
        preexisting = {trial.id for trial in registry.trials(FAMILY_ID)}
        for spec in grid:
            table = tables[(int(spec["phase"]), int(spec["lag_days"]))]
            selector = _selector_factory(spec, yields)
            print(
                f"trial {spec['block']} {spec['filter']} {spec['yield']} lag={spec['lag_days']} phase={spec['phase']} aum={spec['aum']:.0f}",
                flush=True,
            )
            run = simulate(sessions, tapes, table, selector, float(spec["aum"]), hold_until_exit=True)
            block = _stats_block(run)
            monthly = block["monthly_net"]
            cap = capacity_from_logs(run["logs"], float(spec["aum"]))
            params = {
                "family": FAMILY_ID,
                "filter": spec["filter"],
                "plv_max": spec["plv_max"],
                "pe_mode": spec["pe_mode"],
                "yield_proxy": spec["yield"],
                "extra_lag_days": spec["lag_days"],
                "phase": spec["phase"],
                "aum_brl": spec["aum"],
                "block": spec["block"],
                "exit": "double_or_2y",
                "rebalance_months": 4,
                "costs": "fee+half_spread+participation_slippage",
            }
            if len(monthly) >= 3:
                registry.register(
                    FAMILY_ID,
                    params,
                    returns=monthly,
                    costs_included=True,
                    periods_per_year=PERIODS_PER_YEAR,
                    notes=spec["block"],
                )
            results.append({"spec": spec, "performance": block, "capacity": cap, "params": params})
        n_trials = registry.count(FAMILY_ID)
        stored = [trial for trial in registry.trials(FAMILY_ID) if trial.id not in preexisting]
        try:
            eff = registry.effective_n_trials(FAMILY_ID)
        except ValueError:
            eff = {"n_eff": None, "mean_corr": None, "n": 0}
        for item, trial in zip(
            [row for row in results if len(row["performance"]["monthly_net"]) >= 3],
            stored,
            strict=False,
        ):
            monthly = item["performance"]["monthly_net"]
            judged = gate(
                costs_included=True,
                returns=monthly,
                n_trials=float(n_trials),
                periods_per_year=PERIODS_PER_YEAR,
                n_eff=None,
                trial_sharpes=None,
            )
            sr_star = judged.sr_star
            item["inference"] = {
                "psr": judged.psr,
                "dsr": judged.dsr,
                "sr_star": sr_star,
                "min_trl_months": None if judged.min_trl is None or not math.isfinite(judged.min_trl) else judged.min_trl,
                "min_trl_infinite": bool(judged.min_trl is not None and not math.isfinite(judged.min_trl)),
                "n_obs_months": judged.n_obs,
                "n_trials": n_trials,
                "sharpe": judged.observed_sharpe,
                "approved_for_paper": bool(judged.approved),
                "reasons": judged.reasons,
                "trial_id": trial.id,
            }
    # Attach inference to rows that were registered, matched by params hash order.
    # Rows with <3 months have no inference. Recompute explicitly to avoid zip drift.
    with TrialRegistry(registry_path) as registry:
        by_id = {trial.id: trial for trial in registry.trials(FAMILY_ID)}
    for item in results:
        inf = item.get("inference")
        if not inf:
            continue
        trial = by_id.get(inf["trial_id"])
        if trial is None:
            continue
        item["inference"]["costs_included"] = trial.costs_included
    any_dsr = [
        (item["inference"]["dsr"], item)
        for item in results
        if item.get("inference") and item["inference"]["dsr"] is not None
    ]
    best = max(any_dsr, key=lambda pair: (pair[0], pair[1]["performance"]["net"]["cagr"] or -1))[1] if any_dsr else None
    primary = [
        item
        for item in results
        if item["spec"]["block"] == "primary"
    ]
    audit = _audit_block(primary, bench_block)
    return {
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "n_trials": n_trials,
        "n_eff": None if eff.get("n_eff") is None else round(float(eff["n_eff"]), 4),
        "mean_pairwise_corr": None if eff.get("mean_corr") is None else round(float(eff["mean_corr"]), 4),
        "dsr_n": "all_registered_trials",
        "periods_per_year": PERIODS_PER_YEAR,
        "coverage": coverage_report(companies, tapes),
        "sample": {
            "first_session": date.fromordinal(int(sessions[0])).isoformat(),
            "last_session": date.fromordinal(int(sessions[-1])).isoformat(),
            "first_signal_on_or_after": date.fromordinal(first).isoformat(),
        },
        "screen_census": census,
        "benchmark_ew_small": bench_block,
        "benchmark_ibov": ibov,
        "primary": [_public_row(item) for item in primary],
        "trials": [_public_row(item) for item in results],
        "best_by_dsr": None if best is None else _public_row(best),
        "audit": audit,
        "verdict": _verdict(primary, results, bench_block, ibov),
        "paper_reference": {
            "source": "Greenblatt, Pzena & Newberg, JPM 1981",
            "best_filter_cagr_gross": 0.42,
            "best_filter_cagr_net": 0.29,
            "sample": "1972-1978 US OTC",
        },
    }


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _audit_block(primary: list[dict], benchmark: dict[str, Any]) -> dict[str, Any]:
    """Why a sparse net-net book can print a -99% drawdown, and what was fixed."""

    def identity(perf: dict[str, Any]) -> dict[str, Any]:
        # Half-spread is floored at zero when the touch is inside the close, so
        # the cash gap can sit a little under the sum of the reported components.
        # A double charge or a cash bleed would miss by a large fraction.
        gap = _as_float(perf.get("terminal_gap_brl"))
        costs = _as_float(perf.get("cost_components_brl"))
        residual = None if gap is None or costs is None else costs - gap
        tolerance = 50.0 if costs is None else max(50.0, 1e-3 * abs(costs))
        holds = residual is not None and 0 <= residual <= tolerance
        return {
            "terminal_gap_brl": gap,
            "cost_components_brl": costs,
            "identity_holds": holds,
            "cagr_gross": perf["gross"]["cagr"],
            "cagr_net": perf["net"]["cagr"],
            "max_drawdown_gross": perf["gross"]["max_drawdown"],
            "max_drawdown_net": perf["net"]["max_drawdown"],
            "fills_n": perf["fills"]["n"],
            "fills_capped": perf["fills"]["n_capped"],
            "slippage_brl": perf["fills"]["slippage"],
        }

    return {
        "finding": (
            "Primary drawdown near -99% matches a net CAGR near -24% compounded "
            "for about 16 years. It is not a cash charge, not a daily charge on "
            "the whole book, and not a drawdown taken on the wrong series. Gross "
            "and net hold the same shares. The terminal wealth gap matches fee + "
            "half-spread + slippage; a touch inside the close is recorded as zero "
            "half-spread, so the gap can sit slightly under that sum. Slippage is "
            "almost all of the gap. The book is in cash on most rebalances. The "
            "few entries invest the whole NAV in one or two names, far above 10% "
            "of ADV, so the linear participation model hits its 5000 bps cap. "
            "That cost is what the published model charges. A separate bug did "
            "inflate the equal-weight small-cap benchmark: replacing the book "
            "sold and rebought names that stayed, paying spread and slippage on "
            "the whole book every rebalance. Replacement now trades only the "
            "weight change. The primary path holds until exit and did not take "
            "that round trip."
        ),
        "primary": [{"filter": item["spec"]["filter"], **identity(item["performance"])} for item in primary],
        "benchmark_ew_small": identity(benchmark),
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def _screen_census(
    table: dict[int, list[NameRow]],
    yields: dict[str, tuple[np.ndarray, np.ndarray]],
) -> dict[str, Any]:
    """How many names exist and how many pass, before any path is a trial.

    Counts are a description of the primary calendar. They are not registered.
    """
    dates, values = yields["pre_5y"]
    per_signal = []
    for ordinal, rows in sorted(table.items()):
        yld = yield_asof(dates, values, int(ordinal))
        n_positive = n_plv1 = n_plv085 = 0
        for row in rows:
            lv = row.lv_per_share
            if lv is None or lv <= 0 or row.price <= 0:
                continue
            n_positive += 1
            plv = row.price / lv
            if plv <= 1.0:
                n_plv1 += 1
            if plv <= 0.85:
                n_plv085 += 1
        per_signal.append(
            {
                "signal": date.fromordinal(int(ordinal)).isoformat(),
                "n_universe": len(rows),
                "n_positive_lv": n_positive,
                "n_plv_le_1": n_plv1,
                "n_plv_le_085": n_plv085,
                "n_plv1_ey": len(screen_names(rows, 1.0, "ey", yld)),
                "n_plv085_ey": len(screen_names(rows, 0.85, "ey", yld)),
                "n_plv1_pe5": len(screen_names(rows, 1.0, "pe5", None)),
                "n_plv085_pe5": len(screen_names(rows, 0.85, "pe5", None)),
                "yield_pre_5y": None if yld is None else round(float(yld), 4),
            }
        )

    def med(key: str) -> float:
        if not per_signal:
            return 0.0
        return float(np.median([row[key] for row in per_signal]))

    return {
        "calendar": "phase 0, no extra lag",
        "n_signals": len(per_signal),
        "median_universe": med("n_universe"),
        "median_positive_lv": med("n_positive_lv"),
        "median_plv_le_1": med("n_plv_le_1"),
        "median_plv_le_085": med("n_plv_le_085"),
        "median_plv1_ey": med("n_plv1_ey"),
        "median_plv1_pe5": med("n_plv1_pe5"),
        "per_signal": per_signal,
    }


def _verdict(primary: list[dict], results: list[dict], bench: dict[str, Any], ibov: dict[str, Any]) -> dict[str, Any]:
    def cleared(item: dict) -> bool:
        inf = item.get("inference") or {}
        net = item["performance"]["net"]["cagr"]
        return bool(inf.get("approved_for_paper")) and net is not None and net > 0

    bench_cagr = bench["net"]["cagr"]
    return {
        "survives_costs_and_dsr": any(cleared(item) for item in results),
        "primary_survives_costs_and_dsr": any(cleared(item) for item in primary),
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "benchmark_ew_small_cagr_net": bench_cagr,
        "benchmark_ibov_cagr": ibov.get("cagr"),
        "note": (
            "Aprovado para paper só com custos no retorno, DSR >= 0,95 usando N de todas "
            "as variações registradas, e trilha pelo menos tão longa quanto o MinTRL. "
            "Isso não autoriza capital."
        ),
    }


def _public_row(item: dict[str, Any]) -> dict[str, Any]:
    perf = item["performance"]
    inf = item.get("inference") or {}
    return {
        "block": item["spec"]["block"],
        "filter": item["spec"]["filter"],
        "yield_proxy": item["spec"]["yield"],
        "lag_days": item["spec"]["lag_days"],
        "phase": item["spec"]["phase"],
        "aum_brl": item["spec"]["aum"],
        "cagr_gross": perf["gross"]["cagr"],
        "cagr_net": perf["net"]["cagr"],
        "sharpe_net": perf["net"]["sharpe"],
        "max_drawdown_gross": perf["gross"]["max_drawdown"],
        "max_drawdown_net": perf["net"]["max_drawdown"],
        "terminal_gap_brl": perf.get("terminal_gap_brl"),
        "cost_components_brl": perf.get("cost_components_brl"),
        "years": perf["net"]["years"],
        "psr": inf.get("psr"),
        "dsr": inf.get("dsr"),
        "min_trl_months": inf.get("min_trl_months"),
        "min_trl_infinite": inf.get("min_trl_infinite"),
        "n_obs_months": inf.get("n_obs_months"),
        "n_trials": inf.get("n_trials"),
        "approved_for_paper": inf.get("approved_for_paper", False),
        "capacity": item["capacity"],
        "delist_exits": perf["delist_exits"],
        "double_exits": perf["double_exits"],
        "time_exits": perf["time_exits"],
        "fills": perf["fills"],
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def _series_is_daily(ords: np.ndarray) -> bool:
    """A monthly chart has a median gap of about 30 days. That is not this benchmark."""
    if len(ords) < 3:
        return False
    gaps = np.diff(np.asarray(ords, dtype=np.int64))
    return float(np.median(gaps)) <= 5


def _ibov_stats(ords: np.ndarray, close: np.ndarray, sample_ords: Sequence[int]) -> dict[str, Any]:
    if len(ords) == 0 or not sample_ords:
        return {"available": False}
    start, end = int(sample_ords[0]), int(sample_ords[-1])
    mask = (ords >= start) & (ords <= end)
    if int(mask.sum()) < 3:
        return {"available": False}
    if not _series_is_daily(ords[mask]):
        return {
            "available": False,
            "note": "Ibovespa series is coarser than daily, so it was not used as a benchmark.",
        }
    use_ords = ords[mask]
    use_px = close[mask]
    _m_ords, monthly = monthly_simple_returns(use_ords.tolist(), use_px.tolist())
    stats = performance(use_ords.tolist(), use_px.tolist(), monthly)
    return {
        "available": True,
        "note": (
            "Official Ibovespa level (B3 defines it as a gross total-return index, "
            "so cash dividends are already reinvested in the published series). "
            "No extra dividend was added. No investor cost."
        ),
        **{k: _round(v) for k, v in stats.items()},
    }


def track_record_months(min_trl: float | None, n_obs: int | None) -> str:
    if n_obs is None:
        return "sem trilha"
    if min_trl is None:
        return f"{n_obs} meses observados; MinTRL indefinido"
    if not math.isfinite(min_trl):
        return f"{n_obs} meses observados; MinTRL infinito (Sharpe não supera SR*)"
    return f"{n_obs} meses observados contra MinTRL de {min_trl:.0f} meses"

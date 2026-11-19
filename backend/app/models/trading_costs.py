"""Paper fill costs: fee, half-spread, and size-dependent slippage.

Net P&L is the mid-to-mid mark minus ``fee + half_spread + slippage - spread_capture``.
Each component is stored on its own. Nothing in this module sends an order.

Half-spread comes from the bid/ask at the fill. When the book is missing, or the
quotes were synthesized from a bps assumption, the half-spread is the configured
estimate and ``spread_source`` is ``"estimate"``.

Slippage (taker) is linear in participation::

    slippage_bps = impact_bps * abs(qty) / depth

``impact_bps`` is the extra bps paid when the order equals the displayed size
at the touch (default 10). When that size is missing, slippage falls back to
``fallback_slippage_bps`` (default 0 — no invented walk of the book) and
``slippage_source`` is ``"estimate"``.

A maker fill rests at its limit: it pays the maker fee, does not cross, and
does not walk the book. Any improvement versus the mid is ``spread_capture``.

Pairs round-trip is four legs (enter and exit, both legs). As a fraction of
gross two-leg notional that is ``2 * rate``, because each leg pays ``rate`` of
its own notional and the two notionals sum to gross, twice (open and close).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, TypeGuard


# Taker bps match the desk schedules already used by the perp scanner
# (binance USDM 4, OKX 5, Hyperliquid 3.5) and the pairs books (B3 5, spot 10).
# Maker bps are the passive schedule for the limit simulator. Research
# assumptions, not a live fee pull — override per call.
@dataclass(frozen=True)
class VenueFees:
    maker_bps: float
    taker_bps: float


VENUE_FEES: dict[str, VenueFees] = {
    "binance_usdm": VenueFees(maker_bps=2.0, taker_bps=4.0),
    "binance": VenueFees(maker_bps=2.0, taker_bps=4.0),
    "okx": VenueFees(maker_bps=2.0, taker_bps=5.0),
    "hyperliquid": VenueFees(maker_bps=1.5, taker_bps=3.5),
    "b3": VenueFees(maker_bps=5.0, taker_bps=5.0),
    "crypto_spot": VenueFees(maker_bps=10.0, taker_bps=10.0),
    "default": VenueFees(maker_bps=5.0, taker_bps=10.0),
}

# Documented half-spread when no firm book is available. The pairs books
# historically passed this 2 bps under the name "slippage"; it is a half-spread
# estimate, not a measured touch and not a walk of the book.
DEFAULT_HALF_SPREAD_BPS = 2.0
DEFAULT_IMPACT_BPS = 10.0
DEFAULT_FALLBACK_SLIPPAGE_BPS = 0.0
DEFAULT_ENTRY_K = 2.0
DEFAULT_MAX_SPREAD_BPS = 25.0
DEFAULT_MIN_VOLUME = 0.0


@dataclass(frozen=True)
class BookTop:
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    mid: float | None = None
    volume: float | None = None
    # True when bid/ask were built from mid ± a bps guess rather than a snapshot.
    estimated: bool = False


@dataclass(frozen=True)
class FillCost:
    fee: float
    half_spread: float
    slippage: float
    spread_capture: float
    notional: float
    qty: float
    side: str
    liquidity: str
    fee_bps: float
    half_spread_bps: float
    slippage_bps: float
    spread_source: str
    slippage_source: str
    fill_px: float
    flagged_estimate: bool
    venue: str

    @property
    def total(self) -> float:
        """Cash drag versus filling at the mid. Capture reduces it."""
        return self.fee + self.half_spread + self.slippage - self.spread_capture

    def as_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["total"] = self.total
        return raw


@dataclass(frozen=True)
class LiquidityDecision:
    ok: bool
    reason: str | None
    spread_bps: float | None
    volume: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def venue_fees(venue: str | None, override: VenueFees | None = None) -> VenueFees:
    if override is not None:
        return override
    key = (venue or "default").strip().lower()
    return VENUE_FEES.get(key, VENUE_FEES["default"])


def _finite_positive(value: float | None) -> TypeGuard[float]:
    return value is not None and math.isfinite(value) and value > 0


def quote_fill(
    *,
    side: str,
    qty: float,
    mid: float,
    venue: str = "default",
    liquidity: str = "taker",
    book: BookTop | None = None,
    limit_px: float | None = None,
    fallback_half_spread_bps: float = DEFAULT_HALF_SPREAD_BPS,
    impact_bps: float = DEFAULT_IMPACT_BPS,
    fallback_slippage_bps: float = DEFAULT_FALLBACK_SLIPPAGE_BPS,
    fee_bps: float | None = None,
    fees: VenueFees | None = None,
) -> FillCost:
    """Price one fill and split its cost versus ``mid``.

    ``qty`` is an absolute size. ``side`` is ``buy`` or ``sell``.
    ``liquidity`` is ``taker`` (cross the touch, then walk) or ``maker``
    (rest at ``limit_px``, or at the passive touch when the book is real).
    """
    side_n = side.lower().strip()
    liq = liquidity.lower().strip()
    if side_n not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if liq not in ("taker", "maker"):
        raise ValueError("liquidity must be taker or maker")
    if not _finite_positive(mid) or not math.isfinite(qty) or qty == 0:
        raise ValueError("mid must be positive and qty non-zero")
    if fallback_half_spread_bps < 0 or impact_bps < 0 or fallback_slippage_bps < 0:
        raise ValueError("bps assumptions cannot be negative")

    abs_qty = abs(float(qty))
    book = book or BookTop()
    book_mid = book.mid
    ref_mid = float(book_mid) if _finite_positive(book_mid) else float(mid)
    bid = book.bid
    ask = book.ask
    bid_px = float(bid) if _finite_positive(bid) else None
    ask_px = float(ask) if ask is not None and math.isfinite(ask) else None
    flagged_spread = False
    if bid_px is not None and ask_px is not None and ask_px >= bid_px:
        use_touch = True
        touch = ask_px if side_n == "buy" else bid_px
        half_paid = (touch - ref_mid) if side_n == "buy" else (ref_mid - touch)
        spread_source = "estimate" if book.estimated else "book"
        flagged_spread = bool(book.estimated)
    else:
        use_touch = False
        half_paid = ref_mid * float(fallback_half_spread_bps) / 10_000.0
        touch = ref_mid + half_paid if side_n == "buy" else ref_mid - half_paid
        spread_source = "estimate"
        flagged_spread = True

    capture = 0.0
    if liq == "maker":
        chosen = limit_px
        if chosen is None:
            if use_touch and not book.estimated and bid_px is not None and ask_px is not None:
                chosen = bid_px if side_n == "buy" else ask_px
            else:
                chosen = ref_mid
        fill_px = float(chosen)
        if not math.isfinite(fill_px) or fill_px <= 0:
            raise ValueError("maker limit must be a positive price")
        half_spread = 0.0
        slippage = 0.0
        slip_bps = 0.0
        slippage_source = "limit"
        favorable = (ref_mid - fill_px) if side_n == "buy" else (fill_px - ref_mid)
        capture = abs_qty * max(favorable, 0.0)
        half_bps = 0.0
    else:
        raw_depth = book.ask_size if side_n == "buy" else book.bid_size
        if _finite_positive(raw_depth):
            slip_bps = float(impact_bps) * (abs_qty / raw_depth)
            slippage_source = "depth"
        else:
            slip_bps = float(fallback_slippage_bps)
            slippage_source = "estimate"
        slip_px = ref_mid * slip_bps / 10_000.0
        fill_px = touch + slip_px if side_n == "buy" else touch - slip_px
        half_spread = abs_qty * max(half_paid, 0.0)
        slippage = abs_qty * slip_px
        half_bps = (half_spread / (abs_qty * ref_mid) * 10_000.0) if ref_mid else 0.0

    if fill_px <= 0 or not math.isfinite(fill_px):
        raise ValueError("fill price is not positive")
    notional = abs_qty * fill_px
    if fee_bps is None:
        sched = venue_fees(venue, fees)
        fee_bps = sched.maker_bps if liq == "maker" else sched.taker_bps
    if fee_bps < 0:
        raise ValueError("fee_bps cannot be negative")
    fee = notional * float(fee_bps) / 10_000.0
    return FillCost(
        fee=fee,
        half_spread=half_spread,
        slippage=slippage,
        spread_capture=capture,
        notional=notional,
        qty=abs_qty,
        side=side_n,
        liquidity=liq,
        fee_bps=float(fee_bps),
        half_spread_bps=float(half_bps),
        slippage_bps=float(slip_bps),
        spread_source=spread_source,
        slippage_source=slippage_source,
        fill_px=float(fill_px),
        flagged_estimate=bool(flagged_spread or slippage_source == "estimate"),
        venue=(venue or "default").lower(),
    )


def cash_delta(cost: FillCost) -> float:
    """Signed cash change of the fill (buys spend, sells receive), fee included."""
    if cost.side == "buy":
        return -(cost.qty * cost.fill_px + cost.fee)
    return cost.qty * cost.fill_px - cost.fee


def leg_rate_bps(fee_bps: float, half_spread_bps: float, slippage_bps: float) -> float:
    if min(fee_bps, half_spread_bps, slippage_bps) < 0:
        raise ValueError("component bps cannot be negative")
    return float(fee_bps) + float(half_spread_bps) + float(slippage_bps)


def four_leg_fraction(fee_bps: float, half_spread_bps: float, slippage_bps: float) -> float:
    """Open and close on both legs, as a fraction of gross two-leg notional.

    Each leg pays ``rate`` of its own notional. Those notionals sum to the
    gross, and the book pays that once to enter and once to exit: ``2 * rate``.
    """
    return 2.0 * leg_rate_bps(fee_bps, half_spread_bps, slippage_bps) / 10_000.0


def four_leg_dollars(
    y_notional: float,
    x_notional: float,
    fee_bps: float,
    half_spread_bps: float,
    slippage_bps: float,
) -> float:
    """Same four fills, in currency. Gross notional is ``|y| + |x|``."""
    rate = leg_rate_bps(fee_bps, half_spread_bps, slippage_bps) / 10_000.0
    return 2.0 * rate * (abs(float(y_notional)) + abs(float(x_notional)))


def entry_allowed(expected_gain: float, round_trip_cost: float, k: float = DEFAULT_ENTRY_K) -> bool:
    """Enter only when the expected gain covers ``k`` times the round-trip cost.

    ``k <= 0`` turns the gate off (research clocks that must replay an old
    path). Non-finite inputs do not enter.
    """
    if k <= 0:
        return True
    if not math.isfinite(expected_gain) or not math.isfinite(round_trip_cost):
        return False
    if round_trip_cost < 0:
        raise ValueError("round_trip_cost cannot be negative")
    return expected_gain + 1e-15 >= k * round_trip_cost


def pairs_entry_allowed(
    expected_gain: float,
    fee_bps: float,
    half_spread_bps: float,
    slippage_bps: float,
    k: float = DEFAULT_ENTRY_K,
) -> bool:
    """Pairs gate. The hurdle is ``k`` times the four-leg cost, not one leg."""
    return entry_allowed(
        expected_gain,
        four_leg_fraction(fee_bps, half_spread_bps, slippage_bps),
        k,
    )


def spread_bps(bid: float, ask: float, mid: float) -> float:
    if not _finite_positive(mid) or not math.isfinite(bid) or not math.isfinite(ask) or ask < bid:
        return float("inf")
    return (ask - bid) / mid * 10_000.0


def check_liquidity(
    *,
    spread_bps_value: float | None,
    volume: float | None,
    max_spread_bps: float = DEFAULT_MAX_SPREAD_BPS,
    min_volume: float = DEFAULT_MIN_VOLUME,
) -> LiquidityDecision:
    """Refuse a signal when the book is too wide or too thin.

    ``min_volume <= 0`` disables the size floor. A positive floor with no
    volume observation is ``volume_unavailable`` — the signal is skipped and
    the reason is logged, rather than treated as liquid.
    """
    if max_spread_bps < 0 or min_volume < 0:
        raise ValueError("liquidity limits cannot be negative")
    width = None if spread_bps_value is None else float(spread_bps_value)
    if width is not None and math.isfinite(width) and width > max_spread_bps:
        return LiquidityDecision(False, "spread", width, volume)
    if min_volume > 0:
        if volume is None or not math.isfinite(volume):
            return LiquidityDecision(False, "volume_unavailable", width, volume)
        if volume < min_volume:
            return LiquidityDecision(False, "volume", width, volume)
    return LiquidityDecision(True, None, width, volume)


def limit_cross_index(
    prices: list[float] | tuple[float, ...],
    origin: float,
    level: float,
    timeout: int,
) -> int | None:
    """Index of the first bar that crosses ``level``, or None.

    A cross is a move from one side of ``level`` to the other (or onto it).
    Starting on the level is not a fill. ``timeout`` is the last index, inclusive,
    that is still allowed to fill. Prices after ``timeout`` are ignored.
    """
    if timeout < 0:
        return None
    if not math.isfinite(origin) or not math.isfinite(level):
        return None
    prev = float(origin)
    last = min(int(timeout), len(prices) - 1)
    for t in range(last + 1):
        px = float(prices[t])
        if not math.isfinite(px):
            prev = px
            continue
        crossed = (prev < level <= px) or (prev > level >= px)
        if crossed:
            return t
        prev = px
    return None


def classify_limit(
    prices: list[float] | tuple[float, ...],
    origin: float,
    level: float,
    timeout: int,
) -> str:
    """``filled``, ``expired`` (clock ran out before a cross), or ``unfilled``.

    ``unfilled`` means the path ended without a cross and the timeout was at
    least as long as the path, so the order was not cut off early.
    """
    idx = limit_cross_index(prices, origin, level, timeout)
    if idx is not None:
        return "filled"
    if timeout < len(prices) - 1:
        return "expired"
    return "unfilled"


def costs_included_flag(*, round_trip_cost: float, model_applied: bool) -> bool:
    """True only when the registered returns were actually net of the model.

    A zero round-trip (fees and spread and slippage all off) is not "costs
    included". Gross series must pass ``model_applied=False``.
    """
    return bool(model_applied) and math.isfinite(round_trip_cost) and round_trip_cost > 0

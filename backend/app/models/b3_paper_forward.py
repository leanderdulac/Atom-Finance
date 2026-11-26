"""Forward paper books on B3. Research only. No order leaves this process.

Two sleeves start at the close of 2026-11-23. Portfolio B's first membership is
the equal-weight small-cap rule in ``equal_weight.build_signal_book``, applied
to information through 2026-11-19 and then frozen. Later quarters call that
same function. ``eligible_for_live_trading`` stays false.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from app.models.corporate_actions import cash_scale_at
from app.models.equal_weight import (
    SMALL_MIN_NAMES,
    UNKNOWN_WITHHOLDING,
    Ledger,
    Position,
    Target,
    _apply_splits,
    _close_on,
    _credit,
    _rebalance,
    _sell,
    build_signal_book,
    event_arrays,
    plausible_cash,
)
from app.models.equal_weight_io import CashEvent, Listing, listings_from_tapes, share_class_of_ticker
from app.models.net_net import (
    DELIST_STALE_SESSIONS,
    Company,
    FillStats,
    Tape,
    execution_book,
    monthly_simple_returns,
    performance,
    price_fill,
    trailing_adv,
)
from app.models.trading_costs import cash_delta

ELIGIBLE_FOR_LIVE_TRADING = False
FAMILY_ID = "b3_paper_forward"
SIGNAL_SESSION = date(2026, 11, 19)
ENTRY_SESSION = date(2026, 11, 23)
A_AUM = 1_000_000.0
B_AUM = 100_000.0
A_CDI_WEIGHT = 0.70
A_BOVA_WEIGHT = 0.30
A_BAND_LOW = 0.25
A_BAND_HIGH = 0.35
BOVA_TICKER = "BOVA11"
BOVA_ADMIN_FEE = 0.001
COMBINED_A = 0.90
COMBINED_B = 0.10
B_UNIVERSE = "small"
B_ADV_FLOOR = 200_000.0
B_FREQUENCY = "quarterly"
B_MIN_NAMES = SMALL_MIN_NAMES
COME_COTAS_RATE = 0.15
BOVA_IR_RATE = 0.15
JCP_AND_UNKNOWN_RATE = UNKNOWN_WITHHOLDING
# Locked reference for the R$ 100k sleeve of the equal-weight study.
B_REF_FULL_CAGR = 0.384
B_REF_OOS_CAGR = 0.446
B_REF_SHARPE = 0.73
B_REF_MAX_DD = -0.613
B_REF_OOS_EXCESS_OVER_CDI = 0.350
GENESIS_PREV = "0" * 64
OPENING_CASH_DATE = "2026-11-22"

_REPO = Path(__file__).resolve().parents[3]


class PaperError(Exception):
    pass


class LedgerIntegrityError(PaperError):
    pass


class LedgerTimeError(LedgerIntegrityError):
    """A mark is older than the log, or it uses a price after the session."""


class PaperDataError(PaperError):
    pass


def paper_root() -> Path:
    raw = os.environ.get("ATOM_B3_PAPER_ROOT")
    if raw:
        return Path(raw)
    return _REPO / "docs" / "reports"


def preregistration_path(root: Path | None = None) -> Path:
    return (root or paper_root()) / "b3-paper-preregistration.json"


def paper_dir(root: Path | None = None) -> Path:
    return (root or paper_root()) / "b3_paper"


def regressive_ir_rate(holding_days: int) -> float:
    """IR on fixed-income funds. ``holding_days`` is the calendar gap between dates."""
    if holding_days < 0:
        raise ValueError("holding days cannot be negative")
    if holding_days <= 180:
        return 0.225
    if holding_days <= 360:
        return 0.20
    if holding_days <= 720:
        return 0.175
    return 0.15


def outside_bova_band(weight: float) -> bool:
    """True when BOVA11 is strictly outside [25%, 35%]. Endpoints stay inside."""
    rounded = round(float(weight), 6)
    return rounded < A_BAND_LOW or rounded > A_BAND_HIGH


def combined_multiplier(a_equity: float, b_equity: float) -> float:
    """Initial 90/10 mix of the two sleeves. The mix is not rebalanced later."""
    return COMBINED_A * (a_equity / A_AUM) + COMBINED_B * (b_equity / B_AUM)


def monthly_mean_from_cagr(cagr: float) -> float:
    return (1.0 + cagr) ** (1.0 / 12.0) - 1.0


def reference_monthly_vol() -> float:
    """Monthly vol implied by the full-sample geometric mean and the published Sharpe.

    Sharpe here is ``sqrt(12) * mean(monthly simple returns) / sample std``.
    The published figure is a full-sample Sharpe, and the numerator used to
    invert it is the monthly geometric mean of the full-sample CAGR, not the
    arithmetic mean. The gap is part of the frozen definition.
    """
    mu = monthly_mean_from_cagr(B_REF_FULL_CAGR)
    return mu * math.sqrt(12.0) / B_REF_SHARPE


def tracking_vs_backtest(monthly_returns: Sequence[float]) -> dict[str, Any]:
    """Z-score of B's monthly mean against the frozen R$ 100k expectation."""
    mu_oos = monthly_mean_from_cagr(B_REF_OOS_CAGR)
    mu_full = monthly_mean_from_cagr(B_REF_FULL_CAGR)
    sigma = reference_monthly_vol()
    rows = [float(item) for item in monthly_returns if math.isfinite(float(item))]
    n = len(rows)
    base = {
        "n_months": n,
        "oos_cagr": B_REF_OOS_CAGR,
        "full_sample_cagr": B_REF_FULL_CAGR,
        "reference_sharpe": B_REF_SHARPE,
        "reference_max_drawdown": B_REF_MAX_DD,
        "monthly_mean_oos": mu_oos,
        "monthly_mean_full": mu_full,
        "monthly_vol": sigma,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }
    if n == 0:
        base.update({"z_oos": None, "z_full": None, "outside_95": None, "preliminary": True})
        return base
    mean = sum(rows) / n
    se = sigma / math.sqrt(n)
    z_oos = (mean - mu_oos) / se
    z_full = (mean - mu_full) / se
    wealth = 1.0
    for item in rows:
        wealth *= 1.0 + item
    log_mu = math.log1p(mu_oos)
    cum_lo = math.exp(n * log_mu - 1.96 * sigma * math.sqrt(n)) - 1.0
    cum_hi = math.exp(n * log_mu + 1.96 * sigma * math.sqrt(n)) - 1.0
    base.update(
        {
            "realized_monthly_mean": mean,
            "z_oos": z_oos,
            "z_full": z_full,
            "mean_interval_95": [mu_oos - 1.96 * se, mu_oos + 1.96 * se],
            "realized_cumulative": wealth - 1.0,
            "expected_cumulative_oos": (1.0 + mu_oos) ** n - 1.0,
            "cumulative_interval_95": [cum_lo, cum_hi],
            "outside_95": abs(z_oos) > 2.0 and n >= 3,
            "preliminary": n < 3,
        }
    )
    return base


def truncate_tapes(tapes: Mapping[str, Tape], ordinal: int) -> dict[str, Tape]:
    """Drop every print after ``ordinal``. A later close cannot enter the mark."""
    out: dict[str, Tape] = {}
    for ticker, tape in tapes.items():
        idx = tape.index_on_or_before(int(ordinal))
        if idx is None:
            continue
        stop = idx + 1
        if int(tape.dates[stop - 1]) > int(ordinal):
            raise PaperDataError(f"{ticker} tape is not ordered")
        source = None if tape.split_source is None else tape.split_source[:stop].copy()
        scale = None if tape.heuristic_cash_scale is None else tape.heuristic_cash_scale[:stop].copy()
        out[ticker] = Tape(
            tape.dates[:stop].copy(),
            tape.close[:stop].copy(),
            tape.bid[:stop].copy(),
            tape.ask[:stop].copy(),
            tape.qty[:stop].copy(),
            tape.vol[:stop].copy(),
            tape.split[:stop].copy(),
            source,
            scale,
        )
    return out


def _clip_listings(listings: Sequence[Listing], ordinal: int) -> list[Listing]:
    clipped: list[Listing] = []
    for item in listings:
        if int(item.start) > ordinal:
            continue
        end = item.end
        if end is not None and int(end) > ordinal:
            end = None
        clipped.append(Listing(item.cnpj, item.ticker, int(item.start), None if end is None else int(end), item.share_class))
    return clipped


def select_small_book(
    companies: Sequence[Company],
    listings: Sequence[Listing],
    tapes: Mapping[str, Tape],
    asof: date,
) -> dict[str, Any]:
    """Equal-weight small book. Membership is ``build_signal_book`` with no extra filter.

    Tape-only listings are rebuilt from prints on or before ``asof``. A filed
    end date after ``asof`` is ignored. Share counts already ignore receipts
    after the signal, inside ``build_signal_book``.
    """
    ordinal = asof.toordinal()
    visible = truncate_tapes(tapes, ordinal)
    filed = _clip_listings(listings, ordinal)
    universe = listings_from_tapes(visible, filed, ordinal)
    book = build_signal_book(companies, universe, visible, [ordinal], B_UNIVERSE, B_ADV_FLOOR, min_names=B_MIN_NAMES)
    rows = list(book.get(ordinal, []))
    n = len(rows)
    weight = 0.0 if n == 0 else 1.0 / n
    names: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item.ticker):
        if row.adv_brl < B_ADV_FLOOR:
            raise PaperError(f"{row.ticker} is below the ADV floor")
        tape = visible.get(row.ticker)
        close = None
        if tape is not None:
            px, _idx, stale = _close_on(tape, ordinal, 10**9)
            if px is not None and not stale:
                close = float(px)
        names.append(
            {
                "ticker": row.ticker,
                "cnpj": row.cnpj,
                "adv_brl": float(row.adv_brl),
                "adv_shares": float(row.adv_shares),
                "mcap": None if row.mcap is None else float(row.mcap),
                "signal_close": close,
                "share_class": share_class_of_ticker(row.ticker),
                "weight": weight,
                "adv_floor_brl": B_ADV_FLOOR,
                "adv_ok": True,
            }
        )
    return {
        "signal_date": asof.isoformat(),
        "universe": B_UNIVERSE,
        "adv_floor_brl": B_ADV_FLOOR,
        "frequency": B_FREQUENCY,
        "weighting": "1/N",
        "resize_not_round_trip": True,
        "min_names": B_MIN_NAMES,
        "n": n,
        "cash": n == 0,
        "weight": weight,
        "names": names,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def _targets_from_names(names: Sequence[Mapping[str, Any]]) -> list[Target]:
    out: list[Target] = []
    for row in names:
        out.append(
            Target(
                str(row["cnpj"]),
                str(row["ticker"]),
                float(row["adv_brl"]),
                float(row["adv_shares"]),
                None if row.get("mcap") is None else float(row["mcap"]),
            )
        )
    return out


def _empty_costs() -> dict[str, float]:
    return {"fee": 0.0, "half_spread": 0.0, "slippage": 0.0, "n": 0.0, "n_capped": 0.0, "notional": 0.0}


def _empty_cdi() -> dict[str, Any]:
    return {"cota": 1.0, "lots": []}


def initial_state(book: Mapping[str, Any]) -> dict[str, Any]:
    if book.get("signal_date") != SIGNAL_SESSION.isoformat():
        raise PaperError("the frozen book is not the 2026-11-19 signal")
    names = list(book.get("names") or [])
    if names and abs(sum(float(row["weight"]) for row in names) - 1.0) > 1e-8:
        raise PaperError("frozen weights must sum to 1")
    if names and any(abs(float(row["weight"]) - (1.0 / len(names))) > 1e-12 for row in names):
        raise PaperError("frozen weights must be equal")
    if any(float(row["adv_brl"]) < B_ADV_FLOOR for row in names):
        raise PaperError("frozen book contains a name under the ADV floor")
    if 0 < len(names) < B_MIN_NAMES:
        raise PaperError("a non-empty book must have at least 15 names")
    return {
        "version": 1,
        "eligible_for_live_trading": False,
        "last_session": None,
        "pending_inception": True,
        "pending_a_rebalance": False,
        "annual_reviews_done": [],
        "frozen_b_targets": [dict(row) for row in names],
        "a": {
            "idle_cash": A_AUM,
            "cdi": _empty_cdi(),
            "bova_shares": 0.0,
            "bova_cost": 0.0,
            "bova_loss_carry": 0.0,
            "come_cotas_paid": 0.0,
            "cdi_statutory_realized": 0.0,
            "cdi_complementary_paid": 0.0,
            "bova_ir_gross": 0.0,
            "bova_ir_paid": 0.0,
            "bova_fee_charged": 0.0,
            "costs": _empty_costs(),
        },
        "b": {
            "net_cash": B_AUM,
            "gross_cash": B_AUM,
            "net_positions": [],
            "gross_positions": [],
            "dividend_gross": 0.0,
            "dividend_withheld": 0.0,
            "dividend_net": 0.0,
            "stale_sells": 0,
            "worthless_exits": 0,
            "rebalance_turnover": 0.0,
            "costs": _empty_costs(),
            "last_target_weights": {},
        },
        "benchmark": {"cdi_index": 1.0, "ibov_base": None, "ibov_index": 1.0},
        "curve": [
            {
                "date": OPENING_CASH_DATE,
                "phase": "opening_cash",
                "a_equity": A_AUM,
                "b_equity": B_AUM,
                "combined_multiplier": 1.0,
                "cdi_index": 1.0,
                "ibov_index": 1.0,
                "a_bova_weight": None,
            }
        ],
    }


def _lots(sleeve: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sleeve["cdi"]["lots"]


def _cdi_value(sleeve: Mapping[str, Any]) -> float:
    cota = float(sleeve["cdi"]["cota"])
    return sum(float(lot["units"]) * cota for lot in _lots(sleeve))


def _contribute_cdi(sleeve: dict[str, Any], amount: float, session: date) -> None:
    if amount <= 1e-8:
        return
    cota = float(sleeve["cdi"]["cota"])
    if cota <= 0:
        raise PaperError("CDI quota is not positive")
    _lots(sleeve).append(
        {
            "opened": session.isoformat(),
            "principal": amount,
            "units": amount / cota,
            "withheld": 0.0,
            "taxed_nav": amount,
        }
    )


def _accrue_cdi(sleeve: dict[str, Any], rate: float) -> None:
    if not math.isfinite(rate) or rate <= -0.5 or rate >= 0.05:
        raise PaperDataError("CDI daily rate is missing or implausible")
    sleeve["cdi"]["cota"] = float(sleeve["cdi"]["cota"]) * (1.0 + rate)


def _come_cotas(sleeve: dict[str, Any]) -> float:
    """Fifteen percent of the gain since the previous tax point. Quotas fall, the price does not."""
    cota = float(sleeve["cdi"]["cota"])
    paid = 0.0
    for lot in _lots(sleeve):
        value = float(lot["units"]) * cota
        gain = value - float(lot["taxed_nav"])
        if gain <= 1e-8:
            lot["taxed_nav"] = value
            continue
        tax = COME_COTAS_RATE * gain
        lot["units"] = float(lot["units"]) - tax / cota
        lot["withheld"] = float(lot["withheld"]) + tax
        lot["taxed_nav"] = float(lot["units"]) * cota
        paid += tax
    sleeve["come_cotas_paid"] = float(sleeve["come_cotas_paid"]) + paid
    return paid


def _lot_redeem(lot: Mapping[str, Any], cota: float, fraction: float, session: date) -> tuple[float, float, float, float]:
    value = float(lot["units"]) * cota * fraction
    principal = float(lot["principal"]) * fraction
    withheld = float(lot["withheld"]) * fraction
    gross_gain = value - principal + withheld
    days = (session - date.fromisoformat(str(lot["opened"]))).days
    statutory = regressive_ir_rate(days) * max(gross_gain, 0.0)
    complementary = max(0.0, statutory - withheld)
    return value - complementary, complementary, statutory, value


def _shrink_lot(lot: dict[str, Any], fraction: float) -> None:
    keep = 1.0 - fraction
    for key in ("principal", "units", "withheld", "taxed_nav"):
        lot[key] = float(lot[key]) * keep


def redeem_cdi_fifo(sleeve: dict[str, Any], net_needed: float, session: date) -> dict[str, float]:
    """Raise ``net_needed`` after the complementary IR. Oldest lot first."""
    if net_needed <= 1e-8:
        return {"net": 0.0, "complementary": 0.0, "statutory": 0.0, "gross": 0.0}
    cota = float(sleeve["cdi"]["cota"])
    raised = 0.0
    complementary = 0.0
    statutory = 0.0
    gross = 0.0
    for lot in list(_lots(sleeve)):
        if raised >= net_needed - 1e-6:
            break
        full_net, full_comp, full_stat, full_gross = _lot_redeem(lot, cota, 1.0, session)
        if full_net <= 1e-10:
            _lots(sleeve).remove(lot)
            continue
        if raised + full_net <= net_needed + 1e-6:
            raised += full_net
            complementary += full_comp
            statutory += full_stat
            gross += full_gross
            _lots(sleeve).remove(lot)
            continue
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2.0
            net, _comp, _stat, _gross = _lot_redeem(lot, cota, mid, session)
            if raised + net >= net_needed:
                hi = mid
            else:
                lo = mid
        net, comp, stat, got = _lot_redeem(lot, cota, hi, session)
        raised += net
        complementary += comp
        statutory += stat
        gross += got
        _shrink_lot(lot, hi)
        if float(lot["units"]) <= 1e-10:
            _lots(sleeve).remove(lot)
        break
    sleeve["cdi_complementary_paid"] = float(sleeve["cdi_complementary_paid"]) + complementary
    sleeve["cdi_statutory_realized"] = float(sleeve["cdi_statutory_realized"]) + statutory
    return {"net": raised, "complementary": complementary, "statutory": statutory, "gross": gross}


def cdi_provision(sleeve: Mapping[str, Any], session: date) -> float:
    cota = float(sleeve["cdi"]["cota"])
    return sum(_lot_redeem(lot, cota, 1.0, session)[1] for lot in _lots(sleeve))


def _bova_book(tape: Tape, ordinal: int) -> tuple[float, Any, str]:
    px, idx, stale = _close_on(tape, ordinal, 0)
    if px is None or idx is None or stale or int(tape.dates[idx]) != ordinal:
        raise PaperDataError("BOVA11 did not print on this session")
    adv_brl, adv_sh = trailing_adv(tape, idx)
    book, source = execution_book(px, float(tape.bid[idx]), float(tape.ask[idx]), adv_brl, adv_sh)
    return px, book, source


def _fit_buy_qty(cash: float, qty: float, mid: float, book: Any) -> float:
    if qty <= 0 or cash <= 0:
        return 0.0
    trial, _capped = price_fill("buy", qty, mid, book)
    if -cash_delta(trial) <= cash + 1e-6:
        return qty
    lo, hi = 0.0, qty
    for _ in range(28):
        mid_q = (lo + hi) / 2.0
        if mid_q <= 0:
            break
        probe, _capped = price_fill("buy", mid_q, mid, book)
        if -cash_delta(probe) <= cash:
            lo = mid_q
        else:
            hi = mid_q
    return lo


def _add_cost(bucket: dict[str, float], fill: Any, capped: bool, mid: float) -> None:
    bucket["fee"] += float(fill.fee)
    bucket["half_spread"] += float(fill.half_spread)
    bucket["slippage"] += float(fill.slippage)
    bucket["n"] += 1.0
    bucket["n_capped"] += 1.0 if capped else 0.0
    bucket["notional"] += abs(float(fill.qty) * mid)


def _trade_bova(sleeve: dict[str, Any], side: str, qty: float, mid: float, book: Any, session: date) -> dict[str, float]:
    if qty <= 1e-8:
        return {"qty": 0.0, "cash": 0.0, "ir": 0.0, "capped": 0.0}
    fill, capped = price_fill(side, qty, mid, book)
    _add_cost(sleeve["costs"], fill, capped, mid)
    if side == "buy":
        spent = -cash_delta(fill)
        sleeve["bova_shares"] = float(sleeve["bova_shares"]) + qty
        sleeve["bova_cost"] = float(sleeve["bova_cost"]) + spent
        return {"qty": qty, "cash": -spent, "ir": 0.0, "capped": 1.0 if capped else 0.0}
    shares = float(sleeve["bova_shares"])
    if qty > shares + 1e-8:
        raise PaperError("BOVA11 sell is larger than the position")
    basis = float(sleeve["bova_cost"]) * (qty / shares) if shares > 0 else 0.0
    proceeds = cash_delta(fill)
    gain = proceeds - basis
    ir_gross = 0.0
    ir_paid = 0.0
    if gain >= 0:
        ir_gross = BOVA_IR_RATE * gain
        offset = min(float(sleeve["bova_loss_carry"]), gain)
        sleeve["bova_loss_carry"] = float(sleeve["bova_loss_carry"]) - offset
        ir_paid = BOVA_IR_RATE * (gain - offset)
    else:
        sleeve["bova_loss_carry"] = float(sleeve["bova_loss_carry"]) + (-gain)
    sleeve["bova_ir_gross"] = float(sleeve["bova_ir_gross"]) + ir_gross
    sleeve["bova_ir_paid"] = float(sleeve["bova_ir_paid"]) + ir_paid
    sleeve["bova_shares"] = shares - qty
    sleeve["bova_cost"] = float(sleeve["bova_cost"]) - basis
    if sleeve["bova_shares"] <= 1e-8:
        sleeve["bova_shares"] = 0.0
        sleeve["bova_cost"] = 0.0
    return {"qty": -qty, "cash": proceeds - ir_paid, "ir": ir_paid, "capped": 1.0 if capped else 0.0}


def a_equity(sleeve: Mapping[str, Any], bova_close: float) -> float:
    return float(sleeve["idle_cash"]) + _cdi_value(sleeve) + float(sleeve["bova_shares"]) * bova_close


def bova_weight(sleeve: Mapping[str, Any], bova_close: float) -> float:
    equity = a_equity(sleeve, bova_close)
    if equity <= 0:
        return 0.0
    return float(sleeve["bova_shares"]) * bova_close / equity


def bova_provision(sleeve: Mapping[str, Any], bova_close: float) -> float:
    unrealized = float(sleeve["bova_shares"]) * bova_close - float(sleeve["bova_cost"])
    taxable = unrealized - float(sleeve["bova_loss_carry"])
    if taxable <= 0:
        return 0.0
    return BOVA_IR_RATE * taxable


def embedded_bova_fee(curve: Sequence[Mapping[str, Any]], bova_close_now: float, shares: float) -> float:
    """Informational only. The market close is already net of the ETF fee."""
    points = [row for row in curve if row.get("phase") != "opening_cash" and row.get("a_bova_mv")]
    if not points and shares <= 0:
        return 0.0
    values = [float(row["a_bova_mv"]) for row in points]
    if shares > 0:
        values.append(shares * bova_close_now)
    if len(values) < 2:
        return 0.0
    first = date.fromisoformat(str(points[0]["date"]))
    last = date.fromisoformat(str(points[-1]["date"])) if points else first
    days = max((last - first).days, 1)
    return BOVA_ADMIN_FEE * (sum(values) / len(values)) * (days / 365.25)


def _sweep_idle_to_cdi(sleeve: dict[str, Any], session: date) -> None:
    idle = float(sleeve["idle_cash"])
    if idle > 1e-6:
        _contribute_cdi(sleeve, idle, session)
        sleeve["idle_cash"] = 0.0


def rebalance_portfolio_a(sleeve: dict[str, Any], tape: Tape, ordinal: int, session: date) -> dict[str, Any]:
    """Trade BOVA11 back to 30% of portfolio A. Costs and IR stay inside the sleeve."""
    mid, book, source = _bova_book(tape, ordinal)
    equity = a_equity(sleeve, mid)
    target = A_BOVA_WEIGHT * equity
    current = float(sleeve["bova_shares"]) * mid
    if abs(current - target) <= 1.0:
        _sweep_idle_to_cdi(sleeve, session)
        return {"side": "none", "qty": 0.0, "spread_source": source}
    if current > target:
        qty = min(float(sleeve["bova_shares"]), (current - target) / mid)
        result = _trade_bova(sleeve, "sell", qty, mid, book, session)
        sleeve["idle_cash"] = float(sleeve["idle_cash"]) + float(result["cash"])
        _sweep_idle_to_cdi(sleeve, session)
        return {"side": "sell", "qty": qty, "ir": result["ir"], "capped": result["capped"], "spread_source": source}
    gap = target - current
    idle = float(sleeve["idle_cash"])
    raised_net = 0.0
    if idle < gap * 1.02:
        raised = redeem_cdi_fifo(sleeve, gap * 1.02 - idle, session)
        raised_net = float(raised["net"])
        sleeve["idle_cash"] = idle + raised_net
    qty = _fit_buy_qty(float(sleeve["idle_cash"]), gap / mid, mid, book)
    result = _trade_bova(sleeve, "buy", qty, mid, book, session)
    sleeve["idle_cash"] = float(sleeve["idle_cash"]) + float(result["cash"])
    _sweep_idle_to_cdi(sleeve, session)
    return {
        "side": "buy",
        "qty": qty,
        "ir": 0.0,
        "capped": result["capped"],
        "raised": raised_net,
        "spread_source": source,
    }


def open_portfolio_a(sleeve: dict[str, Any], tape: Tape, ordinal: int, session: date) -> dict[str, Any]:
    """Spend 30% of the opening cash on BOVA11, costs inside that budget. The rest is CDI."""
    mid, book, source = _bova_book(tape, ordinal)
    budget = A_BOVA_WEIGHT * float(sleeve["idle_cash"])
    qty = _fit_buy_qty(budget, budget / mid, mid, book)
    result = _trade_bova(sleeve, "buy", qty, mid, book, session)
    sleeve["idle_cash"] = float(sleeve["idle_cash"]) + float(result["cash"])
    _sweep_idle_to_cdi(sleeve, session)
    return {"side": "buy", "qty": qty, "capped": result["capped"], "spread_source": source, "fee_charged_twice": 0.0}


def _positions_from(rows: Sequence[Mapping[str, Any]]) -> dict[str, Position]:
    out: dict[str, Position] = {}
    for row in rows:
        out[str(row["ticker"])] = Position(
            str(row["cnpj"]),
            str(row["ticker"]),
            float(row["shares"]),
            float(row["entry_px"]),
            int(row["entry_ord"]),
        )
    return out


def _positions_to(book: Mapping[str, Position]) -> list[dict[str, Any]]:
    rows = []
    for ticker in sorted(book):
        pos = book[ticker]
        rows.append(
            {
                "ticker": pos.ticker,
                "cnpj": pos.cnpj,
                "shares": float(pos.shares),
                "entry_px": float(pos.entry_px),
                "entry_ord": int(pos.entry_ord),
            }
        )
    return rows


def _load_ledgers(sleeve: Mapping[str, Any]) -> tuple[Ledger, Ledger]:
    net = Ledger(cash=float(sleeve["net_cash"]), positions=_positions_from(sleeve["net_positions"]))
    gross = Ledger(cash=float(sleeve["gross_cash"]), positions=_positions_from(sleeve["gross_positions"]))
    return net, gross


def _store_ledgers(sleeve: dict[str, Any], net: Ledger, gross: Ledger) -> None:
    sleeve["net_cash"] = float(net.cash)
    sleeve["gross_cash"] = float(gross.cash)
    sleeve["net_positions"] = _positions_to(net.positions)
    sleeve["gross_positions"] = _positions_to(gross.positions)


def b_equity(net: Ledger, tapes: Mapping[str, Tape], ordinal: int) -> float:
    total = float(net.cash)
    for pos in net.positions.values():
        tape = tapes.get(pos.ticker)
        if tape is None:
            raise PaperDataError(f"missing tape for held {pos.ticker}")
        px, _idx, _stale = _close_on(tape, ordinal, 10**9)
        if px is None:
            raise PaperDataError(f"missing close for held {pos.ticker}")
        total += float(pos.shares) * float(px)
    return total


def _share_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    keys = set(before) | set(after)
    return {key: after.get(key, 0.0) - before.get(key, 0.0) for key in keys if abs(after.get(key, 0.0) - before.get(key, 0.0)) > 1e-8}


def step_portfolio_b(
    sleeve: dict[str, Any],
    tapes: dict[str, Tape],
    ordinal: int,
    prev_ordinal: int | None,
    targets: list[Target] | None,
    events: dict[str, list[CashEvent]] | None,
    *,
    count_turnover: bool,
) -> dict[str, Any]:
    """One session of the locked book: split, net dividend, stale exit, then resize.

    ``round_trip`` stays false. A name that remains is not sold and bought back.
    """
    net, gross = _load_ledgers(sleeve)
    _apply_splits(net, tapes, ordinal, True)
    _apply_splits(gross, tapes, ordinal, True)
    dividend = {"gross": 0.0, "withheld": 0.0, "net": 0.0, "feed": "none" if not events else "events"}
    if events and prev_ordinal is not None:
        kept, _audit = plausible_cash(events, tapes)
        for pos in net.positions.values():
            for event in kept.get(pos.ticker, []):
                if prev_ordinal < int(event.ordinal) <= ordinal:
                    tape_held = tapes.get(pos.ticker)
                    scale = 1.0 if tape_held is None else cash_scale_at(tape_held, int(event.ordinal))
                    gross_cash = float(event.amount) * scale * float(pos.shares)
                    rate = 0.0 if event.kind == "dividendo" else JCP_AND_UNKNOWN_RATE
                    dividend["gross"] += gross_cash
                    dividend["withheld"] += gross_cash * rate
        arrays = event_arrays(kept, UNKNOWN_WITHHOLDING)
        net_cash, _count = _credit(net, gross, arrays, prev_ordinal, ordinal, tapes)
        dividend["net"] = float(net_cash)
        sleeve["dividend_gross"] = float(sleeve["dividend_gross"]) + dividend["gross"]
        sleeve["dividend_withheld"] = float(sleeve["dividend_withheld"]) + dividend["withheld"]
        sleeve["dividend_net"] = float(sleeve["dividend_net"]) + dividend["net"]
    stats = FillStats()
    stale = 0
    worthless = 0
    for ticker in list(net.positions):
        tape = tapes.get(ticker)
        if tape is None:
            raise PaperDataError(f"missing tape for held {ticker}")
        _px, idx, _stale = _close_on(tape, ordinal, 10**9)
        dark = idx is None or ordinal - int(tape.dates[idx]) > DELIST_STALE_SESSIONS
        if not dark:
            continue
        reason = _sell(net, gross, ticker, tapes, ordinal, stats, 0.0)
        if reason == "delist":
            stale += 1
        elif reason == "worthless":
            worthless += 1
    sleeve["stale_sells"] = int(sleeve["stale_sells"]) + stale
    sleeve["worthless_exits"] = int(sleeve["worthless_exits"]) + worthless
    before = {ticker: float(pos.shares) for ticker, pos in net.positions.items()}
    priced = 0
    if targets is not None:
        if targets:
            for row in targets:
                tape = tapes.get(row.ticker)
                if tape is None:
                    continue
                _px, _idx, stale_px = _close_on(tape, ordinal, 5)
                if _px is not None and not stale_px:
                    priced += 1
            if priced < min(B_MIN_NAMES, len(targets)):
                raise PaperDataError("too many target names have no print; refusing a false cash book")
        prev_w = {str(key): float(value) for key, value in (sleeve.get("last_target_weights") or {}).items()}
        new_w = {}
        if targets:
            new_w = {row.ticker: 1.0 / len(targets) for row in targets}
        if count_turnover and prev_w:
            keys = set(prev_w) | set(new_w)
            sleeve["rebalance_turnover"] = float(sleeve["rebalance_turnover"]) + 0.5 * sum(
                abs(new_w.get(key, 0.0) - prev_w.get(key, 0.0)) for key in keys
            )
        sleeve["last_target_weights"] = new_w
        _rebalance(net, gross, targets, tapes, ordinal, stats, round_trip=False, haircut=0.0)
    _store_ledgers(sleeve, net, gross)
    sleeve["costs"]["fee"] = float(sleeve["costs"]["fee"]) + float(stats.fee)
    sleeve["costs"]["half_spread"] = float(sleeve["costs"]["half_spread"]) + float(stats.half_spread)
    sleeve["costs"]["slippage"] = float(sleeve["costs"]["slippage"]) + float(stats.slippage)
    sleeve["costs"]["n"] = float(sleeve["costs"]["n"]) + float(stats.n)
    sleeve["costs"]["n_capped"] = float(sleeve["costs"]["n_capped"]) + float(stats.n_capped)
    after = {row["ticker"]: float(row["shares"]) for row in sleeve["net_positions"]}
    return {
        "dividend": dividend,
        "stale_sells": stale,
        "worthless_exits": worthless,
        "fills": stats.n,
        "capped": stats.n_capped,
        "share_delta": _share_delta(before, after),
        "n_held": len(after),
        "priced_targets": priced,
    }


def _anniversary_year(session: date, done: Sequence[int]) -> int | None:
    done_set = {int(item) for item in done}
    for year in range(ENTRY_SESSION.year + 1, session.year + 1):
        if year in done_set:
            continue
        anniversary = date(year, ENTRY_SESSION.month, ENTRY_SESSION.day)
        if session >= anniversary:
            return year
    return None


def _come_cotas_due(prev: date | None, session: date) -> bool:
    if prev is None or prev.month not in (5, 11):
        return False
    return (session.year, session.month) > (prev.year, prev.month)


def _quarter_signal(prev: date | None, session: date) -> date | None:
    if prev is None or prev.month not in (3, 6, 9, 12):
        return None
    if (session.year, session.month) <= (prev.year, prev.month):
        return None
    return prev


def mark_session(
    state: dict[str, Any],
    session: date,
    tapes: Mapping[str, Tape],
    cdi_rate: float | None,
    ibov_close: float | None,
    events: dict[str, list[CashEvent]] | None,
    companies: Sequence[Company] | None,
    listings: Sequence[Listing] | None,
    *,
    today: date,
) -> dict[str, Any]:
    """Mark one session. Raises on a date that is already in the log or still in the future."""
    if state.get("eligible_for_live_trading") is not False:
        raise LedgerIntegrityError("eligible_for_live_trading must stay false")
    if session < ENTRY_SESSION:
        raise LedgerTimeError(f"no fill before {ENTRY_SESSION.isoformat()}")
    if session > today:
        raise LedgerTimeError("refusing a mark after the clock; that would use a future price")
    last = state.get("last_session")
    if last is not None and session.isoformat() <= str(last):
        raise LedgerTimeError(f"refusing to rewrite or backfill {session.isoformat()}")
    ordinal = session.toordinal()
    visible = truncate_tapes(tapes, ordinal)
    for tape in visible.values():
        if int(tape.dates[-1]) > ordinal:
            raise LedgerTimeError("tape still contains a print after the session")
    bova = visible.get(BOVA_TICKER)
    if bova is None:
        raise PaperDataError("BOVA11 close is missing")
    prev = date.fromisoformat(str(last)) if last else None
    notes: dict[str, Any] = {"a_trade": None, "b": None, "come_cotas": 0.0, "quarter_signal": None, "annual_review": None}
    if state["pending_inception"]:
        notes["a_trade"] = open_portfolio_a(state["a"], bova, ordinal, session)
        step = step_portfolio_b(
            state["b"],
            visible,
            ordinal,
            None,
            _targets_from_names(state["frozen_b_targets"]),
            None,
            count_turnover=False,
        )
        notes["b"] = step
        state["pending_inception"] = False
    else:
        if cdi_rate is None or ibov_close is None:
            raise PaperDataError("CDI and Ibovespa are required after the opening fill")
        if _come_cotas_due(prev, session):
            notes["come_cotas"] = _come_cotas(state["a"])
            notes["come_cotas_session"] = None if prev is None else prev.isoformat()
        _accrue_cdi(state["a"], float(cdi_rate))
        state["benchmark"]["cdi_index"] = float(state["benchmark"]["cdi_index"]) * (1.0 + float(cdi_rate))
        signal = _quarter_signal(prev, session)
        targets = None
        if signal is not None:
            if companies is None or listings is None:
                raise PaperDataError("quarterly rebalance needs the point-in-time universe")
            selected = select_small_book(companies, listings, visible, signal)
            notes["quarter_signal"] = signal.isoformat()
            notes["quarter_book"] = {"n": selected["n"], "cash": selected["cash"], "names": selected["names"]}
            targets = _targets_from_names(selected["names"])
        notes["b"] = step_portfolio_b(
            state["b"],
            visible,
            ordinal,
            None if prev is None else prev.toordinal(),
            targets,
            events,
            count_turnover=targets is not None,
        )
        if state["pending_a_rebalance"]:
            notes["a_trade"] = rebalance_portfolio_a(state["a"], bova, ordinal, session)
            state["pending_a_rebalance"] = False
    if ibov_close is None or not math.isfinite(float(ibov_close)) or float(ibov_close) <= 0:
        raise PaperDataError("Ibovespa close is missing")
    if state["benchmark"]["ibov_base"] is None:
        state["benchmark"]["ibov_base"] = float(ibov_close)
        state["benchmark"]["ibov_index"] = 1.0
    else:
        state["benchmark"]["ibov_index"] = float(ibov_close) / float(state["benchmark"]["ibov_base"])
    mid, _book, _source = _bova_book(bova, ordinal)
    weight = bova_weight(state["a"], mid)
    review_year = _anniversary_year(session, state["annual_reviews_done"])
    if review_year is not None:
        state["annual_reviews_done"].append(review_year)
        notes["annual_review"] = {
            "year": review_year,
            "bova_weight": weight,
            "outside_band": outside_bova_band(weight),
            "forced_trade": False,
        }
    if outside_bova_band(weight):
        state["pending_a_rebalance"] = True
        notes["band_breach"] = weight
    else:
        notes["band_breach"] = None
    b_net, _b_gross = _load_ledgers(state["b"])
    a_eq = a_equity(state["a"], mid)
    b_eq = b_equity(b_net, visible, ordinal)
    point = {
        "date": session.isoformat(),
        "phase": "close",
        "a_equity": a_eq,
        "a_equity_after_provision": a_eq - cdi_provision(state["a"], session) - bova_provision(state["a"], mid),
        "b_equity": b_eq,
        "combined_multiplier": combined_multiplier(a_eq, b_eq),
        "cdi_index": float(state["benchmark"]["cdi_index"]),
        "ibov_index": float(state["benchmark"]["ibov_index"]),
        "ibov_close": float(ibov_close),
        "a_bova_weight": weight,
        "a_bova_mv": float(state["a"]["bova_shares"]) * mid,
        "a_costs_notional": float(state["a"]["costs"]["notional"]),
        "b_costs_notional": float(state["b"]["costs"]["notional"]),
        "b_rebalance_turnover": float(state["b"]["rebalance_turnover"]),
        "dividend_net": float(state["b"]["dividend_net"]),
    }
    state["curve"].append(point)
    state["last_session"] = session.isoformat()
    state["a"]["bova_fee_embedded"] = embedded_bova_fee(state["curve"], mid, float(state["a"]["bova_shares"]))
    notes["mark"] = point
    notes["eligible_for_live_trading"] = False
    notes["bova_admin_fee_charged"] = 0.0
    return notes


def scrub(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PaperError("non-finite number in the ledger")
        return round(value, 10)
    if isinstance(value, dict):
        return {str(key): scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str | int | bool) or value is None:
        return value
    raise PaperError(f"unsupported ledger value {type(value).__name__}")


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    data = {key: payload[key] for key in payload if key != "entry_hash"}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def entry_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def make_entry(
    *,
    seq: int,
    timestamp: str,
    kind: str,
    session_date: str | None,
    prev_hash: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "seq": int(seq),
        "timestamp": timestamp,
        "kind": kind,
        "session_date": session_date,
        "prev_hash": prev_hash,
        "body": scrub(dict(body)),
    }
    payload["entry_hash"] = entry_hash(payload)
    return payload


def verify_ledger(entries: Sequence[Mapping[str, Any]], prereg_digest: str | None = None) -> None:
    if not entries:
        raise LedgerIntegrityError("ledger is empty")
    prev = GENESIS_PREV
    saw_target = False
    last_mark: str | None = None
    last_ts: str | None = None
    for index, raw in enumerate(entries):
        entry = dict(raw)
        if int(entry.get("seq", -1)) != index:
            raise LedgerIntegrityError(f"sequence break at {index}")
        if entry.get("prev_hash") != prev:
            raise LedgerIntegrityError(f"prev_hash break at seq {index}")
        digest = entry.get("entry_hash")
        if digest != entry_hash(entry):
            raise LedgerIntegrityError(f"entry_hash break at seq {index}")
        kind = entry.get("kind")
        session_date = entry.get("session_date")
        timestamp = str(entry.get("timestamp") or "")
        if last_ts is not None and timestamp < last_ts:
            raise LedgerTimeError("timestamp moved backwards")
        last_ts = timestamp
        body = entry.get("body") or {}
        state = body.get("state") or {}
        if state.get("eligible_for_live_trading") is not False:
            raise LedgerIntegrityError("eligible_for_live_trading must stay false")
        if kind == "genesis":
            if index != 0 or session_date is not None:
                raise LedgerIntegrityError("genesis must be the first entry and carry no session")
            if prereg_digest is not None and body.get("preregistration_sha256") != prereg_digest:
                raise LedgerIntegrityError("preregistration hash does not match the frozen file")
        elif kind == "target":
            if index != 1 or saw_target:
                raise LedgerIntegrityError("the target entry must be seq 1, once")
            if session_date != SIGNAL_SESSION.isoformat():
                raise LedgerIntegrityError("target signal date is not 2026-11-19")
            if body.get("planned_entry") != ENTRY_SESSION.isoformat():
                raise LedgerTimeError("planned entry is not 2026-11-23")
            saw_target = True
        elif kind == "mark":
            if not saw_target:
                raise LedgerIntegrityError("mark before the frozen target")
            if not isinstance(session_date, str) or session_date < ENTRY_SESSION.isoformat():
                raise LedgerTimeError("mark is before the opening session")
            if last_mark is not None and session_date <= last_mark:
                raise LedgerTimeError(f"backfill or duplicate mark {session_date}")
            if body.get("price_session") != session_date:
                raise LedgerTimeError("price session does not match the mark")
            last_mark = session_date
        else:
            raise LedgerIntegrityError(f"unknown ledger kind {kind}")
        prev = str(digest)
    if not saw_target:
        raise LedgerIntegrityError("missing target entry")


def preregistration_document(book: Mapping[str, Any], *, frozen_on: str = "2026-11-21") -> dict[str, Any]:
    names = list(book.get("names") or [])
    return {
        "id": "b3-paper-forward-2026-11-23",
        "frozen_on": frozen_on,
        "eligible_for_live_trading": False,
        "signal_session": SIGNAL_SESSION.isoformat(),
        "entry_session": ENTRY_SESSION.isoformat(),
        "signal_note": (
            "2026-11-20 is the national holiday of Consciência Negra and has no session. "
            "2026-11-19 is the last COTAHIST session before the entry. "
            "The opening fill uses the close of 2026-11-23, not the signal close."
        ),
        "portfolio_a": {
            "name": "nucleo_passivo",
            "aum_brl": A_AUM,
            "weights": {"cdi_proxy": A_CDI_WEIGHT, "BOVA11": A_BOVA_WEIGHT},
            "band": {
                "asset": "BOVA11",
                "low": A_BAND_LOW,
                "high": A_BAND_HIGH,
                "width_percentage_points": 5,
                "inequality": "trade only when round(weight, 6) < 0.25 or round(weight, 6) > 0.35",
                "daily_check": "every session close after the open",
                "annual_check": "first session on or after each anniversary of 2026-11-23",
                "annual_inside_band": "record the observation and do not trade",
                "fill": "next session close, back to 70/30",
                "weight_base": "CDI value after come-cotas already paid, plus BOVA11 at the close, plus idle cash",
            },
            "bova11_admin_fee": {
                "annual_rate": BOVA_ADMIN_FEE,
                "charged_on_top_of_close": 0,
                "reason": "the exchange close is already net of the ETF administration fee",
            },
            "trading_costs": "price_fill on venue b3: fee, half spread, slippage, 5000 bps cap",
            "tax": {
                "cdi_regressive": {"le_180": 0.225, "le_360": 0.20, "le_720": 0.175, "gt_720": 0.15},
                "holding_day_count": "(redemption date - lot open date).days",
                "lot_order": "FIFO",
                "come_cotas": {
                    "rate": COME_COTAS_RATE,
                    "when": "first marked session of June and of December, on the value before that session's CDI accrual",
                    "dated_as": "previous session, the last marked session of May or November",
                },
                "bova_realized": BOVA_IR_RATE,
                "bova_loss_carry": "positive realized gains offset the accumulated realized loss before the 15% tax",
            },
        },
        "portfolio_b": {
            "name": "small_caps_peso_igual",
            "aum_brl": B_AUM,
            "rule": "app.models.equal_weight.build_signal_book",
            "universe": B_UNIVERSE,
            "adv_floor_brl": B_ADV_FLOOR,
            "frequency": B_FREQUENCY,
            "weighting": "1/N",
            "resize_not_round_trip": True,
            "min_names_else_cash": B_MIN_NAMES,
            "costs": "same price_fill path, half spread, slippage, 5000 bps cap",
            "dividends": "labeled dividends untaxed; labeled JCP and unlabeled events withheld at 15%",
            "delist": "same predicate as simulate_book: date-ordinal age > 10 sells at the last price",
            "initial_book_frozen": True,
            "later_quarters_recomputed": "from tapes truncated to the quarter-end signal, hashed into the ledger",
        },
        "combined": {
            "weights": {"A": COMBINED_A, "B": COMBINED_B},
            "rebalance_across_sleeves": False,
            "definition": "0.90 * (A equity / 1000000) + 0.10 * (B equity / 100000)",
        },
        "benchmarks": {
            "cdi": "BCB SGS series 12, gross, compounded on the same sessions the CDI sleeve accrues",
            "ibovespa": "official Ibovespa level, gross total return, base is the entry close",
        },
        "tracking": {
            "sleeve": "small, ADV floor 200000, quarterly, R$ 100000, net of the locked cost model",
            "full_sample_net_cagr": B_REF_FULL_CAGR,
            "oos_net_cagr": B_REF_OOS_CAGR,
            "sharpe": B_REF_SHARPE,
            "max_drawdown": B_REF_MAX_DD,
            "oos_excess_over_cdi": B_REF_OOS_EXCESS_OVER_CDI,
            "z_primary": "monthly mean versus the OOS CAGR, scaled by vol inverted from the full-sample CAGR and Sharpe",
            "interval": "1.96 standard errors of the monthly mean; cumulative band uses log(1+monthly mean) and the same monthly vol",
        },
        "evaluation": {
            "horizons": [
                {"label": "6m", "on_or_before": "2027-05-23"},
                {"label": "12m", "on_or_before": "2027-11-23"},
            ],
            "reads": "last marked session on or before the horizon date",
            "criteria": [
                {
                    "id": "integrity",
                    "kind": "hard",
                    "text": "Hash chain verifies, no mark is before 2026-11-23, no mark rewrites an older session, and eligible_for_live_trading is false.",
                },
                {
                    "id": "membership",
                    "kind": "hard",
                    "text": "Opening B weights are 1/N, every opening ADV is at least R$ 200,000, and a non-empty book has at least 15 names. Quarterly membership is a fresh build_signal_book call, not a hand edit.",
                },
                {
                    "id": "execution",
                    "kind": "flag",
                    "text": "Flag if more than 5% of B fills hit the 5000 bps cap, or if post-opening one-way target turnover over a year exceeds 1.5. The backtest at R$ 100k hit the cap on 6 of 2864 fills and turned over 0.72.",
                },
                {
                    "id": "drawdown",
                    "kind": "flag",
                    "text": "Flag if B's max drawdown is worse than -61.3%, or if A's max drawdown is worse than -25%. A flag is recorded. It does not change the rule.",
                },
                {
                    "id": "excess_over_cdi",
                    "kind": "record",
                    "text": "Record net excess of A, B and the 90/10 mix over gross CDI. A positive excess is still paper.",
                },
                {
                    "id": "tracking",
                    "kind": "flag",
                    "text": "Flag if the OOS z-score is outside ±2 once at least three monthly returns exist. Do not refit the book.",
                },
                {
                    "id": "live_trading",
                    "kind": "hard",
                    "text": "None of these readings sets eligible_for_live_trading to true.",
                },
            ],
        },
        "portfolio_b_initial_target": {
            "signal_date": SIGNAL_SESSION.isoformat(),
            "planned_entry": ENTRY_SESSION.isoformat(),
            "n": len(names),
            "cash": len(names) == 0,
            "weight": 0.0 if not names else 1.0 / len(names),
            "names": names,
        },
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_preregistration(path: Path, book: Mapping[str, Any], *, frozen_on: str = "2026-11-21") -> str:
    if path.exists():
        raise PaperError("preregistration already exists and is not rewritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = preregistration_document(book, frozen_on=frozen_on)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return file_sha256(path)


class _Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> _Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _ledger_path(root: Path) -> Path:
    return paper_dir(root) / "ledger.jsonl"


def _state_path(root: Path) -> Path:
    return paper_dir(root) / "state.json"


def read_entries(root: Path) -> list[dict[str, Any]]:
    path = _ledger_path(root)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_state(root: Path, head: str, snapshot: Mapping[str, Any]) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ledger_head": head, "eligible_for_live_trading": False, "snapshot": snapshot}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(scrub(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append(root: Path, entry: Mapping[str, Any]) -> None:
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_book(root: Path | None = None) -> dict[str, Any]:
    root = root or paper_root()
    preg = preregistration_path(root)
    if not preg.exists():
        raise FileNotFoundError(str(preg))
    digest = file_sha256(preg)
    entries = read_entries(root)
    verify_ledger(entries, digest)
    head = str(entries[-1]["entry_hash"])
    snapshot = dict(entries[-1]["body"]["state"])
    state_path = _state_path(root)
    if not state_path.exists():
        _write_state(root, head, snapshot)
    else:
        cached = json.loads(state_path.read_text(encoding="utf-8"))
        if cached.get("ledger_head") != head or cached.get("snapshot") != snapshot:
            if entry_hash(entries[-1]) != head:
                raise LedgerIntegrityError("ledger head is not stable")
            _write_state(root, head, snapshot)
            cached = {"ledger_head": head, "snapshot": snapshot}
        if cached.get("eligible_for_live_trading") is False and cached["snapshot"].get("eligible_for_live_trading") is not False:
            raise LedgerIntegrityError("eligible_for_live_trading must stay false")
    return {
        "preregistration_sha256": digest,
        "ledger_head": head,
        "entries": len(entries),
        "snapshot": snapshot,
        "eligible_for_live_trading": False,
    }


def initialize(root: Path, *, timestamp: str) -> dict[str, Any]:
    preg = preregistration_path(root)
    if not preg.exists():
        raise PaperError("preregistration file is missing")
    if _ledger_path(root).exists() and read_entries(root):
        raise PaperError("ledger already exists")
    document = json.loads(preg.read_text(encoding="utf-8"))
    if document.get("eligible_for_live_trading") is not False:
        raise LedgerIntegrityError("eligible_for_live_trading must stay false")
    book = document["portfolio_b_initial_target"]
    state = scrub(initial_state(book))
    digest = file_sha256(preg)
    with _Lock(paper_dir(root) / "ledger.lock"):
        genesis = make_entry(
            seq=0,
            timestamp=timestamp,
            kind="genesis",
            session_date=None,
            prev_hash=GENESIS_PREV,
            body={
                "preregistration_sha256": digest,
                "eligible_for_live_trading": False,
                "entry_session": ENTRY_SESSION.isoformat(),
                "signal_session": SIGNAL_SESSION.isoformat(),
                "state": state,
            },
        )
        target = make_entry(
            seq=1,
            timestamp=timestamp,
            kind="target",
            session_date=SIGNAL_SESSION.isoformat(),
            prev_hash=str(genesis["entry_hash"]),
            body={
                "planned_entry": ENTRY_SESSION.isoformat(),
                "portfolio_a": {"aum_brl": A_AUM, "cdi": A_CDI_WEIGHT, "BOVA11": A_BOVA_WEIGHT},
                "portfolio_b": book,
                "eligible_for_live_trading": False,
                "state": state,
            },
        )
        verify_ledger([genesis, target], digest)
        _append(root, genesis)
        _append(root, target)
        _write_state(root, str(target["entry_hash"]), state)
    return {"preregistration_sha256": digest, "ledger_head": target["entry_hash"], "n": book["n"]}


def commit_mark(
    root: Path,
    session: date,
    tapes: Mapping[str, Tape],
    cdi_rate: float | None,
    ibov_close: float | None,
    events: dict[str, list[CashEvent]] | None,
    companies: Sequence[Company] | None,
    listings: Sequence[Listing] | None,
    *,
    today: date,
    timestamp: str,
) -> dict[str, Any]:
    preg = preregistration_path(root)
    digest = file_sha256(preg)
    with _Lock(paper_dir(root) / "ledger.lock"):
        entries = read_entries(root)
        verify_ledger(entries, digest)
        state = copy.deepcopy(entries[-1]["body"]["state"])
        notes = mark_session(
            state,
            session,
            tapes,
            cdi_rate,
            ibov_close,
            events,
            companies,
            listings,
            today=today,
        )
        state = scrub(state)
        entry = make_entry(
            seq=len(entries),
            timestamp=timestamp,
            kind="mark",
            session_date=session.isoformat(),
            prev_hash=str(entries[-1]["entry_hash"]),
            body={
                "price_session": session.isoformat(),
                "notes": notes,
                "state": state,
                "eligible_for_live_trading": False,
            },
        )
        verify_ledger([*entries, entry], digest)
        _append(root, entry)
        _write_state(root, str(entry["entry_hash"]), state)
    return {"ledger_head": entry["entry_hash"], "notes": notes, "eligible_for_live_trading": False}


def _curve_performance(curve: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    rows = [row for row in curve if row.get(key) is not None]
    if len(rows) < 2:
        return {"cagr": None, "max_drawdown": None, "sharpe": None, "total": None, "years": None}
    ords = [date.fromisoformat(str(row["date"])).toordinal() for row in rows]
    equity = [float(row[key]) for row in rows]
    _m_ords, monthly = monthly_simple_returns(ords, equity)
    stats = performance(ords, equity, monthly)
    stats["monthly_returns"] = [float(item) for item in monthly]
    return stats


def build_monthly_report(snapshot: Mapping[str, Any], month: str) -> dict[str, Any]:
    """``month`` is ``YYYY-MM``. Returns use the last mark of the previous month as the base."""
    curve = list(snapshot["curve"])
    in_month = [row for row in curve if str(row["date"]).startswith(month) and row.get("phase") == "close"]
    if not in_month:
        raise PaperDataError(f"no close in {month}")
    prior = [row for row in curve if str(row["date"]) < in_month[0]["date"]]
    base = prior[-1] if prior else in_month[0]
    end = in_month[-1]

    def _ret(key: str) -> float | None:
        start = float(base[key])
        finish = float(end[key])
        if start <= 0:
            return None
        return finish / start - 1.0

    a_stats = _curve_performance(curve, "a_equity")
    b_stats = _curve_performance(curve, "b_equity")
    c_stats = _curve_performance(curve, "combined_multiplier")
    cdi_stats = _curve_performance(curve, "cdi_index")
    ibov_stats = _curve_performance(curve, "ibov_index")
    tracking = tracking_vs_backtest(b_stats.get("monthly_returns") or [])
    a = snapshot["a"]
    b = snapshot["b"]
    ir_paid = float(a["come_cotas_paid"]) + float(a["cdi_complementary_paid"]) + float(a["bova_ir_paid"])
    ir_provision = 0.0
    if end.get("a_equity") is not None and end.get("a_equity_after_provision") is not None:
        ir_provision = float(end["a_equity"]) - float(end["a_equity_after_provision"])
    open_withheld = sum(float(lot["withheld"]) for lot in a["cdi"]["lots"])
    ir_gross = open_withheld + float(a["cdi_statutory_realized"]) + float(a["bova_ir_gross"])
    month_start_notional_b = 0.0
    if prior:
        month_start_notional_b = float(prior[-1].get("b_costs_notional") or 0.0)
    report = {
        "month": month,
        "eligible_for_live_trading": False,
        "last_session": snapshot.get("last_session"),
        "returns": {
            "A": _ret("a_equity"),
            "B": _ret("b_equity"),
            "combined_90_10": _ret("combined_multiplier"),
            "cdi_gross": _ret("cdi_index"),
            "ibovespa_total_return": _ret("ibov_index"),
        },
        "since_inception": {
            "A": a_stats.get("total"),
            "B": b_stats.get("total"),
            "combined_90_10": c_stats.get("total"),
            "cdi_gross": cdi_stats.get("total"),
            "ibovespa_total_return": ibov_stats.get("total"),
            "excess_A_over_cdi": None if a_stats.get("total") is None or cdi_stats.get("total") is None else a_stats["total"] - cdi_stats["total"],
            "excess_B_over_cdi": None if b_stats.get("total") is None or cdi_stats.get("total") is None else b_stats["total"] - cdi_stats["total"],
            "excess_combined_over_cdi": None
            if c_stats.get("total") is None or cdi_stats.get("total") is None
            else c_stats["total"] - cdi_stats["total"],
        },
        "drawdown": {
            "A": a_stats.get("max_drawdown"),
            "B": b_stats.get("max_drawdown"),
            "combined_90_10": c_stats.get("max_drawdown"),
            "ibovespa": ibov_stats.get("max_drawdown"),
        },
        "sharpe_monthly": {
            "A": a_stats.get("sharpe"),
            "B": b_stats.get("sharpe"),
            "combined_90_10": c_stats.get("sharpe"),
            "definition": "sqrt(12) * mean(monthly simple return) / sample std, same as the equal-weight study",
        },
        "volatility_and_cagr": {
            "A_cagr": a_stats.get("cagr"),
            "B_cagr": b_stats.get("cagr"),
            "combined_cagr": c_stats.get("cagr"),
        },
        "turnover_and_costs": {
            "b_one_way_target_turnover_since_open": float(b["rebalance_turnover"]),
            "b_traded_notional_in_month": float(end.get("b_costs_notional") or 0.0) - month_start_notional_b,
            "a_fee": float(a["costs"]["fee"]),
            "a_half_spread": float(a["costs"]["half_spread"]),
            "a_slippage": float(a["costs"]["slippage"]),
            "a_fills_capped": float(a["costs"]["n_capped"]),
            "b_fee": float(b["costs"]["fee"]),
            "b_half_spread": float(b["costs"]["half_spread"]),
            "b_slippage": float(b["costs"]["slippage"]),
            "b_fills": float(b["costs"]["n"]),
            "b_fills_capped": float(b["costs"]["n_capped"]),
            "b_dividend_gross": float(b["dividend_gross"]),
            "b_dividend_withheld": float(b["dividend_withheld"]),
            "b_dividend_net": float(b["dividend_net"]),
            "bova_admin_fee_charged": float(a["bova_fee_charged"]),
            "bova_admin_fee_embedded_informational": float(a.get("bova_fee_embedded") or 0.0),
        },
        "tax": {
            "ir_gross_brl": ir_gross,
            "ir_paid_brl": ir_paid,
            "ir_provision_brl": ir_provision,
            "equity_a_after_provision": end.get("a_equity_after_provision"),
            "come_cotas_paid": float(a["come_cotas_paid"]),
            "cdi_complementary_paid": float(a["cdi_complementary_paid"]),
            "bova_ir_gross": float(a["bova_ir_gross"]),
            "bova_ir_paid": float(a["bova_ir_paid"]),
        },
        "tracking_b_vs_backtest": tracking,
        "flags": {
            "b_drawdown_beyond_backtest": (b_stats.get("max_drawdown") is not None and b_stats["max_drawdown"] < B_REF_MAX_DD),
            "a_drawdown_beyond_25pct": (a_stats.get("max_drawdown") is not None and a_stats["max_drawdown"] < -0.25),
            "b_cap_hit_fraction_above_5pct": (
                float(b["costs"]["n"]) > 0 and float(b["costs"]["n_capped"]) / float(b["costs"]["n"]) > 0.05
            ),
            "tracking_outside_95": bool(tracking.get("outside_95")),
        },
    }
    return report


def render_monthly_markdown(report: Mapping[str, Any]) -> str:
    def pct(value: object) -> str:
        if not isinstance(value, int | float) or not math.isfinite(float(value)):
            return "—"
        return f"{float(value):.2%}"

    def num(value: object) -> str:
        if not isinstance(value, int | float) or not math.isfinite(float(value)):
            return "—"
        return f"{float(value):,.2f}"

    ret = report["returns"]
    since = report["since_inception"]
    dd = report["drawdown"]
    sh = report["sharpe_monthly"]
    costs = report["turnover_and_costs"]
    tax = report["tax"]
    track = report["tracking_b_vs_backtest"]
    lines = [
        f"# Paper B3 — {report['month']}",
        "",
        "Pesquisa. Nenhuma ordem real. `eligible_for_live_trading` permanece `false`.",
        "",
        "## Retorno do mês",
        "",
        "| Carteira | Mês | Desde a abertura | Excesso sobre o CDI | Max DD | Sharpe mensal |",
        "|---|---:|---:|---:|---:|---:|",
        f"| A | {pct(ret['A'])} | {pct(since['A'])} | {pct(since['excess_A_over_cdi'])} | {pct(dd['A'])} | {num(sh['A'])} |",
        f"| B | {pct(ret['B'])} | {pct(since['B'])} | {pct(since['excess_B_over_cdi'])} | {pct(dd['B'])} | {num(sh['B'])} |",
        f"| 90% A + 10% B | {pct(ret['combined_90_10'])} | {pct(since['combined_90_10'])} | {pct(since['excess_combined_over_cdi'])} | {pct(dd['combined_90_10'])} | {num(sh['combined_90_10'])} |",
        f"| CDI bruto | {pct(ret['cdi_gross'])} | {pct(since['cdi_gross'])} | — | — | — |",
        f"| Ibovespa com dividendos | {pct(ret['ibovespa_total_return'])} | {pct(since['ibovespa_total_return'])} | — | {pct(dd['ibovespa'])} | — |",
        "",
        "## Custos, giro e proventos",
        "",
        f"- Giro de alvo de B desde a abertura, mão única, sem contar o investimento inicial: {num(costs['b_one_way_target_turnover_since_open'])}.",
        f"- Notional negociado de B no mês: R$ {num(costs['b_traded_notional_in_month'])}.",
        f"- Custos de A (taxa / meio spread / slippage): R$ {num(costs['a_fee'])} / {num(costs['a_half_spread'])} / {num(costs['a_slippage'])}.",
        f"- Custos de B (taxa / meio spread / slippage): R$ {num(costs['b_fee'])} / {num(costs['b_half_spread'])} / {num(costs['b_slippage'])}. Fills no teto: {num(costs['b_fills_capped'])} de {num(costs['b_fills'])}.",
        f"- Proventos de B, bruto / IR retido / líquido: R$ {num(costs['b_dividend_gross'])} / {num(costs['b_dividend_withheld'])} / {num(costs['b_dividend_net'])}.",
        f"- Taxa de administração do BOVA11 cobrada de novo: R$ {num(costs['bova_admin_fee_charged'])}. Estimativa já embutida no fechamento: R$ {num(costs['bova_admin_fee_embedded_informational'])}.",
        "",
        "## IR",
        "",
        f"- IR bruto (come-cotas ainda não compensado nos lotes abertos + IR cheio nas vendas de CDI + 15% dos ganhos realizados de BOVA11 antes da compensação): R$ {num(tax['ir_gross_brl'])}.",
        f"- IR recolhido: R$ {num(tax['ir_paid_brl'])}.",
        f"- Provisão se a carteira A fosse liquidada neste fechamento: R$ {num(tax['ir_provision_brl'])}.",
        f"- Patrimônio de A líquido dessa provisão: R$ {num(tax['equity_a_after_provision'])}.",
        "",
        "## B contra o backtest a R$ 100 mil",
        "",
        f"- Meses: {track['n_months']}. Z contra o CAGR fora da amostra de 44,6%: {num(track.get('z_oos'))}. Z contra o CAGR da amostra cheia de 38,4%: {num(track.get('z_full'))}.",
        f"- Sharpe de referência 0,73. Max DD de referência -61,3%. Leitura preliminar: {track['preliminary']}.",
        "",
        "Nenhum destes números autoriza capital.",
        "",
    ]
    return "\n".join(lines)


def write_monthly_report(root: Path, month: str | None = None) -> dict[str, Any]:
    loaded = load_book(root)
    snapshot = loaded["snapshot"]
    if month is None:
        last = snapshot.get("last_session")
        if not last:
            raise PaperDataError("no session has been marked")
        month = str(last)[:7]
    report = build_monthly_report(snapshot, month)
    folder = paper_dir(root) / "monthly"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{month}.json").write_text(json.dumps(scrub(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / f"{month}.md").write_text(render_monthly_markdown(report), encoding="utf-8")
    return report


def public_state(root: Path | None = None) -> dict[str, Any]:
    loaded = load_book(root)
    snap = loaded["snapshot"]
    last = snap.get("last_session")
    point = snap["curve"][-1]
    return {
        "eligible_for_live_trading": False,
        "preregistration_sha256": loaded["preregistration_sha256"],
        "ledger_head": loaded["ledger_head"],
        "ledger_entries": loaded["entries"],
        "last_session": last,
        "pending_inception": snap["pending_inception"],
        "pending_a_rebalance": snap["pending_a_rebalance"],
        "entry_session": ENTRY_SESSION.isoformat(),
        "signal_session": SIGNAL_SESSION.isoformat(),
        "nav": {
            "A": point.get("a_equity"),
            "B": point.get("b_equity"),
            "combined_multiplier": point.get("combined_multiplier"),
            "a_bova_weight": point.get("a_bova_weight"),
            "cdi_index": point.get("cdi_index"),
            "ibov_index": point.get("ibov_index"),
        },
        "composition_b_target": snap["frozen_b_targets"],
        "positions_b": snap["b"]["net_positions"],
        "positions_a": {
            "bova_shares": snap["a"]["bova_shares"],
            "cdi_value": _cdi_value(snap["a"]) if snap["a"]["cdi"]["lots"] else 0.0,
            "idle_cash": snap["a"]["idle_cash"],
        },
    }

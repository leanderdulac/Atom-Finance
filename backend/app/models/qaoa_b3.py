"""Point-in-time subset selection on the locked B3 small-cap book.

Research and paper simulation only. The universe, the costs and the
corporate-action rules are the quarterly small-cap sleeve already chosen on
data through 2018-12-31. Hyperparameters of a subset rule are chosen on that
same window. Nothing here sends an order. ``eligible_for_live_trading`` stays
false.

QAOA on a classical statevector simulator is a solver slot. This module does
not run it. It publishes the causal snapshot a solver reads, checks the
selection that comes back, and scores every solver on one purged walk-forward.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from app.models.afml.gate import gate
from app.models.afml.trials import TrialRegistry
from app.models.covariance import ledoit_wolf_constant_correlation
from app.models.equal_weight import (
    ADV_WINDOW,
    DESIGN_END,
    EVAL_START,
    LONG_HORIZON_TRIALS,
    PUBLISHED_FIRST_SIGNAL,
    SELECTION_AUM,
    SMALL_MIN_NAMES,
    UNKNOWN_WITHHOLDING,
    Target,
    build_signal_book,
    calendar_table,
    capacity_of,
    event_arrays,
    one_way_turnover,
    plausible_cash,
    signal_ordinals,
    simulate_book,
    slice_performance,
)
from app.models.equal_weight import (
    FAMILY_ID as EQUAL_WEIGHT_FAMILY,
)
from app.models.equal_weight_io import CashEvent, Listing
from app.models.net_net import (
    PERIODS_PER_YEAR,
    PRICE_STALE_SESSIONS,
    Company,
    SharePoint,
    Tape,
    execution_book,
    monthly_simple_returns,
    performance,
    price_fill,
)
from app.models.net_net_io import cdi_growth
from app.models.rejected_net_net import rejected_ledger_count

FAMILY_ID = "b3_qaoa_portfolio"
ELIGIBLE_FOR_LIVE_TRADING = False
SCHEMA_VERSION = "qaoa-b3-snapshot-1"
HOLDOUT_SCHEMA_VERSION = "qaoa-b3-holdout-1"
SELECTION_SCHEMA_VERSION = "qaoa-b3-selection-1"
REPORT_SCHEMA_VERSION = "qaoa-b3-phase1-1"

# The sleeve the equal-weight study locked before reading 2019–2026.
ADV_FLOOR = 200_000.0
UNIVERSE = "small"
FREQUENCY = "quarterly"
AUM_LOOSE = 100_000.0
AUMS = (AUM_LOOSE, SELECTION_AUM)

K_MIN = 15
K_MAX = 20
K_GRID = tuple(range(K_MIN, K_MAX + 1))
LAMBDA_GRID = (0.5, 1.0, 2.0, 5.0)

# Purge: μ and Σ stop this many market sessions before the signal.
# The fill is still the next session after the signal, as in the equal-weight book.
EMBARGO_SESSIONS = 5
MU_WINDOW = 252
MU_MIN_OBS = 60
HOLDING_SESSIONS = 63
HASH_DECIMALS = 10

# Solver knobs locked before any out-of-sample path of this study is read.
RANDOM_SEEDS = (7, 11)
SA_SEED = 7
SA_STEPS = 400
SA_T0 = 0.02
SA_COOL = 0.995

UNIVERSE_RULE = (
    "small; bottom 30 percent point-in-time market cap; financial issuers excluded; "
    f"trailing {ADV_WINDOW}-session median BRL volume at least {ADV_FLOOR:.0f}; "
    "at least 20 prints and a print within 5 sessions; one ticker per issuer, the highest ADV; "
    f"quarterly signal on the last market session of March, June, September and December, "
    f"fill on the next session; fewer than {SMALL_MIN_NAMES} names and the book is cash; "
    f"first signal on or after {PUBLISHED_FIRST_SIGNAL.isoformat()}; no earlier rebalance"
)

SOLVER_ALIASES = {
    "equal_weight37": "equal_weight37",
    "equal_weight_universe": "equal_weight37",
    "equal_weight_k": "equal_weight_k",
    "random_K": "random_K",
    "random_k": "random_K",
    "milp_exact": "milp_exact",
    "sa": "sa",
    "simulated_annealing": "sa",
    "qaoa_aer": "qaoa_aer",
}
CANONICAL_SOLVERS = frozenset(SOLVER_ALIASES.values())
GENERATED_SOLVERS = ("equal_weight37", "equal_weight_k", "random_K", "milp_exact", "sa")
OPTIMIZERS = frozenset({"milp_exact", "sa", "qaoa_aer"})
SUBSET_SOLVERS = frozenset({"equal_weight_k", "random_K", "milp_exact", "sa", "qaoa_aer"})

_REPO = Path(__file__).resolve().parents[3]
EQUAL_WEIGHT_REPORT = _REPO / "docs" / "reports" / "equal-weight-b3.json"
DEFAULT_PRIOR_REGISTRIES = (
    _REPO / "data" / "equal-weight" / "trials.sqlite",
    _REPO / "data" / "net-net" / "trials.sqlite",
)

_LEAK_TOKENS = ("oos", "holdout", "forward", "future")


def canon_float(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite value in the snapshot")
    number = round(number, HASH_DECIMALS)
    if number == 0.0:
        return 0.0
    return number


def canonical_solver(name: str) -> str:
    key = str(name).strip()
    if key not in SOLVER_ALIASES:
        known = ", ".join(sorted(SOLVER_ALIASES))
        raise ValueError(f"unknown solver {name!r}; expected one of {known}")
    return SOLVER_ALIASES[key]


def quarter_signals(sessions: Sequence[int]) -> list[int]:
    """Quarter-end sessions on or after the published first signal.

    March 2012 is before 2012-05-02, so it is not a rebalance. No session in
    2010 is a rebalance even when the price cache starts in 2011.
    """
    first = PUBLISHED_FIRST_SIGNAL.toordinal()
    return [int(day) for day in signal_ordinals(sessions, FREQUENCY) if int(day) >= first]


def _as_date(value: Any) -> date:
    if type(value) is date:
        return value
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    convert = getattr(value, "date", None)
    if callable(convert):
        converted = convert()
        if type(converted) is date:
            return converted
        if isinstance(converted, date):
            return date(converted.year, converted.month, converted.day)
    return date.fromisoformat(str(value)[:10])


def _optional_int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, bool):
        raise ValueError("integer field is a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not an integer: {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"not an integer: {value!r}")
    return int(number)


def _optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, bool):
        raise ValueError("lambda is a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not math.isfinite(number):
        return None
    return canon_float(number)


def coerce_tickers(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("tickers JSON must be a list")
            return [str(item).strip().upper() for item in parsed if str(item).strip()]
        return [part.strip().upper() for part in text.split(",") if part.strip()]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    raise ValueError("tickers must be a list or a comma-separated string")


def _leak(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(token in lowered for token in _LEAK_TOKENS)


@dataclass(frozen=True)
class ReturnPoint:
    ordinal: int
    value: float
    in_estimation: bool
    in_mu_window: bool


@dataclass(frozen=True)
class NameView:
    ticker: str
    cnpj: str
    adv_brl: float
    adv_shares: float
    mcap: float | None
    close: float
    bid: float
    ask: float
    spread_source: str
    returns: tuple[ReturnPoint, ...]
    n_history: int
    n_estimation: int
    estimable: bool
    mu: float | None
    sigma_index: int
    costs: dict[str, Any]


@dataclass(frozen=True)
class Snapshot:
    rebalance: date
    rebalance_ordinal: int
    estimation_end: date
    estimation_end_ordinal: int
    names: tuple[NameView, ...]
    sigma_tickers: tuple[str, ...]
    sigma: tuple[tuple[float, ...], ...]
    sigma_method: str
    sigma_alpha: float | None
    sigma_r_bar: float | None
    cash: bool
    snapshot_hash: str

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(name.ticker for name in self.names)


@dataclass(frozen=True)
class Selection:
    rebalance: date
    solver: str
    k: int | None
    lam: float | None
    p: int | None
    tickers: tuple[str, ...]
    seed: int | None = None
    n_trials_total: int | None = None
    meta: tuple[tuple[str, str], ...] = ()


def quote_on(tape: Tape, ordinal: int) -> tuple[float, float, float] | None:
    idx = tape.index_on_or_before(int(ordinal))
    if idx is None:
        return None
    if int(ordinal) - int(tape.dates[idx]) > PRICE_STALE_SESSIONS:
        return None
    close = float(tape.close[idx])
    if not math.isfinite(close) or close <= 0:
        return None
    bid = float(tape.bid[idx]) if math.isfinite(float(tape.bid[idx])) else 0.0
    ask = float(tape.ask[idx]) if math.isfinite(float(tape.ask[idx])) else 0.0
    return close, bid, ask


def quote_cost(
    close: float,
    bid: float,
    ask: float,
    adv_brl: float,
    adv_shares: float,
    aum: float,
    breadth: int,
) -> dict[str, Any]:
    """Round-trip drag versus the mid, in bps of ``aum / breadth``.

    The fill is ``price_fill``: B3 taker fee, half-spread, participation
    slippage, and the 5,000 bps cap. Quantity is ``notional / close``.
    """
    if breadth < 1 or close <= 0 or aum <= 0:
        raise ValueError("breadth, close and aum must be positive")
    notional = float(aum) / float(breadth)
    qty = notional / float(close)
    book, source = execution_book(float(close), float(bid), float(ask), float(adv_brl), float(adv_shares))
    buy, cap_buy = price_fill("buy", qty, float(close), book)
    sell, cap_sell = price_fill("sell", qty, float(close), book)

    def bps(total: float) -> float:
        return float(total) / notional * 10_000.0

    return {
        "entry_bps": bps(buy.total),
        "exit_bps": bps(sell.total),
        "roundtrip_bps": bps(buy.total + sell.total),
        "notional": notional,
        "capped": bool(cap_buy or cap_sell),
        "spread_source": source,
    }


def _cash_on(series: tuple[np.ndarray, np.ndarray] | None, ordinal: int) -> float:
    if series is None:
        return 0.0
    dates, amounts = series
    idx = np.flatnonzero(dates == int(ordinal))
    if len(idx) == 0:
        return 0.0
    total = float(np.sum(amounts[idx]))
    if not math.isfinite(total) or total <= 0:
        return 0.0
    return total


def adjusted_points(
    tape: Tape,
    sessions: Sequence[int],
    cash: tuple[np.ndarray, np.ndarray] | None,
    *,
    lo_exclusive: int,
    hi_inclusive: int,
    estimation_end: int | None = None,
    window: set[int] | None = None,
) -> tuple[ReturnPoint, ...]:
    """One-day total return on sessions the name actually printed.

    ``r_t = f_t * (P_t + d_t) / P_{t-1} - 1``. ``f_t`` is the confirmed split
    factor (1 when there is none). ``d_t`` is after-tax cash per current share.
    A gap of more than one market session does not invent a daily return.
    """
    pos = {int(day): i for i, day in enumerate(tape.dates)}
    points: list[ReturnPoint] = []
    for i, ordinal in enumerate(sessions):
        day = int(ordinal)
        if day <= lo_exclusive or day > hi_inclusive or i == 0:
            continue
        prev = int(sessions[i - 1])
        idx = pos.get(day)
        prev_idx = pos.get(prev)
        if idx is None or prev_idx is None:
            continue
        prev_px = float(tape.close[prev_idx])
        px = float(tape.close[idx])
        if prev_px <= 0 or px <= 0 or not math.isfinite(prev_px) or not math.isfinite(px):
            continue
        factor = float(tape.split[idx])
        if not math.isfinite(factor) or factor <= 0:
            factor = 1.0
        dividend = _cash_on(cash, day)
        value = factor * (px + dividend) / prev_px - 1.0
        if not math.isfinite(value):
            continue
        in_est = estimation_end is not None and day <= int(estimation_end)
        in_win = bool(window) and day in window and in_est
        points.append(
            ReturnPoint(day, canon_float(value), in_est, in_win)
        )
    return tuple(points)


def _mle_var(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    centered = values - float(values.mean())
    return float(centered @ centered / len(values))


def estimate_mu_sigma(
    names: Sequence[NameView],
) -> tuple[tuple[str, ...], tuple[tuple[float, ...], ...], str, float | None, float | None, dict[str, float | None]]:
    """μ and Σ from ``in_mu_window`` rows only.

    Complete cases feed Ledoit–Wolf (constant-correlation target) when at
    least eight sessions remain and at least two names are estimable. A
    shorter intersection falls back to a diagonal of each name's own MLE
    variance. Names with fewer than ``MU_MIN_OBS`` window returns are not
    estimable: they stay in the universe and out of Σ.
    """
    estimable = [name for name in names if name.n_estimation >= MU_MIN_OBS]
    mus = {name.ticker: (None if name.n_estimation < MU_MIN_OBS else _mean_window(name)) for name in names}
    if len(estimable) == 0:
        return (), (), "none", None, None, mus
    tickers = tuple(name.ticker for name in estimable)
    if len(estimable) == 1:
        var = _mle_var(np.asarray([point.value for point in estimable[0].returns if point.in_mu_window], dtype=np.float64))
        return tickers, ((canon_float(var),),), "single_name", None, None, mus
    maps = [{point.ordinal: point.value for point in name.returns if point.in_mu_window} for name in estimable]
    sessions = sorted(set().union(*[set(item) for item in maps]))
    rows = [session for session in sessions if all(session in item for item in maps)]
    method = "diagonal_fallback"
    alpha: float | None = None
    r_bar: float | None = None
    if len(rows) >= 8:
        panel = np.asarray([[item[session] for item in maps] for session in rows], dtype=np.float64)
        try:
            shrunk, meta = ledoit_wolf_constant_correlation(panel)
            if not np.all(np.isfinite(shrunk)):
                raise ValueError("non-finite shrinkage")
            matrix = tuple(tuple(canon_float(float(value)) for value in row) for row in shrunk)
            alpha = canon_float(float(meta["alpha"]))
            r_bar = canon_float(float(meta["r_bar"]))
            return tickers, matrix, "ledoit_wolf_constant_correlation", alpha, r_bar, mus
        except ValueError:
            method = "diagonal_fallback"
    variances = [_mle_var(np.asarray(list(item.values()), dtype=np.float64)) for item in maps]
    matrix = []
    for i, var_i in enumerate(variances):
        line = [0.0] * len(variances)
        line[i] = canon_float(var_i)
        matrix.append(tuple(line))
    return tickers, tuple(matrix), method, alpha, r_bar, mus


def _mean_window(name: NameView) -> float | None:
    values = [point.value for point in name.returns if point.in_mu_window]
    if len(values) < MU_MIN_OBS:
        return None
    return canon_float(float(np.mean(np.asarray(values, dtype=np.float64))))


def universe_book(
    companies: Sequence[Company],
    listings: Sequence[Listing],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
) -> dict[int, list[Target]]:
    """The locked small-cap book at each quarter-end on or after 2012-05-02."""
    signals = quarter_signals(sessions)
    if not signals:
        return {}
    return build_signal_book(
        companies,
        listings,
        tapes,
        signals,
        UNIVERSE,
        ADV_FLOOR,
        min_names=SMALL_MIN_NAMES,
        adv_window=ADV_WINDOW,
    )


def _round_cost(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_bps": canon_float(float(raw["entry_bps"])),
        "exit_bps": canon_float(float(raw["exit_bps"])),
        "roundtrip_bps": canon_float(float(raw["roundtrip_bps"])),
        "notional": canon_float(float(raw["notional"])),
        "capped": bool(raw["capped"]),
        "spread_source": str(raw["spread_source"]),
    }


def build_snapshot(
    signal: int,
    sessions: Sequence[int],
    targets: Sequence[Target],
    tapes: dict[str, Tape],
    taxed: Mapping[str, tuple[np.ndarray, np.ndarray]] | None,
) -> Snapshot:
    """Causal panel for one rebalance. Every return date is on or before ``signal``."""
    ordered = [int(day) for day in sessions]
    try:
        pos = ordered.index(int(signal))
    except ValueError as exc:
        raise ValueError("signal is not on the session calendar") from exc
    if pos < EMBARGO_SESSIONS:
        raise ValueError("not enough sessions before the signal to place the embargo")
    estimation_end = ordered[pos - EMBARGO_SESSIONS]
    history = [day for day in ordered if day <= estimation_end]
    window = set(history[-MU_WINDOW:])
    breadth = len(targets)
    draft: list[NameView] = []
    for target in sorted(targets, key=lambda item: item.ticker):
        tape = tapes.get(target.ticker)
        if tape is None:
            raise ValueError(f"{target.ticker} is in the universe and has no tape")
        quote = quote_on(tape, int(signal))
        if quote is None:
            raise ValueError(f"{target.ticker} has no usable quote on the signal")
        close, bid, ask = (canon_float(quote[0]), canon_float(quote[1]), canon_float(quote[2]))
        adv_brl = canon_float(float(target.adv_brl))
        adv_shares = canon_float(float(target.adv_shares))
        points = adjusted_points(
            tape,
            ordered,
            None if taxed is None else taxed.get(target.ticker),
            lo_exclusive=ordered[0] - 1,
            hi_inclusive=int(signal),
            estimation_end=estimation_end,
            window=window,
        )
        if any(point.ordinal > int(signal) for point in points):
            raise ValueError("snapshot return is after the rebalance")
        n_est = sum(1 for point in points if point.in_mu_window)
        costs = {
            "aum_100k": _round_cost(quote_cost(close, bid, ask, adv_brl, adv_shares, AUM_LOOSE, breadth)),
            "aum_1m": _round_cost(quote_cost(close, bid, ask, adv_brl, adv_shares, SELECTION_AUM, breadth)),
        }
        draft.append(
            NameView(
                ticker=target.ticker,
                cnpj=target.cnpj,
                adv_brl=adv_brl,
                adv_shares=adv_shares,
                mcap=None if target.mcap is None else canon_float(float(target.mcap)),
                close=close,
                bid=bid,
                ask=ask,
                spread_source=str(costs["aum_1m"]["spread_source"]),
                returns=points,
                n_history=len(points),
                n_estimation=n_est,
                estimable=n_est >= MU_MIN_OBS,
                mu=None,
                sigma_index=-1,
                costs=costs,
            )
        )
    tickers, matrix, method, alpha, r_bar, mus = estimate_mu_sigma(draft)
    index = {ticker: i for i, ticker in enumerate(tickers)}
    names = tuple(
        NameView(
            ticker=name.ticker,
            cnpj=name.cnpj,
            adv_brl=name.adv_brl,
            adv_shares=name.adv_shares,
            mcap=name.mcap,
            close=name.close,
            bid=name.bid,
            ask=name.ask,
            spread_source=name.spread_source,
            returns=name.returns,
            n_history=name.n_history,
            n_estimation=name.n_estimation,
            estimable=name.ticker in index,
            mu=mus[name.ticker],
            sigma_index=index.get(name.ticker, -1),
            costs=name.costs,
        )
        for name in draft
    )
    snap = Snapshot(
        rebalance=date.fromordinal(int(signal)),
        rebalance_ordinal=int(signal),
        estimation_end=date.fromordinal(estimation_end),
        estimation_end_ordinal=estimation_end,
        names=names,
        sigma_tickers=tickers,
        sigma=matrix,
        sigma_method=method,
        sigma_alpha=alpha,
        sigma_r_bar=r_bar,
        cash=breadth < SMALL_MIN_NAMES,
        snapshot_hash="",
    )
    digest = payload_hash(canonical_payload(snap))
    return Snapshot(
        rebalance=snap.rebalance,
        rebalance_ordinal=snap.rebalance_ordinal,
        estimation_end=snap.estimation_end,
        estimation_end_ordinal=snap.estimation_end_ordinal,
        names=snap.names,
        sigma_tickers=snap.sigma_tickers,
        sigma=snap.sigma,
        sigma_method=snap.sigma_method,
        sigma_alpha=snap.sigma_alpha,
        sigma_r_bar=snap.sigma_r_bar,
        cash=snap.cash,
        snapshot_hash=digest,
    )


def build_snapshots(
    companies: Sequence[Company],
    listings: Sequence[Listing],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    events: dict[str, list[CashEvent]] | None,
) -> tuple[dict[int, list[Target]], dict[str, tuple[np.ndarray, np.ndarray]], list[Snapshot]]:
    book = universe_book(companies, listings, tapes, sessions)
    kept, _dropped = plausible_cash(events, tapes)
    taxed = event_arrays(kept, UNKNOWN_WITHHOLDING)
    snapshots = [
        build_snapshot(int(signal), sessions, book.get(int(signal), []), tapes, taxed)
        for signal in sorted(book)
    ]
    return book, taxed, snapshots


def holdout_points(
    signal: int,
    nxt: int | None,
    sessions: Sequence[int],
    targets: Sequence[Target],
    tapes: dict[str, Tape],
    taxed: Mapping[str, tuple[np.ndarray, np.ndarray]] | None,
) -> tuple[int, tuple[tuple[str, int, float], ...]]:
    """Realized one-day returns on ``(signal, next]``. Not an input to selection."""
    ordered = [int(day) for day in sessions]
    last = int(ordered[-1] if nxt is None else nxt)
    rows: list[tuple[str, int, float]] = []
    for target in sorted(targets, key=lambda item: item.ticker):
        tape = tapes.get(target.ticker)
        if tape is None:
            continue
        points = adjusted_points(
            tape,
            ordered,
            None if taxed is None else taxed.get(target.ticker),
            lo_exclusive=int(signal),
            hi_inclusive=last,
        )
        for point in points:
            if point.ordinal <= int(signal):
                raise ValueError("holdout return is not after the signal")
            rows.append((target.ticker, point.ordinal, point.value))
    rows.sort()
    return last, tuple(rows)


def canonical_payload(snap: Snapshot) -> dict[str, Any]:
    names = []
    for name in snap.names:
        names.append(
            {
                "adv_brl": name.adv_brl,
                "adv_shares": name.adv_shares,
                "ask": name.ask,
                "bid": name.bid,
                "close": name.close,
                "cnpj": name.cnpj,
                "costs": name.costs,
                "estimable": name.estimable,
                "mcap": name.mcap,
                "mu": name.mu,
                "n_estimation": name.n_estimation,
                "n_history": name.n_history,
                "returns": [
                    {
                        "in_estimation": point.in_estimation,
                        "in_mu_window": point.in_mu_window,
                        "r": point.value,
                        "session_date": date.fromordinal(point.ordinal).isoformat(),
                    }
                    for point in name.returns
                ],
                "sigma_index": name.sigma_index,
                "spread_source": name.spread_source,
                "ticker": name.ticker,
            }
        )
    return {
        "as_of": snap.rebalance.isoformat(),
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "embargo_sessions": EMBARGO_SESSIONS,
        "estimation_end": snap.estimation_end.isoformat(),
        "family_id": FAMILY_ID,
        "holding_sessions": HOLDING_SESSIONS,
        "k_max": K_MAX,
        "k_min": K_MIN,
        "lambda_grid": [canon_float(value) for value in LAMBDA_GRID],
        "mu_min_obs": MU_MIN_OBS,
        "mu_window_sessions": MU_WINDOW,
        "names": names,
        "rebalance_date": snap.rebalance.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "sigma": {
            "alpha": snap.sigma_alpha,
            "matrix": [list(row) for row in snap.sigma],
            "method": snap.sigma_method,
            "r_bar": snap.sigma_r_bar,
            "tickers": list(snap.sigma_tickers),
        },
        "universe_rule": UNIVERSE_RULE,
    }


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def definitions() -> dict[str, Any]:
    return {
        "return": "r_t = f_t * (P_t + d_t) / P_{t-1} - 1 on a market session where the name prints on both t and the previous market session",
        "split": "f_t is the confirmed split factor on t, else 1. An unconfirmed price gap stays in P.",
        "cash": (
            "d_t is after-tax reais per current share. Labeled dividends are exempt. "
            "Labeled JCP is withheld at 15 percent. Unlabeled events are withheld at 15 percent. "
            "An amount above the previous close is dropped. Same-day confirmed split scales the cash "
            "because the share count changes before the cash is credited."
        ),
        "gap": "A name that skips a market session contributes no daily return for that pair. The gap move is not spread into a one-day return.",
        "embargo": (
            f"estimation_end is the market session {EMBARGO_SESSIONS} sessions before the signal. "
            "in_mu_window is the last "
            f"{MU_WINDOW} sessions on or before estimation_end. Rows after estimation_end and through "
            "the signal stay in the file and are excluded from mu and Sigma."
        ),
        "mu": f"Arithmetic mean of in_mu_window adjusted returns. estimable requires at least {MU_MIN_OBS} such returns.",
        "sigma": (
            "Ledoit-Wolf linear shrinkage toward constant correlation, "
            "Sigma_LW = alpha* F + (1 - alpha*) S, S the 1/T sample covariance of complete cases "
            "in the mu window. If fewer than 8 complete sessions remain, Sigma is diagonal "
            "(each name's own MLE variance, covariance 0). Order is ticker ascending among estimable names."
        ),
        "objective": (
            "score(x) = (H/K) x·mu - lambda (H/K^2) x' Sigma x - (1/K) x·c, "
            f"H = {HOLDING_SESSIONS}, sum(x) = K, x binary, only estimable names. "
            "c_i is the round-trip cost as a fraction of notional at AUM "
            f"{SELECTION_AUM:.0f} and breadth K, from quote_cost. "
            "The parquet bps columns are the same model at breadth = n_universe for AUM "
            f"{AUM_LOOSE:.0f} and {SELECTION_AUM:.0f}. They are not the K-subset penalty."
        ),
        "costs": "price_fill on the B3 taker schedule: fee, half-spread, participation slippage, cap 5000 bps.",
        "holdout": "holdout/YYYY-MM-DD_fwd.parquet is realized returns after the signal. It is not a selection input.",
        "eligible_for_live_trading": False,
    }


def objective_score(mu: np.ndarray, sigma: np.ndarray, cost: np.ndarray, chosen: Sequence[int], lam: float) -> float:
    k = len(chosen)
    if k < 1:
        return 0.0
    x = np.zeros(len(mu), dtype=np.float64)
    x[list(chosen)] = 1.0
    quad = float(x @ sigma @ x)
    return (HOLDING_SESSIONS / k) * float(x @ mu) - lam * (HOLDING_SESSIONS / (k * k)) * quad - (1.0 / k) * float(x @ cost)


def _estimable_panel(snap: Snapshot) -> tuple[list[str], np.ndarray, np.ndarray]:
    names = [name for name in snap.names if name.estimable and name.mu is not None and name.sigma_index >= 0]
    names.sort(key=lambda item: item.sigma_index)
    if not names:
        return [], np.zeros(0), np.zeros((0, 0))
    mu_list: list[float] = []
    for name in names:
        value = name.mu
        if value is None:
            raise ValueError(f"{name.ticker} is estimable without mu")
        mu_list.append(float(value))
    mu = np.asarray(mu_list, dtype=np.float64)
    if snap.sigma:
        sigma = np.asarray(snap.sigma, dtype=np.float64)
    else:
        sigma = np.zeros((len(names), len(names)))
    return [name.ticker for name in names], mu, sigma


def _cost_vector(snap: Snapshot, tickers: Sequence[str], k: int) -> np.ndarray:
    by_ticker = {name.ticker: name for name in snap.names}
    out = np.zeros(len(tickers), dtype=np.float64)
    for i, ticker in enumerate(tickers):
        name = by_ticker[ticker]
        raw = quote_cost(name.close, name.bid, name.ask, name.adv_brl, name.adv_shares, SELECTION_AUM, k)
        out[i] = float(raw["roundtrip_bps"]) / 10_000.0
    return out


def solve_milp(mu: np.ndarray, sigma: np.ndarray, cost: np.ndarray, k: int, lam: float) -> list[int] | None:
    """Exact cardinality quadratic via a linearization. HiGHS is the MIP solver."""
    n = int(mu.shape[0])
    if k < 1 or n < k:
        return None
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    m = len(pairs)
    nvar = n + m
    coef = np.zeros(nvar, dtype=np.float64)
    scale = lam * HOLDING_SESSIONS / (k * k)
    for i in range(n):
        coef[i] = -(HOLDING_SESSIONS / k) * float(mu[i]) + scale * float(sigma[i, i]) + (1.0 / k) * float(cost[i])
    for p, (i, j) in enumerate(pairs):
        coef[n + p] = scale * 2.0 * float(sigma[i, j])
    integrality = np.zeros(nvar, dtype=np.int8)
    integrality[:n] = 1
    n_cons = 1 + 3 * m
    matrix = lil_matrix((n_cons, nvar), dtype=np.float64)
    lower = np.full(n_cons, -np.inf, dtype=np.float64)
    upper = np.full(n_cons, np.inf, dtype=np.float64)
    matrix[0, :n] = 1.0
    lower[0] = float(k)
    upper[0] = float(k)
    row = 1
    for p, (i, j) in enumerate(pairs):
        matrix[row, n + p] = 1.0
        matrix[row, i] = -1.0
        upper[row] = 0.0
        row += 1
        matrix[row, n + p] = 1.0
        matrix[row, j] = -1.0
        upper[row] = 0.0
        row += 1
        matrix[row, i] = 1.0
        matrix[row, j] = 1.0
        matrix[row, n + p] = -1.0
        upper[row] = 1.0
        row += 1
    result = milp(
        coef,
        integrality=integrality,
        bounds=Bounds(np.zeros(nvar), np.ones(nvar)),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 20.0, "mip_rel_gap": 1e-8},
    )
    if result.x is None or not result.success:
        return None
    picked = [i for i in range(n) if float(result.x[i]) > 0.5]
    if len(picked) != k:
        return None
    return picked


def solve_sa(mu: np.ndarray, sigma: np.ndarray, cost: np.ndarray, k: int, lam: float, seed: int) -> list[int]:
    """Deterministic annealing from the highest ``mu - cost`` names. One locked schedule."""
    n = int(mu.shape[0])
    if k < 1 or n < k:
        return []
    order = sorted(range(n), key=lambda i: (-(float(mu[i]) - float(cost[i])), i))
    chosen = order[:k]
    outside = [i for i in range(n) if i not in set(chosen)]
    rng = np.random.Generator(np.random.PCG64(int(seed)))

    def score(sel: Sequence[int]) -> float:
        return objective_score(mu, sigma, cost, sel, lam)

    current = score(chosen)
    best = list(chosen)
    best_score = current
    temp = SA_T0
    for _ in range(SA_STEPS):
        if not outside:
            break
        i_pos = int(rng.integers(0, len(chosen)))
        j_pos = int(rng.integers(0, len(outside)))
        leave = chosen[i_pos]
        enter = outside[j_pos]
        trial = list(chosen)
        trial[i_pos] = enter
        trial_score = score(trial)
        delta = trial_score - current
        accept = delta >= 0 or float(rng.random()) < math.exp(max(delta / max(temp, 1e-12), -700.0))
        if accept:
            chosen = trial
            outside[j_pos] = leave
            current = trial_score
            if current > best_score:
                best_score = current
                best = list(chosen)
        temp *= SA_COOL
    return sorted(best)


def _preserve(order: Sequence[Target], chosen: set[str]) -> tuple[str, ...]:
    return tuple(row.ticker for row in order if row.ticker in chosen)


def select_equal_weight_k(targets: Sequence[Target], k: int) -> tuple[str, ...]:
    if len(targets) < k:
        return ()
    ranked = sorted(targets, key=lambda row: (-float(row.adv_brl), row.ticker))
    chosen = {row.ticker for row in ranked[:k]}
    return _preserve(targets, chosen)


def select_random_k(targets: Sequence[Target], k: int, seed: int) -> tuple[str, ...]:
    """Sample without replacement. Population order is ticker ascending. Result keeps universe order."""
    if len(targets) < k:
        return ()
    population = sorted({row.ticker for row in targets})
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    draw = rng.choice(len(population), size=k, replace=False)
    chosen = {population[int(i)] for i in draw}
    return _preserve(targets, chosen)


def select_optimizer(snap: Snapshot, k: int, lam: float, solver: str, seed: int | None) -> tuple[str, ...]:
    tickers, mu, sigma = _estimable_panel(snap)
    if len(tickers) < k:
        return ()
    cost = _cost_vector(snap, tickers, k)
    if solver == "milp_exact":
        picked = solve_milp(mu, sigma, cost, k, lam)
        if picked is None:
            return ()
    elif solver == "sa":
        picked = solve_sa(mu, sigma, cost, k, lam, SA_SEED if seed is None else int(seed))
    else:
        raise ValueError(f"{solver} is not a generated optimizer")
    chosen = {tickers[i] for i in picked}
    return tuple(name.ticker for name in snap.names if name.ticker in chosen)


def generate_selections(
    book: Mapping[int, Sequence[Target]],
    snapshots: Sequence[Snapshot],
    *,
    solvers: Sequence[str] = GENERATED_SOLVERS,
    k_values: Sequence[int] = K_GRID,
    lambdas: Sequence[float] = LAMBDA_GRID,
    random_seeds: Sequence[int] = RANDOM_SEEDS,
) -> list[Selection]:
    """Classical baselines. ``qaoa_aer`` is never generated."""
    by_ord = {snap.rebalance_ordinal: snap for snap in snapshots}
    out: list[Selection] = []
    for solver in solvers:
        if solver == "qaoa_aer":
            continue
        canonical = canonical_solver(solver)
        if canonical == "qaoa_aer":
            continue
        for ordinal in sorted(book):
            targets = list(book[ordinal])
            snap = by_ord[ordinal]
            day = snap.rebalance
            if canonical == "equal_weight37":
                out.append(
                    Selection(day, canonical, len(targets), None, None, tuple(row.ticker for row in targets))
                )
                continue
            if canonical == "equal_weight_k":
                for k in k_values:
                    out.append(Selection(day, canonical, int(k), None, None, select_equal_weight_k(targets, int(k))))
                continue
            if canonical == "random_K":
                for k in k_values:
                    for seed in random_seeds:
                        out.append(
                            Selection(
                                day,
                                canonical,
                                int(k),
                                None,
                                None,
                                select_random_k(targets, int(k), int(seed)),
                                seed=int(seed),
                            )
                        )
                continue
            if canonical in ("milp_exact", "sa"):
                for k in k_values:
                    for lam in lambdas:
                        seed = SA_SEED if canonical == "sa" else None
                        out.append(
                            Selection(
                                day,
                                canonical,
                                int(k),
                                canon_float(float(lam)),
                                None,
                                select_optimizer(snap, int(k), float(lam), canonical, seed),
                                seed=seed,
                                meta=(("generator", "classical"),),
                            )
                        )
                continue
            raise ValueError(f"no generator for {canonical}")
    return out


def selection_from_mapping(row: Mapping[str, Any]) -> Selection:
    for key in row:
        if _leak(str(key)):
            raise ValueError(f"selection column leaks held-out information: {key}")
    solver = canonical_solver(str(row.get("solver", "")))
    rebalance = _as_date(row.get("rebalance_date"))
    tickers = tuple(sorted(set(coerce_tickers(row.get("tickers")))))
    meta_raw = row.get("meta", row.get("solver_meta", {}))
    if meta_raw is None:
        meta_raw = {}
    if not isinstance(meta_raw, Mapping):
        raise ValueError("solver metadata must be an object")
    meta_pairs: list[tuple[str, str]] = []
    for key, value in meta_raw.items():
        if _leak(str(key)):
            raise ValueError(f"selection metadata leaks held-out information: {key}")
        meta_pairs.append((str(key), json.dumps(value, sort_keys=True, default=str)))
    return Selection(
        rebalance=rebalance,
        solver=solver,
        k=_optional_int(row.get("K", row.get("k"))),
        lam=_optional_float(row.get("lambda", row.get("lam"))),
        p=_optional_int(row.get("p")),
        tickers=tickers,
        seed=_optional_int(row.get("seed")),
        n_trials_total=_optional_int(row.get("n_trials_total")),
        meta=tuple(sorted(meta_pairs)),
    )


def validate_selection(sel: Selection, universe: Sequence[str]) -> None:
    """Reject a name that was not eligible on that date, and reject a leaked field."""
    if sel.solver not in CANONICAL_SOLVERS:
        raise ValueError(f"unknown solver {sel.solver}")
    for key, _value in sel.meta:
        if _leak(key):
            raise ValueError(f"selection metadata leaks held-out information: {key}")
    universe_list = list(universe)
    universe_set = set(universe_list)
    unknown = [ticker for ticker in sel.tickers if ticker not in universe_set]
    if unknown:
        raise ValueError(f"ticker outside the {sel.rebalance.isoformat()} universe: {', '.join(unknown)}")
    if len(sel.tickers) != len(set(sel.tickers)):
        raise ValueError("duplicate ticker in the selection")
    if sel.seed is not None and sel.seed < 0:
        raise ValueError("seed must be >= 0")
    if sel.solver == "equal_weight37":
        if set(sel.tickers) != universe_set:
            raise ValueError("equal_weight37 must be the full universe of that date, including when the book is cash")
        if sel.k is not None and sel.k != len(universe_list):
            raise ValueError(
                f"equal_weight37 K is the universe size that day ({len(universe_list)}), not a fixed 37"
            )
        if sel.lam is not None or sel.p is not None:
            raise ValueError("equal_weight37 has no lambda and no p")
        return
    if sel.p is not None and sel.solver != "qaoa_aer":
        raise ValueError("p is only defined for qaoa_aer")
    if sel.solver == "qaoa_aer" and sel.p not in (1, 2):
        raise ValueError("qaoa_aer p must be 1 or 2")
    if sel.k is None or sel.k < K_MIN or sel.k > K_MAX:
        raise ValueError(f"{sel.solver} K must be in {K_MIN}..{K_MAX}")
    if sel.tickers and len(sel.tickers) != sel.k:
        raise ValueError(f"{sel.solver} returned {len(sel.tickers)} names for K={sel.k}")
    if not sel.tickers and universe_list and len(universe_list) >= sel.k and sel.solver == "equal_weight37":
        raise ValueError("empty equal_weight37 selection on a live universe")
    if sel.solver in OPTIMIZERS:
        if sel.lam is None or canon_float(sel.lam) not in LAMBDA_GRID:
            raise ValueError(f"lambda must be one of {list(LAMBDA_GRID)}")
    elif sel.lam is not None:
        raise ValueError(f"{sel.solver} does not take lambda")


def group_key(sel: Selection) -> tuple[Any, ...]:
    if sel.solver == "equal_weight37":
        return (sel.solver, None, None, None, None)
    if sel.solver in ("random_K", "equal_weight_k"):
        return (sel.solver, sel.k, None, None, sel.seed)
    return (sel.solver, sel.k, None if sel.lam is None else canon_float(sel.lam), sel.p, sel.seed)


def cover_dates(selections: Sequence[Selection], dates: Sequence[date]) -> dict[tuple[Any, ...], dict[date, Selection]]:
    needed = list(dates)
    groups: dict[tuple[Any, ...], dict[date, Selection]] = defaultdict(dict)
    for sel in selections:
        key = group_key(sel)
        if sel.rebalance in groups[key]:
            raise ValueError(f"duplicate selection for {sel.solver} on {sel.rebalance.isoformat()}")
        groups[key][sel.rebalance] = sel
    for key, rows in groups.items():
        missing = [day.isoformat() for day in needed if day not in rows]
        if missing:
            raise ValueError(f"{key[0]} is missing rebalance dates: {', '.join(missing[:8])}")
    return groups


def _cdi_cagr(ords: np.ndarray, rates: np.ndarray, start_ord: int, end_ord: int) -> float | None:
    if len(ords) == 0 or end_ord <= start_ord:
        return None
    growth = cdi_growth(ords, rates, start_ord, end_ord)
    years = (end_ord - start_ord) / 365.25
    if years <= 0.05 or growth <= 0:
        return None
    return float(growth ** (1.0 / years) - 1.0)


def _round(value: Any, ndigits: int = 6) -> Any:
    if value is None or isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


def choose_rule(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Highest design-window net Sharpe. Out-of-sample fields are not read.

    Ties break toward higher design CAGR, lower design turnover, smaller K,
    smaller lambda, the solver name, smaller p, then smaller seed.
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

    def sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        cagr = row.get("design_cagr")
        turnover = row.get("design_turnover")
        lam = row.get("lam")
        return (
            -float(row["design_sharpe"]),
            -(float(cagr) if cagr is not None else -1e9),
            float(turnover) if turnover is not None else 1e9,
            int(row["k"]) if row.get("k") is not None else 10**9,
            float(lam) if lam is not None else 1e9,
            str(row.get("solver")),
            int(row["p"]) if row.get("p") is not None else 0,
            int(row["seed"]) if row.get("seed") is not None else 0,
        )

    return dict(sorted(usable, key=sort_key)[0])


def judge(returns: Sequence[float], n_trials: float) -> dict[str, Any] | None:
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
    infinite = min_trl is not None and not math.isfinite(float(min_trl))
    return {
        "psr": judged.psr,
        "dsr": judged.dsr,
        "sr_star": judged.sr_star,
        "min_trl_months": None if min_trl is None or infinite else min_trl,
        "min_trl_infinite": infinite,
        "n_obs_months": judged.n_obs,
        "n_trials": float(n_trials),
        "sharpe": judged.observed_sharpe,
    }


def _readonly_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute("SELECT family_id, COUNT(*) FROM trials GROUP BY family_id").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {str(family): int(count) for family, count in rows}


def published_equal_weight_trials() -> int:
    if not EQUAL_WEIGHT_REPORT.exists():
        return 55
    payload = json.loads(EQUAL_WEIGHT_REPORT.read_text(encoding="utf-8"))
    return int(payload["n_trials"])


def prior_ledger(registry: TrialRegistry, extra_registries: Sequence[Path] = ()) -> dict[str, Any]:
    """N for DSR: this family, the 32 rejected net-nets, the 55 equal-weight trials, and factor trials only when a registry actually holds them."""
    rejected = rejected_ledger_count()
    equal_n = 0
    equal_source = "published_report"
    factor_n = 0
    factor_source = "not_accessible"
    paths = list(extra_registries) + list(DEFAULT_PRIOR_REGISTRIES)
    for path in paths:
        counts = _readonly_counts(Path(path))
        if counts.get(EQUAL_WEIGHT_FAMILY, 0) > equal_n:
            equal_n = counts[EQUAL_WEIGHT_FAMILY]
            equal_source = str(path)
        for family, count in counts.items():
            if "factor" in family.lower() and count > factor_n:
                factor_n = count
                factor_source = f"{path}:{family}"
    if equal_n == 0:
        equal_n = published_equal_weight_trials()
        equal_source = "published_report"
    family_n = registry.count(FAMILY_ID)
    n_decision = int(family_n + rejected + equal_n + factor_n)
    return {
        "family": family_n,
        "rejected_net_net": rejected,
        "equal_weight": equal_n,
        "equal_weight_source": equal_source,
        "factor_trials": factor_n,
        "factor_source": factor_source,
        "factor_accessible": factor_n > 0,
        "published_factor_trials_not_in_registry": 0 if factor_n else LONG_HORIZON_TRIALS,
        "n_decision": n_decision,
        "n_transparency_if_factor_block_added": n_decision if factor_n else n_decision + LONG_HORIZON_TRIALS,
        "dsr_uses": "n_decision",
    }


def _reset_registry(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix) if suffix else path
        if candidate.exists():
            candidate.unlink()


def _book_from_group(
    book: Mapping[int, Sequence[Target]],
    snaps: Mapping[int, Snapshot],
    group: Mapping[date, Selection],
) -> dict[int, list[Target]]:
    out: dict[int, list[Target]] = {}
    for ordinal, rows in book.items():
        day = date.fromordinal(int(ordinal))
        sel = group.get(day)
        if sel is None or not sel.tickers:
            out[int(ordinal)] = []
            continue
        chosen = set(sel.tickers)
        out[int(ordinal)] = [row for row in rows if row.ticker in chosen]
    if snaps and len(out) != len(book):
        raise ValueError("selection book dropped a rebalance")
    return out


def _path_fields(
    spec: Selection,
    run: dict[str, Any],
    selected: dict[int, list[Target]],
    monthly_ords: Sequence[int],
    monthly: Sequence[float],
    cdi_ords: np.ndarray,
    cdi_rates: np.ndarray,
) -> dict[str, Any]:
    design_end = DESIGN_END.toordinal()
    eval_start = EVAL_START.toordinal()
    _g_ords, monthly_g = monthly_simple_returns(run["ords"], run["gross"])
    full_net = performance(run["ords"], run["net"], monthly)
    full_gross = performance(run["ords"], run["gross"], monthly_g)
    design = slice_performance(run, "net", None, design_end)
    oos_net = slice_performance(run, "net", eval_start, None)
    oos_gross = slice_performance(run, "gross", eval_start, None)
    design_rets = [ret for ordinal, ret in zip(monthly_ords, monthly, strict=False) if int(ordinal) <= design_end]
    oos_rets = [ret for ordinal, ret in zip(monthly_ords, monthly, strict=False) if int(ordinal) >= eval_start]
    design_book = {int(ordinal): rows for ordinal, rows in selected.items() if int(ordinal) <= design_end}
    turnover = one_way_turnover(selected) * 4.0
    design_turnover = one_way_turnover(design_book) * 4.0
    cap = capacity_of(selected)
    base_marks = [int(day) for day in run["ords"] if int(day) <= design_end]
    cdi_start = base_marks[-1] if base_marks else (int(run["ords"][0]) if run["ords"] else design_end)
    cdi_end = int(run["ords"][-1]) if run["ords"] else cdi_start
    oos_cdi = _cdi_cagr(cdi_ords, cdi_rates, cdi_start, cdi_end)
    oos_cagr = oos_net.get("cagr")
    excess = None if oos_cagr is None or oos_cdi is None else float(oos_cagr) - float(oos_cdi)
    stats = run["stats"]
    return {
        "solver": spec.solver,
        "k": spec.k,
        "lam": spec.lam,
        "p": spec.p,
        "seed": spec.seed,
        "selection_candidate": spec.solver != "equal_weight37",
        "aum_brl": SELECTION_AUM,
        "cagr_gross": _round(full_gross.get("cagr")),
        "cagr_net": _round(full_net.get("cagr")),
        "sharpe_net": _round(full_net.get("sharpe")),
        "max_drawdown_net": _round(full_net.get("max_drawdown")),
        "design_sharpe": _round(design.get("sharpe")),
        "design_cagr": _round(design.get("cagr")),
        "design_max_drawdown": _round(design.get("max_drawdown")),
        "n_design": len(design_rets),
        "design_turnover": _round(design_turnover, 4),
        "turnover_one_way_annual": _round(turnover, 4),
        "oos_cagr_gross": _round(oos_gross.get("cagr")),
        "oos_cagr_net": _round(oos_cagr),
        "oos_sharpe": _round(oos_net.get("sharpe")),
        "oos_max_drawdown_net": _round(oos_net.get("max_drawdown")),
        "oos_cagr_cdi": _round(oos_cdi),
        "oos_excess_cagr_over_cdi": _round(excess),
        "oos_n_months": len(oos_rets),
        "capacity_typical_10pct_adv": _round(cap["capacity_typical_10pct_adv"], 2),
        "capacity_thin_10pct_adv": _round(cap["capacity_thin_10pct_adv"], 2),
        "median_names": cap["median_names"],
        "fraction_rebalances_in_cash": _round(cap["fraction_rebalances_in_cash"], 4),
        "fills_capped": int(stats.n_capped),
        "fills": int(stats.n),
        "month_ends": [date.fromordinal(int(day)).isoformat() for day in monthly_ords],
        "monthly_net": [round(float(value), 8) for value in monthly],
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "_oos_rets": [float(value) for value in oos_rets],
        "_monthly": [float(value) for value in monthly],
        "_monthly_ords": [int(day) for day in monthly_ords],
        "_run": run,
        "_book": selected,
    }


def _spec_params(spec: Selection, role: str, aum: float) -> dict[str, Any]:
    return {
        "family": FAMILY_ID,
        "role": role,
        "solver": spec.solver,
        "K": spec.k,
        "lambda": spec.lam,
        "p": spec.p,
        "seed": spec.seed,
        "aum_brl": aum,
        "oos_split": "design_through_2018-12-31_eval_from_2019-01-01",
        "reported_n_trials_total": spec.n_trials_total,
    }


def run_study(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    events: dict[str, list[CashEvent]] | None,
    cdi_ords: np.ndarray,
    cdi_rates: np.ndarray,
    registry_path: str | Path,
    listings: Sequence[Listing],
    *,
    selections: Sequence[Selection] | None = None,
    solvers: Sequence[str] | None = None,
    k_values: Sequence[int] | None = None,
    lambdas: Sequence[float] | None = None,
    random_seeds: Sequence[int] | None = None,
    prior_registries: Sequence[Path] = (),
) -> dict[str, Any]:
    """Score every solver on one book. The rule is chosen on month-ends through 2018-12-31."""
    if len(sessions) < 30:
        raise ValueError("need a session calendar")
    book, taxed, snapshots = build_snapshots(companies, listings, tapes, sessions, events)
    dates = [snap.rebalance for snap in snapshots]
    by_ord = {snap.rebalance_ordinal: snap for snap in snapshots}
    external = list(selections or [])
    for sel in external:
        snap = next((item for item in snapshots if item.rebalance == sel.rebalance), None)
        if snap is None:
            raise ValueError(f"selection date {sel.rebalance.isoformat()} is not a rebalance in this sample")
        validate_selection(sel, snap.tickers)
    present = {sel.solver for sel in external}
    wanted = tuple(solvers) if solvers is not None else GENERATED_SOLVERS
    fill = [solver for solver in wanted if solver not in present and solver != "qaoa_aer"]
    generated = generate_selections(
        book,
        snapshots,
        solvers=fill,
        k_values=K_GRID if k_values is None else tuple(k_values),
        lambdas=LAMBDA_GRID if lambdas is None else tuple(lambdas),
        random_seeds=RANDOM_SEEDS if random_seeds is None else tuple(random_seeds),
    )
    for sel in generated:
        snap = by_ord[sel.rebalance.toordinal()]
        validate_selection(sel, snap.tickers)
    groups = cover_dates([*external, *generated], dates)
    paths: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda item: tuple(str(part) for part in item)):
        group = groups[key]
        sample = next(iter(group.values()))
        selected = _book_from_group(book, by_ord, group)
        run = simulate_book(
            sessions,
            tapes,
            selected,
            SELECTION_AUM,
            taxed,
            round_trip=False,
            apply_splits=True,
            haircut=0.0,
            exit_when_stale=True,
        )
        m_ords, monthly = monthly_simple_returns(run["ords"], run["net"])
        paths.append(_path_fields(sample, run, selected, m_ords, monthly, cdi_ords, cdi_rates))
    chosen_key = choose_rule(paths)
    registry_file = Path(registry_path)
    _reset_registry(registry_file)
    with TrialRegistry(registry_file) as registry:
        for row in paths:
            if len(row["_monthly"]) < 3:
                continue
            role = "baseline" if row["solver"] == "equal_weight37" else "grid"
            spec = Selection(
                dates[0],
                str(row["solver"]),
                None if row["k"] is None else int(row["k"]),
                None if row["lam"] is None else float(row["lam"]),
                None if row["p"] is None else int(row["p"]),
                (),
                seed=None if row["seed"] is None else int(row["seed"]),
            )
            registry.register(
                FAMILY_ID,
                _spec_params(spec, role, SELECTION_AUM),
                returns=row["_monthly"],
                costs_included=True,
                periods_per_year=PERIODS_PER_YEAR,
                notes=role,
                status=role,
            )
        audit_row = None
        if chosen_key is not None:
            match = [
                row
                for row in paths
                if row["solver"] == chosen_key["solver"]
                and row["k"] == chosen_key["k"]
                and row["lam"] == chosen_key["lam"]
                and row["p"] == chosen_key["p"]
                and row["seed"] == chosen_key["seed"]
            ]
            if match:
                chosen_path = match[0]
                audit_run = simulate_book(
                    sessions,
                    tapes,
                    chosen_path["_book"],
                    AUM_LOOSE,
                    taxed,
                    round_trip=False,
                    apply_splits=True,
                    haircut=0.0,
                    exit_when_stale=True,
                )
                a_ords, a_monthly = monthly_simple_returns(audit_run["ords"], audit_run["net"])
                if len(a_monthly) >= 3:
                    registry.register(
                        FAMILY_ID,
                        {
                            "family": FAMILY_ID,
                            "role": "audit_aum",
                            "solver": chosen_path["solver"],
                            "K": chosen_path["k"],
                            "lambda": chosen_path["lam"],
                            "p": chosen_path["p"],
                            "seed": chosen_path["seed"],
                            "aum_brl": AUM_LOOSE,
                            "selection_candidate": False,
                        },
                        returns=a_monthly,
                        costs_included=True,
                        periods_per_year=PERIODS_PER_YEAR,
                        notes="audit_aum",
                        status="audit",
                    )
                audit_row = _path_fields(
                    Selection(
                        dates[0] if dates else DESIGN_END,
                        str(chosen_path["solver"]),
                        None if chosen_path["k"] is None else int(chosen_path["k"]),
                        None if chosen_path["lam"] is None else float(chosen_path["lam"]),
                        None if chosen_path["p"] is None else int(chosen_path["p"]),
                        (),
                        seed=None if chosen_path["seed"] is None else int(chosen_path["seed"]),
                    ),
                    audit_run,
                    chosen_path["_book"],
                    a_ords,
                    a_monthly,
                    cdi_ords,
                    cdi_rates,
                )
                audit_row["selection_candidate"] = False
                audit_row["aum_brl"] = AUM_LOOSE
                audit_row["role"] = "audit_aum"
        priors = prior_ledger(registry, prior_registries)
    n_decision = float(priors["n_decision"])
    public: list[dict[str, Any]] = []
    for row in paths:
        judged = judge(row["_oos_rets"], n_decision)
        clean = {key: value for key, value in row.items() if not key.startswith("_")}
        clean["oos_psr"] = None if judged is None else _round(judged["psr"])
        clean["oos_dsr"] = None if judged is None else _round(judged["dsr"])
        clean["oos_min_trl_months"] = None if judged is None else _round(judged["min_trl_months"], 2)
        clean["oos_min_trl_infinite"] = bool(judged and judged["min_trl_infinite"])
        clean["n_trials_decision"] = n_decision
        public.append(clean)
    chosen = choose_rule(public)
    chosen_row = None
    if chosen is not None:
        for row in public:
            if (
                row["solver"] == chosen["solver"]
                and row["k"] == chosen["k"]
                and row["lam"] == chosen["lam"]
                and row["p"] == chosen["p"]
                and row["seed"] == chosen["seed"]
                and row["selection_candidate"]
            ):
                chosen_row = row
                break
    baseline = next((row for row in public if row["solver"] == "equal_weight37"), None)
    criterion = False
    if chosen_row is not None:
        dsr = chosen_row.get("oos_dsr")
        excess = chosen_row.get("oos_excess_cagr_over_cdi")
        criterion = bool(dsr is not None and dsr >= 0.95 and excess is not None and excess > 0)
    if chosen_row is None:
        verdict = "inconclusivo"
    elif criterion:
        verdict = "aprovado"
    else:
        verdict = "reprovado"
    annual: list[dict[str, Any]] = []
    if chosen_row is not None:
        match = [
            row
            for row in paths
            if row["solver"] == chosen_row["solver"]
            and row["k"] == chosen_row["k"]
            and row["lam"] == chosen_row["lam"]
            and row["seed"] == chosen_row["seed"]
        ]
        if match:
            annual = calendar_table(
                match[0]["_monthly_ords"],
                match[0]["_monthly"],
                cdi_ords,
                cdi_rates,
                int(sessions[0]),
            )
    excess_vs_baseline = None
    if chosen_row is not None and baseline is not None:
        left = chosen_row.get("oos_cagr_net")
        right = baseline.get("oos_cagr_net")
        if left is not None and right is not None:
            excess_vs_baseline = _round(float(left) - float(right))
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "verdict": verdict,
        "market_sample": True,
        "criterion": "DSR >= 0.95 on out-of-sample net monthly returns, N = this family plus rejected net-net plus the equal-weight family plus factor trials when a registry holds them, AND out-of-sample net CAGR minus CDI CAGR > 0",
        "criterion_met": criterion,
        "paper_only": True,
        "priors": priors,
        "n_trials_decision": n_decision,
        "chosen": None
        if chosen_row is None
        else {
            "solver": chosen_row["solver"],
            "k": chosen_row["k"],
            "lam": chosen_row["lam"],
            "p": chosen_row["p"],
            "seed": chosen_row["seed"],
            "design_sharpe": chosen_row["design_sharpe"],
            "n_design": chosen_row["n_design"],
            "oos_cagr_net": chosen_row["oos_cagr_net"],
            "oos_sharpe": chosen_row["oos_sharpe"],
            "oos_max_drawdown_net": chosen_row["oos_max_drawdown_net"],
            "oos_excess_cagr_over_cdi": chosen_row["oos_excess_cagr_over_cdi"],
            "oos_excess_cagr_over_equal_weight37": excess_vs_baseline,
            "oos_dsr": chosen_row["oos_dsr"],
            "oos_psr": chosen_row["oos_psr"],
            "oos_min_trl_months": chosen_row["oos_min_trl_months"],
            "oos_min_trl_infinite": chosen_row["oos_min_trl_infinite"],
            "turnover_one_way_annual": chosen_row["turnover_one_way_annual"],
            "capacity_thin_10pct_adv": chosen_row["capacity_thin_10pct_adv"],
            "median_names": chosen_row["median_names"],
        },
        "baseline_equal_weight37": baseline,
        "chosen_annual": [
            {
                "year": row["year"],
                "total_return": _round(row["total_return"]),
                "cdi": _round(row["cdi"]),
                "excess_over_cdi": _round(row["excess_over_cdi"]),
                "bad_year": row["bad_year"],
            }
            for row in annual
        ],
        "bad_years": [row["year"] for row in annual if row["bad_year"]],
        "audit_aum_100k": None if audit_row is None else {key: value for key, value in audit_row.items() if not key.startswith("_")},
        "solvers_scored": sorted({str(row["solver"]) for row in public}),
        "awaiting_solver": [] if "qaoa_aer" in present else ["qaoa_aer"],
        "n_rebalances": len(snapshots),
        "rebalance_dates": [day.isoformat() for day in dates],
        "trials": public,
        "contract": contract_public(),
    }


def contract_public() -> dict[str, Any]:
    return {
        "schema_version_snapshot": SCHEMA_VERSION,
        "schema_version_holdout": HOLDOUT_SCHEMA_VERSION,
        "schema_version_selection": SELECTION_SCHEMA_VERSION,
        "family_id": FAMILY_ID,
        "universe_rule": UNIVERSE_RULE,
        "adv_floor_brl": ADV_FLOOR,
        "first_signal_on_or_after": PUBLISHED_FIRST_SIGNAL.isoformat(),
        "design_end": DESIGN_END.isoformat(),
        "eval_start": EVAL_START.isoformat(),
        "k_grid": list(K_GRID),
        "lambda_grid": list(LAMBDA_GRID),
        "embargo_sessions": EMBARGO_SESSIONS,
        "mu_window_sessions": MU_WINDOW,
        "mu_min_obs": MU_MIN_OBS,
        "holding_sessions": HOLDING_SESSIONS,
        "selection_aum_brl": SELECTION_AUM,
        "loose_aum_brl": AUM_LOOSE,
        "solver_aliases": SOLVER_ALIASES,
        "generated_solvers": list(GENERATED_SOLVERS),
        "qaoa_aer": "selection slot only; this study does not run it",
        "random_seeds": list(RANDOM_SEEDS),
        "sa_seed": SA_SEED,
        "sa_steps": SA_STEPS,
        "sa_t0": SA_T0,
        "sa_cool": SA_COOL,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "definitions": definitions(),
    }


def inconclusive_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "verdict": "inconclusivo",
        "market_sample": False,
        "criterion_met": False,
        "paper_only": True,
        "reason": reason,
        "baselines_implemented": list(GENERATED_SOLVERS),
        "awaiting_solver": ["qaoa_aer"],
        "paper_books": "unchanged",
        "contract": contract_public(),
    }


def schema_fixture_world() -> dict[str, Any]:
    """A short synthetic book used as the versioned schema example. Not a market result."""
    start = date(2012, 1, 1).toordinal()
    end = date(2012, 9, 30).toordinal()
    sessions = list(range(start, end + 1))
    companies: list[Company] = []
    listings: list[Listing] = []
    tapes: dict[str, Tape] = {}
    def tape_for(price: float, vol: float, jump_july: bool = False, split_june: bool = False, jump_signal: bool = False) -> Tape:
        n = len(sessions)
        dates = np.asarray(sessions, dtype=np.int64)
        close = np.full(n, price, dtype=np.float64)
        if split_june:
            june10 = date(2012, 6, 10).toordinal()
            idx = sessions.index(june10)
            close[idx:] = price / 2.0
        if jump_signal:
            june30 = date(2012, 6, 30).toordinal()
            idx = sessions.index(june30)
            close[idx:] = price * 2.0
        if jump_july:
            july2 = date(2012, 7, 2).toordinal()
            idx = sessions.index(july2)
            close[idx:] = price * 3.0
        split = np.ones(n, dtype=np.float64)
        if split_june:
            split[sessions.index(date(2012, 6, 10).toordinal())] = 2.0
        return Tape(
            dates,
            close,
            close * 0.99,
            close * 1.01,
            np.full(n, 100_000.0, dtype=np.float64),
            np.full(n, vol, dtype=np.float64),
            split,
        )

    # Eighty issuers put about twenty-four names in the bottom 30%, so K in
    # {15…20} is a real subset. Fifty issuers land on exactly fifteen and every
    # draw of K=15 is the whole book.
    for i in range(80):
        cnpj = f"{i:014d}"
        ticker = f"S{i:03d}"
        shares = float((i + 1) * 1_000)
        point = SharePoint(date(2011, 12, 31).toordinal(), date(2011, 12, 15).toordinal(), shares, 0.0, shares, 0.0)
        companies.append(Company(cnpj, cnpj, "Têxtil", "ATIVO", [], [], [point], [], [], []))
        listings.append(Listing(cnpj, ticker, start, None, "on"))
        tapes[ticker] = tape_for(
            10.0,
            2_000_000.0,
            jump_july=(i == 0),
            split_june=(i == 2),
            jump_signal=(i == 0),
        )
    twin = Listing(f"{0:014d}", "TWIN3", start, None, "on")
    listings.append(twin)
    tapes["TWIN3"] = tape_for(10.0, 500_000.0)
    bank_cnpj = f"{90:014d}"
    bank_point = SharePoint(date(2011, 12, 31).toordinal(), date(2011, 12, 15).toordinal(), 100.0, 0.0, 100.0, 0.0)
    companies.append(Company(bank_cnpj, bank_cnpj, "Bancos", "ATIVO", [], [], [bank_point], [], [], []))
    listings.append(Listing(bank_cnpj, "BANK3", start, None, "on"))
    tapes["BANK3"] = tape_for(10.0, 5_000_000.0)
    thin_cnpj = f"{91:014d}"
    thin_point = SharePoint(date(2011, 12, 31).toordinal(), date(2011, 12, 15).toordinal(), 100.0, 0.0, 100.0, 0.0)
    companies.append(Company(thin_cnpj, thin_cnpj, "Têxtil", "ATIVO", [], [], [thin_point], [], [], []))
    listings.append(Listing(thin_cnpj, "THIN3", start, None, "on"))
    tapes["THIN3"] = tape_for(10.0, 1_000.0)
    events = {"S001": [CashEvent(date(2012, 6, 11).toordinal(), 1.0, "unknown")]}
    return {
        "companies": companies,
        "listings": listings,
        "tapes": tapes,
        "sessions": sessions,
        "events": events,
        "label": "schema_fixture_not_a_market_result",
    }

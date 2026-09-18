"""
Paper-only statistical arbitrage loop for one perpetual pair (ETHUSDT / SOLUSDT).

Six layers: data → signal → decision → risk → paper execution → monitoring.
Reuses Engle–Granger / expanding hedge from ``cointegration`` and the OU/AR(1)
half-life from ``mean_reversion``. Signal at bar t uses information ≤ t; the
paper fill is the next bar's bid (sells) / ask (buys).

This module never talks to a broker, never signs an exchange order, and always
returns ``eligible_for_live_trading=False``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from app.models.cointegration import _expanding_hedge, _half_life, engle_granger
from app.models.mean_reversion import _ar1_half_life

DEFAULT_Y = "ETHUSDT"
DEFAULT_X = "SOLUSDT"
ENTRY_Z = 2.0
EXIT_Z = 0.5
MAX_HALF_LIFE_BARS = 48.0
SIGNIFICANCE = 0.05
Z_WINDOW = 60
WARMUP = 60
MAX_DRAWDOWN = 0.15
MAX_POSITION = 1.0
HALF_SPREAD_BPS = 2.0
TAKER_FEE_BPS = 4.0
UNIT_QTY = 1.0
INITIAL_CASH = 100_000.0
MIN_BARS = 80

# MacKinnon (2010) residual-based tau, constant, bivariate, T=∞ — same table as EG.
_MACKINNON_P = ((-3.90, 0.01), (-3.34, 0.05), (-3.04, 0.10))

_WHAT_BROKE = [
    "Full-sample Engle–Granger is a research gate, not a rolling live rank test.",
    "Expanding OLS beta is not a Kalman hedge; funding, lot size and borrow are ignored.",
    "When the caller omits a book, bid/ask are mid ± half-spread — not a firm quote.",
    "Signal at t fills at t+1; a hole between those bars is flagged, never interpolated.",
    "Kill switch flattens the paper book only. Broker orders sent: always 0.",
    "Paper backtest is research, not evidence. eligible_for_live_trading stays false.",
]


@dataclass(frozen=True)
class PairBar:
    ts_ms: int
    y_mid: float
    x_mid: float
    y_bid: float
    y_ask: float
    x_bid: float
    x_ask: float


@dataclass(frozen=True)
class PipelineConfig:
    y_symbol: str = DEFAULT_Y
    x_symbol: str = DEFAULT_X
    entry_z: float = ENTRY_Z
    exit_z: float = EXIT_Z
    significance: float = SIGNIFICANCE
    max_half_life_bars: float = MAX_HALF_LIFE_BARS
    z_window: int = Z_WINDOW
    warmup: int = WARMUP
    max_drawdown: float = MAX_DRAWDOWN
    max_position: float = MAX_POSITION
    half_spread_bps: float = HALF_SPREAD_BPS
    taker_fee_bps: float = TAKER_FEE_BPS
    unit_qty: float = UNIT_QTY
    initial_cash: float = INITIAL_CASH
    expected_interval_ms: int | None = None


@dataclass
class KillSwitch:
    armed: bool = False
    reason: str | None = None
    flattened_at_ms: int | None = None
    drawdown_at_fire: float | None = None
    broker_orders_sent: int = 0

    def arm(self, reason: str, *, ts_ms: int, drawdown: float) -> None:
        if self.armed:
            return
        self.armed = True
        self.reason = reason
        self.flattened_at_ms = ts_ms
        self.drawdown_at_fire = drawdown


@dataclass
class PaperBook:
    cash: float
    y_qty: float = 0.0
    x_qty: float = 0.0
    position: int = 0
    entry_beta: float | None = None
    peak_equity: float = 0.0
    shadow_cash: float = 0.0
    costs_paid: float = 0.0

    def mark(self, y_mid: float, x_mid: float) -> float:
        return self.cash + self.y_qty * y_mid + self.x_qty * x_mid

    def mark_gross(self, y_mid: float, x_mid: float) -> float:
        return self.shadow_cash + self.y_qty * y_mid + self.x_qty * x_mid


# ── 1. Data ──────────────────────────────────────────────────────────────────


def _require_finite(name: str, values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        raise ValueError(f"{name} is empty")
    bad = ~np.isfinite(arr)
    if np.any(bad):
        idx = np.flatnonzero(bad)[:8].tolist()
        raise ValueError(f"{name} contains non-finite values at indices {idx}; refusing silent NaN")
    return arr


def _quotes_from_mid(mid: float, half_spread_bps: float) -> tuple[float, float]:
    half = mid * half_spread_bps / 10_000.0
    bid = mid - half
    ask = mid + half
    if bid <= 0 or ask < bid:
        raise ValueError("Synthesized book is invalid (bid ≤ 0 or ask < bid)")
    return bid, ask


def document_gaps(timestamps_ms: Sequence[int], expected_interval_ms: int | None) -> dict[str, Any]:
    ts = np.asarray(timestamps_ms, dtype=np.int64)
    if ts.size < 2:
        return {"expected_interval_ms": expected_interval_ms, "n_gaps": 0, "gaps": [], "median_dt_ms": None}
    if np.any(np.diff(ts) <= 0):
        raise ValueError("Timestamps must be strictly increasing")
    dts = np.diff(ts.astype(np.float64))
    median_dt = float(np.median(dts))
    expected = float(expected_interval_ms) if expected_interval_ms else median_dt
    if expected <= 0:
        raise ValueError("expected_interval_ms must be positive")
    gaps = []
    for i, dt in enumerate(dts):
        if dt > 1.5 * expected:
            gaps.append({
                "after_index": i,
                "from_ts_ms": int(ts[i]),
                "to_ts_ms": int(ts[i + 1]),
                "dt_ms": int(dt),
                "missing_bars_est": int(round(dt / expected)) - 1,
            })
    return {
        "expected_interval_ms": int(expected),
        "median_dt_ms": int(median_dt),
        "n_gaps": len(gaps),
        "gaps": gaps[:50],
    }


def bars_from_arrays(
    timestamps_ms: Sequence[int],
    y_mid: Sequence[float],
    x_mid: Sequence[float],
    *,
    y_bid: Sequence[float] | None = None,
    y_ask: Sequence[float] | None = None,
    x_bid: Sequence[float] | None = None,
    x_ask: Sequence[float] | None = None,
    half_spread_bps: float = HALF_SPREAD_BPS,
    expected_interval_ms: int | None = None,
) -> tuple[list[PairBar], dict[str, Any]]:
    ts = np.asarray(timestamps_ms, dtype=np.int64)
    y = _require_finite("y_mid", y_mid)
    x = _require_finite("x_mid", x_mid)
    if not (len(ts) == len(y) == len(x)):
        raise ValueError("timestamps, y_mid and x_mid must have the same length")
    if np.any(y <= 0) or np.any(x <= 0):
        raise ValueError("Mids must be strictly positive")
    if np.any(np.diff(ts) <= 0):
        raise ValueError("Timestamps must be strictly increasing")

    def _opt(name: str, values: Sequence[float] | None) -> np.ndarray | None:
        if values is None:
            return None
        arr = _require_finite(name, values)
        if len(arr) != len(ts):
            raise ValueError(f"{name} must align with timestamps")
        return arr

    yb, ya = _opt("y_bid", y_bid), _opt("y_ask", y_ask)
    xb, xa = _opt("x_bid", x_bid), _opt("x_ask", x_ask)
    if (yb is None) ^ (ya is None) or (xb is None) ^ (xa is None):
        raise ValueError("Bid and ask must be supplied together per leg")

    bars: list[PairBar] = []
    for i in range(len(ts)):
        y_b, y_a = (float(yb[i]), float(ya[i])) if yb is not None else _quotes_from_mid(float(y[i]), half_spread_bps)
        x_b, x_a = (float(xb[i]), float(xa[i])) if xb is not None else _quotes_from_mid(float(x[i]), half_spread_bps)
        if y_b <= 0 or x_b <= 0 or y_a < y_b or x_a < x_b:
            raise ValueError(f"Invalid book at index {i}")
        bars.append(PairBar(int(ts[i]), float(y[i]), float(x[i]), y_b, y_a, x_b, x_a))
    return bars, document_gaps(ts, expected_interval_ms)


def align_pair_series(
    y_rows: Sequence[tuple[int, float]],
    x_rows: Sequence[tuple[int, float]],
    *,
    half_spread_bps: float = HALF_SPREAD_BPS,
    expected_interval_ms: int | None = None,
) -> tuple[list[PairBar], dict[str, Any]]:
    """Inner-join two (ts, mid) series. Unmatched stamps are gaps, never silent NaNs."""
    y_map: dict[int, float] = {}
    for ts, mid in y_rows:
        if not math.isfinite(mid):
            raise ValueError(f"y mid is non-finite at ts={ts}")
        y_map[int(ts)] = float(mid)
    x_map: dict[int, float] = {}
    for ts, mid in x_rows:
        if not math.isfinite(mid):
            raise ValueError(f"x mid is non-finite at ts={ts}")
        x_map[int(ts)] = float(mid)
    y_only = sorted(set(y_map) - set(x_map))
    x_only = sorted(set(x_map) - set(y_map))
    common = sorted(set(y_map) & set(x_map))
    if len(common) < MIN_BARS:
        raise ValueError(f"Need ≥{MIN_BARS} aligned stamps; got {len(common)}")
    bars, gap_doc = bars_from_arrays(
        common,
        [y_map[t] for t in common],
        [x_map[t] for t in common],
        half_spread_bps=half_spread_bps,
        expected_interval_ms=expected_interval_ms,
    )
    gap_doc["unmatched_y_only"] = y_only[:50]
    gap_doc["unmatched_x_only"] = x_only[:50]
    gap_doc["n_unmatched_y"] = len(y_only)
    gap_doc["n_unmatched_x"] = len(x_only)
    return bars, gap_doc


def synthetic_perp_pair(
    n: int = 400,
    *,
    seed: int = 7,
    beta: float = 18.0,
    alpha: float = 200.0,
    half_life: float = 12.0,
    x0: float = 150.0,
    x_vol: float = 1.2,
    resid_vol: float = 2.0,
    interval_ms: int = 3_600_000,
    half_spread_bps: float = HALF_SPREAD_BPS,
    start_ms: int = 1_700_000_000_000,
    independent: bool = False,
) -> list[PairBar]:
    """Cointegrated ETH-like / SOL-like marks, or two independent random walks."""
    if n < MIN_BARS:
        raise ValueError(f"Need ≥{MIN_BARS} bars")
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = x0
    e = np.zeros(n)
    phi = float(2.0 ** (-1.0 / max(half_life, 1e-6)))
    for t in range(1, n):
        x[t] = x[t - 1] + rng.normal(0.0, x_vol)
        e[t] = phi * e[t - 1] + rng.normal(0.0, resid_vol)
    if independent:
        y = 2_000.0 + np.cumsum(rng.normal(0.0, 15.0, n))
    else:
        y = alpha + beta * x + e
    x = np.maximum(x, 1.0)
    y = np.maximum(y, 1.0)
    ts = [start_ms + i * interval_ms for i in range(n)]
    bars, _ = bars_from_arrays(ts, y, x, half_spread_bps=half_spread_bps, expected_interval_ms=interval_ms)
    return bars


# ── 2. Signal ────────────────────────────────────────────────────────────────


def eg_pvalue_bound(adf_tstat: float) -> float:
    """Conservative step p-value from the MacKinnon table used by ``engle_granger``."""
    for crit, p in _MACKINNON_P:
        if adf_tstat < crit:
            return p
    return 1.0


def spread_half_life(residual: np.ndarray) -> float:
    """OU half-life in bars on a spread / EG residual (``cointegration._half_life``)."""
    return float(_half_life(np.asarray(residual, dtype=np.float64)))


def rolling_zscore(values: np.ndarray, window: int) -> np.ndarray:
    """Causal rolling z: at t, moments use only values[max(0,t-window+1):t+1]."""
    if window < 2:
        raise ValueError("z_window must be ≥2")
    x = np.asarray(values, dtype=np.float64)
    z = np.full(len(x), np.nan)
    for t in range(len(x)):
        w = x[max(0, t - window + 1) : t + 1]
        w = w[np.isfinite(w)]
        if len(w) < 2 or not np.isfinite(x[t]):
            continue
        sd = float(np.std(w, ddof=1))
        z[t] = 0.0 if sd < 1e-12 else float((x[t] - float(np.mean(w))) / sd)
    return z


def signal_gate(
    *,
    cointegrated: bool,
    pvalue: float,
    significance: float,
    half_life_bars: float,
    max_half_life_bars: float,
) -> dict[str, Any]:
    if not cointegrated or pvalue > significance:
        return {"ok": False, "reason": "cointegration_failed"}
    if not np.isfinite(half_life_bars) or half_life_bars <= 0 or half_life_bars > max_half_life_bars:
        return {"ok": False, "reason": "half_life_too_slow"}
    return {"ok": True, "reason": None}


# ── 3. Decision ──────────────────────────────────────────────────────────────


def decide_target(z: float, position: int, entry_z: float = ENTRY_Z, exit_z: float = EXIT_Z) -> int:
    """Entry at |z| > entry; exit at |z| < exit. +1 = long spread (long y / short x)."""
    if not math.isfinite(z):
        return position
    if position == 0:
        if z > entry_z:
            return -1
        if z < -entry_z:
            return 1
        return 0
    if abs(z) < exit_z:
        return 0
    return position


def clip_position(target: int, max_position: float) -> int:
    if abs(target) > max_position + 1e-12:
        return 0
    return target


# ── 4–5. Risk + paper execution ──────────────────────────────────────────────


def fill_leg(delta_qty: float, bid: float, ask: float, fee_bps: float) -> tuple[float, float, float | None]:
    """Positive delta buys at ask; negative delta sells at bid. Returns (cash, fee, px)."""
    if abs(delta_qty) < 1e-15:
        return 0.0, 0.0, None
    if delta_qty > 0:
        px = ask
        notional = delta_qty * px
        fee = notional * fee_bps / 10_000.0
        return -(notional + fee), fee, px
    px = bid
    notional = (-delta_qty) * px
    fee = notional * fee_bps / 10_000.0
    return notional - fee, fee, px


def apply_spread_target(
    book: PaperBook,
    target: int,
    beta: float,
    unit_qty: float,
    bar: PairBar,
    fee_bps: float,
    *,
    action: str,
) -> dict[str, Any]:
    want_y = target * unit_qty
    want_x = -target * beta * unit_qty
    dy = want_y - book.y_qty
    dx = want_x - book.x_qty
    cash_y, fee_y, px_y = fill_leg(dy, bar.y_bid, bar.y_ask, fee_bps)
    cash_x, fee_x, px_x = fill_leg(dx, bar.x_bid, bar.x_ask, fee_bps)
    mid_cash = -dy * bar.y_mid - dx * bar.x_mid
    actual_cash = cash_y + cash_x
    book.cash += actual_cash
    book.shadow_cash += mid_cash
    book.y_qty += dy
    book.x_qty += dx
    book.position = target
    book.entry_beta = beta if target != 0 else None
    book.costs_paid += mid_cash - actual_cash
    return {
        "ts_ms": bar.ts_ms,
        "action": action,
        "target": target,
        "beta": round(float(beta), 8),
        "y_qty_delta": dy,
        "x_qty_delta": dx,
        "y_fill_px": px_y,
        "x_fill_px": px_x,
        "y_side": "buy" if dy > 0 else ("sell" if dy < 0 else "flat"),
        "x_side": "buy" if dx > 0 else ("sell" if dx < 0 else "flat"),
        "cash_delta": actual_cash,
        "fee": fee_y + fee_x,
        "inventory": {"y": book.y_qty, "x": book.x_qty, "position": book.position},
    }


def reconcile_book(book: PaperBook, unit_qty: float, tol: float = 1e-8) -> dict[str, Any]:
    beta = book.entry_beta if book.entry_beta is not None else 0.0
    expect_y = book.position * unit_qty
    expect_x = -book.position * beta * unit_qty
    ok = abs(book.y_qty - expect_y) <= tol and abs(book.x_qty - expect_x) <= tol
    if book.position == 0:
        ok = abs(book.y_qty) <= tol and abs(book.x_qty) <= tol
    return {
        "ok": bool(ok),
        "expected": {"y": expect_y, "x": expect_x, "position": book.position},
        "actual": {"y": book.y_qty, "x": book.x_qty, "position": book.position},
        "entry_beta": book.entry_beta,
    }


# ── 6. Pipeline + monitoring ─────────────────────────────────────────────────


def _bars_to_arrays(bars: Sequence[PairBar]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ts = np.array([b.ts_ms for b in bars], dtype=np.int64)
    y = np.array([b.y_mid for b in bars], dtype=np.float64)
    x = np.array([b.x_mid for b in bars], dtype=np.float64)
    return ts, y, x


def _rejected(reason: str, *, cfg: PipelineConfig, data: dict, signal: dict, extra: dict | None = None) -> dict[str, Any]:
    out = {
        "pair": {"y": cfg.y_symbol, "x": cfg.x_symbol},
        "mode": "paper_only",
        "accepted": False,
        "rejection": {"reason": reason, **(extra or {})},
        "data": data,
        "signal": signal,
        "decision": {"entry_z": cfg.entry_z, "exit_z": cfg.exit_z, "trades": 0},
        "risk": {
            "max_position": cfg.max_position,
            "max_drawdown": cfg.max_drawdown,
            "kill_switch": {
                "armed": False,
                "reason": None,
                "flattened_at_ms": None,
                "drawdown_at_fire": None,
                "broker_orders_sent": 0,
                "paper_flatten": "idle",
            },
        },
        "execution": {"fills": [], "inventory": {"y": 0.0, "x": 0.0, "position": 0}, "reconciled": True, "costs_paid": 0.0},
        "monitoring": {
            "pnl_net": 0.0,
            "pnl_gross": 0.0,
            "drawdown": 0.0,
            "gap_flags": data.get("gaps") or [],
            "latency_flags": [],
            "kill_switch_reason": None,
        },
        "eligible_for_live_trading": False,
        "broker_orders_sent": 0,
        "out_of_sample": False,
        "math": (
            "y_t = α + β x_t + e_t; reject a unit root in e_t (Engle–Granger / MacKinnon). "
            "OU half-life = −ln 2 / ln φ on the residual. Skip if p > α or half-life > cap."
        ),
        "what_broke": list(_WHAT_BROKE),
    }
    return out


def run_paper_pipeline(
    bars: Sequence[PairBar],
    cfg: PipelineConfig | None = None,
    *,
    source: str = "caller",
    gap_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or PipelineConfig()
    if len(bars) < MIN_BARS:
        raise ValueError(f"Need ≥{MIN_BARS} aligned bars")
    ts, y, x = _bars_to_arrays(bars)
    if gap_doc is None:
        gap_doc = document_gaps(ts, cfg.expected_interval_ms)
    data = {
        "n": int(len(bars)),
        "source": source,
        "y_symbol": cfg.y_symbol,
        "x_symbol": cfg.x_symbol,
        **gap_doc,
        "synthesized_book": source != "caller_with_book",
    }

    eg = engle_granger(y, x, significance=cfg.significance)
    residual = y - (eg["alpha"] + eg["beta"] * x)
    hl = spread_half_life(residual)
    _, ar1_hl = _ar1_half_life(residual)
    pvalue = eg_pvalue_bound(float(eg["adf_tstat"]))
    gate = signal_gate(
        cointegrated=bool(eg["cointegrated"]),
        pvalue=pvalue,
        significance=cfg.significance,
        half_life_bars=hl,
        max_half_life_bars=cfg.max_half_life_bars,
    )
    signal = {
        **{k: eg[k] for k in ("alpha", "beta", "adf_tstat", "critical_value", "significance", "cointegrated", "n")},
        "pvalue": pvalue,
        "half_life_bars": None if not np.isfinite(hl) else round(float(hl), 4),
        "ar1_half_life_bars": None if not np.isfinite(ar1_hl) else round(float(ar1_hl), 4),
        "z_window": cfg.z_window,
        "max_half_life_bars": cfg.max_half_life_bars,
    }
    if not gate["ok"]:
        return _rejected(gate["reason"], cfg=cfg, data=data, signal=signal, extra={"pvalue": pvalue, "half_life_bars": signal["half_life_bars"]})

    min_est = 20
    warmup = max(min_est, min(cfg.warmup, len(y) // 3))
    _, betas, spread = _expanding_hedge(y, x, min_est)
    z = rolling_zscore(spread, cfg.z_window)

    book = PaperBook(cash=cfg.initial_cash, peak_equity=cfg.initial_cash, shadow_cash=cfg.initial_cash)
    kill = KillSwitch()
    fills: list[dict[str, Any]] = []
    latency_flags: list[dict[str, Any]] = []
    curve = [cfg.initial_cash]
    last_z = None
    expected_dt = float(gap_doc.get("expected_interval_ms") or cfg.expected_interval_ms or 0)

    def _drawdown(equity: float) -> float:
        book.peak_equity = max(book.peak_equity, equity)
        if book.peak_equity <= 0:
            return 0.0
        return equity / book.peak_equity - 1.0

    def _flatten(bar: PairBar, reason: str) -> None:
        beta = book.entry_beta if book.entry_beta is not None else float(eg["beta"])
        fills.append(apply_spread_target(book, 0, beta, cfg.unit_qty, bar, cfg.taker_fee_bps, action=reason))
        kill.flattened_at_ms = bar.ts_ms

    n = len(bars)
    for t in range(warmup, n - 1):
        fill_i = t + 1
        fill_bar = bars[fill_i]
        equity = book.mark(fill_bar.y_mid, fill_bar.x_mid)
        dd = _drawdown(equity)

        # Kill switch is authoritative: flatten (if needed) and refuse further paper fills.
        if kill.armed:
            if book.position != 0:
                _flatten(fill_bar, "kill_flatten")
            break

        if dd <= -cfg.max_drawdown:
            kill.arm("max_drawdown", ts_ms=fill_bar.ts_ms, drawdown=dd)
            if book.position != 0:
                _flatten(fill_bar, "kill_flatten")
            continue

        zt = float(z[t]) if np.isfinite(z[t]) else float("nan")
        last_z = zt if np.isfinite(zt) else last_z
        gap_here = bool(expected_dt and (fill_bar.ts_ms - bars[t].ts_ms) > 1.5 * expected_dt)
        if gap_here:
            latency_flags.append({
                "ts_ms": fill_bar.ts_ms,
                "from_ts_ms": bars[t].ts_ms,
                "kind": "gap_across_fill",
                "dt_ms": fill_bar.ts_ms - bars[t].ts_ms,
            })

        target = decide_target(zt, book.position, cfg.entry_z, cfg.exit_z)
        target = clip_position(target, cfg.max_position)
        if gap_here and book.position == 0 and target != 0:
            continue  # do not open across a hole
        if target == book.position:
            curve.append(equity)
            continue

        beta_t = float(betas[t]) if np.isfinite(betas[t]) else float(eg["beta"])
        if book.position != 0 and book.entry_beta is not None:
            beta_t = book.entry_beta
        if target != 0 and book.position == 0:
            action = "enter_long_spread" if target == 1 else "enter_short_spread"
        else:
            action = "exit"
        fills.append(apply_spread_target(book, target, beta_t, cfg.unit_qty, fill_bar, cfg.taker_fee_bps, action=action))

        equity = book.mark(fill_bar.y_mid, fill_bar.x_mid)
        dd = _drawdown(equity)
        if dd <= -cfg.max_drawdown:
            kill.arm("max_drawdown", ts_ms=fill_bar.ts_ms, drawdown=dd)
            if book.position != 0:
                _flatten(fill_bar, "kill_flatten")
        curve.append(equity)

    final_bar = bars[-1]
    if book.position != 0:
        fills.append(apply_spread_target(
            book, 0, book.entry_beta or float(eg["beta"]), cfg.unit_qty, final_bar, cfg.taker_fee_bps,
            action="eod_flatten",
        ))

    rec = reconcile_book(book, cfg.unit_qty)
    final_eq = book.mark(final_bar.y_mid, final_bar.x_mid)
    final_gross = book.mark_gross(final_bar.y_mid, final_bar.x_mid)
    peak = max(book.peak_equity, final_eq)
    mdd = final_eq / peak - 1.0 if peak else 0.0
    if curve:
        peak_c = np.maximum.accumulate(np.asarray(curve, dtype=np.float64))
        mdd = float(np.min(np.asarray(curve) / peak_c - 1.0))
    sample = [round(v, 4) for v in curve[:: max(1, len(curve) // 80)]] if curve else []

    return {
        "pair": {"y": cfg.y_symbol, "x": cfg.x_symbol},
        "mode": "paper_only",
        "accepted": True,
        "rejection": None,
        "data": data,
        "signal": {**signal, "last_z": None if last_z is None else round(float(last_z), 4), "warmup": warmup},
        "decision": {
            "entry_z": cfg.entry_z,
            "exit_z": cfg.exit_z,
            "trades": len(fills),
            "n_enters": sum(1 for f in fills if str(f["action"]).startswith("enter_")),
            "n_exits": sum(1 for f in fills if f["action"] == "exit"),
            "n_kill_flattens": sum(1 for f in fills if f["action"] == "kill_flatten"),
        },
        "risk": {
            "max_position": cfg.max_position,
            "max_drawdown": cfg.max_drawdown,
            "kill_switch": {
                "armed": kill.armed,
                "reason": kill.reason,
                "flattened_at_ms": kill.flattened_at_ms,
                "drawdown_at_fire": None if kill.drawdown_at_fire is None else round(float(kill.drawdown_at_fire), 6),
                "broker_orders_sent": 0,
                "paper_flatten": "applied" if kill.armed else "idle",
            },
        },
        "execution": {
            "fills": fills,
            "inventory": {"y": book.y_qty, "x": book.x_qty, "position": book.position},
            "reconciled": rec["ok"],
            "reconcile": rec,
            "costs_paid": round(float(book.costs_paid), 6),
            "taker_fee_bps": cfg.taker_fee_bps,
            "half_spread_bps": cfg.half_spread_bps,
        },
        "monitoring": {
            "pnl_net": round(final_eq - cfg.initial_cash, 6),
            "pnl_gross": round(final_gross - cfg.initial_cash, 6),
            "final_equity": round(final_eq, 4),
            "drawdown": round(float(mdd), 6),
            "gap_flags": gap_doc.get("gaps") or [],
            "latency_flags": latency_flags[:50],
            "kill_switch_reason": kill.reason,
            "equity_curve_sample": sample,
        },
        "eligible_for_live_trading": False,
        "broker_orders_sent": 0,
        "out_of_sample": False,
        "math": (
            "y_t = α + β x_t + e_t (Engle–Granger). OU half-life = −ln 2 / ln φ on e_t. "
            "Causal expanding hedge + rolling z; |z|>entry opens, |z|<exit flattens. "
            "Buys fill at ask, sells at bid, plus taker fee. Kill switch flattens paper first."
        ),
        "what_broke": list(_WHAT_BROKE) + list(eg.get("what_broke") or []),
    }


def run_demo(n: int = 400, seed: int = 7, **kwargs: Any) -> dict[str, Any]:
    cfg = PipelineConfig(**{k: v for k, v in kwargs.items() if k in PipelineConfig.__dataclass_fields__})
    bars = synthetic_perp_pair(n, seed=seed, half_spread_bps=cfg.half_spread_bps)
    return run_paper_pipeline(bars, cfg, source="synthetic")


def evaluate(
    *,
    timestamps_ms: Sequence[int] | None = None,
    y_mid: Sequence[float] | None = None,
    x_mid: Sequence[float] | None = None,
    y_bid: Sequence[float] | None = None,
    y_ask: Sequence[float] | None = None,
    x_bid: Sequence[float] | None = None,
    x_ask: Sequence[float] | None = None,
    bars: Sequence[PairBar] | Iterable[dict[str, Any]] | None = None,
    demo: bool = False,
    n: int = 400,
    seed: int = 7,
    source: str = "caller",
    **cfg_kwargs: Any,
) -> dict[str, Any]:
    cfg = PipelineConfig(**{k: v for k, v in cfg_kwargs.items() if k in PipelineConfig.__dataclass_fields__})
    if bars:
        parsed: list[PairBar] = []
        for b in bars:
            if isinstance(b, PairBar):
                parsed.append(b)
                continue
            y_mid_b, x_mid_b = float(b["y_mid"]), float(b["x_mid"])
            y_bid_b = b.get("y_bid")
            y_ask_b = b.get("y_ask")
            x_bid_b = b.get("x_bid")
            x_ask_b = b.get("x_ask")
            if y_bid_b is None or y_ask_b is None:
                y_bid_b, y_ask_b = _quotes_from_mid(y_mid_b, cfg.half_spread_bps)
            if x_bid_b is None or x_ask_b is None:
                x_bid_b, x_ask_b = _quotes_from_mid(x_mid_b, cfg.half_spread_bps)
            parsed.append(PairBar(
                ts_ms=int(b["ts_ms"]),
                y_mid=y_mid_b,
                x_mid=x_mid_b,
                y_bid=float(y_bid_b),
                y_ask=float(y_ask_b),
                x_bid=float(x_bid_b),
                x_ask=float(x_ask_b),
            ))
        gap = document_gaps([b.ts_ms for b in parsed], cfg.expected_interval_ms)
        return run_paper_pipeline(parsed, cfg, source=source, gap_doc=gap)
    if y_mid is not None and x_mid is not None:
        if timestamps_ms is None:
            timestamps_ms = [1_700_000_000_000 + i * 3_600_000 for i in range(len(y_mid))]
        book = y_bid is not None
        parsed_bars, gap = bars_from_arrays(
            timestamps_ms, y_mid, x_mid,
            y_bid=y_bid, y_ask=y_ask, x_bid=x_bid, x_ask=x_ask,
            half_spread_bps=cfg.half_spread_bps,
            expected_interval_ms=cfg.expected_interval_ms,
        )
        return run_paper_pipeline(parsed_bars, cfg, source="caller_with_book" if book else "caller", gap_doc=gap)
    if demo:
        return run_demo(n=n, seed=seed, **asdict(cfg))
    raise ValueError("Supply bars, y_mid+x_mid, or demo=True")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "ETH/SOL paper statistical-arbitrage pipeline. "
            "Simulates fills only — never sends real orders, never uses private API keys."
        )
    )
    p.add_argument("--demo", action="store_true", help="Run on a synthetic cointegrated pair (default if no --fetch).")
    p.add_argument("--fetch", action="store_true", help="Pull unsigned Binance USDM markPriceKlines (public, no keys).")
    p.add_argument("--interval", default="1h", help="Kline interval for --fetch (default 1h).")
    p.add_argument("--limit", type=int, default=500, help="Bars to fetch (80–1500).")
    p.add_argument("--n", type=int, default=400, help="Synthetic length for --demo.")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--entry-z", type=float, default=ENTRY_Z)
    p.add_argument("--exit-z", type=float, default=EXIT_Z)
    p.add_argument("--max-half-life", type=float, default=MAX_HALF_LIFE_BARS)
    p.add_argument("--max-drawdown", type=float, default=MAX_DRAWDOWN)
    args = p.parse_args(argv)

    cfg_kw = dict(
        entry_z=args.entry_z,
        exit_z=args.exit_z,
        max_half_life_bars=args.max_half_life,
        max_drawdown=args.max_drawdown,
    )
    if args.fetch:
        import asyncio

        import httpx

        from app.services.perp_klines import fetch_eth_sol_pair

        async def _pull() -> dict[str, Any]:
            async with httpx.AsyncClient() as client:
                pulled = await fetch_eth_sol_pair(
                    client=client, interval=args.interval, limit=args.limit,
                    half_spread_bps=HALF_SPREAD_BPS,
                )
            return run_paper_pipeline(
                pulled["bars"],
                PipelineConfig(**cfg_kw, expected_interval_ms=pulled.get("expected_interval_ms")),
                source="binance_usdm_mark_klines",
                gap_doc=pulled.get("gaps"),
            )

        report = asyncio.run(_pull())
    else:
        report = run_demo(n=args.n, seed=args.seed, **cfg_kw)
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0 if report.get("eligible_for_live_trading") is False else 2


if __name__ == "__main__":
    raise SystemExit(main())

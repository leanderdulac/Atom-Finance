"""Paper-trade simulator: GBM Monte Carlo over declared entry/exit levels.

Answers "what if I run THIS plan" with a distribution, never a promise:
P&L percentiles, probability of profit, stop/target/expiry split, expected
shortfall. The model is geometric Brownian motion with constant volatility
— stated in every response, with the ways it breaks.
"""
from __future__ import annotations

import numpy as np

from app.models.trading_costs import entry_allowed


def simulate_levels(
    S0: float,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    horizon_days: int,
    vol_annual: float,
    drift_annual: float = 0.0,
    n_paths: int = 5000,
    seed: int = 0,
    size: float = 1.0,
    cost_total: float = 0.0,
    *,
    order_style: str = "market",
    limit_timeout: int | None = None,
    entry_cost_k: float = 2.0,
    fee: float | None = None,
    half_spread: float | None = None,
    slippage: float | None = None,
) -> dict:
    """Simulate a stop/target plan. First touch decides each path.

    Entry triggers on first touch of `entry` (immediate when S0 == entry).
    After entry, the first of stop / target / horizon expiry exits the path.
    `cost_total` is charged once per entered path (round-trip slip + fees).
    """
    if S0 <= 0 or entry <= 0 or stop <= 0 or target <= 0:
        raise ValueError("S0, entry, stop and target must be positive")
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if direction == "long" and not (stop < entry < target):
        raise ValueError("long needs stop < entry < target")
    if direction == "short" and not (target < entry < stop):
        raise ValueError("short needs target < entry < stop")
    if vol_annual <= 0:
        raise ValueError("vol_annual must be positive")
    if not 1 <= horizon_days <= 365:
        raise ValueError("horizon_days must be within 1..365")
    if not 100 <= n_paths <= 20000:
        raise ValueError("n_paths must be within 100..20000")
    if size <= 0:
        raise ValueError("size must be positive")
    if cost_total < 0:
        raise ValueError("cost_total cannot be negative")
    style = (order_style or "market").lower()
    if style not in ("market", "limit"):
        raise ValueError("order_style must be market or limit")
    components_known = fee is not None or half_spread is not None or slippage is not None
    fee_c = float(fee or 0.0)
    half_c = float(half_spread or 0.0)
    slip_c = float(slippage or 0.0)
    if min(fee_c, half_c, slip_c) < 0:
        raise ValueError("fee, half_spread and slippage cannot be negative")
    cost_used = (fee_c + half_c + slip_c) if components_known else float(cost_total)

    rng = np.random.default_rng(seed)
    dt = 1.0 / 252.0
    drift = (drift_annual - 0.5 * vol_annual**2) * dt
    diff = vol_annual * np.sqrt(dt)
    shocks = rng.normal(drift, diff, size=(n_paths, horizon_days))
    log_paths = np.log(S0) + np.cumsum(shocks, axis=1)
    log_entry, log_stop, log_target = np.log(entry), np.log(stop), np.log(target)

    # Entry: first touch of the level (day 0 counts when S0 == entry).
    if S0 == entry:
        entry_day = np.zeros(n_paths, dtype=int)
        entered = np.ones(n_paths, dtype=bool)
    elif S0 < entry:
        touched = log_paths >= log_entry
        entered = touched.any(axis=1)
        entry_day = np.where(entered, touched.argmax(axis=1), -1)
    else:
        touched = log_paths <= log_entry
        entered = touched.any(axis=1)
        entry_day = np.where(entered, touched.argmax(axis=1), -1)

    timeout = horizon_days - 1 if limit_timeout is None else int(limit_timeout)
    n_expired = 0
    if style == "limit":
        # A limit fills only when the path crosses the level. Resting exactly
        # on the level (S0 == entry) is not a fill. Timeout is inclusive.
        px = np.exp(log_paths)
        prev = np.concatenate([np.full((n_paths, 1), S0), px[:, :-1]], axis=1)
        crossed = ((prev < entry) & (px >= entry)) | ((prev > entry) & (px <= entry))
        if timeout < horizon_days - 1:
            crossed[:, timeout + 1 :] = False
        entered = crossed.any(axis=1)
        entry_day = np.where(entered, crossed.argmax(axis=1), -1)
        n_expired = int((~entered).sum()) if timeout < horizon_days - 1 else 0
    n_unfilled = int((~entered).sum()) - n_expired

    expected_gain = abs(target - entry) * size
    entry_blocked = not entry_allowed(expected_gain, cost_used, entry_cost_k)
    if entry_blocked:
        entered[:] = False
        entry_day[:] = -1
        n_expired = 0
        n_unfilled = n_paths

    pnl = np.zeros(n_paths)
    outcome = np.full(n_paths, "no_entry", dtype=object)
    holding = np.zeros(n_paths, dtype=int)
    sign = 1.0 if direction == "long" else -1.0
    for i in np.flatnonzero(entered):
        d0 = int(entry_day[i])
        tail = log_paths[i, d0:]
        if direction == "long":
            hit_stop = np.flatnonzero(tail <= log_stop)
            hit_tgt = np.flatnonzero(tail >= log_target)
        else:
            hit_stop = np.flatnonzero(tail >= log_stop)
            hit_tgt = np.flatnonzero(tail <= log_target)
        ds = int(hit_stop[0]) if hit_stop.size else None
        dtg = int(hit_tgt[0]) if hit_tgt.size else None
        if ds is not None and (dtg is None or ds <= dtg):
            exit_px, outcome[i], hold = stop, "stop", ds
        elif dtg is not None:
            exit_px, outcome[i], hold = target, "target", dtg
        else:
            exit_px, outcome[i], hold = float(np.exp(tail[-1])), "expiry", len(tail) - 1
        holding[i] = hold
        pnl[i] = sign * (exit_px - entry) * size - cost_used

    entered_n = int(entered.sum())
    won = pnl > 0
    qs = np.percentile(pnl, [5, 25, 50, 75, 95])
    tail = pnl[pnl <= qs[0]]
    expected_shortfall = float(-tail.mean()) if tail.size else 0.0
    return {
        "n_paths": n_paths,
        "n_entered": entered_n,
        "p_enter": round(entered_n / n_paths, 6),
        "p_profit": round(float(won.mean()), 6),
        "p_profit_given_entry": round(float(won[entered].mean()) if entered_n else 0.0, 6),
        "p_stop": round(float((outcome == "stop").mean()), 6),
        "p_target": round(float((outcome == "target").mean()), 6),
        "p_expiry": round(float((outcome == "expiry").mean()), 6),
        "pnl_p5": round(float(qs[0]), 4),
        "pnl_p25": round(float(qs[1]), 4),
        "pnl_p50": round(float(qs[2]), 4),
        "pnl_p75": round(float(qs[3]), 4),
        "pnl_p95": round(float(qs[4]), 4),
        "pnl_mean": round(float(pnl.mean()), 4),
        "expected_shortfall_95": round(expected_shortfall, 4),
        "median_holding_days": int(np.median(holding[entered])) if entered_n else 0,
        "order_style": style,
        "n_orders": n_paths,
        "n_filled": entered_n,
        "n_expired": n_expired,
        "n_unfilled": n_unfilled,
        "fill_rate": round(entered_n / n_paths, 6),
        "entry_blocked": entry_blocked,
        "costs": {
            "fee": round(fee_c, 6) if components_known else None,
            "half_spread": round(half_c, 6) if components_known else None,
            "slippage": round(slip_c, 6) if components_known else None,
            "total": round(cost_used, 6),
            "flagged_estimate": (not components_known) and cost_used > 0,
        },
        "model": "gbm_constant_vol",
        "assumptions": {
            "S0": S0, "direction": direction, "entry": entry, "stop": stop,
            "target": target, "horizon_days": horizon_days, "vol_annual": vol_annual,
            "drift_annual": drift_annual, "size": size, "cost_total": cost_total,
            "seed": seed, "steps": "daily, 252d year",
        },
        "eligible_for_live_trading": False,
        "what_broke": [
            "GBM with constant vol: no jumps, no regime change, no vol smile.",
            "First-touch fills at the level: no slippage beyond cost_total, no gaps through stops.",
            "Past vol calibrates the dial; it does not predict future vol.",
            "P(profit) is a frequency over simulated paths, not a certainty about the market.",
        ],
    }

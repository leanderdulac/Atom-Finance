"""
Regime classifier for the research desk.

Six signals, a 90-day percentile gate, a four-state label
(trending / mean-reverting / high_vol / crisis), strategy tags, a
resize recommendation, and a research kill switch.

Live public books (Yahoo + FRED HY OAS) are pulled by
`app.services.regime_feeds`. A 4-hour asyncio job is started from
lifespan when ATOM_REGIME_JOB=1. The kill switch flattens *paper*
trades at last mark; it still never talks to a broker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np

from app.models.mean_reversion import _hurst

RegimeName = Literal["trending", "mean_reverting", "high_vol", "crisis"]

REGIMES: tuple[RegimeName, ...] = ("trending", "mean_reverting", "high_vol", "crisis")

DEFAULT_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "stat_arb",
        "name": "Statistical arbitrage / pairs",
        "live_in": ["mean_reverting"],
        "standby_in": ["trending", "high_vol"],
        "kill_in": ["crisis"],
        "half_kelly": 0.5,
        "kelly_by_regime": {"trending": 0.04, "mean_reverting": 0.18, "high_vol": 0.04, "crisis": 0.0},
    },
    {
        "id": "momentum",
        "name": "Trend / momentum",
        "live_in": ["trending"],
        "standby_in": ["mean_reverting", "high_vol"],
        "kill_in": ["crisis"],
        "half_kelly": 0.5,
        "kelly_by_regime": {"trending": 0.18, "mean_reverting": 0.04, "high_vol": 0.05, "crisis": 0.0},
    },
    {
        "id": "vol_selling",
        "name": "Short vol / carry",
        "live_in": ["mean_reverting"],
        "standby_in": ["trending"],
        "kill_in": ["crisis", "high_vol"],
        "half_kelly": 0.25,
        "kelly_by_regime": {"trending": 0.06, "mean_reverting": 0.12, "high_vol": 0.0, "crisis": 0.0},
    },
]

_WHAT_BROKE = [
    "The nowcast percentile still includes today; holdout_backtest is the purged check.",
    "softmax P(regime) is a z-score map, not a fitted HMM or a structural model.",
    "Hurst is a 126-day R/S slope smoothed over 5 windows — still noisy on crashes.",
    "Yahoo VIX3M/TNX and FRED OAS are delayed public prints, not a desk Bloomberg box.",
    "Paper flatten closes simulated trades at last mark. Broker orders sent: always 0.",
    "Strategy tags remain priors until holdout accuracy on *your* book says otherwise.",
    "Half-Kelly by regime is still a haircut table, not an estimated edge.",
]


def _as_float(x: Any) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 1 or len(arr) == 0 or not np.all(np.isfinite(arr)):
        raise ValueError("Each series must be a non-empty 1-d finite vector")
    return arr


def percentile_snapshot(series: np.ndarray, window: int = 90) -> dict[str, Any]:
    """Last point vs the trailing window, including today."""
    x = _as_float(series)
    if len(x) < window:
        raise ValueError(f"Need ≥{window} observations, got {len(x)}")
    w = x[-window:]
    last = float(w[-1])
    pct = 100.0 * float(np.mean(w <= last))
    if pct >= 90.0:
        flag: str | None = "high"
    elif pct <= 10.0:
        flag = "low"
    else:
        flag = None
    return {
        "value": last,
        "percentile": round(pct, 2),
        "flag": flag,
        "window": window,
        "median": round(float(np.median(w)), 6),
    }


def _smooth(x: np.ndarray, k: int = 5) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.empty_like(x)
    for i in range(len(x)):
        sl = x[max(0, i - k + 1) : i + 1]
        sl = sl[np.isfinite(sl)]
        out[i] = float(np.mean(sl)) if len(sl) else np.nan
    return out


def _rolling_hurst(prices: np.ndarray, lookback: int = 126) -> np.ndarray:
    p = _as_float(prices)
    if np.any(p <= 0):
        raise ValueError("Prices must be positive")
    log_p = np.log(p)
    if len(log_p) < lookback + 2:
        raise ValueError(f"Need ≥{lookback + 2} prices for rolling Hurst")
    out = []
    for t in range(lookback, len(log_p) + 1):
        h = _hurst(log_p[t - lookback : t])
        out.append(h if np.isfinite(h) else np.nan)
    return np.asarray(out, dtype=np.float64)


def _mean_pairwise_corr(returns: np.ndarray) -> float:
    """returns: (T, N). Average upper-triangle correlation."""
    if returns.shape[0] < 10 or returns.shape[1] < 2:
        return float("nan")
    c = np.corrcoef(returns, rowvar=False)
    n = c.shape[0]
    iu = np.triu_indices(n, k=1)
    vals = c[iu]
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return float("nan")
    return float(np.mean(vals))


def _rolling_corr(price_panel: dict[str, np.ndarray], corr_window: int = 20) -> np.ndarray:
    names = list(price_panel)
    cols = [price_panel[n] for n in names]
    n = min(len(c) for c in cols)
    panel = np.column_stack([c[-n:] for c in cols])
    rets = np.diff(panel, axis=0) / panel[:-1]
    out = []
    for t in range(corr_window, len(rets) + 1):
        out.append(_mean_pairwise_corr(rets[t - corr_window : t]))
    return np.asarray(out, dtype=np.float64)


def _rv(prices: np.ndarray, rv_window: int = 20) -> np.ndarray:
    p = _as_float(prices)
    r = np.diff(p) / p[:-1]
    out = []
    for t in range(rv_window, len(r) + 1):
        out.append(float(np.std(r[t - rv_window : t], ddof=1) * np.sqrt(252)))
    return np.asarray(out, dtype=np.float64)


def compute_signal_histories(
    equity_prices: dict[str, list[float]],
    vix_front: list[float],
    vix_back: list[float],
    implied_vol: list[float],
    credit_spread: list[float],
    yield_2y: list[float],
    yield_10y: list[float],
    *,
    hurst_lookback: int = 126,
    corr_window: int = 20,
    rv_window: int = 20,
) -> dict[str, np.ndarray]:
    if len(equity_prices) < 2:
        raise ValueError("Need at least two equity series for cross-asset correlation")
    panel = {k: _as_float(v) for k, v in equity_prices.items()}
    benchmark = next(iter(panel.values()))
    vf, vb = _as_float(vix_front), _as_float(vix_back)
    if np.any(vf <= 0) or np.any(vb <= 0):
        raise ValueError("VIX series must be positive")
    iv = _as_float(implied_vol)
    credit = _as_float(credit_spread)
    y2, y10 = _as_float(yield_2y), _as_float(yield_10y)

    hurst = _smooth(_rolling_hurst(benchmark, hurst_lookback), k=5)
    term = vb / vf
    rv = _rv(benchmark, rv_window)
    n_iv = min(len(rv), len(iv))
    rv_iv = rv[-n_iv:] - iv[-n_iv:]
    corr = _rolling_corr(panel, corr_window)
    slope = y10 - y2
    return {
        "hurst": hurst,
        "vix_term_structure": term,
        "rv_iv_spread": rv_iv,
        "cross_asset_corr": corr,
        "credit_spread": credit,
        "rates_curve_slope": slope,
    }


def classify(flags: dict[str, str | None], hurst_value: float | None = None) -> RegimeName:
    """Priority: crisis > high_vol > Hurst-driven trend/mean-reversion."""
    stress = 0
    if flags.get("credit_spread") == "high":
        stress += 1
    if flags.get("cross_asset_corr") == "high":
        stress += 1
    if flags.get("vix_term_structure") == "low":
        stress += 1
    if flags.get("rates_curve_slope") == "low":
        stress += 1
    if flags.get("rv_iv_spread") == "high":
        stress += 1

    crisis = (
        (flags.get("credit_spread") == "high" and flags.get("cross_asset_corr") == "high")
        or (flags.get("vix_term_structure") == "low" and stress >= 2)
        or stress >= 3
    )
    if crisis:
        return "crisis"
    if flags.get("rv_iv_spread") == "high":
        return "high_vol"
    if flags.get("hurst") == "high":
        return "trending"
    if flags.get("hurst") == "low":
        return "mean_reverting"
    if hurst_value is not None and np.isfinite(hurst_value):
        return "trending" if hurst_value >= 0.5 else "mean_reverting"
    return "mean_reverting"


def regime_probs(snapshots: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Softmax over z-scored percentiles. Crisis logit gets the stress signs."""

    def z(name: str, invert: bool = False) -> float:
        p = float(snapshots[name]["percentile"])
        val = (p - 50.0) / 25.0
        return -val if invert else val

    logits = np.array([
        z("hurst"),  # trending
        -z("hurst"),  # mean_reverting
        z("rv_iv_spread"),  # high_vol
        (
            z("credit_spread")
            + z("cross_asset_corr")
            + z("vix_term_structure", invert=True)
            + z("rates_curve_slope", invert=True)
            + max(0.0, z("rv_iv_spread"))
        ),
    ], dtype=float)
    logits = np.clip(logits, -20.0, 20.0)
    e = np.exp(logits - np.max(logits))
    p = e / float(np.sum(e))
    rounded = [round(float(pi), 4) for pi in p]
    drift = round(1.0 - sum(rounded[:-1]), 4)
    rounded[-1] = drift
    return {name: val for name, val in zip(REGIMES, rounded, strict=True)}


def holdout_backtest(
    histories: dict[str, np.ndarray],
    window: int = 90,
    horizon: int = 10,
) -> dict[str, Any]:
    """Walk-forward: predict at t on data[:t], label from [t, t+horizon)."""
    keys = list(histories)
    n = min(len(histories[k]) for k in keys)
    if n < window + horizon + 5:
        return {"n": 0, "accuracy": None, "crisis_recall": None, "note": "series too short for holdout"}
    aligned = {k: np.asarray(histories[k][-n:], dtype=float) for k in keys}
    preds: list[str] = []
    labels: list[str] = []
    for t in range(window, n - horizon):
        flags: dict[str, str | None] = {}
        hurst_val = None
        for k, series in aligned.items():
            snap = percentile_snapshot(series[:t], window=window)
            flags[k] = snap["flag"]
            if k == "hurst":
                hurst_val = snap["value"]
        pred = classify(flags, hurst_value=hurst_val)
        fut_credit = aligned["credit_spread"][t : t + horizon]
        fut_corr = aligned["cross_asset_corr"][t : t + horizon]
        past_c = aligned["credit_spread"][:t]
        past_r = aligned["cross_asset_corr"][:t]
        cred_hi = float(np.max(fut_credit)) >= float(np.quantile(past_c, 0.9))
        corr_hi = float(np.max(fut_corr)) >= float(np.quantile(past_r, 0.9))
        fut_rv = aligned["rv_iv_spread"][t : t + horizon]
        rv_hi = float(np.mean(fut_rv)) >= float(np.quantile(aligned["rv_iv_spread"][:t], 0.9))
        fut_h = aligned["hurst"][t : t + horizon]
        if cred_hi and corr_hi:
            lab: RegimeName = "crisis"
        elif rv_hi:
            lab = "high_vol"
        elif float(np.nanmean(fut_h)) >= 0.5:
            lab = "trending"
        else:
            lab = "mean_reverting"
        preds.append(pred)
        labels.append(lab)
    acc = float(np.mean([p == y for p, y in zip(preds, labels, strict=True)]))
    crisis_idx = [i for i, y in enumerate(labels) if y == "crisis"]
    recall = (
        float(np.mean([preds[i] == "crisis" for i in crisis_idx])) if crisis_idx else None
    )
    return {
        "n": len(preds),
        "horizon_days": horizon,
        "accuracy": round(acc, 4),
        "crisis_labels": len(crisis_idx),
        "crisis_recall": None if recall is None else round(recall, 4),
        "note": "Labels are heuristic (future credit/corr/RV/Hurst), not a human regime diary.",
    }


def map_strategies(regime: RegimeName, strategies: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    book = strategies if strategies is not None else DEFAULT_STRATEGIES
    rows = []
    for raw in book:
        s = dict(raw)
        live = list(s.get("live_in") or [])
        kill = list(s.get("kill_in") or [])
        if regime in kill:
            status = "flatten"
        elif regime in live:
            status = "live"
        else:
            status = "standby"
        s["status"] = status
        s["regime"] = regime
        rows.append(s)
    return rows


def _book_corr_penalty(positions: list[dict[str, Any]]) -> float:
    """Average |corr| among names that still have a target > 0. Caller may pass corr."""
    corrs = [float(p["book_corr"]) for p in positions if p.get("book_corr") is not None]
    if not corrs:
        return 0.0
    return float(np.mean(np.abs(corrs)))


def resize(
    regime: RegimeName,
    mapped: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in mapped}
    if not positions:
        positions = [
            {
                "id": s["id"],
                "strategy_id": s["id"],
                "weight": 0.10 if s["status"] == "live" else 0.08,
            }
            for s in mapped
        ]
    penalty = _book_corr_penalty(positions)
    haircut = 1.0 if penalty < 0.6 else max(0.4, 1.0 - (penalty - 0.6))
    out = []
    for p in positions:
        sid = str(p.get("strategy_id") or p["id"])
        strat = by_id.get(sid)
        current = float(p.get("weight") or 0.0)
        if strat is None:
            target = 0.0
            action = "cut"
            reason = f"unknown strategy {sid}"
        else:
            kelly_tbl = strat.get("kelly_by_regime") or {}
            half = float(strat.get("half_kelly") or 0.5)
            raw_k = float(kelly_tbl.get(regime, 0.0))
            target = max(0.0, half * raw_k * haircut)
            if strat["status"] == "flatten":
                target = 0.0
                action = "flatten"
                reason = f"{sid} tagged kill_in={strat.get('kill_in')} under {regime}"
            elif strat["status"] == "standby":
                target = min(target, 0.0)
                action = "cut"
                reason = f"{sid} not live in {regime}"
            elif target > current + 0.01:
                action = "scale_up"
                reason = f"{sid} favored in {regime}; half-Kelly {half * raw_k:.3f}"
            elif target < current - 0.01:
                action = "cut"
                reason = f"{sid} live but current {current:.3f} > target {target:.3f}"
            else:
                action = "hold"
                reason = f"{sid} already near half-Kelly target {target:.3f}"
        delta = target - current
        out.append({
            "id": p["id"],
            "strategy_id": sid,
            "current_weight": round(current, 4),
            "target_weight": round(target, 4),
            "delta": round(delta, 4),
            "action": action,
            "reason": reason,
            "corr_haircut": round(haircut, 4),
        })
    return out


def kill_switch(regime: RegimeName) -> dict[str, Any]:
    armed = regime == "crisis"
    return {
        "armed": armed,
        "regime": regime,
        "action": "research_risk_off" if armed else "watch",
        "broker_orders_sent": 0,
        "paper_flatten": "armed" if armed else "idle",
        "eligible_for_live_trading": False,
        "note": (
            "Crisis arms research_risk_off and, when flatten=true on /regime/live, "
            "closes open paper trades at last mark. ATOM still does not talk to a broker."
        ),
    }


def evaluate(
    *,
    equity_prices: dict[str, list[float]],
    vix_front: list[float],
    vix_back: list[float],
    implied_vol: list[float],
    credit_spread: list[float],
    yield_2y: list[float],
    yield_10y: list[float],
    window: int = 90,
    strategies: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    histories = compute_signal_histories(
        equity_prices, vix_front, vix_back, implied_vol,
        credit_spread, yield_2y, yield_10y,
    )
    snapshots: dict[str, dict[str, Any]] = {}
    flags: dict[str, str | None] = {}
    for name, series in histories.items():
        snap = percentile_snapshot(series, window=window)
        snapshots[name] = snap
        flags[name] = snap["flag"]

    hurst_val = snapshots["hurst"]["value"]
    regime = classify(flags, hurst_value=hurst_val)
    probs = regime_probs(snapshots)
    holdout = holdout_backtest(histories, window=window)
    mapped = map_strategies(regime, strategies)
    adjustments = resize(regime, mapped, positions)
    ks = kill_switch(regime)
    ts = as_of or datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "as_of": ts,
        "regime": regime,
        "probs": probs,
        "holdout": holdout,
        "signals": snapshots,
        "flags": flags,
        "strategies": [
            {
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "status": s["status"],
                "live_in": s.get("live_in"),
                "kill_in": s.get("kill_in"),
            }
            for s in mapped
        ],
        "adjustments": adjustments,
        "kill_switch": ks,
        "eligible_for_live_trading": False,
        "math": (
            "Nowcast: p = 100 · #{x_{t−89…t} ≤ x_t}/90; hard crisis rule as before. "
            "P(regime) = softmax of percentile z-scores (stress signs on VIX term and curve). "
            "Holdout predicts at t on data[:t] and labels the next 10 days. "
            "Hurst is 126-day R/S, 5-window mean."
        ),
        "what_broke": list(_WHAT_BROKE),
    }


def demo_payload(kind: Literal["calm", "trending", "crisis"] = "crisis", n: int = 260, seed: int = 7) -> dict[str, Any]:
    """Aligned synthetic books so the UI/tests do not scrape CBOE/FRED."""
    rng = np.random.default_rng(seed)

    def ou(theta=0.15, sigma=0.01, x0=100.0) -> list[float]:
        x = x0
        out = [x]
        for _ in range(n - 1):
            x = x + theta * (x0 - x) + sigma * x * rng.normal()
            out.append(max(x, 1.0))
        return out

    def gbm(mu=0.0012, sigma=0.01, x0=100.0) -> list[float]:
        x = x0
        out = [x]
        for _ in range(n - 1):
            x = x * np.exp(mu + sigma * rng.normal())
            out.append(float(x))
        return out

    if kind == "trending":
        names = {f"EQ{i}": gbm(0.0015, 0.009, 100 + i) for i in range(4)}
        vix_f = list(18 + 1.5 * rng.normal(size=n))
        vix_b = [max(v * 1.12, 8.0) for v in vix_f]
        credit = list(320 + 8 * rng.normal(size=n))
        y2 = list(4.0 + 0.05 * rng.normal(size=n))
        y10 = [y + 0.45 for y in y2]
    elif kind == "calm":
        names = {f"EQ{i}": ou(0.2, 0.008, 100 + 2 * i) for i in range(4)}
        vix_f = list(14 + 0.8 * rng.normal(size=n))
        vix_b = [max(v * 1.15, 8.0) for v in vix_f]
        credit = list(280 + 6 * rng.normal(size=n))
        y2 = list(3.8 + 0.04 * rng.normal(size=n))
        y10 = [y + 0.6 for y in y2]
    else:
        names = {f"EQ{i}": ou(0.08, 0.012, 100 + i) for i in range(4)}
        shock = np.zeros(n)
        shock[-12:] = -0.035
        for k, series in list(names.items()):
            p = np.asarray(series, dtype=float)
            p = p * np.cumprod(1.0 + shock)
            names[k] = [float(x) for x in np.maximum(p, 1.0)]
        vix_f = list(16 + 1.0 * rng.normal(size=n))
        vix_b = [max(v * 1.14, 8.0) for v in vix_f]
        credit = list(310 + 8 * rng.normal(size=n))
        y2 = list(4.1 + 0.04 * rng.normal(size=n))
        y10 = [y + 0.4 for y in y2]
        for i in range(12):
            t = n - 12 + i
            vix_f[t] = 22.0 + 1.8 * i
            vix_b[t] = 28.0 - 0.15 * i  # last front > back → backwardation
            credit[t] = 400.0 + 35.0 * i  # last point is the window max
            y10[t] = y2[t] - 0.05 * (i + 1)

    iv = list(0.16 + 0.01 * rng.normal(size=n))
    if kind == "crisis":
        for i in range(n - 12, n):
            iv[i] = 0.42
    iv = [max(v, 0.05) for v in iv]
    vix_f = [max(v, 8.0) for v in vix_f]
    return {
        "equity_prices": names,
        "vix_front": vix_f,
        "vix_back": vix_b,
        "implied_vol": iv,
        "credit_spread": credit,
        "yield_2y": y2,
        "yield_10y": y10,
        "window": 90,
    }

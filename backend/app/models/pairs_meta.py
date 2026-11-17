"""Triple-barrier labels + meta-labeling on ATOM's existing pairs signal.

Primary side comes from the causal Engle–Granger / expanding-z book already in
``cointegration.pairs_backtest`` (Gatev-style residual z; Avellaneda–Lee half-life
as a feature). Outcomes are three-barrier, net of two-leg fee+spread — not
"up or down". A second model, scored out-of-fold with purged+embargo CV,
estimates P(the trade works). Below the threshold we stay out; above, size
scales with that probability.

This module never talks to a broker. ``eligible_for_live_trading`` is always false.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import lfilter
from sklearn.ensemble import RandomForestClassifier

from app.models.afml.cv import PurgedKFold
from app.models.afml.gate import gate_trial
from app.models.afml.labeling import triple_barrier_on_pnl
from app.models.afml.trials import TrialRegistry
from app.models.cointegration import _expanding_hedge, _half_life, engle_granger, johansen
from app.models.winners_curse import DEFAULT_PERIODS

FAMILY_ID = "pairs_gatev_avellaneda"
ENTRY_Z = 2.0
EXIT_Z = 0.5  # documented primary exit; barriers replace it for the label
COMMISSION = 0.0005
SLIPPAGE = 0.0002
WARMUP = 60
META_THRESHOLD = 0.55
PT_MULT = 1.0
SL_MULT = 1.0
N_SPLITS = 4
PCT_EMBARGO = 0.05
MIN_EVENTS = 24
DEMO_N = 2200
DEMO_SEED = 11

_WHAT_BROKE = [
    "Sinal primário é o z expanding do resíduo EG (Gatev / Avellaneda–Lee), não um Kalman.",
    "PnL é retorno sobre o nocional bruto das duas pernas (|y|+|β||x|), hedge congelado na entrada.",
    "β expanding é OLS em nível, congelado na entrada; ainda não é Kalman.",
    "Lote, aluguel e funding de perpétuo ficam de fora do PnL à vista.",
    "Meta-rótulo é um RF raso com purga/embargo — não é um modelo de produção.",
    "DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.",
    "DGP sintético do relatório reproduz cointegração com saltos; não é um livro real.",
]


def round_trip_cost(commission: float = COMMISSION, slippage: float = SLIPPAGE) -> float:
    """Open+close, both legs, as a fraction of gross two-leg notional.

    Each fill costs ``commission+slippage`` of that leg. Two legs, twice
    (open and close) ⇒ 2×(c+s) × (|y|+|β||x|).
    """
    return 2.0 * (commission + slippage)


def synthetic_coint_pair(
    n: int = DEMO_N,
    seed: int = DEMO_SEED,
    beta: float = 1.4,
    phi: float = 0.82,
    jump_prob: float = 0.008,
    jump_sigma: float = 1.6,
) -> tuple[np.ndarray, np.ndarray]:
    """Random-walk X plus OU residual (with rare jumps that break the spread)."""
    if n < 120:
        raise ValueError("Need at least 120 bars")
    rng = np.random.default_rng(seed)
    x = 40.0 + np.cumsum(rng.normal(0.0, 0.35, n))
    shock = rng.normal(0.0, 0.28, n)
    jumps = rng.random(n) < jump_prob
    shock[jumps] += rng.normal(0.0, jump_sigma, int(jumps.sum()))
    e = lfilter([1.0], [1.0, -phi], shock)
    y = 4.0 + beta * x + e
    y = np.maximum(y, 0.5)
    x = np.maximum(x, 0.5)
    return y, x


def _expanding_z(spread: np.ndarray, min_periods: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s = pd.Series(spread, dtype=float)
    mu = s.expanding(min_periods=min_periods).mean().to_numpy()
    sd = s.expanding(min_periods=min_periods).std(ddof=1).to_numpy()
    z = np.full(len(spread), np.nan)
    ok = np.isfinite(sd) & (sd > 1e-12) & np.isfinite(spread)
    z[ok] = (spread[ok] - mu[ok]) / sd[ok]
    return z, mu, sd


def _vol20(prices: np.ndarray) -> np.ndarray:
    r = np.diff(prices) / prices[:-1]
    r = np.concatenate([[np.nan], r])
    return pd.Series(r).rolling(20, min_periods=10).std().to_numpy()


def causal_pairs_state(y: np.ndarray, x: np.ndarray, warmup: int = WARMUP) -> dict[str, np.ndarray]:
    """Expanding hedge, residual z and 20-bar leg vol. Information at t uses ≤ t.

    β_t is OLS on data[:t+1] (Gatev residual). The fill is the next bar, so
    today's print is not in the trade PnL. During the hold, β is frozen at
    entry — see ``frozen_gross_path``.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if y.shape != x.shape or len(y) < warmup + 20:
        raise ValueError("Need two aligned series longer than the warmup")
    alpha, beta, spread = _expanding_hedge(y, x, 20)
    z, mu, sd = _expanding_z(spread, 20)
    return {
        "alpha": alpha,
        "beta": beta,
        "spread": spread,
        "z": z,
        "mu": mu,
        "resid_std": sd,
        "y_vol20": _vol20(y),
        "x_vol20": _vol20(x),
    }


def primary_entry_indices(z: np.ndarray, entry_z: float = ENTRY_Z, warmup: int = WARMUP) -> np.ndarray:
    """Bars where |z| crosses above ``entry_z`` from below. Side is applied later."""
    absz = np.abs(z)
    prev = np.roll(absz, 1)
    prev[0] = np.nan
    cross = (absz > entry_z) & (prev <= entry_z) & np.isfinite(absz) & np.isfinite(prev)
    cross[:warmup] = False
    return np.flatnonzero(cross)


def gross_notional(y: float, x: float, beta: float) -> float:
    """Gross two-leg notional of +1 share of y vs β shares of x."""
    return float(abs(y) + abs(beta) * abs(x))


def pair_pnl_path(y: np.ndarray, x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Cumulative *rehedged* return on gross notional. Prefer frozen-β event paths."""
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    beta = np.asarray(beta, dtype=np.float64)
    path = np.zeros(len(y))
    if len(y) < 2:
        return path
    dy = np.diff(y)
    dx = np.diff(x)
    b = beta[:-1]
    gross = np.abs(y[:-1]) + np.abs(b) * np.abs(x[:-1])
    r = np.zeros(len(dy))
    ok = np.isfinite(dy) & np.isfinite(dx) & np.isfinite(b) & (gross > 1e-12)
    r[ok] = (dy[ok] - b[ok] * dx[ok]) / gross[ok]
    path[1:] = np.cumsum(r)
    return path


def frozen_gross_path(y: np.ndarray, x: np.ndarray, t0: int, beta0: float) -> np.ndarray:
    """MTM path of a book opened at t0: +1 y vs β0 x, return on gross notional at t0.

    path[t] = [(y_t−y_t0) − β0 (x_t−x_t0)] / (|y_t0|+|β0||x_t0|), 0 for t < t0.
    Hedge does not update during the hold — no silent rehedge.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    n = len(y)
    path = np.zeros(n)
    if t0 < 0 or t0 >= n:
        return path
    g = gross_notional(float(y[t0]), float(x[t0]), float(beta0))
    if not np.isfinite(beta0) or g < 1e-12:
        return path
    dollar = (y - y[t0]) - float(beta0) * (x - x[t0])
    path[t0:] = dollar[t0:] / g
    return path


def _event_half_life(spread: np.ndarray, t0: int) -> float:
    window = spread[: t0 + 1]
    window = window[np.isfinite(window)]
    if len(window) < 20:
        return float("nan")
    return float(_half_life(window))


def _horizon_bars(half_life: float) -> int:
    if not np.isfinite(half_life) or half_life <= 0:
        return 12
    return int(np.clip(round(2.0 * half_life), 5, 25))


def build_event_table(
    y: np.ndarray,
    x: np.ndarray,
    *,
    entry_z: float = ENTRY_Z,
    warmup: int = WARMUP,
    commission: float = COMMISSION,
    slippage: float = SLIPPAGE,
    pt: float = PT_MULT,
    sl: float = SL_MULT,
    min_events: int = MIN_EVENTS,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Primary entries → three-barrier labels net of round-trip costs."""
    state = causal_pairs_state(y, x, warmup=warmup)
    entries = primary_entry_indices(state["z"], entry_z=entry_z, warmup=warmup)
    cost = round_trip_cost(commission, slippage)
    sides, widths, horizons, hls, z5 = [], [], [], [], []
    keep = []
    chunks: list[pd.DataFrame] = []
    for t0 in entries:
        if t0 >= len(y) - 3:
            continue
        z0 = state["z"][t0]
        side = -float(np.sign(z0))
        if side == 0:
            continue
        b0 = float(state["beta"][t0])
        if not np.isfinite(b0):
            continue
        sd = state["resid_std"][t0]
        g = gross_notional(float(y[t0]), float(x[t0]), b0)
        width = float(sd / g) if np.isfinite(sd) and g > 0 else 0.0
        width = max(width, 0.003)
        hl = _event_half_life(state["spread"], int(t0))
        h = _horizon_bars(hl)
        path = frozen_gross_path(y, x, int(t0), b0)
        lab = triple_barrier_on_pnl(path, [int(t0)], [side], [width], [h], pt=pt, sl=sl, cost=cost)
        if lab.empty:
            continue
        keep.append(int(t0))
        sides.append(side)
        widths.append(width)
        horizons.append(h)
        hls.append(hl)
        z5.append(state["z"][t0] - state["z"][max(t0 - 5, 0)])
        chunks.append(lab)
    empty_cols = [
        "t0", "t1", "side", "touch", "ret", "ret_net", "bin",
        "z_delta_5", "half_life", "horizon",
    ]
    if not chunks or len(keep) < min_events:
        if min_events > 0:
            raise ValueError(
                f"Poucos eventos de pares ({len(keep)}; mínimo {min_events}). "
                "Aumente o histórico ou relaxe o z de entrada — isto não é um ajuste de grade."
            )
        return pd.DataFrame({c: [] for c in empty_cols}), state
    labels = pd.concat(chunks, ignore_index=True)
    if len(labels) < min_events:
        if min_events > 0:
            raise ValueError(f"Poucas barreiras resolvidas ({len(labels)}; mínimo {min_events}).")
        return pd.DataFrame({c: [] for c in empty_cols}), state
    extra = pd.DataFrame({"t0": keep, "z_delta_5": z5, "half_life": hls, "horizon": horizons})
    labels = labels.merge(extra, on="t0", how="left")
    feat_idx = labels["t0"].to_numpy(dtype=int)
    z = state["z"]
    labels["z"] = z[feat_idx]
    labels["abs_z"] = np.abs(z[feat_idx])
    labels["beta"] = state["beta"][feat_idx]
    labels["resid_std"] = state["resid_std"][feat_idx]
    labels["y_vol20"] = state["y_vol20"][feat_idx]
    labels["x_vol20"] = state["x_vol20"][feat_idx]
    labels["half_life"] = labels["half_life"].replace([np.inf, -np.inf], np.nan).fillna(25.0)
    return labels, state


FEATURE_COLS = ["z", "abs_z", "z_delta_5", "beta", "resid_std", "half_life", "y_vol20", "x_vol20"]


def _meta_oof(
    events: pd.DataFrame,
    threshold: float = META_THRESHOLD,
    feature_cols: list[str] | None = None,
    regime_veto: bool = False,
) -> pd.Series:
    """Purged+embargo out-of-fold P(success). Features at t0; labels use t1.

    Regime vetoes are chosen **inside each train fold** (hit rate < 0.5 with
    ≥6 train events in that regime) and applied only to that fold's test rows.
    """
    cols = [c for c in (feature_cols or FEATURE_COLS) if c in events.columns]
    if not cols:
        raise ValueError("Nenhuma coluna de feature disponível para o meta-rótulo")
    X = events[cols].astype(float)
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = events["bin"].astype(int)
    # Integer time index so purge sees the actual label span on the bar clock.
    index = pd.Index(events["t0"].to_numpy(), name="t0")
    X.index = index
    y.index = index
    t1 = pd.Series(events["t1"].to_numpy(), index=index)
    n_splits = int(min(N_SPLITS, max(2, len(events) // 15)))
    cv = PurgedKFold(n_splits, t1, pct_embargo=PCT_EMBARGO)
    oof = pd.Series(np.nan, index=index, dtype=float)
    regimes = events["regime"].astype(str) if "regime" in events.columns else None
    for tr, te in cv.split(X):
        if len(tr) < 12 or len(te) < 3:
            continue
        if len(np.unique(y.iloc[tr])) < 2:
            oof.iloc[te] = float(y.iloc[tr].mean())
            continue
        clf = RandomForestClassifier(
            n_estimators=80,
            max_depth=4,
            min_samples_leaf=6,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=0,
            n_jobs=1,
        )
        clf.fit(X.iloc[tr], y.iloc[tr])
        proba = np.asarray(clf.predict_proba(X.iloc[te]))
        classes = [int(c) for c in clf.classes_]
        p1 = proba[:, classes.index(1)] if 1 in classes else np.zeros(len(te))
        if regime_veto and regimes is not None:
            tr_reg = regimes.iloc[tr].to_numpy()
            tr_y = y.iloc[tr].to_numpy()
            veto: set[str] = set()
            for rg in np.unique(tr_reg):
                if rg in {"nan", "None", ""}:
                    continue
                m = tr_reg == rg
                if int(m.sum()) >= 6 and float(np.mean(tr_y[m])) < 0.5:
                    veto.add(str(rg))
            te_reg = regimes.iloc[te].to_numpy()
            for i, rg in enumerate(te_reg):
                if str(rg) in veto:
                    p1[i] = 0.0
        oof.iloc[te] = p1
    # Chronological leftover (rows never in a test fold) stay NaN → treated as abstain.
    _ = threshold
    return oof


def _trade_stats(net: np.ndarray, bins: np.ndarray) -> dict[str, float]:
    net = np.asarray(net, dtype=float)
    bins = np.asarray(bins, dtype=int)
    n = int(len(net))
    if n == 0:
        return {
            "n_trades": 0,
            "hit_rate": float("nan"),
            "net_per_trade": float("nan"),
            "total_net": 0.0,
        }
    return {
        "n_trades": n,
        "hit_rate": float(np.mean(bins)),
        "net_per_trade": float(np.mean(net)),
        "total_net": float(np.sum(net)),
    }


def _occupy_bar_returns(
    y: np.ndarray,
    x: np.ndarray,
    events: pd.DataFrame,
    size: np.ndarray,
    cost: float,
) -> np.ndarray:
    """Non-overlapping book: first accepted event occupies until t1.

    Bar return is frozen-β dollar PnL over the entry gross notional.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    n_bars = len(y)
    rets = np.zeros(n_bars, dtype=float)
    busy_until = -1
    order = np.argsort(events["t0"].to_numpy())
    for i in order:
        if size[i] <= 0:
            continue
        t0 = int(events["t0"].iloc[i])
        t1 = int(events["t1"].iloc[i])
        if t0 <= busy_until:
            continue
        fill = t0 + 1
        if fill >= n_bars:
            continue
        b0 = float(events["beta"].iloc[i]) if "beta" in events.columns else 1.0
        g0 = gross_notional(float(y[t0]), float(x[t0]), b0)
        if g0 < 1e-12:
            continue
        s = float(events["side"].iloc[i]) * float(size[i])
        end = min(t1, n_bars - 1)
        dy = np.diff(y[t0 : end + 1])
        dx = np.diff(x[t0 : end + 1])
        bar_r = (dy - b0 * dx) / g0
        rets[fill : end + 1] += s * bar_r
        rets[fill] -= 0.5 * cost * abs(size[i])
        rets[end] -= 0.5 * cost * abs(size[i])
        busy_until = end
    return rets


def _count_overlaps(events: pd.DataFrame) -> int:
    if events.empty:
        return 0
    t0 = events["t0"].to_numpy(dtype=int)
    t1 = events["t1"].to_numpy(dtype=int)
    n = 0
    for i in range(len(t0)):
        for j in range(i + 1, len(t0)):
            if t0[j] <= t1[i] and t0[i] <= t1[j]:
                n += 1
                break
    return n


def _oos_slice(n: int, oos_frac: float) -> int:
    frac = min(max(float(oos_frac), 0.1), 0.5)
    cut = int(round(n * (1.0 - frac)))
    return min(max(cut, 60), n - 60) if n >= 120 else n // 2


def evaluate_pairs_meta(
    y: np.ndarray,
    x: np.ndarray,
    *,
    entry_z: float = ENTRY_Z,
    commission: float = COMMISSION,
    slippage: float = SLIPPAGE,
    threshold: float = META_THRESHOLD,
    warmup: int = WARMUP,
    registry: TrialRegistry | None = None,
    family_id: str = FAMILY_ID,
    pair_id: str | None = None,
    periods_per_year: float = DEFAULT_PERIODS,
    min_events: int = MIN_EVENTS,
    min_oos_scored: int = 10,
    apply_gate: bool = True,
    oos_frac: float = 0.3,
    include_bar_returns: bool = False,
    extra_features: dict[str, np.ndarray] | None = None,
    feature_cols: list[str] | None = None,
    regimes: np.ndarray | None = None,
    regime_veto: bool = False,
    register_primary: bool = True,
    meta_variant: str = "meta_filtered",
) -> dict[str, Any]:
    """Run primary pairs → triple barrier → meta-label OOF → DSR gate.

    Parameters are the desk defaults. This function does not search a grid.
    ``extra_features`` are bar-aligned arrays (info ≤ t) attached at t0.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    cost = round_trip_cost(commission, slippage)
    events, state = build_event_table(
        y, x, entry_z=entry_z, warmup=warmup, commission=commission, slippage=slippage,
        min_events=min_events,
    )
    if not events.empty:
        idx = events["t0"].to_numpy(dtype=int)
        if extra_features:
            for name, arr in extra_features.items():
                vec = np.asarray(arr, dtype=float)
                events[name] = vec[idx] if len(vec) == len(y) else np.nan
        if regimes is not None:
            reg = np.asarray(regimes)
            events["regime"] = [str(reg[i]) if i < len(reg) else "nan" for i in idx]
    skipped_meta = False
    skip_reason = None
    n_oos_scored = 0
    used_cols = list(feature_cols or FEATURE_COLS)
    if events.empty:
        skipped_meta = True
        skip_reason = "sem eventos de entrada resolvidos"
        scored = events
        primary = _trade_stats(np.array([]), np.array([], dtype=int))
        filtered = _trade_stats(np.array([]), np.array([], dtype=int))
        bar_primary = np.zeros(len(y), dtype=float)
        bar_filtered = np.zeros(len(y), dtype=float)
    elif len(events) < 8:
        skipped_meta = True
        skip_reason = f"poucos eventos para meta OOF ({len(events)})"
        if min_oos_scored > 0:
            raise ValueError("Purga/embargo deixou poucas previsões fora da amostra.")
        scored = events
        primary = _trade_stats(events["ret_net"].to_numpy(), events["bin"].to_numpy())
        filtered = _trade_stats(np.array([]), np.array([], dtype=int))
        bar_primary = _occupy_bar_returns(y, x, events, np.ones(len(events)), cost)
        bar_filtered = np.zeros(len(y), dtype=float)
    else:
        oof = _meta_oof(
            events,
            threshold=threshold,
            feature_cols=used_cols,
            regime_veto=regime_veto,
        )
        events = events.copy()
        events["p_success"] = oof.to_numpy()
        scored = events.dropna(subset=["p_success"])
        n_oos_scored = int(len(scored))
        if len(scored) < min_oos_scored or (min_oos_scored == 0 and scored.empty):
            if min_oos_scored > 0:
                raise ValueError("Purga/embargo deixou poucas previsões fora da amostra.")
            skipped_meta = True
            skip_reason = f"poucas previsões OOF ({len(scored)})"
            scored = events
            primary = _trade_stats(events["ret_net"].to_numpy(), events["bin"].to_numpy())
            filtered = _trade_stats(np.array([]), np.array([], dtype=int))
            bar_primary = _occupy_bar_returns(y, x, events, np.ones(len(events)), cost)
            bar_filtered = np.zeros(len(y), dtype=float)
        else:
            primary = _trade_stats(scored["ret_net"].to_numpy(), scored["bin"].to_numpy())
            accepted = scored["p_success"].to_numpy() >= threshold
            filtered = _trade_stats(
                scored["ret_net"].to_numpy()[accepted],
                scored["bin"].to_numpy()[accepted],
            )
            size = np.zeros(len(scored))
            p = scored["p_success"].to_numpy()
            size[accepted] = np.clip((p[accepted] - threshold) / max(1.0 - threshold, 1e-9), 0.0, 1.0)
            primary_size = np.ones(len(scored))
            bar_primary = _occupy_bar_returns(y, x, scored, primary_size, cost)
            bar_filtered = _occupy_bar_returns(y, x, scored, size, cost)

    close_reg = False
    if registry is None:
        registry = TrialRegistry(":memory:")
        close_reg = True
    params_common = {
        "entry_z": entry_z,
        "exit_z_replaced_by_barriers": EXIT_Z,
        "commission": commission,
        "slippage": slippage,
        "pt": PT_MULT,
        "sl": SL_MULT,
        "warmup": warmup,
        "periods_per_year": periods_per_year,
    }
    if pair_id:
        params_common["pair_id"] = pair_id
    params_common["pnl_unit"] = "gross_two_leg_notional"
    params_common["hedge"] = "expanding_ols_frozen_at_entry"
    meta_trial = None
    if register_primary:
        registry.register(
            family_id,
            {**params_common, "variant": "primary_triple_barrier"},
            returns=bar_primary[warmup:].tolist(),
            costs_included=True,
            periods_per_year=periods_per_year,
            notes="Todas as entradas Gatev/EG, barreiras triplas, custo nas duas pernas, PnL/nocional bruto.",
        )
    meta_trial = registry.register(
        family_id,
        {
            **params_common,
            "variant": meta_variant,
            "threshold": threshold,
            "regime_veto": regime_veto,
            "feature_set": ",".join(used_cols),
        },
        returns=bar_filtered[warmup:].tolist(),
        costs_included=True,
        periods_per_year=periods_per_year,
        notes="Mesmo primário; só opera se P(sucesso) OOF ≥ limiar; tamanho ∝ probabilidade.",
    )
    verdict = None
    if apply_gate:
        verdict = gate_trial(registry, family_id, costs_included=True, trial_id=meta_trial.id)
    n_trials = registry.count(family_id)
    if close_reg:
        registry.close()

    hit_delta = filtered["hit_rate"] - primary["hit_rate"] if filtered["n_trades"] else float("nan")
    pnl_delta = (
        filtered["net_per_trade"] - primary["net_per_trade"] if filtered["n_trades"] else float("nan")
    )
    filter_helps = bool(
        filtered["n_trades"] >= 5
        and np.isfinite(hit_delta)
        and np.isfinite(pnl_delta)
        and (hit_delta > 0 or pnl_delta > 0)
    )
    eg = engle_granger(y, x)
    cut = _oos_slice(len(y), oos_frac)
    try:
        eg_oos = engle_granger(y[cut:], x[cut:])
        eg_oos_payload = {
            "cointegrated": eg_oos["cointegrated"],
            "beta": eg_oos["beta"],
            "adf_tstat": eg_oos["adf_tstat"],
            "half_life_days": eg_oos["half_life_days"],
            "n": eg_oos["n"],
            "cut": int(cut),
        }
    except ValueError as exc:
        eg_oos_payload = {
            "cointegrated": False,
            "beta": None,
            "adf_tstat": None,
            "half_life_days": None,
            "n": int(max(len(y) - cut, 0)),
            "cut": int(cut),
            "error": str(exc),
        }
    try:
        joh = johansen(np.column_stack([y, x]), k_ar=2)
        johansen_rank = joh["rank"]
    except ValueError:
        johansen_rank = None

    def _round_stats(s: dict[str, float]) -> dict[str, Any]:
        out: dict[str, Any] = dict(s)
        out["n_trades"] = int(s["n_trades"])
        if s["n_trades"]:
            out["hit_rate"] = round(float(s["hit_rate"]), 6)
            out["net_per_trade"] = round(float(s["net_per_trade"]), 8)
            out["total_net"] = round(float(s["total_net"]), 8)
        else:
            out["hit_rate"] = None
            out["net_per_trade"] = None
            out["total_net"] = 0.0
        return out

    out: dict[str, Any] = {
        "family_id": family_id,
        "pair_id": pair_id,
        "n_bars": int(len(y)),
        "n_events": int(len(events)),
        "n_oos_scored": int(n_oos_scored),
        "n_trials_registered": int(n_trials),
        "entry_z": entry_z,
        "threshold": threshold,
        "round_trip_cost": cost,
        "periods_per_year": float(periods_per_year),
        "engle_granger": {
            "cointegrated": eg["cointegrated"],
            "beta": eg["beta"],
            "adf_tstat": eg["adf_tstat"],
            "half_life_days": eg["half_life_days"],
        },
        "engle_granger_oos": eg_oos_payload,
        "johansen_rank": johansen_rank,
        "primary": _round_stats(primary),
        "filtered": _round_stats(filtered),
        "filter_improves_hit_or_net": filter_helps,
        "hit_rate_delta": None if not np.isfinite(hit_delta) else round(float(hit_delta), 6),
        "net_per_trade_delta": None if not np.isfinite(pnl_delta) else round(float(pnl_delta), 8),
        "gate": None if verdict is None else verdict.to_dict(),
        "skipped_meta": skipped_meta,
        "skip_reason": skip_reason,
        "eligible_for_live_trading": False,
        "out_of_sample": True,
        "pnl_unit": "gross_two_leg_notional",
        "n_overlapping": 0 if events.empty else _count_overlaps(events),
        "meta_variant": meta_variant,
        "feature_cols": used_cols,
        "regime_veto": regime_veto,
        "math": (
            "Primário: z expanding do resíduo y−(α_t+β_t x) (OLS em data[:t+1]; fill em t+1). "
            "Rótulo: primeira barreira no PnL com β congelado na entrada, retorno sobre |y|+|β||x|, líquido de 2×(taxa+spread). "
            "Meta: RF com PurgedKFold + embargo; P(bin=1) OOF. "
            "Gate: DSR de Bailey & López de Prado ≥ 0,95 com N registrado, assimetria, curtose e MinTRL."
        ),
        "what_broke": list(_WHAT_BROKE),
    }
    if include_bar_returns:
        out["bar_primary"] = [round(float(v), 10) for v in bar_primary]
        out["bar_filtered"] = [round(float(v), 10) for v in bar_filtered]
    return out


def render_report_md(result: dict[str, Any]) -> str:
    p, f = result["primary"], result["filtered"]
    g: dict[str, Any] = result["gate"] or {}
    dsr = g.get("dsr")
    approved = bool(g.get("approved"))
    reasons = g.get("reasons") or []
    helps = result["filter_improves_hit_or_net"]
    total_down = (
        f["n_trades"]
        and p["n_trades"]
        and np.isfinite(f["total_net"])
        and np.isfinite(p["total_net"])
        and f["total_net"] < p["total_net"]
    )
    if helps:
        extra = (
            " O ganho líquido **total** caiu porque o filtro opera menos vezes."
            if total_down
            else ""
        )
        verdict_filter = (
            "O filtro de meta-rótulo melhorou a taxa de acerto e/ou o ganho líquido por operação "
            f"fora da amostra.{extra}"
        )
    else:
        verdict_filter = (
            "O filtro de meta-rótulo **não** melhorou a taxa de acerto nem o ganho líquido "
            "por operação fora da amostra."
        )
    n_reg = result["n_trials_registered"]
    if approved and dsr is not None:
        gate_line = (
            f"DSR = {dsr:.4f} — **passou** no portão (≥ 0,95) com N={n_reg} tentativas "
            "realmente registradas. Isso só autoriza considerar paper, não capital ao vivo. "
            "N pequeno deixa o portão mais brando — não é evidência de alpha."
        )
    elif dsr is not None:
        gate_line = f"DSR = {dsr:.4f} — **não passou** no portão (limiar 0,95, N={n_reg})."
    else:
        gate_line = "DSR indisponível — o portão recusou."
    reasons_md = "\n".join(f"- {r}" for r in reasons) or "- (nenhum)"
    return f"""# Pares Gatev / Avellaneda–Lee — barreiras triplas, meta-rótulo e portão DSR

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

Sinal primário: resíduo de Engle–Granger com hedge expanding, entrada quando |z| > {result["entry_z"]}
(o backtest de pares já existente no ATOM). Rótulo: três barreiras (alvo, stop, prazo) no PnL
do book, **retorno sobre o nocional bruto** das duas pernas (|y|+|β||x|),
**líquido** de taxa e spread (ida e volta = {result["round_trip_cost"]:.4f} do nocional bruto).
Meta-rótulo: um RF estima P(a operação dar certo) fora da amostra com PurgedKFold e embargo.
Abaixo do limiar {result["threshold"]} não entra; acima, o tamanho segue a probabilidade.

## Fora da amostra (previsões OOF)

| | Sem filtro (primário) | Com filtro (meta) |
|---|---|---|
| Operações | {p["n_trades"]} | {f["n_trades"]} |
| Taxa de acerto | {_pct(p["hit_rate"])} | {_pct(f["hit_rate"])} |
| Ganho líquido / operação | {_bps(p["net_per_trade"])} | {_bps(f["net_per_trade"])} |
| Ganho líquido total (soma das operações) | {_bps(p["total_net"])} | {_bps(f["total_net"])} |

{verdict_filter}

Eventos gerados: {result["n_events"]}. Eventos com previsão OOF: {result["n_oos_scored"]}.
Tentativas registradas na família `{result["family_id"]}`: {result["n_trials_registered"]}.

## Portão de Sharpe deflacionado

{gate_line}

- Sharpe observado (série em barra, líquida de custo): {g.get("observed_sharpe")}
- SR\\* (esperado da busca): {g.get("sr_star")}
- PSR: {g.get("psr")}
- MinTRL: {g.get("min_trl")}
- T (barras): {g.get("n_obs")}
- N: {g.get("n_trials")}
- N efetivo: {_fmt_n(g.get("n_eff"))}
- Assimetria: {g.get("skew")}
- Curtose excedente: {g.get("excess_kurtosis")}
- Custos declarados na série: {g.get("costs_included")}

Motivos do portão:

{reasons_md}

Aprovação do portão **não** autoriza capital ao vivo.

## Diagnóstico de cointegração (amostra cheia, hipótese)

- EG cointegrado: {result["engle_granger"]["cointegrated"]} (ADF={result["engle_granger"]["adf_tstat"]}, β={result["engle_granger"]["beta"]})
- Meia-vida do resíduo (dias): {result["engle_granger"]["half_life_days"]}
- Rank de Johansen: {result["johansen_rank"]}

## O que quebrou

{chr(10).join(f"- {w}" for w in result["what_broke"])}

Reprodução: `python -m app.models.pairs_meta --demo` a partir de `backend/`.
"""


def _pct(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.1f}%"


def _bps(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.3f}%"


def _fmt_n(x) -> str:
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not np.isfinite(v):
        return "n/a"
    return f"{v:.3f}"


def write_report(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "pairs-meta-label-oos.md"
    json_path = out_dir / "pairs-meta-label-oos.json"
    md_path.write_text(render_report_md(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


def run_demo(
    n: int = DEMO_N,
    seed: int = DEMO_SEED,
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    y, x = synthetic_coint_pair(n=n, seed=seed)
    registry = TrialRegistry(registry_path) if registry_path else TrialRegistry(":memory:")
    try:
        return evaluate_pairs_meta(y, x, registry=registry)
    finally:
        registry.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pares + barreiras triplas + meta-rótulo + portão DSR (paper only).")
    p.add_argument("--demo", action="store_true", help="Série sintética cointegrada (padrão).")
    p.add_argument("--n", type=int, default=DEMO_N)
    p.add_argument("--seed", type=int, default=DEMO_SEED)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Pasta para o markdown/json (default: docs/reports na raiz do repo).",
    )
    args = p.parse_args(argv)
    result = run_demo(n=args.n, seed=args.seed)
    repo = Path(__file__).resolve().parents[3]
    out_dir = args.out_dir or (repo / "docs" / "reports")
    md_path, json_path = write_report(result, out_dir)
    print(md_path)
    print(json_path)
    print(json.dumps({
        "primary": result["primary"],
        "filtered": result["filtered"],
        "gate_approved": result["gate"]["approved"],
        "dsr": result["gate"]["dsr"],
        "eligible_for_live_trading": result["eligible_for_live_trading"],
    }, indent=2))
    return 0 if result.get("eligible_for_live_trading") is False else 2


if __name__ == "__main__":
    raise SystemExit(main())

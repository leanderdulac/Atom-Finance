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
    "Barreiras usam o PnL do book unitário; lote, aluguel e funding ficam de fora.",
    "Meta-rótulo é um RF raso com purga/embargo — não é um modelo de produção.",
    "DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.",
    "DGP sintético do relatório reproduz cointegração com saltos; não é um livro real.",
]


def round_trip_cost(commission: float = COMMISSION, slippage: float = SLIPPAGE) -> float:
    """Open+close, two legs, same costing as ``pairs_backtest``."""
    return 4.0 * (commission + slippage)


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
    """Expanding hedge, residual z and 20-bar leg vol. Information at t uses ≤ t."""
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


def pair_pnl_path(y: np.ndarray, x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Cumulative return of a +1 spread unit: long y, short β_{t-1} x."""
    dy = np.diff(y) / y[:-1]
    dx = np.diff(x) / x[:-1]
    r = dy - beta[:-1] * dx
    path = np.zeros(len(y))
    path[1:] = np.cumsum(np.where(np.isfinite(r), r, 0.0))
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
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Primary entries → three-barrier labels net of round-trip costs."""
    state = causal_pairs_state(y, x, warmup=warmup)
    entries = primary_entry_indices(state["z"], entry_z=entry_z, warmup=warmup)
    cost = round_trip_cost(commission, slippage)
    path = pair_pnl_path(y, x, state["beta"])
    sides, widths, horizons, hls, z5 = [], [], [], [], []
    keep = []
    for t0 in entries:
        if t0 >= len(y) - 3:
            continue
        z0 = state["z"][t0]
        side = -float(np.sign(z0))
        if side == 0:
            continue
        sd = state["resid_std"][t0]
        width = float(sd / y[t0]) if np.isfinite(sd) and y[t0] > 0 else 0.0
        width = max(width, 0.003)
        hl = _event_half_life(state["spread"], int(t0))
        h = _horizon_bars(hl)
        keep.append(int(t0))
        sides.append(side)
        widths.append(width)
        horizons.append(h)
        hls.append(hl)
        z5.append(state["z"][t0] - state["z"][max(t0 - 5, 0)])
    if len(keep) < MIN_EVENTS:
        raise ValueError(
            f"Poucos eventos de pares ({len(keep)}; mínimo {MIN_EVENTS}). "
            "Aumente o histórico ou relaxe o z de entrada — isto não é um ajuste de grade."
        )
    labels = triple_barrier_on_pnl(path, keep, sides, widths, horizons, pt=pt, sl=sl, cost=cost)
    if len(labels) < MIN_EVENTS:
        raise ValueError(f"Poucas barreiras resolvidas ({len(labels)}; mínimo {MIN_EVENTS}).")
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


def _meta_oof(events: pd.DataFrame, threshold: float = META_THRESHOLD) -> pd.Series:
    """Purged+embargo out-of-fold P(success). Features at t0; labels use t1."""
    X = events[FEATURE_COLS].astype(float)
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
        if 1 in classes:
            oof.iloc[te] = proba[:, classes.index(1)]
        else:
            oof.iloc[te] = 0.0
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
    n_bars: int,
    events: pd.DataFrame,
    pair_ret: np.ndarray,
    size: np.ndarray,
    cost: float,
) -> np.ndarray:
    """Non-overlapping book: first accepted event occupies until t1; bar returns net of costs."""
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
        s = float(events["side"].iloc[i]) * float(size[i])
        end = min(t1, n_bars - 1)
        sl = slice(fill, end + 1)
        rets[sl] += s * pair_ret[sl]
        rets[fill] -= 0.5 * cost * abs(size[i])
        rets[end] -= 0.5 * cost * abs(size[i])
        busy_until = end
    return rets


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
) -> dict[str, Any]:
    """Run primary pairs → triple barrier → meta-label OOF → DSR gate.

    Parameters are the desk defaults. This function does not search a grid.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    cost = round_trip_cost(commission, slippage)
    events, state = build_event_table(
        y, x, entry_z=entry_z, warmup=warmup, commission=commission, slippage=slippage,
    )
    oof = _meta_oof(events, threshold=threshold)
    events = events.copy()
    events["p_success"] = oof.to_numpy()
    scored = events.dropna(subset=["p_success"])
    if len(scored) < 10:
        raise ValueError("Purga/embargo deixou poucas previsões fora da amostra.")

    primary = _trade_stats(scored["ret_net"].to_numpy(), scored["bin"].to_numpy())
    accepted = scored["p_success"].to_numpy() >= threshold
    filtered = _trade_stats(
        scored["ret_net"].to_numpy()[accepted],
        scored["bin"].to_numpy()[accepted],
    )
    size = np.zeros(len(scored))
    p = scored["p_success"].to_numpy()
    size[accepted] = np.clip((p[accepted] - threshold) / max(1.0 - threshold, 1e-9), 0.0, 1.0)

    dy = np.diff(y) / y[:-1]
    dx = np.diff(x) / x[:-1]
    pair_ret = np.zeros(len(y))
    pair_ret[1:] = np.where(np.isfinite(dy - state["beta"][:-1] * dx), dy - state["beta"][:-1] * dx, 0.0)
    primary_size = np.ones(len(scored))
    bar_primary = _occupy_bar_returns(len(y), scored, pair_ret, primary_size, cost)
    bar_filtered = _occupy_bar_returns(len(y), scored, pair_ret, size, cost)

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
    }
    registry.register(
        family_id,
        {**params_common, "variant": "primary_triple_barrier"},
        returns=bar_primary[warmup:].tolist(),
        costs_included=True,
        notes="Todas as entradas Gatev/EG, barreiras triplas, custo nas duas pernas.",
    )
    meta_trial = registry.register(
        family_id,
        {**params_common, "variant": "meta_filtered", "threshold": threshold},
        returns=bar_filtered[warmup:].tolist(),
        costs_included=True,
        notes="Mesmo primário; só opera se P(sucesso) OOF ≥ limiar; tamanho ∝ probabilidade.",
    )
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
    try:
        joh = johansen(np.column_stack([y, x]), k_ar=2)
        johansen_rank = joh["rank"]
    except ValueError:
        johansen_rank = None

    def _round_stats(s: dict[str, float]) -> dict[str, float]:
        out = dict(s)
        out["n_trades"] = int(s["n_trades"])
        if s["n_trades"]:
            out["hit_rate"] = round(float(s["hit_rate"]), 6)
            out["net_per_trade"] = round(float(s["net_per_trade"]), 8)
            out["total_net"] = round(float(s["total_net"]), 8)
        return out

    return {
        "family_id": family_id,
        "n_bars": int(len(y)),
        "n_events": int(len(events)),
        "n_oos_scored": int(len(scored)),
        "n_trials_registered": int(n_trials),
        "entry_z": entry_z,
        "threshold": threshold,
        "round_trip_cost": cost,
        "engle_granger": {
            "cointegrated": eg["cointegrated"],
            "beta": eg["beta"],
            "adf_tstat": eg["adf_tstat"],
            "half_life_days": eg["half_life_days"],
        },
        "johansen_rank": johansen_rank,
        "primary": _round_stats(primary),
        "filtered": _round_stats(filtered),
        "filter_improves_hit_or_net": filter_helps,
        "hit_rate_delta": None if not np.isfinite(hit_delta) else round(float(hit_delta), 6),
        "net_per_trade_delta": None if not np.isfinite(pnl_delta) else round(float(pnl_delta), 8),
        "gate": verdict.to_dict(),
        "eligible_for_live_trading": False,
        "out_of_sample": True,
        "math": (
            "Primário: z expanding do resíduo y−(α_t+β_t x), entrada |z|>entry_z, lado = −sign(z). "
            "Rótulo: primeira barreira (alvo / stop / prazo) no PnL do book, líquido de 4×(taxa+spread). "
            "Meta: RF com PurgedKFold + embargo; P(bin=1) OOF. "
            "Gate: DSR de Bailey & López de Prado ≥ 0,95 com N registrado, assimetria, curtose e MinTRL."
        ),
        "what_broke": list(_WHAT_BROKE),
    }


def render_report_md(result: dict[str, Any]) -> str:
    p, f = result["primary"], result["filtered"]
    g: dict[str, Any] = result["gate"]
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
do book unitário, **líquido** de taxa e spread nas duas pernas (ida e volta = {result["round_trip_cost"]:.4f}).
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

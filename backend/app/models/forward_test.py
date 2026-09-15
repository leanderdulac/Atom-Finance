"""
Sequential forward test.

A backtest is a research tool. Evidence is a frozen spec whose signal at
close t uses only prices[0:t+1] and is scored by the next return — a price
that did not exist when the decision was made. Repeating that every bar
builds a genuine out-of-sample series. Mining indicators on the same
history is the technical-analysis version of the winner's curse.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.models.winners_curse import annualized_sharpe, deflated_sharpe

_WHAT_BROKE = [
    "Synthetic GBM is a clock, not a market. Real TA still needs point-in-time data.",
    "SMA(fast, slow) is one family. A broader search inflates the mined print further.",
    "Walk-forward still searches; it is more honest than a full-sample max, not a proof.",
    "One-bar delay is the research-policy execution lag, not a fill model.",
    "This does not authorize live trading. eligible_for_live_trading stays false.",
]

FAST_GRID = (5, 8, 10, 13, 21)
SLOW_GRID = (30, 40, 50, 63, 80)
CANDIDATES = tuple((f, s) for f in FAST_GRID for s in SLOW_GRID if f < s)


def demo_prices(n: int = 756, mu: float = 0.0, vol: float = 0.01, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, vol, n - 1)
    return 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + r]))


def rolling_mean(prices: np.ndarray, window: int) -> np.ndarray:
    if window < 2:
        raise ValueError("SMA window must be ≥2")
    x = np.asarray(prices, dtype=np.float64)
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[window - 1 :] = (c[window:] - c[:-window]) / window
    return out


def sma_position(prices: np.ndarray, fast: int, slow: int) -> np.ndarray:
    if not 2 <= fast < slow:
        raise ValueError("Need 2 ≤ fast < slow")
    f = rolling_mean(prices, fast)
    s = rolling_mean(prices, slow)
    pos = np.zeros(len(prices), dtype=np.float64)
    valid = np.isfinite(f) & np.isfinite(s)
    pos[valid & (f > s)] = 1.0
    pos[valid & (f < s)] = -1.0
    return pos


def sequential_pnl(
    prices: np.ndarray,
    pos_at_close: np.ndarray,
    commission: float = 0.001,
    slippage: float = 0.0005,
    delay: bool = True,
) -> dict[str, Any]:
    """Score a causal position series.

    delay=True  — signal at close t multiplies r[t→t+1] (unknown at decision).
    delay=False — signal at close t+1 multiplies r[t→t+1] (same-bar leak).
    """
    p = np.asarray(prices, dtype=np.float64)
    pos = np.asarray(pos_at_close, dtype=np.float64)
    if len(p) != len(pos) or len(p) < 10:
        raise ValueError("prices and positions must align and have length ≥10")
    r = np.diff(p) / p[:-1]
    sig = pos[:-1] if delay else pos[1:]
    turnover = np.abs(np.diff(np.concatenate([[0.0], sig])))
    net = sig * r - (commission + slippage) * turnover
    active = sig != 0
    hit = float(np.mean((sig[active] * r[active]) > 0)) if np.any(active) else 0.0
    if np.std(sig) < 1e-12 or np.std(r) < 1e-12:
        ic = 0.0
    else:
        ic = float(np.corrcoef(sig, r)[0, 1])
    equity = np.concatenate([[1.0], np.cumprod(1.0 + net)])
    return {
        "net": net,
        "signal": sig,
        "sharpe": round(annualized_sharpe(net) if len(net) >= 3 else 0.0, 4),
        "hit_rate": round(hit, 4),
        "ic": round(ic, 4),
        "turnover": round(float(np.mean(turnover)), 4),
        "n_active": int(np.sum(active)),
        "equity": equity,
    }


def _sharpe_only(prices: np.ndarray, fast: int, slow: int, commission: float, slippage: float, delay: bool) -> float:
    pos = sma_position(prices, fast, slow)
    return float(sequential_pnl(prices, pos, commission, slippage, delay=delay)["sharpe"])


def walk_forward_positions(
    prices: np.ndarray,
    commission: float,
    slippage: float,
    min_train: int = 180,
    refit_every: int = 21,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    n = len(prices)
    if n < min_train + 40:
        raise ValueError("Need a longer sample for walk-forward")
    pos = np.zeros(n, dtype=np.float64)
    log: list[dict[str, Any]] = []
    t = min_train
    while t < n:
        train = prices[:t]
        ranked = [
            (_sharpe_only(train, f, s, commission, slippage, delay=True), f, s)
            for f, s in CANDIDATES
        ]
        train_sr, fast, slow = max(ranked)
        stop = min(t + refit_every, n)
        frozen = sma_position(prices, fast, slow)
        pos[t:stop] = frozen[t:stop]
        log.append({
            "from": t, "to": stop, "fast": int(fast), "slow": int(slow),
            "train_sharpe": round(float(train_sr), 4),
        })
        t = stop
    return pos, log


def _downsample(eq: np.ndarray, cap: int = 180) -> list[float]:
    step = max(1, len(eq) // cap)
    out = [round(float(v), 4) for v in eq[::step]]
    last = round(float(eq[-1]), 4)
    if out[-1] != last:
        out.append(last)
    return out


def evaluate(
    prices: list[float] | None = None,
    locked_fast: int = 10,
    locked_slow: int = 40,
    commission: float = 0.001,
    slippage: float = 0.0005,
    seed: int = 11,
    n: int = 756,
) -> dict[str, Any]:
    if prices is None:
        p = demo_prices(n=n, mu=0.0, vol=0.01, seed=seed)
        source = "synthetic_gbm_mu0"
    else:
        p = np.asarray(prices, dtype=np.float64)
        if not 250 <= len(p) <= 3000:
            raise ValueError("Need 250–3000 prices")
        if np.any(p <= 0) or not np.all(np.isfinite(p)):
            raise ValueError("Prices must be positive and finite")
        source = "caller"
    if not 2 <= locked_fast < locked_slow <= 200:
        raise ValueError("Need 2 ≤ locked_fast < locked_slow ≤ 200")

    locked_pos = sma_position(p, locked_fast, locked_slow)
    locked = sequential_pnl(p, locked_pos, commission, slippage, delay=True)
    leak = sequential_pnl(p, locked_pos, commission, slippage, delay=False)

    delayed_grid = [
        (float(_sharpe_only(p, f, s, commission, slippage, True)), f, s) for f, s in CANDIDATES
    ]
    leaked_grid = [
        (float(_sharpe_only(p, f, s, commission, slippage, False)), f, s) for f, s in CANDIDATES
    ]
    mined_d = max(delayed_grid)
    mined_l = max(leaked_grid)
    mined_pos = sma_position(p, mined_d[1], mined_d[2])
    mined = sequential_pnl(p, mined_pos, commission, slippage, delay=True)
    mined_leak = sequential_pnl(p, sma_position(p, mined_l[1], mined_l[2]), commission, slippage, delay=False)

    wf_pos, wf_log = walk_forward_positions(p, commission, slippage)
    wf = sequential_pnl(p, wf_pos, commission, slippage, delay=True)

    r_bh = np.diff(p) / p[:-1]
    dsr = deflated_sharpe(mined_d[0], n_trials=len(CANDIDATES), n_obs=max(len(p) - 1, 30))

    last = int(len(p) - 1)
    fast_now = float(rolling_mean(p, locked_fast)[last])
    slow_now = float(rolling_mean(p, locked_slow)[last])
    today = int(locked_pos[last])
    n_obs = int(len(locked["net"]))

    return {
        "source": source,
        "n_prices": int(len(p)),
        "n_candidates": len(CANDIDATES),
        "locked": {
            "fast": locked_fast,
            "slow": locked_slow,
            "sharpe": locked["sharpe"],
            "hit_rate": locked["hit_rate"],
            "ic": locked["ic"],
            "n_active": locked["n_active"],
            "same_bar_sharpe": leak["sharpe"],
        },
        "mined_delayed": {
            "fast": mined_d[1],
            "slow": mined_d[2],
            "sharpe": mined["sharpe"],
            "hit_rate": mined["hit_rate"],
            "ic": mined["ic"],
        },
        "mined_same_bar": {
            "fast": mined_l[1],
            "slow": mined_l[2],
            "sharpe": mined_leak["sharpe"],
            "hit_rate": mined_leak["hit_rate"],
            "ic": mined_leak["ic"],
        },
        "walk_forward": {
            "sharpe": wf["sharpe"],
            "hit_rate": wf["hit_rate"],
            "ic": wf["ic"],
            "n_refits": len(wf_log),
            "refits": wf_log[-12:],
        },
        "buy_hold": {"sharpe": round(annualized_sharpe(r_bh), 4)},
        "dsr_mined": dsr,
        "today_signal": {
            "bar": last,
            "price": round(float(p[last]), 4),
            "fast_sma": None if not np.isfinite(fast_now) else round(fast_now, 4),
            "slow_sma": None if not np.isfinite(slow_now) else round(slow_now, 4),
            "position": today,
            "side": {1: "long", -1: "short", 0: "flat"}[today],
            "note": (
                "Sinal gerado no último fechamento com a spec travada. "
                "O retorno que o avalia é o próximo preço — ainda não conhecido neste arquivo."
            ),
        },
        "equity": {
            "locked": _downsample(locked["equity"]),
            "mined_delayed": _downsample(mined["equity"]),
            "walk_forward": _downsample(wf["equity"]),
            "buy_hold": _downsample(np.concatenate([[1.0], np.cumprod(1.0 + r_bh)])),
        },
        "n_obs": n_obs,
        "eligible_for_live_trading": False,
        "math": (
            "Decisão no fechamento t usa SMA(fast,slow) só com preços[0:t]. "
            "O PnL é r[t→t+1] · posição_t − (comissão+slippage)·|Δposição|. "
            f"A mineração escolhe o máximo de {len(CANDIDATES)} pares no mesmo histórico. "
            "Walk-forward reescolhe o par em dados[:t] e congela até o próximo refit. "
            "O relógio honesto é a série sequencial da spec travada."
        ),
        "what_broke": list(_WHAT_BROKE),
    }

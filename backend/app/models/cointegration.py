"""
Engle & Granger (1987) residual-based cointegration and a lagged pairs backtest.

The cointegration test is OLS of y on x plus an ADF(1) of the residual against
MacKinnon (2010) bivariate critical values. The trading hedge defaults to a
Kalman beta: δ and the observation variance are chosen on an in-sample prefix
and then frozen. Expanding OLS remains available. The loop trades an expanding
z-score after a warm-up, signal at t and fill at t+1. Still a toy: not a
production execution model, and ``eligible_for_live_trading`` stays false.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np

from app.models.kalman import kalman_regression, select_kalman_hyperparams

HedgeMethod = Literal["kalman", "expanding_ols"]

# MacKinnon (2010) residual-based cointegration tau critical values,
# constant, no trend, N=1 extra regressor (bivariate), T=∞.
_MACKINNON = {0.01: -3.90, 0.05: -3.34, 0.10: -3.04}


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, np.ndarray]:
    n = len(y)
    a = np.column_stack([np.ones(n), x])
    coef, _, _, _ = np.linalg.lstsq(a, y, rcond=None)
    alpha, beta = float(coef[0]), float(coef[1])
    residual = y - (alpha + beta * x)
    return alpha, beta, residual


def _adf_tstat(residual: np.ndarray, lags: int = 1) -> float:
    """ADF(1) t-statistic, constant, no trend.

    The intercept column is load-bearing: callers compare this statistic
    against constant-included critical values (MacKinnon residual tables in
    engle_granger, Dickey-Fuller -2.86 in mean_reversion/target_choice).
    """
    e = np.asarray(residual, dtype=np.float64)
    de = np.diff(e)
    y = de[lags:]
    lagged = e[lags:-1]
    cols = [np.ones_like(y), lagged]
    for lag in range(1, lags + 1):
        cols.append(de[lags - lag : len(de) - lag])
    x = np.column_stack(cols)
    coef, residuals, _, _ = np.linalg.lstsq(x, y, rcond=None)
    if residuals.size:
        sse = float(residuals[0])
    else:
        sse = float(np.sum((y - x @ coef) ** 2))
    df = max(len(y) - x.shape[1], 1)
    sigma2 = sse / df
    xtx_inv = np.linalg.pinv(x.T @ x)
    se_gamma = float(np.sqrt(max(sigma2 * xtx_inv[1, 1], 1e-18)))
    return float(coef[1] / se_gamma)


def _half_life(residual: np.ndarray) -> float:
    e = residual[:-1]
    de = np.diff(residual)
    if np.std(e) < 1e-18:
        return float("inf")
    theta = float(np.dot(e, de) / np.dot(e, e))
    phi = 1.0 + theta
    if phi <= 0 or phi >= 1:
        return float("inf")
    return float(-np.log(2.0) / np.log(phi))


def engle_granger(y: np.ndarray, x: np.ndarray, significance: float = 0.05) -> dict:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if y.shape != x.shape or len(y) < 60:
        raise ValueError("Need two aligned series with at least 60 observations")
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(x)):
        raise ValueError("Series must be finite")

    alpha, beta, residual = _ols(y, x)
    tstat = _adf_tstat(residual, lags=1)
    crit = _MACKINNON.get(significance, _MACKINNON[0.05])
    cointegrated = bool(tstat < crit)
    rho = float(np.corrcoef(y, x)[0, 1])
    return {
        "alpha": round(alpha, 8),
        "beta": round(beta, 8),
        "adf_tstat": round(tstat, 4),
        "critical_value": crit,
        "significance": significance,
        "cointegrated": cointegrated,
        "half_life_days": None if not np.isfinite(_half_life(residual)) else round(_half_life(residual), 2),
        "residual_std": round(float(np.std(residual, ddof=1)), 6),
        "correlation": round(rho, 4),
        "n": int(len(y)),
        "math": (
            "y_t = α + β x_t + e_t. Reject a unit root in e_t (Engle–Granger) "
            "if the ADF t-stat is below the MacKinnon critical value."
        ),
        "what_broke": [
            "The Engle–Granger beta is full-sample OLS. The paper hedge is a separate Kalman (or expanding OLS) path.",
            "ADF has low power in short samples and is sensitive to lag choice.",
            "Bivariate EG ignores a possible third common factor — run johansen() on the panel.",
            "Cointegration can vanish after a corporate action the price series did not adjust.",
        ],
    }


def _expanding_hedge(
    y: np.ndarray, x: np.ndarray, min_est: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Causal (expanding) OLS hedge ratio: at bar t, (α_t, β_t) use only data[:t+1].

    Returns (alpha, beta, residual) arrays over y, x. The residual at t is
    y_t − (α_t + β_t x_t) with coefficients that never consume the t+1…T
    observations, so a signal built on it does not look through the future.
    """
    n = len(y)
    res = np.full(n, np.nan)
    beta = np.zeros(n)
    alpha = np.zeros(n)
    sx = sxx = sxy = sy = 0.0
    for t in range(n):
        xt, yt = float(x[t]), float(y[t])
        sx += xt
        sxx += xt * xt
        sxy += xt * yt
        sy += yt
        k = t + 1
        if k < min_est:
            continue
        m = np.array([[k, sx], [sx, sxx]])
        c = np.array([sy, sxy])
        ab = np.linalg.pinv(m) @ c  # [α_t, β_t] — causal, normal-equations OLS
        alpha[t], beta[t] = ab
        res[t] = yt - (ab[0] + ab[1] * xt)
    return alpha, beta, res


def dynamic_hedge(
    y: np.ndarray,
    x: np.ndarray,
    *,
    method: HedgeMethod = "kalman",
    min_est: int = 20,
    delta: float | None = None,
    obs_var: float | None = None,
    insample_end: int | None = None,
) -> dict[str, Any]:
    """Causal hedge path.

    ``expanding_ols`` is OLS of ``y[:t+1]`` on ``x[:t+1]``. ``kalman`` publishes
    the posterior β after bar t and the innovation against the prior. When
    ``delta`` and ``obs_var`` are omitted they are chosen by innovation
    likelihood on ``y[:insample_end]`` only (default: the first half, at least
    60 bars) and frozen for the rest of the series.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if y.shape != x.shape or y.ndim != 1:
        raise ValueError("y and x must be aligned 1-D series")
    if method == "expanding_ols":
        alpha, beta, spread = _expanding_hedge(y, x, min_est)
        return {
            "method": method,
            "alpha": alpha,
            "beta": beta,
            "spread": spread,
            "beta_prior": None,
            "zscore": None,
            "delta": None,
            "obs_var": None,
            "insample_end": None,
            "hedge": "expanding_ols_frozen_at_entry",
        }
    if method != "kalman":
        raise ValueError("hedge must be 'kalman' or 'expanding_ols'")
    n = len(y)
    if (delta is None) ^ (obs_var is None):
        raise ValueError("pass both delta and obs_var, or neither")
    cut = insample_end
    if delta is None:
        if cut is None:
            cut = max(60, n // 2)
        if cut < 40 or cut > n:
            raise ValueError("insample_end must cover at least 40 bars and not exceed the sample")
        chosen = select_kalman_hyperparams(y[:cut], x[:cut])
        delta = chosen.delta
        obs_var = chosen.obs_var
    elif cut is None:
        cut = n
    if cut is None or delta is None or obs_var is None:
        raise RuntimeError("Kalman hedge is missing hyperparameters")
    fit = kalman_regression(y, x, delta=float(delta), obs_var=float(obs_var))
    return {
        "method": "kalman",
        "alpha": fit.alpha,
        "beta": fit.beta,
        "spread": fit.spread,
        "beta_prior": fit.beta_prior,
        "zscore": fit.zscore,
        "delta": float(delta),
        "obs_var": float(obs_var),
        "insample_end": int(cut),
        "hedge": "kalman_posterior_frozen_at_entry",
    }


def frozen_spread_return(y0: float, x0: float, y1: float, x1: float, beta0: float) -> float:
    """One-bar return of +1 y vs β0 x on the entry gross notional.

    (Δy − β0 Δx) / (|y0| + |β0||x0|). This is the book, not r_y − β r_x.
    """
    g0 = abs(float(y0)) + abs(float(beta0)) * abs(float(x0))
    if g0 < 1e-12 or not np.isfinite(beta0):
        return 0.0
    return (float(y1) - float(y0) - float(beta0) * (float(x1) - float(x0))) / g0


def pairs_backtest(
    y: np.ndarray,
    x: np.ndarray,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    warmup: int = 60,
    commission: float = 0.0005,
    slippage: float = 0.0002,
    initial_capital: float = 100_000.0,
    *,
    entry_cost_k: float = 2.0,
    max_spread_bps: float = 25.0,
    min_volume: float = 0.0,
    volume: np.ndarray | None = None,
    hedge: HedgeMethod = "kalman",
    kalman_delta: float | None = None,
    kalman_obs_var: float | None = None,
    insample_end: int | None = None,
) -> dict:
    """
    Dollar-neutral pairs: long the cheap leg / short the rich leg when |z| > entry,
    flatten when |z| < exit. Signal at t, fill at t+1. Costs on both legs.

    PnL is the frozen book on gross two-leg notional:
    r = (Δy − β0 Δx) / (|y| + |β0||x|), with β frozen at entry. Applying a
    share-count OLS β to percent returns (r_y − β r_x) inflates ETH/SOL-like books.

    The hedge that *defines the z-score* is causal. The default is a Kalman
    posterior β and its innovation, with δ and obs_var chosen on the in-sample
    prefix only. ``hedge='expanding_ols'`` keeps OLS on data[:t+1]. Either way
    β is frozen at entry. ``engle_granger`` is still the full-sample hypothesis
    test and is reported as a diagnostic.
    """
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    stats = engle_granger(y, x)
    try:
        joh = johansen(np.column_stack([y, x]), k_ar=2)
        stats["johansen_rank"] = joh["rank"]
        stats["johansen_trace"] = joh["trace"]
    except ValueError:
        stats["johansen_rank"] = None

    n = len(y)
    min_est = 20
    warmup = max(min_est, min(warmup, n // 3))
    path = dynamic_hedge(
        y, x, method=hedge, min_est=min_est, delta=kalman_delta, obs_var=kalman_obs_var, insample_end=insample_end,
    )
    beta = path["beta"]
    spread = path["spread"]
    spread_window: list[float] = []  # causal residuals accumulated for the expanding z

    from app.models.trading_costs import check_liquidity, four_leg_fraction, pairs_entry_allowed

    position = 0  # +1 long spread (long y, short β x)
    equity = initial_capital
    gross_equity = initial_capital
    curve = [equity]
    trades = 0
    costs_paid = 0.0
    fee_paid = 0.0
    half_paid = 0.0
    wins = 0
    closed = 0
    beta0 = 0.0
    # commission = taker fee; slippage = half-spread estimate (no book on this clock).
    fee_bps = commission * 10_000.0
    half_bps = slippage * 10_000.0
    one_way = four_leg_fraction(fee_bps, half_bps, 0.0) / 2.0  # open both legs, fraction of gross
    round_trip = four_leg_fraction(fee_bps, half_bps, 0.0)
    skipped: list[dict] = []
    estimated_spread_bps = 2.0 * half_bps

    for t in range(warmup, n - 1):
        st = spread[t]
        if np.isfinite(st):
            spread_window.append(st)
        w = np.asarray(spread_window)
        if len(w) < 2:
            continue
        mu = float(np.mean(w))
        sd = float(np.std(w, ddof=1)) if len(w) > 1 else 0.0
        z = 0.0 if sd < 1e-12 else (st - mu) / sd
        target = position
        if position == 0:
            if z > entry_z:
                target = -1
            elif z < -entry_z:
                target = 1
        elif abs(z) < exit_z:
            target = 0

        fill = t + 1
        b_sig = beta[t] if np.isfinite(beta[t]) else float(stats["beta"])
        if position == 0 and target != 0:
            y_t = float(y[t])
            x_t = float(x[t])
            gross_n = abs(y_t) + abs(float(b_sig)) * abs(x_t)
            expected = (
                max(abs(z) - exit_z, 0.0) * (sd / gross_n) if gross_n > 0 else float("nan")
            )
            vol_t = None if volume is None or t >= len(volume) else float(volume[t])
            liq = check_liquidity(
                spread_bps_value=estimated_spread_bps,
                volume=vol_t,
                max_spread_bps=max_spread_bps,
                min_volume=min_volume,
            )
            reason = None if liq.ok else liq.reason
            if reason is None and not pairs_entry_allowed(expected, fee_bps, half_bps, 0.0, entry_cost_k):
                reason = "expected_gain"
            if reason is not None:
                skipped.append({
                    "t": int(t),
                    "reason": reason,
                    "expected_gain": None if not np.isfinite(expected) else round(float(expected), 8),
                    "round_trip_cost": round_trip,
                    "k": entry_cost_k,
                    "legs": 4,
                    "spread_bps": liq.spread_bps,
                })
                target = 0
        if target != position:
            turnover = abs(target - position)
            cost = turnover * one_way
            drag = cost * equity
            costs_paid += drag
            rate_sum = fee_bps + half_bps
            fee_paid += drag * (fee_bps / rate_sum) if rate_sum > 0 else 0.0
            half_paid += drag * (half_bps / rate_sum) if rate_sum > 0 else 0.0
            equity *= 1.0 - cost
            if position != 0:
                closed += 1
            trades += 1
            if target != 0:
                beta0 = float(b_sig)
            position = target
        if position != 0:
            pnl = position * frozen_spread_return(
                float(y[fill - 1]), float(x[fill - 1]),
                float(y[fill]), float(x[fill]),
                beta0,
            )
            equity *= 1.0 + pnl
            gross_equity *= 1.0 + pnl
        curve.append(equity)

    rets = np.diff(curve) / np.array(curve[:-1])
    if closed:
        wins = int(np.sum(rets > 0))
    total = curve[-1] / initial_capital - 1
    vol = float(np.std(rets) * np.sqrt(252)) if len(rets) else 0.0
    sharpe = float(np.mean(rets) / max(np.std(rets), 1e-12) * np.sqrt(252)) if len(rets) else 0.0
    peak = np.maximum.accumulate(curve)
    mdd = float(np.min(np.array(curve) / peak - 1.0))
    return {
        **stats,
        "entry_z": entry_z,
        "exit_z": exit_z,
        "warmup": warmup,
        "trades": trades,
        "costs_paid": round(float(costs_paid), 4),
        "fee": round(float(fee_paid), 4),
        "half_spread": round(float(half_paid), 4),
        "slippage": 0.0,
        "cost_components": {
            "fee_bps": fee_bps,
            "half_spread_bps": half_bps,
            "slippage_bps": 0.0,
            "half_spread_source": "estimate",
            "slippage_source": "estimate",
            "flagged_estimate": True,
            "four_leg_fraction": round_trip,
            "entry_cost_k": entry_cost_k,
            "legs": 4,
        },
        "gross_return_pct": round((gross_equity / initial_capital - 1.0) * 100, 4),
        "n_skipped": len(skipped),
        "skipped_by_reason": {
            reason: sum(1 for row in skipped if row.get("reason") == reason)
            for reason in ("expected_gain", "spread", "volume", "volume_unavailable")
        },
        "skipped_signals": skipped[:40],
        "total_return_pct": round(total * 100, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(mdd * 100, 4),
        "annualized_vol_pct": round(vol * 100, 4),
        "final_equity": round(float(curve[-1]), 2),
        "win_day_pct": round(100.0 * wins / max(len(rets), 1), 2),
        "costs_drag_note": (
            "Fee + half-spread estimate (no bid/ask on this clock, flagged) of gross "
            "two-leg notional at each unit of turnover. Four legs (open and close, "
            "both names) = 2×(fee+half-spread). Entry only if expected reversion "
            "covers k times that round trip. β frozen at entry."
        ),
        "pnl_unit": "gross_two_leg_notional",
        "hedge": path["hedge"],
        "kalman_delta": path["delta"],
        "kalman_obs_var": path["obs_var"],
        "kalman_insample_end": path["insample_end"],
        "out_of_sample": False,
        "eligible_for_live_trading": False,
        "equity_curve_sample": [round(v, 2) for v in curve[:: max(1, len(curve) // 80)]],
        "what_broke": stats["what_broke"] + [
            "β is frozen at entry. Kalman δ and obs_var, when estimated, use only the in-sample prefix.",
            "β shares of x vs 1 share of y ignores lot size, borrow, and dividend timing.",
            "PnL is (Δy − β0 Δx)/(|y|+|β0||x|); r_y − β r_x with share-count β inflates the book.",
            "No capacity, no halt on residual-variance jumps, no corporate-action calendar.",
        ],
    }


# MacKinnon–Haug–Michelis (1999) asymptotic 5% trace critical values,
# constant in the VECM, no deterministic trend. Indexed by (n − r).
_JOHANSEN_TRACE_5 = {1: 3.8415, 2: 15.4943, 3: 29.7971, 4: 47.8545}


def johansen(levels: np.ndarray, k_ar: int = 2) -> dict:
    """
    Johansen trace test on a levels panel (T × n).

    VECM: Δy_t = Π y_{t-1} + Σ Γ_i Δy_{t-i} + μ + ε_t,  Π = αβ′.
    Rank(Π) is the number of cointegrating relations. Bivariate EG is the
    special case n=2 estimated by OLS; Johansen does not pick a dependent
    variable and will reject a third common factor that EG would miss.
    """
    Y = np.asarray(levels, dtype=np.float64)
    if Y.ndim != 2:
        raise ValueError("levels must be a 2-D array of shape (T, n)")
    T_full, n = Y.shape
    if n < 2 or n > 4:
        raise ValueError("Johansen here supports 2 to 4 series")
    if T_full < 80:
        raise ValueError("Need at least 80 observations for Johansen")
    if not np.all(np.isfinite(Y)):
        raise ValueError("levels must be finite")

    p = max(int(k_ar), 1)
    dY = np.diff(Y, axis=0)
    lags = p - 1
    start = lags
    Z0 = dY[start:]
    Z1 = Y[start:-1]
    N = Z0.shape[0]
    if lags > 0:
        parts = [np.ones((N, 1))]
        for lag in range(1, lags + 1):
            parts.append(dY[start - lag : start - lag + N])
        Z2 = np.hstack(parts)
    else:
        Z2 = np.ones((N, 1))

    def _resid(Z: np.ndarray) -> np.ndarray:
        coef, _, _, _ = np.linalg.lstsq(Z2, Z, rcond=None)
        return Z - Z2 @ coef

    R0 = _resid(Z0)
    R1 = _resid(Z1)
    S00 = (R0.T @ R0) / N
    S11 = (R1.T @ R1) / N
    S01 = (R0.T @ R1) / N
    A = np.linalg.pinv(S11) @ (S01.T @ np.linalg.pinv(S00) @ S01)
    eigvals, eigvecs = np.linalg.eig(A)
    eigvals = np.clip(np.real(eigvals), 0.0, 0.999999)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = np.real(eigvecs[:, order])

    trace = []
    crits = []
    for r in range(n):
        stat = float(-N * np.sum(np.log(1.0 - eigvals[r:])))
        crit = _JOHANSEN_TRACE_5[n - r]
        trace.append(round(stat, 4))
        crits.append(crit)

    rank = 0
    for r, (stat, crit) in enumerate(zip(trace, crits, strict=True)):
        if stat > crit:
            rank = r + 1
        else:
            break

    vec = eigvecs[:, 0]
    if abs(vec[0]) > 1e-12:
        vec = vec / vec[0]
    return {
        "n_series": n,
        "n_obs": int(N),
        "k_ar": p,
        "eigenvalues": [round(float(v), 6) for v in eigvals],
        "trace": trace,
        "trace_crit_5pct": crits,
        "rank": int(rank),
        "cointegrated": bool(rank >= 1),
        "first_coint_vector": [round(float(v), 6) for v in vec],
        "math": (
            "Trace(r) = −T Σ_{i=r+1}^n ln(1−λ_i). Reject r=0 at 5% if trace exceeds "
            "MacKinnon–Haug–Michelis (1999). The first eigenvector is β̂, normalised on series 0."
        ),
        "what_broke": [
            "Asymptotic critical values, not a small-sample Bartlett correction.",
            "Lag p is not selected by information criteria; misspecified p distorts rank.",
            "A constant in the VECM is assumed; a linear trend needs a different table.",
            "Rank 1 is not a tradable spread: you still need a hedge, costs, and a halt rule.",
        ],
    }


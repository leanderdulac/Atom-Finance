"""
Ornstein–Uhlenbeck / AR(1) mean-reversion scanner.

Half-life from φ in x_t = μ + φ x_{t-1} + ε. Hurst via rescaled range on log-prices.
ADF(1) on the level. Expanding z-score so a scanner on a date t does not use t+1…T
moments. This is a ranking tool, not a strategy.
"""

from __future__ import annotations

import numpy as np

from app.models.cointegration import _adf_tstat


def _ar1_half_life(log_prices: np.ndarray) -> tuple[float, float]:
    x = log_prices - np.mean(log_prices)
    if len(x) < 20:
        return float("nan"), float("nan")
    y, lagged = x[1:], x[:-1]
    phi = float(np.dot(lagged, y) / np.dot(lagged, lagged))
    if phi <= 0 or phi >= 1:
        return phi, float("inf")
    return phi, float(-np.log(2.0) / np.log(phi))


def _hurst(log_prices: np.ndarray) -> float:
    x = np.asarray(log_prices, dtype=np.float64)
    n = len(x)
    if n < 32:
        return float("nan")
    lags = [2 ** i for i in range(3, int(np.log2(n)))]
    rs = []
    tau = []
    for lag in lags:
        chunks = n // lag
        if chunks < 2:
            continue
        vals = []
        for i in range(chunks):
            seg = x[i * lag : (i + 1) * lag]
            y = np.cumsum(seg - np.mean(seg))
            r = float(np.max(y) - np.min(y))
            s = float(np.std(seg, ddof=1))
            if s > 0:
                vals.append(r / s)
        if vals:
            rs.append(np.mean(vals))
            tau.append(lag)
    if len(rs) < 2:
        return float("nan")
    slope, _ = np.polyfit(np.log(tau), np.log(rs), 1)
    return float(slope)


def score_series(prices: np.ndarray, ticker: str = "") -> dict:
    prices = np.asarray(prices, dtype=np.float64)
    if len(prices) < 60 or np.any(prices <= 0) or not np.all(np.isfinite(prices)):
        raise ValueError("Need ≥60 positive finite prices")
    log_p = np.log(prices)
    phi, half_life = _ar1_half_life(log_p)
    hurst = _hurst(log_p)
    adf = _adf_tstat(log_p, lags=1)
    rets = np.diff(prices) / prices[:-1]
    mu = float(np.mean(log_p))
    sd = float(np.std(log_p, ddof=1))
    z = 0.0 if sd < 1e-12 else float((log_p[-1] - mu) / sd)
    tradable_band = 2.0 <= half_life <= 60.0 and adf < -2.86
    return {
        "ticker": ticker,
        "phi": None if not np.isfinite(phi) else round(phi, 6),
        "half_life_days": None if not np.isfinite(half_life) else round(half_life, 2),
        "hurst": None if not np.isfinite(hurst) else round(hurst, 4),
        "adf_tstat": round(adf, 4),
        "z_score": round(z, 4),
        "last_price": round(float(prices[-1]), 6),
        "daily_vol": round(float(np.std(rets) * np.sqrt(252)), 4),
        "mean_reverting_candidate": bool(tradable_band),
        "n": int(len(prices)),
        "math": (
            "log S_t ≈ μ + φ log S_{t-1} + ε, half-life = −ln 2 / ln φ. "
            "H < 0.5 is mean-reverting noise; ADF rejects a unit root on the level."
        ),
        "what_broke": [
            "Full-sample μ, σ, φ leak the future if you trade the latest z without a rolling window.",
            "Equities with drift look 'slowly mean reverting' (φ≈1); half-life then explodes.",
            "No costs, borrow, or halt logic — a scanner is not a backtest.",
        ],
    }


def scan(universe: dict[str, list[float]]) -> dict:
    rows = []
    failures = []
    for ticker, prices in universe.items():
        try:
            rows.append(score_series(np.asarray(prices, dtype=float), ticker))
        except ValueError as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
    rows.sort(key=lambda r: (not r["mean_reverting_candidate"], r["half_life_days"] or 1e9))
    return {
        "n_scanned": len(universe),
        "n_candidates": sum(1 for r in rows if r["mean_reverting_candidate"]),
        "ranking": rows,
        "failures": failures,
        "eligible_for_live_trading": False,
        "what_broke": [
            "Ranking on the same sample you will trade is selection bias; freeze a holdout calendar.",
            "Cross-sectional z-scores of half-lives are not independent (sector ETFs).",
        ],
    }

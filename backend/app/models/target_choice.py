"""
Price is a bad modelling target.

A R$500 move is 0.4% of BTC and a multi-bagger in PETR4. Prices are I(1);
returns are (approximately) I(0) and dimensionless. The research protocol
predicts the next return or the next regime, never the next print.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import Ridge

from app.models.cointegration import _adf_tstat

ADF_5PCT = -2.86  # Dickey–Fuller, constant, no trend (mean_reversion convention)
MOVE_BRL = 500.0
PETR4_LEVEL = 32.0
BTC_LEVEL = 120_000.0

_WHAT_BROKE = [
    "Identical log-returns by construction: the scale lesson is the point, not two real books.",
    "ADF(1) is a unit-root screen, not a proof of covariance stationarity.",
    "Regime here is trailing-vol vs expanding median — not the six-signal desk classifier.",
    "Walk-forward Ridge has no costs, no embargo, no claim of edge.",
    "This does not authorize live trading. eligible_for_live_trading stays false.",
]


def demo_pair(n: int = 504, seed: int = 5) -> dict[str, np.ndarray]:
    """One return path, two price scales, plus a planted high-vol episode."""
    if not 250 <= n <= 2000:
        raise ValueError("n must be in [250, 2000]")
    rng = np.random.default_rng(seed)
    r = np.empty(n - 1)
    for t in range(n - 1):
        sigma = 0.04 if 180 <= t < 260 else 0.012
        r[t] = rng.normal(0.0002, sigma)
    petr = PETR4_LEVEL * np.cumprod(np.concatenate([[1.0], 1.0 + r]))
    btc = BTC_LEVEL * np.cumprod(np.concatenate([[1.0], 1.0 + r]))
    return {"petr4": petr, "btc": btc, "r": r}


def _expanding_predict(X: np.ndarray, y: np.ndarray, min_train: int = 150, refit_every: int = 10) -> np.ndarray:
    pred = np.full(len(y), np.nan)
    model: Ridge | None = None
    for t in range(min_train, len(y)):
        if model is None or (t - min_train) % refit_every == 0:
            model = Ridge(alpha=1.0)
            model.fit(X[:t], y[:t])
        pred[t] = float(model.predict(X[t : t + 1])[0])
    return pred


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(yhat)
    if m.sum() < 20:
        return 0.0
    ss_res = float(np.sum((y[m] - yhat[m]) ** 2))
    ss_tot = float(np.sum((y[m] - np.mean(y[m])) ** 2))
    if ss_tot < 1e-18:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def _rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(yhat)
    if m.sum() < 20:
        return float("nan")
    return float(np.sqrt(np.mean((y[m] - yhat[m]) ** 2)))


def _directional(realized: np.ndarray, predicted: np.ndarray) -> float:
    m = np.isfinite(realized) & np.isfinite(predicted)
    if m.sum() < 20:
        return 0.5
    return float(np.mean(np.sign(realized[m]) == np.sign(predicted[m])))


def _pack(name: str, y: np.ndarray, pred: np.ndarray, *, level: np.ndarray | None = None, regime: bool = False) -> dict[str, Any]:
    if regime:
        m = np.isfinite(y) & np.isfinite(pred)
        acc = float(np.mean((pred[m] >= 0.5) == (y[m] >= 0.5))) if m.sum() else 0.5
    elif level is not None:
        acc = _directional(y - level, pred - level)
    else:
        acc = _directional(y, pred)
    return {
        "name": name,
        "r2": round(_r2(y, pred), 4),
        "rmse": round(_rmse(y, pred), 6),
        "accuracy": round(acc, 4),
        "n": int(np.sum(np.isfinite(pred))),
    }


def _price_xy(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(p, dtype=np.float64)
    t = np.arange(5, len(p) - 1)
    X = np.column_stack([p[t], p[t - 1], p[t - 5]])
    y = p[t + 1]
    return X, y


def _return_xy(r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r = np.asarray(r, dtype=np.float64)
    t = np.arange(20, len(r) - 1)
    X = np.column_stack([
        r[t],
        np.array([np.mean(r[i - 5 : i]) for i in t]),
        np.array([np.std(r[i - 20 : i], ddof=1) for i in t]),
    ])
    y = r[t + 1]
    return X, y


def _regime_xy(r: np.ndarray, horizon: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Label: next `horizon` days are high-vol vs expanding median of trailing vol."""
    r = np.asarray(r, dtype=np.float64)
    n = len(r)
    trail = np.array([np.std(r[max(0, i - 20) : i], ddof=1) if i >= 21 else np.nan for i in range(n)])
    fut = np.array([
        np.std(r[i : i + horizon], ddof=1) if i + horizon <= n else np.nan
        for i in range(n)
    ])
    t = np.arange(40, n - horizon)
    med = np.array([np.nanmedian(trail[21 : i + 1]) for i in t])
    y = (fut[t] > med).astype(np.float64)
    X = np.column_stack([
        trail[t],
        np.abs(r[t - 1]),
        np.array([np.mean(np.abs(r[i - 5 : i])) for i in t]),
    ])
    return X, y


def evaluate(n: int = 504, seed: int = 5) -> dict[str, Any]:
    pair = demo_pair(n=n, seed=seed)
    petr, btc, r = pair["petr4"], pair["btc"], pair["r"]
    xp, yp = _price_xy(petr)
    xb, yb = _price_xy(btc)
    xr, yr = _return_xy(r)
    xg, yg = _regime_xy(r)
    pred_p = _expanding_predict(xp, yp)
    pred_b = _expanding_predict(xb, yb)
    pred_r = _expanding_predict(xr, yr)
    pred_g = _expanding_predict(xg, yg)

    # Transfer: PETR4 price coefficients applied to BTC levels.
    min_train = 150
    model_p = Ridge(alpha=1.0).fit(xp[:min_train], yp[:min_train])
    transfer_price_rmse = _rmse(yb[min_train:], model_p.predict(xb[min_train:]))
    model_r = Ridge(alpha=1.0).fit(xr[:min_train], yr[:min_train])
    # Same return path: applying the return model to itself is the control.
    transfer_return_rmse = _rmse(yr[min_train:], model_r.predict(xr[min_train:]))

    adf_petr = float(_adf_tstat(petr, lags=1))
    adf_btc = float(_adf_tstat(btc, lags=1))
    adf_r = float(_adf_tstat(r, lags=1))
    step = max(1, n // 160)
    path = [
        {
            "t": i,
            "petr4_indexed": round(float(petr[i] / petr[0]), 4),
            "btc_indexed": round(float(btc[i] / btc[0]), 4),
        }
        for i in range(0, n, step)
    ]

    price_petr = _pack("price_petr4", yp, pred_p, level=xp[:, 0])
    price_btc = _pack("price_btc", yb, pred_b, level=xb[:, 0])
    ret = _pack("return", yr, pred_r)
    regime = _pack("regime_high_vol", yg, pred_g, regime=True)

    return {
        "n": n,
        "scale": {
            "move_brl": MOVE_BRL,
            "petr4_last": round(float(petr[-1]), 2),
            "btc_last": round(float(btc[-1]), 2),
            "petr4_move_pct": round(MOVE_BRL / float(petr[-1]) * 100.0, 2),
            "btc_move_pct": round(MOVE_BRL / float(btc[-1]) * 100.0, 4),
            "same_log_return_path": True,
        },
        "stationarity": {
            "adf_petr4_price": round(adf_petr, 3),
            "adf_btc_price": round(adf_btc, 3),
            "adf_returns": round(adf_r, 3),
            "critical_5pct": ADF_5PCT,
            "price_rejects_unit_root": bool(adf_petr < ADF_5PCT and adf_btc < ADF_5PCT),
            "returns_reject_unit_root": bool(adf_r < ADF_5PCT),
        },
        "targets": {
            "next_price_petr4": price_petr,
            "next_price_btc": price_btc,
            "next_return": ret,
            "next_vol_regime": regime,
        },
        "transfer": {
            "price_rmse_petr_model_on_btc": round(transfer_price_rmse, 2),
            "return_rmse_same_path": round(transfer_return_rmse, 6),
            "price_rmse_ratio_btc_over_petr": round(price_btc["rmse"] / max(price_petr["rmse"], 1e-12), 1),
        },
        "path": path,
        "eligible_for_live_trading": False,
        "math": (
            "PETR4 e BTC compartilham o mesmo caminho de log-retorno; só o nível muda. "
            f"ΔP = R${MOVE_BRL:.0f} é {MOVE_BRL / PETR4_LEVEL * 100:.0f}% em PETR4 a R${PETR4_LEVEL:.0f} "
            f"e {MOVE_BRL / BTC_LEVEL * 100:.2f}% em BTC a R${BTC_LEVEL:,.0f}. "
            "Ridge walk-forward: y = P_{t+1} a partir de defasagens de P (R² alto, RMSE na unidade do ativo); "
            "y = r_{t+1} a partir de defasagens de r (R² honesto, RMSE adimensional); "
            "y = 1{{vol futura > mediana expansiva}} (regime). "
            "ADF(1) no preço vs no retorno. O Laboratório Quant já rotula r[t+1→t+2], nunca o print."
        ),
        "what_broke": list(_WHAT_BROKE),
    }

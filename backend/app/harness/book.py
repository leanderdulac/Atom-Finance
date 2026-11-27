"""Cross-sectional paper book, expressed as a harness backtest report.

Gross is the weight decided at t times the asset return that ends at t+1.
Net subtracts fee + half-spread + slippage on traded notional, including the
open and the final flatten. The report is what the verifiable gate sees.
No order is sent.
"""

from __future__ import annotations

import numpy as np

from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.types import BacktestReport, CausalContract, ExperimentSpec
from app.models.trading_costs import leg_rate_bps


def run_book_backtest(
    asset_returns: np.ndarray,
    weights: np.ndarray,
    *,
    commission_bps: float,
    slippage_bps: float,
    half_spread_bps: float,
    n_trials: int,
    embargo: int,
    folds: tuple[tuple[int, int, int], ...],
    feature_matrix: np.ndarray,
    signal: np.ndarray | None = None,
) -> BacktestReport:
    """Build a report whose net series matches the harness cost identity."""
    if ELIGIBLE_FOR_LIVE_TRADING is not False:
        raise ValueError("eligible_for_live_trading must remain false")
    earned = np.asarray(asset_returns, dtype=np.float64)
    book = np.asarray(weights, dtype=np.float64)
    features = np.asarray(feature_matrix, dtype=np.float64)
    if earned.ndim != 2 or book.shape != earned.shape:
        raise ValueError("weights and asset returns must share shape (time, asset)")
    if features.ndim != 2 or features.shape[0] != earned.shape[0]:
        raise ValueError("feature matrix must have one row per decision")
    if not np.all(np.isfinite(earned)) or not np.all(np.isfinite(book)) or not np.all(np.isfinite(features)):
        raise ValueError("book series must be finite")
    if embargo < 1:
        raise ValueError("embargo must be an integer >= 1")
    n = earned.shape[0]
    _assert_folds(n, folds, embargo)
    gross = np.sum(book * earned, axis=1)
    previous = np.vstack([np.zeros((1, book.shape[1]), dtype=np.float64), book[:-1]])
    turnover = np.sum(np.abs(book - previous), axis=1)
    turnover[-1] += float(np.sum(np.abs(book[-1])))
    rate = leg_rate_bps(float(commission_bps), float(half_spread_bps), float(slippage_bps)) / 10_000.0
    net = gross - turnover * rate
    if signal is None:
        exposure = np.clip(np.sum(book, axis=1), -1.0, 1.0)
    else:
        exposure = np.asarray(signal, dtype=np.float64)
        if exposure.shape != (n,) or not np.all(np.isfinite(exposure)):
            raise ValueError("signal must be a finite value per decision")
    contract = CausalContract(
        n=n,
        lag=1,
        embargo=int(embargo),
        feature_end=tuple(range(n)),
        decision=tuple(range(n)),
        label_start=tuple(range(1, n + 1)),
        folds=tuple((int(a), int(b), int(c)) for a, b, c in folds),
    )
    return BacktestReport(
        gross_returns=tuple(float(v) for v in gross),
        net_returns=tuple(float(v) for v in net),
        turnover=tuple(float(v) for v in turnover),
        commission_bps=float(commission_bps),
        slippage_bps=float(slippage_bps),
        half_spread_bps=float(half_spread_bps),
        n_trials=int(n_trials),
        causal=contract,
        signal=tuple(float(v) for v in exposure),
        feature_matrix=tuple(tuple(float(v) for v in row) for row in features),
    )


def assert_book_report(spec: ExperimentSpec, report: BacktestReport) -> None:
    """Refuse a report that is not the spec's costed book."""
    if report.eligible_for_live_trading is not False or spec.eligible_for_live_trading is not False:
        raise ValueError("eligible_for_live_trading must remain false")
    if (
        report.commission_bps != spec.commission_bps
        or report.slippage_bps != spec.slippage_bps
        or report.half_spread_bps != spec.half_spread_bps
    ):
        raise ValueError("book costs must match the experiment spec")
    if len(report.net_returns) != len(spec.signal) or len(report.gross_returns) != len(spec.signal):
        raise ValueError("book report must align with the spec signal")
    if len(report.turnover) != len(spec.signal):
        raise ValueError("book turnover must align with the spec signal")
    signal = np.asarray(spec.signal, dtype=np.float64)
    reported = np.asarray(report.signal, dtype=np.float64)
    if signal.shape != reported.shape or not np.allclose(signal, reported, rtol=0.0, atol=1e-12):
        raise ValueError("book signal must match the spec signal")
    if spec.feature_matrix is not None:
        if report.feature_matrix is None:
            raise ValueError("book feature matrix is missing")
        left = np.asarray(spec.feature_matrix, dtype=np.float64)
        right = np.asarray(report.feature_matrix, dtype=np.float64)
        if left.shape != right.shape or not np.allclose(left, right, rtol=0.0, atol=1e-12):
            raise ValueError("book feature matrix must match the spec")
    rate = leg_rate_bps(report.commission_bps, report.half_spread_bps, report.slippage_bps) / 10_000.0
    gross = np.asarray(report.gross_returns, dtype=np.float64)
    net = np.asarray(report.net_returns, dtype=np.float64)
    turnover = np.asarray(report.turnover, dtype=np.float64)
    if not np.allclose(net, gross - turnover * rate, rtol=0.0, atol=1e-8):
        raise ValueError("book net returns do not match gross minus costs")


def nav_from_gross(gross: np.ndarray, start: float = 100.0) -> np.ndarray:
    """Positive price path whose simple returns equal ``gross``."""
    series = np.asarray(gross, dtype=np.float64)
    growth = np.cumprod(1.0 + series)
    if not np.all(np.isfinite(growth)) or np.any(growth <= 0.0):
        raise ValueError("book gross path left the positive reals")
    return np.concatenate([np.asarray([start], dtype=np.float64), start * growth])


def _assert_folds(n: int, folds: tuple[tuple[int, int, int], ...], embargo: int) -> None:
    if not folds:
        raise ValueError("book needs at least one purged fold")
    for train_end, test_start, fold_embargo in folds:
        if fold_embargo < 1 or train_end < 0 or test_start >= n or test_start <= train_end:
            raise ValueError(f"fold ({train_end}, {test_start}, {fold_embargo}) is outside the book")
        if train_end + fold_embargo >= test_start or fold_embargo != embargo:
            raise ValueError(f"fold ({train_end}, {test_start}, {fold_embargo}) breaks the embargo")

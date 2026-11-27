"""Causal paper backtest and no-lookahead checks.

The book is a lagged weight in ``[-1, 1]``. The weight at ``t`` is taken from
the signal at ``t - (lag - 1)`` with ``lag >= 1``, and it earns the return that
ends at the next price. Costs use the desk's fee + half-spread + slippage rate.
No order is sent.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.harness.types import BacktestReport, CausalContract
from app.models.trading_costs import leg_rate_bps


def run_paper_backtest(
    prices: Sequence[float],
    signal: Sequence[float],
    *,
    lag: int,
    commission_bps: float,
    slippage_bps: float,
    half_spread_bps: float,
    n_trials: int,
    feature_matrix: Sequence[Sequence[float]] | None = None,
    trial_sharpes: Sequence[float] | None = None,
) -> BacktestReport:
    if isinstance(lag, bool) or not isinstance(lag, int) or lag < 1:
        raise ValueError("lag must be an integer >= 1")
    px = np.asarray(prices, dtype=np.float64)
    raw_signal = np.asarray(signal, dtype=np.float64)
    if px.ndim != 1 or raw_signal.ndim != 1:
        raise ValueError("prices and signal must be 1-D")
    if len(px) < 30 or len(raw_signal) != len(px) - 1:
        raise ValueError("signal must align to one return per price interval")
    if not np.all(np.isfinite(px)) or np.any(px <= 0):
        raise ValueError("prices must be finite and strictly positive")
    if not np.all(np.isfinite(raw_signal)):
        raise ValueError("signal must be finite")

    returns = np.diff(px) / px[:-1]
    weight = np.clip(raw_signal, -1.0, 1.0)
    position = np.zeros(len(returns), dtype=np.float64)
    shift = lag - 1
    if shift == 0:
        position[:] = weight
    else:
        position[shift:] = weight[:-shift]

    rate = leg_rate_bps(float(commission_bps), float(half_spread_bps), float(slippage_bps)) / 10_000.0
    previous = np.empty_like(position)
    previous[0] = 0.0
    previous[1:] = position[:-1]
    turnover = np.abs(position - previous)
    turnover[-1] += abs(float(position[-1]))
    gross = position * returns
    net = gross - turnover * rate

    contract = _contract(len(returns), lag)
    matrix: tuple[tuple[float, ...], ...] | None = None
    if feature_matrix is not None:
        matrix = tuple(tuple(float(v) for v in row) for row in feature_matrix)
    sharpes = None if trial_sharpes is None else tuple(float(v) for v in trial_sharpes)
    return BacktestReport(
        gross_returns=tuple(float(v) for v in gross),
        net_returns=tuple(float(v) for v in net),
        turnover=tuple(float(v) for v in turnover),
        commission_bps=float(commission_bps),
        slippage_bps=float(slippage_bps),
        half_spread_bps=float(half_spread_bps),
        n_trials=int(n_trials),
        causal=contract,
        signal=tuple(float(v) for v in weight),
        feature_matrix=matrix,
        trial_sharpes=sharpes,
    )


def _contract(n: int, lag: int) -> CausalContract:
    train_end = n // 2
    embargo = lag
    test_start = train_end + embargo + 1
    if test_start >= n:
        raise ValueError("sample is too short for the embargoed split")
    index = np.arange(n, dtype=np.int64)
    decision = index - (lag - 1)
    return CausalContract(
        n=n,
        lag=lag,
        embargo=embargo,
        feature_end=tuple(int(v) for v in decision),
        decision=tuple(int(v) for v in decision),
        label_start=tuple(int(v) for v in (index + 1)),
        folds=((int(train_end), int(test_start), int(embargo)),),
    )


def causal_failures(contract: CausalContract) -> list[str]:
    """Return human-readable lookahead failures. An empty list means the contract holds."""
    reasons: list[str] = []
    if contract.lag < 1:
        reasons.append("lookahead: lag < 1 lets the signal earn the same-bar return")
    n = contract.n
    feature_end = np.asarray(contract.feature_end, dtype=np.int64)
    decision = np.asarray(contract.decision, dtype=np.int64)
    label_start = np.asarray(contract.label_start, dtype=np.int64)
    if not (len(feature_end) == len(decision) == len(label_start) == n):
        reasons.append("lookahead: causal index arrays do not match the sample")
        return reasons
    valid = decision >= 0
    if not np.any(valid):
        reasons.append("lookahead: the sample has no causal decision")
        return reasons
    if np.any(feature_end[valid] > decision[valid]):
        reasons.append("lookahead: a feature ends after its decision")
    if np.any(label_start[valid] <= decision[valid]):
        reasons.append("lookahead: a label starts at or before its decision")
    if np.any(feature_end[valid] >= label_start[valid]):
        reasons.append("lookahead: a feature window overlaps its label")
    if not contract.folds:
        reasons.append("lookahead: no purged train/test split was declared")
    for train_end, test_start, embargo in contract.folds:
        if embargo < 1 or train_end + embargo >= test_start:
            reasons.append(
                f"lookahead: fold train_end={train_end} embargo={embargo} reaches test_start={test_start}"
            )
        if test_start <= train_end or test_start >= n or train_end < 0:
            reasons.append(f"lookahead: fold ({train_end}, {test_start}, {embargo}) is outside the sample")
    return reasons


def label_copies(series: Sequence[float] | np.ndarray, labels: Sequence[float] | np.ndarray) -> bool:
    """True when ``series[t]`` is an exact copy of the label at ``t`` or later.

    A feature equal to the return it is supposed to predict is lookahead.
    A feature equal to an earlier return is not.
    """
    left = np.asarray(series, dtype=np.float64)
    right = np.asarray(labels, dtype=np.float64)
    if left.shape != right.shape or left.ndim != 1 or len(left) < 3:
        return True
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        return True
    horizon = min(3, len(right) - 2)
    for shift in range(horizon):
        sample = left[: len(right) - shift]
        future = right[shift : shift + len(sample)]
        if len(sample) >= 3 and np.allclose(sample, future, rtol=0.0, atol=1e-12):
            return True
    return False


def earned_labels(report: BacktestReport) -> tuple[float, ...]:
    """Asset return the position earned, recovered as gross / position.

    Flat bars are filled with zero so the comparison stays finite. A signal
    that copies this series is using the return it is supposed to forecast.
    """
    gross = np.asarray(report.gross_returns, dtype=np.float64)
    signal = np.asarray(report.signal, dtype=np.float64)
    position = np.zeros(len(gross), dtype=np.float64)
    shift = max(report.causal.lag - 1, 0)
    if len(signal) == len(gross) and shift < len(signal):
        if shift == 0:
            position[:] = signal
        else:
            position[shift:] = signal[:-shift]
    active = np.abs(position) > 1e-12
    if not np.any(active):
        return tuple(float(v) for v in gross)
    labels = np.zeros(len(gross), dtype=np.float64)
    labels[active] = gross[active] / position[active]
    return tuple(float(v) for v in labels)


def probe(report: BacktestReport) -> list[str]:
    """Structural contract failures plus exact copies of the earned label."""
    return causal_failures(report.causal) + leakage_failures(
        report.signal, earned_labels(report), report.feature_matrix
    )


def leakage_failures(
    signal: Sequence[float],
    labels: Sequence[float],
    feature_matrix: Sequence[Sequence[float]] | None,
) -> list[str]:
    reasons: list[str] = []
    if label_copies(signal, labels):
        reasons.append("lookahead: the signal copies the return it earns")
    if feature_matrix is not None:
        columns = np.asarray(feature_matrix, dtype=np.float64)
        if columns.ndim != 2 or columns.shape[0] != len(labels):
            reasons.append("lookahead: the feature matrix is not aligned to the labels")
        else:
            for index in range(columns.shape[1]):
                if label_copies(columns[:, index], labels):
                    reasons.append(f"lookahead: feature column {index} copies a current or future label")
    return reasons

"""Shared records for the research loop, the gate, and the allocator.

Every record carries ``eligible_for_live_trading`` and refuses a true value.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass

from app.harness.errors import PaperViolation
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING


def _refuse_live(value: bool) -> None:
    if value is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
        raise PaperViolation("eligible_for_live_trading must remain false")


@dataclass(frozen=True, slots=True)
class Hypothesis:
    statement: str
    family: str
    fingerprint: str
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)


@dataclass(frozen=True, slots=True)
class CausalContract:
    """Structural no-lookahead contract of one paper backtest.

    ``feature_end[t]`` is the last bar the feature at decision ``t`` may use.
    ``label_start[t]`` is the first bar of the return that decision earns.
    Folds are ``(train_end, test_start, embargo)`` on the return index.
    """

    n: int
    lag: int
    embargo: int
    feature_end: tuple[int, ...]
    decision: tuple[int, ...]
    label_start: tuple[int, ...]
    folds: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    gross_returns: tuple[float, ...]
    net_returns: tuple[float, ...]
    turnover: tuple[float, ...]
    commission_bps: float
    slippage_bps: float
    half_spread_bps: float
    n_trials: int
    causal: CausalContract
    signal: tuple[float, ...]
    feature_matrix: tuple[tuple[float, ...], ...] | None
    trial_sharpes: tuple[float, ...] | None = None
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)


@dataclass(frozen=True, slots=True)
class GateDecision:
    approved: bool
    reasons: tuple[str, ...]
    causal_ok: bool
    costs_ok: bool
    dsr_ok: bool
    paper_ok: bool
    dsr: float | None
    observed_sharpe: float | None
    n_trials: int
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)

    def to_dict(self) -> dict[str, object]:
        return {
            "approved": self.approved,
            "reasons": list(self.reasons),
            "causal_ok": self.causal_ok,
            "costs_ok": self.costs_ok,
            "dsr_ok": self.dsr_ok,
            "paper_ok": self.paper_ok,
            "dsr": self.dsr,
            "observed_sharpe": self.observed_sharpe,
            "n_trials": self.n_trials,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """One paper candidate. The live-trading flag cannot be set true."""

    statement: str
    family: str
    feature_names: tuple[str, ...]
    feature_formulas: tuple[str, ...]
    prices: tuple[float, ...]
    signal: tuple[float, ...]
    feature_matrix: tuple[tuple[float, ...], ...] | None = None
    lag: int = 1
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    half_spread_bps: float = 2.0
    n_trials: int = 2
    trial_sharpes: tuple[float, ...] | None = None
    use_model: bool = False
    compute_units: int = 1
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)
        if len(self.statement.strip()) < 8:
            raise ValueError("hypothesis statement is too short")
        if not self.family.strip():
            raise ValueError("family is required")
        if len(self.feature_names) < 1:
            raise ValueError("at least one feature is required")
        if len(self.feature_names) != len(self.feature_formulas):
            raise ValueError("feature names and formulas must align")
        if any(not name.strip() or not formula.strip() for name, formula in zip(
            self.feature_names, self.feature_formulas, strict=True
        )):
            raise ValueError("feature names and formulas must be non-empty")
        if isinstance(self.lag, bool) or not isinstance(self.lag, int) or self.lag < 1:
            raise ValueError("lag must be an integer >= 1")
        if isinstance(self.n_trials, bool) or not isinstance(self.n_trials, int) or self.n_trials < 1:
            raise ValueError("n_trials must be an integer >= 1")
        if isinstance(self.compute_units, bool) or not isinstance(self.compute_units, int) or self.compute_units < 1:
            raise ValueError("compute_units must be an integer >= 1")
        if len(self.prices) < 30:
            raise ValueError("prices are too short for a paper backtest")
        if len(self.signal) != len(self.prices) - 1:
            raise ValueError("signal must have one value per return interval")
        _finite("price", self.prices, positive=True)
        _finite("signal", self.signal, positive=False)
        for label, bps in (
            ("commission_bps", self.commission_bps),
            ("slippage_bps", self.slippage_bps),
            ("half_spread_bps", self.half_spread_bps),
        ):
            if not math.isfinite(bps) or bps < 0:
                raise ValueError(f"{label} must be finite and >= 0")
        if self.feature_matrix is not None:
            width = len(self.feature_names)
            if len(self.feature_matrix) != len(self.signal):
                raise ValueError("feature matrix must have one row per return")
            for row in self.feature_matrix:
                if len(row) != width:
                    raise ValueError("feature matrix width must match the feature names")
                _finite("feature", row, positive=False)
        if self.trial_sharpes is not None and len(self.trial_sharpes) < 2:
            raise ValueError("trial_sharpes needs at least two values when it is set")


def _finite(name: str, values: tuple[float, ...], *, positive: bool) -> None:
    for value in values:
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(float(value)):
            raise ValueError(f"{name} values must be finite")
        if positive and float(value) <= 0:
            raise ValueError(f"{name} values must be strictly positive")


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    terminal: str
    phase: str
    history: tuple[str, ...]
    fingerprint: str
    reasons: tuple[str, ...]
    approved: bool
    dsr: float | None
    observed_sharpe: float | None
    n_trials_used: int | None
    checks: tuple[tuple[str, bool], ...]
    experiments_used: int
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "terminal": self.terminal,
            "phase": self.phase,
            "history": list(self.history),
            "fingerprint": self.fingerprint,
            "reasons": list(self.reasons),
            "approved": self.approved,
            "dsr": self.dsr,
            "observed_sharpe": self.observed_sharpe,
            "n_trials_used": self.n_trials_used,
            "checks": {key: value for key, value in self.checks},
            "experiments_used": self.experiments_used,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }

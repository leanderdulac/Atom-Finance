"""Typed research lifecycle.

The only forward path is draft, hypothesis, feature/signal, backtest,
verdict, memory. A run may close early (duplicate, budget cutoff, prune).
It cannot skip a scientific phase, and it cannot move after it has closed.
"""

from __future__ import annotations

from enum import StrEnum

from app.harness.errors import IllegalTransition
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.types import BacktestReport, GateDecision, Hypothesis


class Phase(StrEnum):
    DRAFT = "draft"
    HYPOTHESIS = "hypothesis"
    FEATURE_SIGNAL = "feature_signal"
    BACKTEST = "backtest"
    VERDICT = "verdict"
    MEMORY = "memory"


class Terminal(StrEnum):
    REJECTED = "rejected"
    PROMOTED_PAPER = "promoted_paper"
    PRUNED = "pruned"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DUPLICATE = "duplicate"


_ORDER: tuple[Phase, ...] = (
    Phase.DRAFT,
    Phase.HYPOTHESIS,
    Phase.FEATURE_SIGNAL,
    Phase.BACKTEST,
    Phase.VERDICT,
    Phase.MEMORY,
)


class ResearchLoop:
    """One candidate's state machine. Promotion is only a closed memory phase."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.phase = Phase.DRAFT
        self.terminal: Terminal | None = None
        self.history: list[str] = [Phase.DRAFT.value]
        self.hypothesis: Hypothesis | None = None
        self.report: BacktestReport | None = None
        self.decision: GateDecision | None = None
        self.probe_reasons: tuple[str, ...] = ()
        self.reasons: list[str] = []

    @property
    def eligible_for_live_trading(self) -> bool:
        return ELIGIBLE_FOR_LIVE_TRADING

    def _advance(self, target: Phase) -> None:
        if self.terminal is not None:
            raise IllegalTransition(f"run {self.run_id} is closed ({self.terminal.value})")
        index = _ORDER.index(self.phase)
        if index + 1 >= len(_ORDER):
            raise IllegalTransition(f"run {self.run_id} has no phase after {self.phase.value}")
        expected = _ORDER[index + 1]
        if target is not expected:
            raise IllegalTransition(
                f"cannot move {self.phase.value} -> {target.value}; next is {expected.value}"
            )
        self.phase = target
        self.history.append(target.value)

    def close(self, terminal: Terminal, reasons: list[str] | tuple[str, ...] | None = None) -> None:
        if self.terminal is not None:
            raise IllegalTransition(f"run {self.run_id} is closed ({self.terminal.value})")
        if ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise IllegalTransition("eligible_for_live_trading must remain false")
        self.terminal = terminal
        if reasons:
            self.reasons.extend(reasons)

    def open_hypothesis(self, hypothesis: Hypothesis) -> None:
        self._advance(Phase.HYPOTHESIS)
        self.hypothesis = hypothesis

    def attach_feature_signal(self) -> None:
        self._advance(Phase.FEATURE_SIGNAL)

    def record_backtest(self, report: BacktestReport) -> None:
        self._advance(Phase.BACKTEST)
        self.report = report

    def record_verdict(self, decision: GateDecision, probe_reasons: tuple[str, ...]) -> None:
        self._advance(Phase.VERDICT)
        self.decision = decision
        self.probe_reasons = probe_reasons

    def record_memory(self, terminal: Terminal, reasons: list[str] | tuple[str, ...]) -> None:
        self._advance(Phase.MEMORY)
        self.close(terminal, reasons)

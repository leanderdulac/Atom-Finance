"""Hard experiment, compute, and model-call budgets.

A debit that would pass the limit raises ``BudgetExhausted`` and does not
partially consume the remainder. Callers stop the run when that happens.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from app.harness.errors import BudgetExhausted


class BudgetKind(StrEnum):
    EXPERIMENT = "experiment"
    COMPUTE = "compute"
    MODEL_CALL = "model_call"


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    max_experiments: int = 32
    max_compute_units: int = 128
    max_model_calls: int = 16

    def __post_init__(self) -> None:
        for name in ("max_experiments", "max_compute_units", "max_model_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be an integer >= 0")

    def limit_for(self, kind: BudgetKind) -> int:
        if kind is BudgetKind.EXPERIMENT:
            return self.max_experiments
        if kind is BudgetKind.COMPUTE:
            return self.max_compute_units
        return self.max_model_calls


@dataclass(frozen=True, slots=True)
class Debit:
    kind: str
    amount: int
    used: int
    remaining: int


class ResearchBudget:
    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self.limits = limits or BudgetLimits()
        self._used: dict[BudgetKind, int] = {kind: 0 for kind in BudgetKind}
        self._lock = threading.Lock()

    def used(self, kind: BudgetKind) -> int:
        return self._used[kind]

    def remaining(self, kind: BudgetKind) -> int:
        return self.limits.limit_for(kind) - self._used[kind]

    @property
    def experiments_used(self) -> int:
        return self._used[BudgetKind.EXPERIMENT]

    @property
    def compute_used(self) -> int:
        return self._used[BudgetKind.COMPUTE]

    @property
    def model_calls_used(self) -> int:
        return self._used[BudgetKind.MODEL_CALL]

    def debit(self, kind: BudgetKind, amount: int = 1) -> Debit:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f"debit amount must be an integer >= 0, got {amount!r}")
        with self._lock:
            limit = self.limits.limit_for(kind)
            used = self._used[kind]
            if amount == 0:
                return Debit(kind.value, 0, used, limit - used)
            if used + amount > limit:
                raise BudgetExhausted(kind.value, used, limit, amount)
            self._used[kind] = used + amount
            return Debit(kind.value, amount, used + amount, limit - (used + amount))

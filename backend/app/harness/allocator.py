"""Test-time budget allocator.

Each branch gets one action: deepen, branch, adversarial_check, or prune.
The choice uses verifiable intermediate signals (leakage, costs, Deflated
Sharpe, fold path, and whether the fingerprint was already stored). A raw
Sharpe does not buy a deeper backtest. Spend is then fit to the budget that
is actually left, and anything that does not fit is pruned.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.types import _refuse_live


class Action(StrEnum):
    DEEPEN = "deepen"
    BRANCH = "branch"
    ADVERSARIAL_CHECK = "adversarial_check"
    PRUNE = "prune"


# Experiments, then compute units.
_COST: dict[Action, tuple[int, int]] = {
    Action.DEEPEN: (2, 4),
    Action.BRANCH: (1, 2),
    Action.ADVERSARIAL_CHECK: (1, 1),
    Action.PRUNE: (0, 0),
}

_PRIORITY: dict[Action, int] = {
    Action.ADVERSARIAL_CHECK: 3,
    Action.DEEPEN: 2,
    Action.BRANCH: 1,
    Action.PRUNE: 0,
}


@dataclass(frozen=True, slots=True)
class BranchSignal:
    branch_id: str
    fingerprint: str
    dsr: float | None
    observed_sharpe: float | None
    n_trials: int
    costs_accounted: bool
    leakage: bool
    adversarial_done: bool
    fold_sharpes: tuple[float, ...] = ()
    known_dead: bool = False
    already_tested: bool = False
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)


@dataclass(frozen=True, slots=True)
class Allocation:
    branch_id: str
    fingerprint: str
    action: str
    experiments: int
    compute_units: int
    reason: str
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)

    def to_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "fingerprint": self.fingerprint,
            "action": self.action,
            "experiments": self.experiments,
            "compute_units": self.compute_units,
            "reason": self.reason,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    items: tuple[Allocation, ...]
    experiments_spent: int
    compute_spent: int
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        _refuse_live(self.eligible_for_live_trading)

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "experiments_spent": self.experiments_spent,
            "compute_spent": self.compute_spent,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }


def choose_action(branch: BranchSignal) -> tuple[Action, str]:
    """Pick the next use of budget for one branch. Pure and deterministic."""
    if branch.leakage:
        return Action.PRUNE, "leakage"
    if branch.known_dead or branch.already_tested:
        return Action.PRUNE, "already in research memory"
    if not branch.costs_accounted:
        return Action.ADVERSARIAL_CHECK, "costs are not verified"
    if branch.dsr is not None and branch.dsr >= 0.95:
        if not branch.adversarial_done:
            return Action.ADVERSARIAL_CHECK, "high DSR still needs an adversarial check"
        return Action.PRUNE, "verified candidate; refusing a redundant backtest"
    if branch.dsr is not None and branch.dsr >= 0.5 and _improving(branch.fold_sharpes):
        return Action.DEEPEN, "intermediate DSR is improving"
    if branch.dsr is None and branch.observed_sharpe is not None and branch.observed_sharpe > 1.0:
        if not branch.adversarial_done:
            return Action.ADVERSARIAL_CHECK, "raw Sharpe has no deflated score"
    if (branch.dsr is None or branch.dsr < 0.5) and branch.n_trials < 3:
        return Action.BRANCH, "weak intermediate result; branch a sibling instead of repeating the backtest"
    return Action.PRUNE, "no verifiable reason to spend more budget"


def allocate_budget(
    branches: tuple[BranchSignal, ...] | list[BranchSignal],
    experiments_left: int,
    compute_left: int,
) -> AllocationPlan:
    """Assign actions, then drop any assignment the remaining budget cannot pay for."""
    if experiments_left < 0 or compute_left < 0:
        raise ValueError("remaining budget cannot be negative")
    chosen: list[tuple[Action, str]] = []
    seen: set[str] = set()
    for branch in branches:
        if branch.fingerprint in seen:
            chosen.append((Action.PRUNE, "redundant fingerprint in this plan"))
        else:
            seen.add(branch.fingerprint)
            chosen.append(choose_action(branch))

    order = sorted(range(len(chosen)), key=lambda index: -_PRIORITY[chosen[index][0]])
    assigned: list[Allocation | None] = [None] * len(branches)
    experiments = experiments_left
    compute = compute_left
    for index in order:
        action, reason = chosen[index]
        need_e, need_c = _COST[action]
        branch = branches[index]
        if need_e > experiments or need_c > compute:
            assigned[index] = _allocation(branch, Action.PRUNE, "budget exhausted")
            continue
        experiments -= need_e
        compute -= need_c
        assigned[index] = _allocation(branch, action, reason, need_e, need_c)

    items = tuple(item for item in assigned if item is not None)
    return AllocationPlan(
        items=items,
        experiments_spent=sum(item.experiments for item in items),
        compute_spent=sum(item.compute_units for item in items),
    )


def _improving(fold_sharpes: tuple[float, ...]) -> bool:
    if len(fold_sharpes) < 2:
        return False
    return float(fold_sharpes[-1]) > float(fold_sharpes[0])


def _allocation(
    branch: BranchSignal,
    action: Action,
    reason: str,
    experiments: int | None = None,
    compute_units: int | None = None,
) -> Allocation:
    need_e, need_c = _COST[action]
    return Allocation(
        branch_id=branch.branch_id,
        fingerprint=branch.fingerprint,
        action=action.value,
        experiments=need_e if experiments is None else experiments,
        compute_units=need_c if compute_units is None else compute_units,
        reason=reason,
    )

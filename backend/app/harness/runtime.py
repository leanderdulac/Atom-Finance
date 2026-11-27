"""Research harness runtime.

One ``execute`` walks hypothesis, feature/signal, paper backtest, adversarial
probe, verifiable verdict, and memory. Budgets cut the run off. Capabilities
are checked against the acting role. The audit ledger records each step.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from app.harness.adapters import DeterministicResearchModel, ResearchModel
from app.harness.allocator import AllocationPlan, BranchSignal, allocate_budget
from app.harness.audit import AuditLedger
from app.harness.budget import BudgetKind, BudgetLimits, Debit, ResearchBudget
from app.harness.causal import probe, run_paper_backtest
from app.harness.codec import hypothesis_fingerprint
from app.harness.errors import BudgetExhausted, CapabilityDenied, PaperViolation, VerdictOverride
from app.harness.gate import VerifiableGate, assert_verdict_matches, with_trials
from app.harness.identity import DUTIES, AgentIdentity, AgentRegistry, AgentRole, Capability
from app.harness.identity import authorize as require_capability
from app.harness.loop import ResearchLoop, Terminal
from app.harness.memory import ResearchMemory
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.types import ExperimentSpec, GateDecision, Hypothesis, RunOutcome

_LOOP_ROLES = (
    AgentRole.HYPOTHESIS,
    AgentRole.EVIDENCE,
    AgentRole.CODE,
    AgentRole.EXPERIMENT,
    AgentRole.ADVERSARIAL,
    AgentRole.JUDGE,
)


class HarnessRuntime:
    def __init__(
        self,
        root: Path | str,
        limits: BudgetLimits | None = None,
        model: ResearchModel | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.memory = ResearchMemory(self.root / "memory.sqlite")
        self.audit = AuditLedger(self.root / "audit.jsonl", clock=clock)
        self.budget = ResearchBudget(limits)
        self.registry = AgentRegistry()
        self.model = model or DeterministicResearchModel()
        self.gate = VerifiableGate()
        self._lock = threading.Lock()
        self.agents: dict[AgentRole, AgentIdentity] = {
            role: self.registry.register(role, f"{role.value}:agent") for role in AgentRole
        }

    def authorize(self, agent_id: str, capability: Capability) -> AgentIdentity:
        agent = self.registry.get(agent_id)
        try:
            require_capability(agent, capability)
        except CapabilityDenied:
            self.audit.append(
                run_id="",
                agent_id=agent.agent_id,
                role=agent.role.value,
                action=capability.value,
                payload={"capability": capability.value, "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING},
                decision="denied",
            )
            raise
        return agent

    def execute(
        self,
        spec: ExperimentSpec,
        *,
        agents: Mapping[AgentRole, str] | None = None,
        run_id: str | None = None,
    ) -> RunOutcome:
        with self._lock:
            return self._execute(spec, agents, run_id or str(uuid4()))

    def allocate(self, branches: list[BranchSignal] | tuple[BranchSignal, ...], agent_id: str | None = None) -> AllocationPlan:
        with self._lock:
            agent = self.authorize(agent_id or self.agents[AgentRole.ALLOCATOR].agent_id, Capability.ALLOCATE_BUDGET)
            self.authorize(agent.agent_id, Capability.PRUNE_BRANCH)
            enriched: list[BranchSignal] = []
            for branch in branches:
                record = self.memory.lookup(branch.fingerprint)
                known_dead = branch.known_dead or (record is not None and record.status in {"rejected", "pruned"})
                already = branch.already_tested or record is not None
                enriched.append(
                    BranchSignal(
                        branch_id=branch.branch_id,
                        fingerprint=branch.fingerprint,
                        dsr=branch.dsr,
                        observed_sharpe=branch.observed_sharpe,
                        n_trials=branch.n_trials,
                        costs_accounted=branch.costs_accounted,
                        leakage=branch.leakage,
                        adversarial_done=branch.adversarial_done,
                        fold_sharpes=branch.fold_sharpes,
                        known_dead=known_dead,
                        already_tested=already,
                    )
                )
            plan = allocate_budget(
                enriched,
                self.budget.remaining(BudgetKind.EXPERIMENT),
                self.budget.remaining(BudgetKind.COMPUTE),
            )
            for item in plan.items:
                experiment_debit = self.budget.debit(BudgetKind.EXPERIMENT, item.experiments) if item.experiments else None
                compute_debit = self.budget.debit(BudgetKind.COMPUTE, item.compute_units) if item.compute_units else None
                self._audit(
                    agent,
                    "",
                    "allocate",
                    item.to_dict(),
                    item.action,
                    budget=experiment_debit or compute_debit,
                )
            self.audit.verify()
            return plan

    def _execute(self, spec: ExperimentSpec, agents: Mapping[AgentRole, str] | None, run_id: str) -> RunOutcome:
        loop = ResearchLoop(run_id)
        fingerprint = ""
        try:
            roster = self._roster(agents)
            if spec.use_model:
                debit = self.budget.debit(BudgetKind.MODEL_CALL, 1)
                reply = self.model.complete(
                    role=AgentRole.HYPOTHESIS.value,
                    task="draft_hypothesis",
                    payload={
                        "statement": spec.statement,
                        "family": spec.family,
                        "features": list(spec.feature_names),
                        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
                    },
                )
                if not isinstance(reply, Mapping) or reply.get("eligible_for_live_trading", False) is not False:
                    raise PaperViolation("eligible_for_live_trading must remain false")
                self._audit(
                    roster[AgentRole.HYPOTHESIS],
                    run_id,
                    "model_call",
                    {"task": "draft_hypothesis", "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING},
                    "noted",
                    budget=debit,
                )

            fingerprint = hypothesis_fingerprint(
                family=spec.family,
                statement=spec.statement,
                feature_names=spec.feature_names,
                feature_formulas=spec.feature_formulas,
                lag=spec.lag,
                commission_bps=spec.commission_bps,
                slippage_bps=spec.slippage_bps,
                half_spread_bps=spec.half_spread_bps,
            )
            summary = _summary(spec, fingerprint)
            self.authorize(roster[AgentRole.HYPOTHESIS].agent_id, Capability.DRAFT_HYPOTHESIS)
            loop.open_hypothesis(Hypothesis(spec.statement, spec.family.strip().lower(), fingerprint))
            self._audit(roster[AgentRole.HYPOTHESIS], run_id, "open_hypothesis", summary, "opened")

            self.authorize(roster[AgentRole.EVIDENCE].agent_id, Capability.READ_MEMORY)
            prior = self.memory.lookup(fingerprint)
            dead = self.memory.dead_features(spec.feature_names, spec.feature_formulas)
            if prior is None and not dead:
                self._audit(roster[AgentRole.EVIDENCE], run_id, "read_memory", summary, "new")
            if prior is not None or dead:
                reason = (
                    f"duplicate: prior status {prior.status}"
                    if prior is not None
                    else f"duplicate: dead feature {', '.join(dead)}"
                )
                loop.close(Terminal.DUPLICATE, [reason])
                self._audit(roster[AgentRole.EVIDENCE], run_id, "read_memory", summary, "duplicate")
                return self._finish(loop, fingerprint)

            self.authorize(roster[AgentRole.EVIDENCE].agent_id, Capability.WRITE_FEATURE)
            self.authorize(roster[AgentRole.CODE].agent_id, Capability.WRITE_SIGNAL)
            loop.attach_feature_signal()
            self._audit(roster[AgentRole.EVIDENCE], run_id, "write_feature", summary, "attached")
            self._audit(roster[AgentRole.CODE], run_id, "write_signal", summary, "attached")

            self.authorize(roster[AgentRole.EXPERIMENT].agent_id, Capability.RUN_BACKTEST)
            experiment_debit = self.budget.debit(BudgetKind.EXPERIMENT, 1)
            compute_debit = self.budget.debit(BudgetKind.COMPUTE, spec.compute_units)
            n_trials = max(spec.n_trials, self.memory.count_family(spec.family) + 1)
            report = with_trials(
                run_paper_backtest(
                    spec.prices,
                    spec.signal,
                    lag=spec.lag,
                    commission_bps=spec.commission_bps,
                    slippage_bps=spec.slippage_bps,
                    half_spread_bps=spec.half_spread_bps,
                    n_trials=n_trials,
                    feature_matrix=spec.feature_matrix,
                    trial_sharpes=spec.trial_sharpes,
                ),
                n_trials,
            )
            loop.record_backtest(report)
            self._audit(
                roster[AgentRole.EXPERIMENT],
                run_id,
                "run_backtest",
                {**summary, "n_trials": n_trials},
                "ran",
                budget=experiment_debit,
            )
            self._audit(
                roster[AgentRole.EXPERIMENT],
                run_id,
                "run_backtest_compute",
                summary,
                "ran",
                budget=compute_debit,
            )

            self.authorize(roster[AgentRole.ADVERSARIAL].agent_id, Capability.ADVERSARIAL_PROBE)
            probe_debit = self.budget.debit(BudgetKind.COMPUTE, 1)
            findings = tuple(probe(report))
            self._audit(
                roster[AgentRole.ADVERSARIAL],
                run_id,
                "adversarial_probe",
                {**summary, "findings": len(findings)},
                "reject" if findings else "clear",
                budget=probe_debit,
            )

            self.authorize(roster[AgentRole.JUDGE].agent_id, Capability.REQUEST_GATE)
            decision = self.gate.evaluate(report, n_trials=n_trials)
            if findings and decision.causal_ok:
                raise VerdictOverride("adversarial probe found lookahead the gate missed")
            self.authorize(roster[AgentRole.JUDGE].agent_id, Capability.ISSUE_VERDICT)
            assert_verdict_matches(decision, decision.approved)
            loop.record_verdict(decision, findings)
            self._audit(
                roster[AgentRole.JUDGE],
                run_id,
                "issue_verdict",
                summary,
                "promoted_paper" if decision.approved else "rejected",
                gate_approved=decision.approved,
            )

            self.authorize(roster[AgentRole.JUDGE].agent_id, Capability.COMMIT_MEMORY)
            self._commit(loop, spec, fingerprint, decision)
            self._audit(
                roster[AgentRole.JUDGE],
                run_id,
                "commit_memory",
                summary,
                loop.terminal.value if loop.terminal else "rejected",
                gate_approved=decision.approved,
            )
            return self._finish(loop, fingerprint)
        except BudgetExhausted as exc:
            if loop.terminal is None:
                loop.close(Terminal.BUDGET_EXHAUSTED, [str(exc)])
            self._audit(
                self.agents[AgentRole.ALLOCATOR],
                run_id,
                "budget_cutoff",
                {"kind": exc.kind, "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING},
                "budget_exhausted",
            )
            return self._finish(loop, fingerprint)
        except PaperViolation:
            self._audit(
                self.agents[AgentRole.JUDGE],
                run_id,
                "paper_guard",
                {"eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING},
                "paper_violation",
            )
            self.audit.verify()
            raise
        except ValueError as exc:
            if loop.terminal is None:
                loop.close(Terminal.REJECTED, [str(exc)])
            if fingerprint and not self.memory.is_finished(fingerprint):
                self.memory.reject(
                    fingerprint=fingerprint,
                    family=spec.family,
                    statement=spec.statement,
                    failure_kind="spec",
                    reasons=tuple(loop.reasons),
                    run_id=run_id,
                    sharpe=None,
                    n_obs=None,
                    n_trials=spec.n_trials,
                )
            self._audit(
                self.agents[AgentRole.EXPERIMENT],
                run_id,
                "spec_rejected",
                _summary(spec, fingerprint),
                "rejected",
            )
            return self._finish(loop, fingerprint)

    def _commit(self, loop: ResearchLoop, spec: ExperimentSpec, fingerprint: str, decision: GateDecision) -> None:
        sharpe = decision.observed_sharpe
        n_obs = len(loop.report.net_returns) if loop.report is not None else None
        if decision.approved:
            self.memory.promote(
                fingerprint=fingerprint,
                family=spec.family,
                statement=spec.statement,
                reasons=decision.reasons,
                run_id=loop.run_id,
                sharpe=sharpe,
                n_obs=n_obs,
                n_trials=decision.n_trials,
                dsr=decision.dsr,
            )
            loop.record_memory(Terminal.PROMOTED_PAPER, decision.reasons)
            return
        self.memory.reject(
            fingerprint=fingerprint,
            family=spec.family,
            statement=spec.statement,
            failure_kind=_failure_kind(decision),
            reasons=decision.reasons,
            run_id=loop.run_id,
            sharpe=sharpe,
            n_obs=n_obs,
            n_trials=decision.n_trials,
            feature_names=spec.feature_names,
            feature_formulas=spec.feature_formulas,
            mark_features_dead=not decision.causal_ok,
        )
        loop.record_memory(Terminal.REJECTED, decision.reasons)

    def _roster(self, override: Mapping[AgentRole, str] | None) -> dict[AgentRole, AgentIdentity]:
        roster = dict(self.agents)
        if override:
            for role, agent_id in override.items():
                roster[role] = self.registry.get(agent_id)
        for role in _LOOP_ROLES:
            self.authorize(roster[role].agent_id, DUTIES[role])
        return roster

    def _audit(
        self,
        agent: AgentIdentity,
        run_id: str,
        action: str,
        payload: Mapping[str, object],
        decision: str,
        *,
        gate_approved: bool | None = None,
        budget: Debit | None = None,
    ) -> None:
        self.audit.append(
            run_id=run_id,
            agent_id=agent.agent_id,
            role=agent.role.value,
            action=action,
            payload=payload,
            decision=decision,
            gate_approved=gate_approved,
            budget_kind=None if budget is None else budget.kind,
            budget_amount=0 if budget is None else budget.amount,
        )

    def _finish(self, loop: ResearchLoop, fingerprint: str) -> RunOutcome:
        self.audit.verify()
        decision = loop.decision
        checks: tuple[tuple[str, bool], ...] = ()
        if decision is not None:
            checks = (
                ("causal", decision.causal_ok),
                ("costs", decision.costs_ok),
                ("dsr", decision.dsr_ok),
                ("paper", decision.paper_ok),
            )
        reasons: tuple[str, ...]
        if loop.reasons:
            reasons = tuple(loop.reasons)
        elif decision is not None:
            reasons = decision.reasons
        else:
            reasons = ()
        promoted = loop.terminal is Terminal.PROMOTED_PAPER and decision is not None and decision.approved
        return RunOutcome(
            run_id=loop.run_id,
            terminal=loop.terminal.value if loop.terminal is not None else loop.phase.value,
            phase=loop.phase.value,
            history=tuple(loop.history),
            fingerprint=fingerprint,
            reasons=reasons,
            approved=promoted,
            dsr=None if decision is None else decision.dsr,
            observed_sharpe=None if decision is None else decision.observed_sharpe,
            n_trials_used=None if decision is None else decision.n_trials,
            checks=checks,
            experiments_used=self.budget.experiments_used,
        )


def _summary(spec: ExperimentSpec, fingerprint: str) -> dict[str, object]:
    return {
        "fingerprint": fingerprint,
        "family": spec.family,
        "lag": spec.lag,
        "n_trials": spec.n_trials,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def _failure_kind(decision: GateDecision) -> str:
    if not decision.causal_ok:
        return "leakage"
    if not decision.costs_ok:
        return "cost"
    if not decision.dsr_ok:
        return "dsr"
    return "other"

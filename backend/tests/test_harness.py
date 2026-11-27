"""Research harness: loop, gate, identity, budget, audit, memory, allocator."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.client_mode import client_may_access
from app.harness.adapters import DeterministicResearchModel
from app.harness.allocator import Action, BranchSignal, allocate_budget, choose_action
from app.harness.audit import AuditLedger
from app.harness.budget import BudgetKind, BudgetLimits, ResearchBudget
from app.harness.causal import run_paper_backtest
from app.harness.errors import (
    AuditIntegrityError,
    BudgetExhausted,
    CapabilityDenied,
    IllegalTransition,
    PaperViolation,
    VerdictOverride,
)
from app.harness.gate import VerifiableGate, assert_verdict_matches
from app.harness.identity import ALLOWLIST, AgentRegistry, AgentRole, Capability
from app.harness.loop import ResearchLoop, Terminal
from app.harness.memory import ResearchMemory
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.runtime import HarnessRuntime
from app.harness.types import Hypothesis
from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING as DESK_FLAG
from tests.harness_support import make_spec, prices_from_returns, strong_returns, weak_returns


def _report(returns, **kwargs):
    prices = prices_from_returns(returns)
    signal = kwargs.pop("signal", None)
    if signal is None:
        signal = [1.0] * len(returns)
    matrix = kwargs.pop("feature_matrix", None)
    return run_paper_backtest(
        prices,
        signal,
        lag=kwargs.pop("lag", 1),
        commission_bps=kwargs.pop("commission_bps", 5.0),
        slippage_bps=kwargs.pop("slippage_bps", 5.0),
        half_spread_bps=kwargs.pop("half_spread_bps", 2.0),
        n_trials=kwargs.pop("n_trials", 2),
        feature_matrix=matrix,
        trial_sharpes=kwargs.pop("trial_sharpes", None),
    )


def test_live_trading_flag_matches_the_desk_constant():
    assert ELIGIBLE_FOR_LIVE_TRADING is False
    assert DESK_FLAG is False
    assert ELIGIBLE_FOR_LIVE_TRADING is DESK_FLAG
    assert not client_may_access("/api/harness/runs")
    root = Path(__file__).resolve().parents[1] / "app" / "harness"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "eligible_for_live_trading=True" not in text
        assert "eligible_for_live_trading = True" not in text


def test_loop_is_a_single_forward_path():
    loop = ResearchLoop("run-1")
    assert loop.eligible_for_live_trading is False
    loop.open_hypothesis(Hypothesis("A paper hypothesis about lagged drift.", "fam", "fp"))
    with pytest.raises(IllegalTransition):
        loop.record_backtest(None)  # type: ignore[arg-type]
    loop.attach_feature_signal()
    loop.close(Terminal.PRUNED, ["stopped"])
    with pytest.raises(IllegalTransition):
        loop.close(Terminal.REJECTED)
    assert loop.history == ["draft", "hypothesis", "feature_signal"]
    assert loop.terminal is Terminal.PRUNED


def test_gate_rejects_lookahead_missing_slippage_and_undeflated_sharpe():
    gate = VerifiableGate()
    healthy = _report(strong_returns())
    passed = gate.evaluate(healthy)
    assert passed.approved, passed.reasons
    assert passed.causal_ok and passed.costs_ok and passed.dsr_ok and passed.paper_ok
    assert passed.eligible_for_live_trading is False
    assert passed.dsr is not None and passed.dsr >= 0.95

    leaked = _report(strong_returns(), signal=strong_returns())
    leak = gate.evaluate(leaked)
    assert not leak.approved
    assert not leak.causal_ok
    assert any("lookahead" in reason for reason in leak.reasons)

    column = tuple((float(value),) for value in strong_returns())
    feature_leak = gate.evaluate(_report(strong_returns(), feature_matrix=column))
    assert not feature_leak.causal_ok
    assert any("feature column" in reason for reason in feature_leak.reasons)

    folded = replace(healthy, causal=replace(healthy.causal, folds=((20, 10, 1),)))
    assert not gate.evaluate(folded).causal_ok
    same_bar = replace(healthy, causal=replace(healthy.causal, lag=0))
    assert any("lag < 1" in reason for reason in gate.evaluate(same_bar).reasons)

    free = gate.evaluate(_report(strong_returns(), commission_bps=0.0, slippage_bps=0.0, half_spread_bps=0.0))
    assert not free.costs_ok
    assert not free.approved
    assert any("slippage" in reason for reason in free.reasons)

    lied = replace(healthy, net_returns=healthy.gross_returns)
    assert not gate.evaluate(lied).costs_ok

    weak = gate.evaluate(_report(weak_returns(), n_trials=10))
    assert weak.causal_ok and weak.costs_ok
    assert not weak.dsr_ok
    assert not weak.approved
    assert any("DSR" in reason for reason in weak.reasons)

    single = gate.evaluate(_report(strong_returns(), n_trials=1))
    assert not single.dsr_ok
    assert any("multiple-testing" in reason for reason in single.reasons)
    with pytest.raises(VerdictOverride):
        assert_verdict_matches(single, True)
    with pytest.raises(PaperViolation):
        gate.evaluate(healthy, eligible_for_live_trading=True)


def test_roles_are_stable_and_least_privilege():
    registry = AgentRegistry()
    hypothesis = registry.register(AgentRole.HYPOTHESIS, "hyp-1")
    again = registry.register(AgentRole.HYPOTHESIS, "hyp-1")
    assert again is hypothesis
    with pytest.raises(CapabilityDenied):
        registry.register(AgentRole.JUDGE, "hyp-1")
    assert Capability.ISSUE_VERDICT not in ALLOWLIST[AgentRole.HYPOTHESIS]
    assert Capability.RUN_BACKTEST not in ALLOWLIST[AgentRole.HYPOTHESIS]
    assert Capability.ALLOCATE_BUDGET not in ALLOWLIST[AgentRole.HYPOTHESIS]
    assert Capability.ISSUE_VERDICT not in ALLOWLIST[AgentRole.EXPERIMENT]
    assert Capability.COMMIT_MEMORY not in ALLOWLIST[AgentRole.EXPERIMENT]
    assert Capability.RUN_BACKTEST not in ALLOWLIST[AgentRole.JUDGE]
    assert Capability.RUN_BACKTEST not in ALLOWLIST[AgentRole.ALLOCATOR]
    assert Capability.ISSUE_VERDICT not in ALLOWLIST[AgentRole.ADVERSARIAL]
    assert Capability.COMMIT_MEMORY not in ALLOWLIST[AgentRole.CODE]
    assert Capability.RUN_BACKTEST not in ALLOWLIST[AgentRole.EVIDENCE]


def test_budget_debit_stops_at_the_limit():
    budget = ResearchBudget(BudgetLimits(max_experiments=1, max_compute_units=2, max_model_calls=0))
    first = budget.debit(BudgetKind.EXPERIMENT, 1)
    assert first.remaining == 0
    with pytest.raises(BudgetExhausted) as exc:
        budget.debit(BudgetKind.EXPERIMENT, 1)
    assert exc.value.kind == "experiment"
    assert budget.experiments_used == 1
    with pytest.raises(BudgetExhausted):
        budget.debit(BudgetKind.MODEL_CALL, 1)
    assert budget.model_calls_used == 0


def test_audit_chain_detects_tampering_and_truncation(tmp_path: Path):
    ledger = AuditLedger(tmp_path / "audit.jsonl", clock=lambda: "2026-01-01T00:00:00Z")
    assert ledger.verify() == 0
    first = ledger.append(
        run_id="r",
        agent_id="hypothesis:agent",
        role="hypothesis",
        action="open_hypothesis",
        payload={"fingerprint": "abc", "eligible_for_live_trading": False},
        decision="opened",
    )
    second = ledger.append(
        run_id="r",
        agent_id="judge:agent",
        role="judge",
        action="issue_verdict",
        payload={"fingerprint": "abc", "eligible_for_live_trading": False},
        decision="rejected",
        gate_approved=False,
        budget_kind="experiment",
        budget_amount=1,
    )
    assert ledger.verify() == 2
    assert second["prev_hash"] == first["entry_hash"]
    assert all(row["eligible_for_live_trading"] is False for row in ledger.records())

    rows = ledger.records()
    rows[0]["decision"] = "tampered"
    ledger.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        ledger.verify()

    ledger.path.write_text("", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        ledger.verify()


def test_memory_dedup_and_paper_column(tmp_path: Path):
    memory = ResearchMemory(tmp_path / "memory.sqlite")
    rejected = memory.reject(
        fingerprint="fp-1",
        family="Fam",
        statement="A refuted drift hypothesis.",
        failure_kind="dsr",
        reasons=("DSR below threshold",),
        run_id="run-a",
        sharpe=0.1,
        n_obs=100,
        n_trials=4,
        feature_names=("lagged_return",),
        feature_formulas=("prior close-to-close return",),
        mark_features_dead=False,
    )
    assert rejected.status == "rejected"
    assert rejected.eligible_for_live_trading is False
    resurrected = memory.promote(
        fingerprint="fp-1",
        family="Fam",
        statement="A refuted drift hypothesis.",
        reasons=(),
        run_id="run-b",
        sharpe=3.0,
        n_obs=100,
        n_trials=4,
        dsr=0.99,
    )
    assert resurrected.status == "rejected"
    assert memory.count_family("fam") == 1
    assert memory.failure_modes("fp-1")[0]["kind"] == "dsr"

    conn = sqlite3.connect(memory.path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE hypotheses SET eligible_for_live_trading = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE hypotheses SET status = 'promoted_paper'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO hypotheses (fingerprint, family, statement, status, detail_json, run_id, created_at, eligible_for_live_trading)"
            " VALUES ('fp-2', 'fam', 's', 'rejected', '{}', 'r', 't', 1)"
        )
    conn.close()


def test_allocator_spends_only_on_verifiable_signals():
    leakage = _branch("leak", "fp-leak", leakage=True, dsr=0.99, costs_accounted=True)
    improving = _branch("deep", "fp-deep", dsr=0.72, costs_accounted=True, fold_sharpes=(0.2, 0.8), n_trials=4)
    hot = _branch("hot", "fp-hot", dsr=0.99, costs_accounted=True, adversarial_done=False, n_trials=4)
    verified = _branch("done", "fp-done", dsr=0.99, costs_accounted=True, adversarial_done=True, n_trials=4)
    weak = _branch("sib", "fp-weak", dsr=0.1, costs_accounted=True, n_trials=1)
    repeat = _branch("sib-2", "fp-weak", dsr=0.1, costs_accounted=True, n_trials=1)
    raw = _branch("raw", "fp-raw", dsr=None, observed_sharpe=2.4, costs_accounted=True, n_trials=1)
    flat = _branch("flat", "fp-flat", dsr=0.7, costs_accounted=True, fold_sharpes=(0.8, 0.2), n_trials=4)
    uncosted = _branch("cost", "fp-cost", dsr=0.2, costs_accounted=False, n_trials=1)

    assert choose_action(leakage)[0] is Action.PRUNE
    assert choose_action(improving)[0] is Action.DEEPEN
    assert choose_action(hot)[0] is Action.ADVERSARIAL_CHECK
    assert choose_action(verified) == (Action.PRUNE, "verified candidate; refusing a redundant backtest")
    assert choose_action(weak)[0] is Action.BRANCH
    assert choose_action(raw)[0] is Action.ADVERSARIAL_CHECK
    assert choose_action(flat)[0] is Action.PRUNE
    assert choose_action(uncosted)[0] is Action.ADVERSARIAL_CHECK

    plan = allocate_budget([leakage, improving, hot, weak, repeat], experiments_left=3, compute_left=100)
    by_id = {item.branch_id: item for item in plan.items}
    assert by_id["leak"].action == "prune"
    assert by_id["leak"].reason == "leakage"
    assert by_id["hot"].action == "adversarial_check"
    assert by_id["deep"].action == "deepen"
    assert by_id["sib"].action == "prune"
    assert by_id["sib"].reason == "budget exhausted"
    assert by_id["sib-2"].reason == "redundant fingerprint in this plan"
    assert plan.experiments_spent == 3
    assert plan.experiments_spent <= 3
    assert plan.eligible_for_live_trading is False

    broke = allocate_budget([improving, hot], experiments_left=0, compute_left=0)
    assert all(item.action == "prune" for item in broke.items)
    assert broke.experiments_spent == 0
    assert {item.reason for item in broke.items} == {"budget exhausted"}


def test_runtime_promotes_once_then_remembers(tmp_path: Path):
    runtime = HarnessRuntime(tmp_path)
    outcome = runtime.execute(make_spec(strong_returns(), family="promote"))
    assert outcome.history == ("draft", "hypothesis", "feature_signal", "backtest", "verdict", "memory")
    assert outcome.terminal == "promoted_paper"
    assert outcome.approved
    assert outcome.eligible_for_live_trading is False
    assert outcome.checks == (("causal", True), ("costs", True), ("dsr", True), ("paper", True))
    stored = runtime.memory.lookup(outcome.fingerprint)
    assert stored is not None and stored.status == "promoted_paper"
    assert stored.eligible_for_live_trading is False

    actions = [(row["role"], row["action"], row["decision"]) for row in runtime.audit.records()]
    assert ("hypothesis", "open_hypothesis", "opened") in actions
    assert ("evidence", "read_memory", "new") in actions
    assert ("experiment", "run_backtest", "ran") in actions
    assert ("adversarial", "adversarial_probe", "clear") in actions
    assert ("judge", "issue_verdict", "promoted_paper") in actions
    assert ("judge", "commit_memory", "promoted_paper") in actions
    backtest = next(row for row in runtime.audit.records() if row["action"] == "run_backtest")
    assert backtest["budget_kind"] == "experiment"
    assert backtest["budget_amount"] == 1
    verdict = next(row for row in runtime.audit.records() if row["action"] == "issue_verdict")
    assert verdict["gate_approved"] is True
    assert all(row["eligible_for_live_trading"] is False for row in runtime.audit.records())
    assert runtime.audit.verify() == len(runtime.audit.records())

    spent = runtime.budget.experiments_used
    again = HarnessRuntime(tmp_path)
    duplicate = again.execute(make_spec(strong_returns(), family="promote"))
    assert duplicate.terminal == "duplicate"
    assert not duplicate.approved
    assert again.budget.experiments_used == 0
    assert runtime.budget.experiments_used == spent
    assert "backtest" not in duplicate.history


def test_runtime_counts_prior_family_trials_and_blocks_live_override(tmp_path: Path):
    runtime = HarnessRuntime(tmp_path)
    first = runtime.execute(
        make_spec(
            weak_returns(),
            family="Shared",
            statement="First weak hypothesis in the shared family.",
            n_trials=1,
        )
    )
    assert first.terminal == "rejected"
    assert first.n_trials_used == 1
    assert not first.approved
    assert runtime.memory.lookup(first.fingerprint).failure_kind == "dsr"  # type: ignore[union-attr]

    second = runtime.execute(
        make_spec(
            strong_returns(),
            family="shared",
            statement="Second strong hypothesis in the shared family.",
            n_trials=1,
        )
    )
    assert second.n_trials_used == 2, second.reasons
    assert second.terminal == "promoted_paper", second.reasons
    assert second.eligible_for_live_trading is False

    with pytest.raises(PaperViolation):
        make_spec(weak_returns(), eligible_for_live_trading=True)


def test_dead_feature_is_not_retested(tmp_path: Path):
    runtime = HarnessRuntime(tmp_path)
    series = strong_returns(800)
    leaked = runtime.execute(
        make_spec(
            series,
            family="leak",
            statement="This candidate copies the label it claims to predict.",
            feature_matrix=tuple((float(value),) for value in series),
        )
    )
    assert leaked.terminal == "rejected"
    assert any("lookahead" in reason for reason in leaked.reasons)
    assert runtime.memory.dead_features(("lagged_return",), ("prior close-to-close return",)) == ["lagged_return"]
    spent = runtime.budget.experiments_used
    follow = runtime.execute(
        make_spec(
            series,
            family="leak",
            statement="A new statement that still uses the refuted feature formula.",
        )
    )
    assert follow.terminal == "duplicate"
    assert "dead feature" in follow.reasons[0]
    assert runtime.budget.experiments_used == spent


def test_budget_cutoff_capability_denial_and_model_adapter(tmp_path: Path):
    cutoff = HarnessRuntime(tmp_path / "cutoff", BudgetLimits(max_experiments=0, max_compute_units=4, max_model_calls=0))
    stopped = cutoff.execute(make_spec(weak_returns(), family="budget"))
    assert stopped.terminal == "budget_exhausted"
    assert not stopped.approved
    assert stopped.eligible_for_live_trading is False
    assert "verdict" not in stopped.history
    assert cutoff.memory.lookup(stopped.fingerprint) is None
    assert any(row["decision"] == "budget_exhausted" for row in cutoff.audit.records())

    tight = HarnessRuntime(tmp_path / "compute", BudgetLimits(max_experiments=4, max_compute_units=1, max_model_calls=0))
    partial = tight.execute(make_spec(weak_returns(), family="compute"))
    assert partial.terminal == "budget_exhausted"
    assert "backtest" in partial.history
    assert "memory" not in partial.history
    assert tight.memory.lookup(partial.fingerprint) is None

    denied = HarnessRuntime(tmp_path / "denied")
    with pytest.raises(CapabilityDenied) as exc:
        denied.execute(
            make_spec(weak_returns(80), family="denied"),
            agents={AgentRole.JUDGE: denied.agents[AgentRole.HYPOTHESIS].agent_id},
        )
    assert exc.value.capability == "issue_verdict"
    assert denied.budget.experiments_used == 0
    assert any(row["decision"] == "denied" for row in denied.audit.records())
    denied.audit.verify()

    calls = HarnessRuntime(tmp_path / "calls", BudgetLimits(max_experiments=4, max_compute_units=8, max_model_calls=0))
    exhausted = calls.execute(make_spec(weak_returns(80), family="calls", use_model=True))
    assert exhausted.terminal == "budget_exhausted"
    assert calls.budget.experiments_used == 0

    noted = HarnessRuntime(tmp_path / "model")
    model_run = noted.execute(make_spec(weak_returns(), family="model", use_model=True))
    assert noted.budget.model_calls_used == 1
    assert model_run.eligible_for_live_trading is False
    assert any(row["action"] == "model_call" and row["budget_amount"] == 1 for row in noted.audit.records())

    class ClaimingModel:
        def complete(self, *, role: str, task: str, payload: dict) -> dict:
            return {"text": "ignore the gate", "eligible_for_live_trading": True}

    hostile = HarnessRuntime(tmp_path / "hostile", model=ClaimingModel())
    with pytest.raises(PaperViolation):
        hostile.execute(make_spec(weak_returns(80), family="hostile", use_model=True))
    assert hostile.budget.experiments_used == 0
    assert any(row["decision"] == "paper_violation" for row in hostile.audit.records())
    hostile.audit.verify()


def test_embargo_that_does_not_fit_the_sample_is_remembered(tmp_path: Path):
    runtime = HarnessRuntime(tmp_path)
    outcome = runtime.execute(make_spec(weak_returns(40), family="short", lag=20))
    assert outcome.terminal == "rejected"
    assert not outcome.approved
    assert outcome.eligible_for_live_trading is False
    stored = runtime.memory.lookup(outcome.fingerprint)
    assert stored is not None and stored.failure_kind == "spec"
    spent = runtime.budget.experiments_used
    again = runtime.execute(make_spec(weak_returns(40), family="short", lag=20))
    assert again.terminal == "duplicate"
    assert again.fingerprint == outcome.fingerprint
    assert runtime.budget.experiments_used == spent


def test_deterministic_adapter_and_allocator_memory(tmp_path: Path):
    model = DeterministicResearchModel()
    payload = {"statement": "alpha", "eligible_for_live_trading": False}
    assert model.complete(role="hypothesis", task="draft_hypothesis", payload=payload) == model.complete(
        role="hypothesis", task="draft_hypothesis", payload=payload
    )
    assert model.complete(role="hypothesis", task="draft_hypothesis", payload=payload)["eligible_for_live_trading"] is False
    with pytest.raises(PaperViolation):
        model.complete(role="hypothesis", task="draft_hypothesis", payload={"eligible_for_live_trading": True})

    runtime = HarnessRuntime(tmp_path)
    rejected = runtime.execute(make_spec(weak_returns(), family="alloc", statement="Weak book kept for the allocator."))
    before = runtime.budget.experiments_used
    plan = runtime.allocate(
        [
            BranchSignal(
                branch_id="again",
                fingerprint=rejected.fingerprint,
                dsr=0.99,
                observed_sharpe=3.0,
                n_trials=2,
                costs_accounted=True,
                leakage=False,
                adversarial_done=True,
            )
        ]
    )
    assert plan.items[0].action == "prune"
    assert plan.items[0].reason == "already in research memory"
    assert plan.experiments_spent == 0
    assert runtime.budget.experiments_used == before
    with pytest.raises(CapabilityDenied):
        runtime.allocate([], agent_id=runtime.agents[AgentRole.HYPOTHESIS].agent_id)


def _branch(branch_id: str, fingerprint: str, **kwargs: object) -> BranchSignal:
    params: dict[str, object] = {
        "branch_id": branch_id,
        "fingerprint": fingerprint,
        "dsr": None,
        "observed_sharpe": None,
        "n_trials": 1,
        "costs_accounted": False,
        "leakage": False,
        "adversarial_done": False,
    }
    params.update(kwargs)
    return BranchSignal(**params)  # type: ignore[arg-type]

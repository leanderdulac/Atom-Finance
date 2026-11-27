"""Stable agent identity and least-privilege capabilities.

A role is fixed for the life of an id. The allowlist is the only source of
what that role may do. There is no path that adds a capability at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from app.harness.errors import AgentNotFound, CapabilityDenied


class AgentRole(StrEnum):
    HYPOTHESIS = "hypothesis"
    EVIDENCE = "evidence"
    CODE = "code"
    EXPERIMENT = "experiment"
    ADVERSARIAL = "adversarial"
    JUDGE = "judge"
    ALLOCATOR = "allocator"


class Capability(StrEnum):
    DRAFT_HYPOTHESIS = "draft_hypothesis"
    READ_MEMORY = "read_memory"
    WRITE_FEATURE = "write_feature"
    WRITE_SIGNAL = "write_signal"
    RUN_BACKTEST = "run_backtest"
    REQUEST_GATE = "request_gate"
    ADVERSARIAL_PROBE = "adversarial_probe"
    ISSUE_VERDICT = "issue_verdict"
    COMMIT_MEMORY = "commit_memory"
    ALLOCATE_BUDGET = "allocate_budget"
    PRUNE_BRANCH = "prune_branch"
    READ_AUDIT = "read_audit"


# Least privilege: each role can do its job and cannot do the next role's job.
ALLOWLIST: dict[AgentRole, frozenset[Capability]] = {
    AgentRole.HYPOTHESIS: frozenset({Capability.DRAFT_HYPOTHESIS, Capability.READ_MEMORY}),
    AgentRole.EVIDENCE: frozenset({Capability.READ_MEMORY, Capability.WRITE_FEATURE, Capability.READ_AUDIT}),
    AgentRole.CODE: frozenset({Capability.WRITE_FEATURE, Capability.WRITE_SIGNAL}),
    AgentRole.EXPERIMENT: frozenset({Capability.RUN_BACKTEST, Capability.REQUEST_GATE, Capability.READ_MEMORY}),
    AgentRole.ADVERSARIAL: frozenset(
        {
            Capability.ADVERSARIAL_PROBE,
            Capability.READ_MEMORY,
            Capability.READ_AUDIT,
            Capability.REQUEST_GATE,
        }
    ),
    AgentRole.JUDGE: frozenset(
        {
            Capability.ISSUE_VERDICT,
            Capability.REQUEST_GATE,
            Capability.READ_AUDIT,
            Capability.READ_MEMORY,
            Capability.COMMIT_MEMORY,
        }
    ),
    AgentRole.ALLOCATOR: frozenset(
        {
            Capability.ALLOCATE_BUDGET,
            Capability.PRUNE_BRANCH,
            Capability.READ_MEMORY,
            Capability.READ_AUDIT,
        }
    ),
}

# The capability a role must hold to take its step in the research loop.
DUTIES: dict[AgentRole, Capability] = {
    AgentRole.HYPOTHESIS: Capability.DRAFT_HYPOTHESIS,
    AgentRole.EVIDENCE: Capability.WRITE_FEATURE,
    AgentRole.CODE: Capability.WRITE_SIGNAL,
    AgentRole.EXPERIMENT: Capability.RUN_BACKTEST,
    AgentRole.ADVERSARIAL: Capability.ADVERSARIAL_PROBE,
    AgentRole.JUDGE: Capability.ISSUE_VERDICT,
    AgentRole.ALLOCATOR: Capability.ALLOCATE_BUDGET,
}


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: str
    role: AgentRole
    capabilities: frozenset[Capability]

    def allows(self, capability: Capability) -> bool:
        return capability in self.capabilities


def authorize(agent: AgentIdentity, capability: Capability) -> None:
    if capability not in agent.capabilities:
        raise CapabilityDenied(agent.agent_id, agent.role.value, capability.value)


class AgentRegistry:
    """Ids are stable. Registering the same id under a second role is denied."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentIdentity] = {}

    def register(self, role: AgentRole, agent_id: str | None = None) -> AgentIdentity:
        chosen = agent_id or f"{role.value}:{uuid4()}"
        existing = self._agents.get(chosen)
        if existing is not None:
            if existing.role != role:
                raise CapabilityDenied(chosen, existing.role.value, f"change_role:{role.value}")
            return existing
        identity = AgentIdentity(agent_id=chosen, role=role, capabilities=ALLOWLIST[role])
        self._agents[chosen] = identity
        return identity

    def get(self, agent_id: str) -> AgentIdentity:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise AgentNotFound(agent_id) from None

    def __len__(self) -> int:
        return len(self._agents)

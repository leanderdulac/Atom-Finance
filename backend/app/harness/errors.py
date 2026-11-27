"""Failures of the research harness.

Scientific rejection (a gate that says no) is a result, not one of these.
These are broken runs: a live-trading flag, a skipped lifecycle step,
a capability the role does not have, a spent budget, or a torn audit log.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base type for harness failures."""


class PaperViolation(HarnessError):
    """``eligible_for_live_trading`` was not false."""


class IllegalTransition(HarnessError):
    """The research loop was asked to skip or rewind a phase."""


class CapabilityDenied(HarnessError):
    """An agent asked for an action outside its role."""

    def __init__(self, agent_id: str, role: str, capability: str) -> None:
        self.agent_id = agent_id
        self.role = role
        self.capability = capability
        super().__init__(f"{role}:{agent_id} cannot {capability}")


class AgentNotFound(HarnessError):
    """No registered agent has this id."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"unknown agent {agent_id}")


class BudgetExhausted(HarnessError):
    """A hard experiment, compute, or model-call budget has been spent."""

    def __init__(self, kind: str, used: int, limit: int, requested: int) -> None:
        self.kind = kind
        self.used = used
        self.limit = limit
        self.requested = requested
        super().__init__(f"{kind} budget exhausted ({used}/{limit}, requested {requested})")


class VerdictOverride(HarnessError):
    """A judge tried to promote a candidate the verifiable gate rejected."""


class AuditIntegrityError(HarnessError):
    """The append-only ledger no longer matches its hash chain."""

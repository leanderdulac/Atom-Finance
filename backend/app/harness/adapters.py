"""Model-agnostic research adapter.

The default implementation is deterministic and makes no network call.
An implementation that does call a hosted model must send the task through
``AIFactory.complete``, which already prefixes the desk doctrine. The adapter
cannot authorize live trading and is not the promotion gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.harness.codec import fingerprint
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING, enforce_paper


class ResearchModel(Protocol):
    def complete(self, *, role: str, task: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a structured note. Must include ``eligible_for_live_trading: false``."""
        raise NotImplementedError


class DeterministicResearchModel:
    """Same input, same note. Used by tests and by runs that do not call a model."""

    model_id = "deterministic-research-adapter"

    def complete(self, *, role: str, task: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        enforce_paper(payload)
        digest = fingerprint({"role": role, "task": task, "payload": dict(payload)})
        return {
            "role": role,
            "task": task,
            "text": f"{role}:{task}:{digest[:16]}",
            "model": self.model_id,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }

"""Paper-only stamp for every harness result.

The flag is the same constant the rest of the desk uses. A caller that
tries to set it true is rejected. Nothing in this package places an order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.harness.errors import PaperViolation
from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING

__all__ = ["ELIGIBLE_FOR_LIVE_TRADING", "enforce_paper", "paper_stamp"]


def enforce_paper(value: object) -> None:
    """Raise if a payload claims live trading, or if the desk constant is not false."""
    if ELIGIBLE_FOR_LIVE_TRADING is not False:
        raise PaperViolation("eligible_for_live_trading must remain false")
    if isinstance(value, Mapping) and value.get("eligible_for_live_trading", False) is not False:
        raise PaperViolation("eligible_for_live_trading must remain false")
    if not isinstance(value, Mapping) and value is not False:
        raise PaperViolation("eligible_for_live_trading must remain false")


def paper_stamp(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy ``payload`` and set the live-trading flag to the desk constant."""
    enforce_paper(payload)
    stamped = dict(payload)
    stamped["eligible_for_live_trading"] = ELIGIBLE_FOR_LIVE_TRADING
    enforce_paper(stamped)
    return stamped

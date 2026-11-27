"""Paper-only research harness.

The loop, the gate, the agent roster, the budget, the audit log, the
cross-run memory, and the budget allocator. ``eligible_for_live_trading``
stays false. This package does not place orders.
"""

from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.runtime import HarnessRuntime

__all__ = ["ELIGIBLE_FOR_LIVE_TRADING", "HarnessRuntime"]

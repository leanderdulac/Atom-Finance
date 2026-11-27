"""Verifiable promotion gate.

A candidate is promoted to the paper book only when the causal contract holds,
fee and slippage are in the net returns, the Deflated Sharpe gate clears
multiple testing, and live trading is off. The statistical half reuses
``app.models.afml.gate`` and is not sufficient on its own.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from app.harness.causal import probe
from app.harness.errors import PaperViolation, VerdictOverride
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING, enforce_paper
from app.harness.types import BacktestReport, GateDecision
from app.models.afml.gate import gate as multiple_testing_gate
from app.models.trading_costs import costs_included_flag, leg_rate_bps
from app.models.winners_curse import DEFAULT_DSR_THRESHOLD


def assert_verdict_matches(decision: GateDecision, claimed_promoted: bool) -> None:
    """Judges record the gate. They do not replace it."""
    enforce_paper(decision.eligible_for_live_trading)
    if claimed_promoted is not decision.approved:
        raise VerdictOverride("judge cannot override the verifiable gate")


class VerifiableGate:
    def __init__(self, threshold: float = DEFAULT_DSR_THRESHOLD) -> None:
        if not np.isfinite(threshold) or not 0.0 < threshold < 1.0:
            raise ValueError("DSR threshold must lie in (0, 1)")
        self.threshold = float(threshold)

    def evaluate(
        self,
        report: BacktestReport,
        *,
        n_trials: int | None = None,
        eligible_for_live_trading: bool = False,
    ) -> GateDecision:
        if eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise PaperViolation("eligible_for_live_trading must remain false")
        enforce_paper({"eligible_for_live_trading": report.eligible_for_live_trading})

        used = report.n_trials if n_trials is None else int(n_trials)
        lookahead = probe(report)
        cost = _cost_failures(report)
        causal_ok = not lookahead
        costs_ok = not cost
        statistical_reasons: list[str] = []
        dsr: float | None = None
        observed: float | None = None
        dsr_ok = False
        if len(report.net_returns) >= 3 and used >= 1:
            # costs_included=True isolates multiple testing. Promotion still
            # requires the harness cost check, which is independent of this call.
            statistical = multiple_testing_gate(
                costs_included=True,
                returns=report.net_returns,
                n_trials=float(used),
                trial_sharpes=report.trial_sharpes,
                threshold=self.threshold,
            )
            dsr = None if statistical.dsr is None else float(statistical.dsr)
            observed = None if statistical.observed_sharpe is None else float(statistical.observed_sharpe)
            dsr_ok = bool(statistical.approved and used >= 2 and dsr is not None and dsr >= self.threshold)
            if used < 2:
                statistical_reasons.append(
                    f"multiple-testing: N={used} is below 2, so the Sharpe was not deflated"
                )
            elif not dsr_ok:
                shown = "nan" if dsr is None else f"{dsr:.4f}"
                statistical_reasons.append(f"DSR {shown} is below {self.threshold:.2f} after N={used}")
                statistical_reasons.extend(statistical.reasons)
        else:
            statistical_reasons.append("multiple-testing: the net sample or N is too small to deflate a Sharpe")

        approved = bool(causal_ok and costs_ok and dsr_ok and ELIGIBLE_FOR_LIVE_TRADING is False)
        return GateDecision(
            approved=approved,
            reasons=tuple([*lookahead, *cost, *statistical_reasons]),
            causal_ok=causal_ok,
            costs_ok=costs_ok,
            dsr_ok=dsr_ok,
            paper_ok=True,
            dsr=dsr,
            observed_sharpe=observed,
            n_trials=used,
        )


def _cost_failures(report: BacktestReport) -> list[str]:
    reasons: list[str] = []
    try:
        rate_bps = leg_rate_bps(report.commission_bps, report.half_spread_bps, report.slippage_bps)
    except ValueError as exc:
        return [str(exc)]
    one_way = rate_bps / 10_000.0
    if report.slippage_bps <= 0.0 and report.half_spread_bps <= 0.0:
        reasons.append("slippage and half-spread are both zero, so the book was not costed")
    if not costs_included_flag(round_trip_cost=one_way, model_applied=True):
        reasons.append("transaction cost is missing from the net returns")
    gross = np.asarray(report.gross_returns, dtype=np.float64)
    net = np.asarray(report.net_returns, dtype=np.float64)
    turnover = np.asarray(report.turnover, dtype=np.float64)
    if gross.shape != net.shape or net.shape != turnover.shape or net.ndim != 1 or len(net) < 3:
        reasons.append("cost series are missing or misaligned")
        return reasons
    if not np.all(np.isfinite(gross)) or not np.all(np.isfinite(net)) or not np.all(np.isfinite(turnover)):
        reasons.append("cost series must be finite")
        return reasons
    expected = gross - turnover * one_way
    if not np.allclose(net, expected, rtol=0.0, atol=1e-8):
        reasons.append("net returns do not match gross minus fee, half-spread, and slippage")
    if float(np.sum(turnover)) <= 0.0:
        reasons.append("turnover is zero, so costs were never applied")
    return reasons


def with_trials(report: BacktestReport, n_trials: int) -> BacktestReport:
    return replace(report, n_trials=int(n_trials))

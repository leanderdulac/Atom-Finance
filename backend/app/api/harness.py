"""Operator routes for the paper research harness.

The route runs the in-process roster. It does not accept a client-chosen
role, and it cannot set ``eligible_for_live_trading``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.limiter import limiter
from app.harness.allocator import BranchSignal
from app.harness.errors import AuditIntegrityError, PaperViolation
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.runtime import HarnessRuntime
from app.harness.types import ExperimentSpec

router = APIRouter()


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=8, max_length=2000)
    family: str = Field(min_length=1, max_length=80)
    feature_names: list[str] = Field(min_length=1, max_length=20)
    feature_formulas: list[str] | None = None
    prices: list[float] = Field(min_length=30, max_length=5000)
    signal: list[float] = Field(min_length=29, max_length=4999)
    feature_matrix: list[list[float]] | None = None
    lag: int = Field(default=1, ge=1, le=20)
    commission_bps: float = Field(default=5, ge=0, le=100)
    slippage_bps: float = Field(default=5, ge=0, le=100)
    half_spread_bps: float = Field(default=2, ge=0, le=100)
    n_trials: int = Field(default=2, ge=1, le=1_000_000)
    use_model: bool = False
    eligible_for_live_trading: bool = False

    @field_validator("eligible_for_live_trading")
    @classmethod
    def paper_only(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("eligible_for_live_trading must remain false")
        return False

    def to_spec(self) -> ExperimentSpec:
        formulas = tuple(self.feature_formulas) if self.feature_formulas is not None else tuple(self.feature_names)
        matrix = None if self.feature_matrix is None else tuple(tuple(float(v) for v in row) for row in self.feature_matrix)
        return ExperimentSpec(
            statement=self.statement,
            family=self.family,
            feature_names=tuple(self.feature_names),
            feature_formulas=formulas,
            prices=tuple(float(v) for v in self.prices),
            signal=tuple(float(v) for v in self.signal),
            feature_matrix=matrix,
            lag=self.lag,
            commission_bps=self.commission_bps,
            slippage_bps=self.slippage_bps,
            half_spread_bps=self.half_spread_bps,
            n_trials=self.n_trials,
            use_model=self.use_model,
        )


class BranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: str = Field(min_length=1, max_length=80)
    fingerprint: str = Field(min_length=8, max_length=128)
    dsr: float | None = None
    observed_sharpe: float | None = None
    n_trials: int = Field(default=1, ge=0, le=1_000_000)
    costs_accounted: bool = False
    leakage: bool = False
    adversarial_done: bool = False
    fold_sharpes: list[float] = Field(default_factory=list, max_length=32)
    known_dead: bool = False
    already_tested: bool = False
    eligible_for_live_trading: bool = False

    @field_validator("eligible_for_live_trading")
    @classmethod
    def paper_only(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("eligible_for_live_trading must remain false")
        return False

    def to_signal(self) -> BranchSignal:
        return BranchSignal(
            branch_id=self.branch_id,
            fingerprint=self.fingerprint,
            dsr=self.dsr,
            observed_sharpe=self.observed_sharpe,
            n_trials=self.n_trials,
            costs_accounted=self.costs_accounted,
            leakage=self.leakage,
            adversarial_done=self.adversarial_done,
            fold_sharpes=tuple(self.fold_sharpes),
            known_dead=self.known_dead,
            already_tested=self.already_tested,
        )


class AllocateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branches: list[BranchIn] = Field(max_length=32)


def get_runtime(request: Request) -> HarnessRuntime:
    existing = getattr(request.app.state, "harness", None)
    if isinstance(existing, HarnessRuntime):
        return existing
    root = Path(os.environ.get("ATOM_HARNESS_DIR", Path(tempfile.gettempdir()) / "atom-harness"))
    runtime = HarnessRuntime(root)
    request.app.state.harness = runtime
    return runtime


@router.post("/runs")
@limiter.limit("30/minute")
async def create_run(request: Request, body: RunIn):
    runtime = get_runtime(request)
    try:
        outcome = runtime.execute(body.to_spec())
    except PaperViolation as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return outcome.to_dict()


@router.post("/allocate")
@limiter.limit("30/minute")
async def allocate(request: Request, body: AllocateIn):
    runtime = get_runtime(request)
    plan = runtime.allocate([branch.to_signal() for branch in body.branches])
    return plan.to_dict()


@router.get("/memory/{fingerprint}")
@limiter.limit("60/minute")
async def read_memory(request: Request, fingerprint: str):
    runtime = get_runtime(request)
    record = runtime.memory.lookup(fingerprint)
    if record is None:
        raise HTTPException(404, "No stored hypothesis for that fingerprint.")
    return {
        "fingerprint": record.fingerprint,
        "family": record.family,
        "status": record.status,
        "failure_kind": record.failure_kind,
        "run_id": record.run_id,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


@router.get("/audit")
@limiter.limit("60/minute")
async def read_audit(request: Request):
    runtime = get_runtime(request)
    try:
        count = runtime.audit.verify()
    except AuditIntegrityError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "count": count, "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING}

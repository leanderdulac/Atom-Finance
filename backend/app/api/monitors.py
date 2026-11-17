"""Thesis monitors: declare a paper operation, check it against the oracle.

Mounted under /api/client so analysts keep access when ATOM_CLIENT_MODE
locks the desk. A declaration snapshots a simulation baseline (conditioned
on entry at the level); each check evaluates the live spot against the
declared levels. This module never writes the paper-trades diary.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.models.derivatives_planner import StrictModel
from app.models.monitor import TERMINAL, evaluate, validate_geometry
from app.models.simulation import simulate_levels
from app.services import oracle
from app.services.market_sources import SourceError

router = APIRouter()

_TICKER_RE = r"^[A-Za-z0-9.\-=]{1,25}$"


class MonitorDeclare(StrictModel):
    ticker: str = Field(min_length=1, max_length=25, pattern=_TICKER_RE)
    direction: Literal["long", "short"]
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    horizon_days: int = Field(ge=1, le=365)
    size: float = Field(1.0, gt=0)
    vol_annual: float = Field(gt=0, le=5)
    note: str = Field("", max_length=500)


def _row_to_monitor(row: dict) -> dict:
    return {
        "direction": row["direction"], "entry": float(row["entry"]),
        "stop": float(row["stop"]), "target": float(row["target"]),
        "declared_at": row["declared_at"].isoformat()
        if hasattr(row["declared_at"], "isoformat") else str(row["declared_at"]),
        "horizon_days": int(row["horizon_days"]), "state": row["state"],
        "last_spot": row.get("last_spot"),
        "entered_at": row["entered_at"].isoformat()
        if row.get("entered_at") and hasattr(row["entered_at"], "isoformat")
        else row.get("entered_at"),
        "entry_px": row.get("entry_px"),
    }


@router.post("/monitors", status_code=201)
@limiter.limit("10/minute")
async def declare(request: Request, req: MonitorDeclare,
                  owner: str = Depends(get_current_user)):
    try:
        validate_geometry(req.direction, req.entry, req.stop, req.target)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        asset_class = oracle.classify(req.ticker)
    except SourceError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    baseline = await asyncio.to_thread(
        simulate_levels, req.entry,
        "long" if req.direction == "long" else "short",
        req.entry, req.stop, req.target, req.horizon_days, req.vol_annual,
        0.0, 5000, 7, req.size, 0.0,
    )
    monitor_id = str(uuid4())
    now = datetime.now(UTC)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        from app.api.paper_trades import lock_owner
        await lock_owner(conn, owner)
        await conn.execute(
            "INSERT INTO operation_monitors (id, owner, ticker, direction, entry, stop,"
            " target, horizon_days, size, vol_annual, baseline, state, declared_at, note)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
            monitor_id, owner, req.ticker.strip().upper(), req.direction,
            req.entry, req.stop, req.target, req.horizon_days, req.size,
            req.vol_annual, baseline, "watching", now, req.note,
        )
    return {"id": monitor_id, "state": "watching", "asset_class": asset_class,
            "baseline": baseline, "declared_at": now.isoformat(),
            "eligible_for_live_trading": False}


@router.get("/monitors")
@limiter.limit("30/minute")
async def list_monitors(request: Request, owner: str = Depends(get_current_user),
                        limit: int = Query(50, ge=1, le=200)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, ticker, direction, entry, stop, target, horizon_days,"
            " state, declared_at, last_spot, last_check FROM operation_monitors"
            " WHERE owner=$1 ORDER BY declared_at DESC LIMIT $2", owner, limit)
    return {"monitors": [
        {**dict(r),
         "declared_at": r["declared_at"].isoformat(),
         "last_check": r["last_check"].isoformat() if r["last_check"] else None}
        for r in rows]}


@router.get("/monitors/{monitor_id}")
@limiter.limit("30/minute")
async def get_monitor(request: Request, monitor_id: str,
                      owner: str = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM operation_monitors WHERE id=$1 AND owner=$2",
            monitor_id, owner)
        if not row:
            raise HTTPException(404, "Monitor não encontrado.")
        checks = await conn.fetch(
            "SELECT checked_at, spot, oracle_usable, state, alerts, metrics"
            " FROM monitor_checks WHERE monitor_id=$1 AND owner=$2"
            " ORDER BY checked_at DESC LIMIT 50", monitor_id, owner)
    monitor = dict(row)
    monitor["declared_at"] = row["declared_at"].isoformat()
    for key in ("entered_at", "last_check"):
        monitor[key] = row[key].isoformat() if row[key] else None
    monitor["checks"] = [
        {**dict(c), "checked_at": c["checked_at"].isoformat()} for c in checks]
    return monitor


@router.post("/monitors/{monitor_id}/check")
@limiter.limit("20/minute")
async def check_monitor(request: Request, monitor_id: str,
                        owner: str = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        from app.api.paper_trades import lock_owner
        await lock_owner(conn, owner)
        row = await conn.fetchrow(
            "SELECT * FROM operation_monitors WHERE id=$1 AND owner=$2",
            monitor_id, owner)
        if not row:
            raise HTTPException(404, "Monitor não encontrado.")
        if row["state"] in TERMINAL:
            return {"id": monitor_id, "state": row["state"], "terminal": True,
                    "note": "Monitor encerrado; leituras novas não mudam o estado.",
                    "eligible_for_live_trading": False}
        try:
            quote = await oracle.spot(row["ticker"], owner)
        except SourceError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        if not quote["usable"] or quote["price"] is None:
            raise HTTPException(502, "; ".join(quote["blockers"]) or "Oráculo sem cotação.")
        now = datetime.now(UTC)
        try:
            result = evaluate(
                _row_to_monitor(dict(row)), float(quote["price"]), now.isoformat(),
                {"usable": quote["usable"], "stale": bool(quote["stale"]),
                 "disagreement_bps": quote["disagreement_bps"]},
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await conn.execute(
            "UPDATE operation_monitors SET state=$1, last_spot=$2, last_check=$3,"
            " entered_at=$4, entry_px=$5 WHERE id=$6 AND owner=$7",
            result["state"], float(quote["price"]), now,
            _as_dt(result["entered_at"]), result["entry_px"], monitor_id, owner)
        await conn.execute(
            "INSERT INTO monitor_checks (id, monitor_id, owner, checked_at, spot,"
            " oracle_usable, disagreement_bps, state, alerts, metrics)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            str(uuid4()), monitor_id, owner, now, float(quote["price"]),
            bool(quote["usable"]), quote["disagreement_bps"], result["state"],
            result["alerts"], result["metrics"])
    return {"id": monitor_id, **result}


def _as_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value)


@router.delete("/monitors/{monitor_id}")
@limiter.limit("10/minute")
async def delete_monitor(request: Request, monitor_id: str,
                         owner: str = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        from app.api.paper_trades import lock_owner
        await lock_owner(conn, owner)
        await conn.execute("DELETE FROM monitor_checks WHERE monitor_id=$1 AND owner=$2",
                           monitor_id, owner)
        deleted = await conn.execute(
            "DELETE FROM operation_monitors WHERE id=$1 AND owner=$2", monitor_id, owner)
    if deleted == "DELETE 0":
        raise HTTPException(404, "Monitor não encontrado.")
    return {"deleted": monitor_id}

"""Authenticated deterministic derivatives planning, with owner-scoped saved snapshots."""
import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.models.derivatives_planner import PlanRequest, make_plans

router = APIRouter(dependencies=[Depends(get_current_user)])


async def save(owner, req, result):
    run_id = str(uuid4())
    result['id'] = run_id
    pool = await get_pool()
    await pool.execute(
        'INSERT INTO derivative_plans (id, owner, created_at, payload, result) VALUES ($1, $2, $3, $4, $5)',
        run_id, owner, datetime.fromisoformat(result['created_at']), req.model_dump(mode='json'), result,
    )
    return result


@router.post('/plan')
@limiter.limit('10/minute')
async def plan(request: Request, req: PlanRequest, owner: str = Depends(get_current_user)):
    result = await asyncio.to_thread(make_plans, req)
    return await save(owner, req, result)


@router.get('/plans')
async def history(owner: str = Depends(get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch(
        'SELECT id, created_at FROM derivative_plans WHERE owner=$1 ORDER BY created_at DESC LIMIT 50', owner,
    )
    return [dict(r) for r in rows]


@router.get('/plans/{run_id}')
async def detail(run_id: str, owner: str = Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow(
        'SELECT payload, result FROM derivative_plans WHERE id=$1 AND owner=$2', run_id, owner,
    )
    if row is None:
        raise HTTPException(404, 'Plano não encontrado.')
    return {'inputs': row['payload'], 'result': row['result']}

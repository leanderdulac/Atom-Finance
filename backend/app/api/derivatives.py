"""Authenticated deterministic derivatives planning, with owner-scoped saved snapshots."""
import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.database import _get_conn
from app.models.derivatives_planner import PlanRequest, make_plans

router = APIRouter(dependencies=[Depends(get_current_user)])

def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS derivative_plans (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
        payload TEXT NOT NULL, result TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS derivative_plans_owner ON derivative_plans(owner, created_at)')

def save(owner, req, result):
    run_id = str(uuid4()); result['id'] = run_id
    with _get_conn() as conn:
        setup(conn)
        conn.execute('INSERT INTO derivative_plans VALUES (?, ?, ?, ?, ?)',
                     (run_id, owner, result['created_at'], req.model_dump_json(), json.dumps(result, allow_nan=False)))
        conn.commit()
    return result

@router.post('/plan')
@limiter.limit('10/minute')
async def plan(request: Request, req: PlanRequest, owner: str = Depends(get_current_user)):
    result = await asyncio.to_thread(make_plans, req)
    return await asyncio.to_thread(save, owner, req, result)

@router.get('/plans')
def history(owner: str = Depends(get_current_user)):
    with _get_conn() as conn:
        setup(conn)
        return [dict(r) for r in conn.execute('SELECT id, created_at FROM derivative_plans WHERE owner=? ORDER BY created_at DESC LIMIT 50', (owner,))]

@router.get('/plans/{run_id}')
def detail(run_id: str, owner: str = Depends(get_current_user)):
    with _get_conn() as conn:
        setup(conn)
        row = conn.execute('SELECT payload, result FROM derivative_plans WHERE id=? AND owner=?', (run_id, owner)).fetchone()
        if row is None: raise HTTPException(404, 'Plano não encontrado.')
        return {'inputs': json.loads(row['payload']), 'result': json.loads(row['result'])}

"""Owner-scoped research journal. Inputs and completed outcomes cannot be edited."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db.postgres import get_pool


async def begin(owner, inputs):
    payload = json.dumps(inputs, sort_keys=True, separators=(',', ':'), allow_nan=False)
    run_id = str(uuid4())
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO experiments (id, owner, created_at, status, input_hash, inputs) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        run_id, owner, datetime.now(UTC), 'running',
        hashlib.sha256(payload.encode()).hexdigest(), inputs,
    )
    return run_id


async def finish(run_id, result=None, error=None):
    pool = await get_pool()
    await pool.execute(
        "UPDATE experiments SET status=$1, result=$2, error=$3 WHERE id=$4 AND status='running'",
        'failed' if error else 'completed', result, error, run_id,
    )


async def history(owner, limit=50, offset=0):
    pool = await get_pool()
    rows = await pool.fetch(
        'SELECT * FROM experiments WHERE owner=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',
        owner, limit, offset,
    )
    count = await pool.fetchval('SELECT COUNT(*) FROM experiments WHERE owner=$1', owner)
    items = []
    for row in rows:
        inp = row['inputs']
        result = row['result'] or {}
        items.append({k: row[k] for k in ('id', 'created_at', 'status', 'input_hash', 'error')} | {
            'hypothesis': inp['hypothesis'], 'data_source': inp['data_source'], 'model': inp['model'],
            'assessment': result.get('assessment')})
    return {'items': items, 'total': count}


async def detail(owner, run_id):
    pool = await get_pool()
    row = await pool.fetchrow('SELECT * FROM experiments WHERE id=$1 AND owner=$2', run_id, owner)
    if not row:
        return None
    result = {k: row[k] for k in ('id', 'created_at', 'status', 'input_hash', 'error')}
    result.update(inputs=row['inputs'], result=row['result'])
    reviews = await pool.fetch(
        'SELECT id, created_at, decision, rationale FROM experiment_reviews '
        'WHERE experiment_id=$1 ORDER BY created_at', run_id,
    )
    result['reviews'] = [dict(r) for r in reviews]
    return result


async def review(owner, run_id, decision, rationale):
    pool = await get_pool()
    status = await pool.fetchval('SELECT status FROM experiments WHERE id=$1 AND owner=$2', run_id, owner)
    if status != 'completed':
        return False
    await pool.execute(
        'INSERT INTO experiment_reviews (id, experiment_id, created_at, decision, rationale) '
        'VALUES ($1, $2, $3, $4, $5)',
        str(uuid4()), run_id, datetime.now(UTC), decision, rationale,
    )
    return True

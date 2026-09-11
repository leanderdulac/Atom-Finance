"""Owner-scoped research journal. Inputs and completed outcomes cannot be edited."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db.database import _get_conn


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS experiments (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL, input_hash TEXT NOT NULL, inputs TEXT NOT NULL,
        result TEXT, error TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS experiments_owner ON experiments(owner, created_at)')
    conn.execute('''CREATE TABLE IF NOT EXISTS experiment_reviews (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, created_at TEXT NOT NULL,
        decision TEXT NOT NULL, rationale TEXT NOT NULL)''')


def begin(owner, inputs):
    payload = json.dumps(inputs, sort_keys=True, separators=(',', ':'), allow_nan=False)
    run_id = str(uuid4())
    with _get_conn() as conn:
        setup(conn)
        conn.execute('INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)',
                     (run_id, owner, datetime.now(UTC).isoformat(), 'running',
                      hashlib.sha256(payload.encode()).hexdigest(), payload))
        conn.commit()
    return run_id


def finish(run_id, result=None, error=None):
    with _get_conn() as conn:
        setup(conn)
        conn.execute("UPDATE experiments SET status=?, result=?, error=? WHERE id=? AND status='running'",
                     ('failed' if error else 'completed', json.dumps(result, allow_nan=False) if result else None, error, run_id))
        conn.commit()


def history(owner, limit=50, offset=0):
    with _get_conn() as conn:
        setup(conn)
        rows = conn.execute('SELECT * FROM experiments WHERE owner=? ORDER BY created_at DESC LIMIT ? OFFSET ?',
                            (owner, limit, offset)).fetchall()
        count = conn.execute('SELECT COUNT(*) FROM experiments WHERE owner=?', (owner,)).fetchone()[0]
        items = []
        for row in rows:
            inp = json.loads(row['inputs']); result = json.loads(row['result']) if row['result'] else {}
            items.append({k: row[k] for k in ('id', 'created_at', 'status', 'input_hash', 'error')} | {
                'hypothesis': inp['hypothesis'], 'data_source': inp['data_source'], 'model': inp['model'],
                'assessment': result.get('assessment')})
        return {'items': items, 'total': count}


def detail(owner, run_id):
    with _get_conn() as conn:
        setup(conn)
        row = conn.execute('SELECT * FROM experiments WHERE id=? AND owner=?', (run_id, owner)).fetchone()
        if not row: return None
        result = {k: row[k] for k in ('id', 'created_at', 'status', 'input_hash', 'error')}
        result.update(inputs=json.loads(row['inputs']), result=json.loads(row['result']) if row['result'] else None)
        result['reviews'] = [dict(r) for r in conn.execute(
            'SELECT id, created_at, decision, rationale FROM experiment_reviews WHERE experiment_id=? ORDER BY created_at', (run_id,))]
        return result


def review(owner, run_id, decision, rationale):
    with _get_conn() as conn:
        setup(conn)
        row = conn.execute('SELECT status FROM experiments WHERE id=? AND owner=?', (run_id, owner)).fetchone()
        if not row or row['status'] != 'completed': return False
        conn.execute('INSERT INTO experiment_reviews VALUES (?, ?, ?, ?, ?)',
                     (str(uuid4()), run_id, datetime.now(UTC).isoformat(), decision, rationale))
        conn.commit()
        return True

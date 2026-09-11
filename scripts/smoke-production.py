"""Destructive only to test records: run against an isolated test deployment."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = os.environ.get('ATOM_SMOKE_URL', 'http://127.0.0.1:18080')
TOKEN = None


def call(path, expected=200, payload=None, authenticated=True):
    headers = {'Content-Type': 'application/json'}
    if authenticated and TOKEN:
        headers['Authorization'] = 'Bearer ' + TOKEN
    req = Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    try:
        response = urlopen(req, timeout=60)
    except HTTPError as exc:
        response = exc
    assert response.status == expected, (path, response.status, expected)
    raw = response.read()
    return json.loads(raw) if raw and response.headers.get('Content-Type','').startswith('application/json') else raw


assert call('/api/health') == {'status': 'healthy'}
call('/')
call('/api/ml/experiments', expected=401)
login = call('/api/auth/login', payload={'username':os.environ['ATOM_SMOKE_USER'], 'password':os.environ['ATOM_SMOKE_PASSWORD']})
TOKEN = login['access_token']
assert call('/api/auth/me')['username'] == os.environ['ATOM_SMOKE_USER']
call('/api/sources/status')
call('/api/derivatives/plans')
call('/api/binance/account', expected=410)
from datetime import date, timedelta
result = call('/api/ml/evaluate', payload={
    'prices':[100+i/100 for i in range(500)],
    'dates':[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(500)],
    'hypothesis':'A synthetic trend is only a test of the research workflow, never evidence of tradable alpha.',
    'data_source':'synthetic_demo', 'model':'ridge'})
record = call('/api/ml/experiments/' + result['run_id'])
assert record['status'] == 'completed'
assert record['result']['eligible_for_live_trading'] is False
print(json.dumps({'smoke':'passed', 'run_id':result['run_id']}))

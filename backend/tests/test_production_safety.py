"""Regression checks for the production boundary and disaster recovery."""
import json
import os
import re
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core.limiter import limiter
from app.core.runtime import exclusive_runtime
from app.core.security import create_access_token, get_current_user, hash_password
from app.db import database, experiments
from app.db.maintenance import backup, restore
from app.db.postgres import get_pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app


@pytest_asyncio.fixture
async def isolated():
    # _clean_db (conftest.py, autouse) already truncates every table before
    # this runs — no per-test SQLite file to point at anymore.
    limiter.reset()
    await database.create_user('alice', 'alice@example.test', hash_password('a-secure-test-password'))
    yield


@pytest.mark.asyncio
async def test_all_business_routes_require_auth(isolated):
    client = TestClient(app)
    checked = 0
    for path, operations in app.openapi()['paths'].items():
        if path in {'/api/health', '/api/live', '/api/auth/login', '/api/auth/register'}:
            continue
        path = re.sub(r"\{[^}]+\}", "1", path)
        for method in operations:
            if method not in {'get', 'post', 'put', 'patch', 'delete'}:
                continue
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked > 50


@pytest.mark.asyncio
async def test_disabled_user_token_is_revoked(isolated):
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token('alice'))
    assert await get_current_user(credentials) == 'alice'
    pool = await get_pool()
    await pool.execute("UPDATE users SET is_active=FALSE WHERE username='alice'")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_reports_private_and_legacy_quarantined(isolated):
    report_id = await database.save_report('PETR4', {'narrative': 'private'}, owner='alice')
    fetched = await database.get_report_by_id(report_id, owner='alice')
    assert fetched['narrative'] == 'private'
    assert await database.get_report_by_id(report_id, owner='bob') is None
    assert await database.list_reports(owner='bob') == []
    pool = await get_pool()
    await pool.execute('UPDATE reports SET owner=NULL')
    assert await database.list_reports(owner='alice') == []
    assert await database.get_report_by_id(report_id, owner='alice') is None


_HEALTH_SECRET_ENV = {
    'ANTHROPIC_API_KEY': 'sk-ant-abcdefghijklmnopqrstuvwxyz012345',
    'OPENAI_API_KEY': 'sk-proj-abcdefghijklmnopqrstuvwxyz012345',
    'PERPLEXITY_API_KEY': 'pplx-abcdefghijklmnopqrstuvwxyz012345',
    'GOOGLE_API_KEY': 'AIzaSyabcdefghijklmnopqrstuvwxyz012345678',
    'XAI_API_KEY': 'xai-abcdefghijklmnopqrstuvwxyz0123456789',
    'BRAPI_TOKEN': 'brapi-secret-token-abcdefghijklmnop',
}


def _assert_health_has_no_secret_fragments(payload: dict, secrets: dict[str, str]) -> None:
    blob = json.dumps(payload)
    for value in secrets.values():
        assert value not in blob
        if len(value) >= 8:
            # The pre-pilot health mask leaked key[:4]...key[-4:].
            assert f'{value[:4]}...{value[-4:]}' not in blob
            assert value[:8] not in blob
            assert value[-8:] not in blob


@pytest.mark.asyncio
async def test_readiness_fails_closed_and_leaks_no_config(isolated, monkeypatch):
    for name, value in _HEALTH_SECRET_ENV.items():
        monkeypatch.setenv(name, value)

    client = TestClient(app)
    healthy = client.get('/api/health').json()
    assert healthy['status'] == 'healthy'
    assert healthy['app'] == 'ATOM'
    assert 'version' in healthy
    assert healthy['dependencies']['database'] == 'healthy'
    assert healthy['dependencies']['cache'] in {'redis', 'memory'}
    assert healthy['dependencies']['brapi'] == {'configured': True}
    assert healthy['ai_configuration'] == {
        'anthropic': True,
        'openai': True,
        'perplexity': True,
        'gemini': True,
        'grok': True,
    }
    assert all(isinstance(flag, bool) for flag in healthy['ai_configuration'].values())
    _assert_health_has_no_secret_fragments(healthy, _HEALTH_SECRET_ENV)
    blob = json.dumps(healthy)
    assert os.getenv('SECRET_KEY', '') not in blob
    assert os.getenv('ATOM_DATABASE_URL', '') not in blob

    async def broken_pool():
        raise RuntimeError('simulated Postgres outage')

    monkeypatch.setattr('app.db.database.get_pool', broken_pool)
    response = client.get('/api/health')
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}
    _assert_health_has_no_secret_fragments(response.json(), _HEALTH_SECRET_ENV)
    assert client.get('/api/live').status_code == 200


@pytest.mark.asyncio
async def test_health_reports_unconfigured_providers_as_false(isolated, monkeypatch):
    for name in _HEALTH_SECRET_ENV:
        monkeypatch.setenv(name, '')

    payload = TestClient(app).get('/api/health').json()
    assert payload['status'] == 'healthy'
    assert payload['dependencies']['brapi'] == {'configured': False}
    assert payload['ai_configuration'] == {
        'anthropic': False,
        'openai': False,
        'perplexity': False,
        'gemini': False,
        'grok': False,
    }
    blob = json.dumps(payload)
    assert 'sk-' not in blob
    assert 'AIza' not in blob
    assert 'pplx-' not in blob


@pytest.mark.asyncio
async def test_production_registration_closed_and_login_throttled(isolated, monkeypatch):
    monkeypatch.setenv('ATOM_ENV', 'production')
    monkeypatch.delenv('ATOM_ALLOW_REGISTRATION', raising=False)
    client = TestClient(app)
    payload = dict(username='newuser', email='new@example.test', password='a-secure-password')
    assert client.post('/api/auth/register', json=payload).status_code == 403
    for _ in range(10):
        assert client.post('/api/auth/login', json={'username':'alice', 'password':'wrong'}).status_code == 401
    assert client.post('/api/auth/login', json={'username':'alice', 'password':'wrong'}).status_code == 429
    payload['password'] = 'é' * 40
    assert client.post('/api/auth/register', json=payload).status_code == 422


@pytest.mark.asyncio
async def test_backup_restore_preserves_identity_and_ownership(isolated, tmp_path):
    report_id = await database.save_report('PETR4', {'narrative': 'durable'}, owner='alice')

    dump = backup(tmp_path / 'backup.dump')
    with pytest.raises(FileExistsError):
        backup(dump)

    # Simulate data loss, then restore from the dump.
    pool = await get_pool()
    await pool.execute('TRUNCATE reports, users RESTART IDENTITY CASCADE')
    assert await database.get_report_by_id(report_id, owner='alice') is None

    restore(dump)
    # pg_restore reconnects the schema; the app's pool may be bound to a
    # now-stale server-side state for prepared statements — get a fresh one.
    from app.db.postgres import close_pool
    await close_pool()

    assert (await database.get_report_by_id(report_id, owner='alice'))['narrative'] == 'durable'
    pool = await get_pool()
    row = await pool.fetchrow('SELECT username FROM users')
    assert row['username'] == 'alice'


@pytest.mark.asyncio
async def test_exclusive_runtime_recovers_unfinished_runs(isolated):
    """The old SQLite runtime also refused a second concurrent process
    (single-writer constraint); Postgres has no such constraint and that
    check was deliberately removed (see app/core/runtime.py's docstring —
    it also flags why blindly running multiple workers isn't safe yet for
    the crash-recovery logic below, independent of this removed lock)."""
    interrupted = await experiments.begin('alice', {'hypothesis': 'test'})
    completed = await experiments.begin('alice', {'hypothesis': 'finished'})
    await experiments.finish(completed, result={'value': 1})
    async with exclusive_runtime():
        assert (await experiments.detail('alice', interrupted))['status'] == 'failed'
        assert (await experiments.detail('alice', completed))['status'] == 'completed'

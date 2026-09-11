"""Regression checks for the production boundary and disaster recovery."""
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.core.runtime import exclusive_runtime
from app.core.security import create_access_token, get_current_user, hash_password
from app.db import database, experiments
from app.db.maintenance import copy_database

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(database, '_DB_PATH', str(tmp_path / 'atom.db'))
    from app.core.limiter import limiter
    limiter.reset()
    database.create_user('alice', 'alice@example.test', hash_password('a-secure-test-password'))
    return tmp_path


def test_all_business_routes_require_auth(isolated):
    client = TestClient(app)
    import re
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


def test_disabled_user_token_is_revoked(isolated):
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token('alice'))
    assert get_current_user(credentials) == 'alice'
    with database._get_conn() as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE username='alice'")
        conn.commit()
    with pytest.raises(HTTPException) as exc:
        get_current_user(credentials)
    assert exc.value.status_code == 401


def test_reports_private_and_legacy_quarantined(isolated):
    report_id = database.save_report('PETR4', {'narrative': 'private'}, owner='alice')
    assert database.get_report_by_id(report_id, owner='alice')['narrative'] == 'private'
    assert database.get_report_by_id(report_id, owner='bob') is None
    assert database.list_reports(owner='bob') == []
    with database._get_conn() as conn:
        conn.execute('UPDATE reports SET owner=NULL')
        conn.commit()
    assert database.list_reports(owner='alice') == []
    assert database.get_report_by_id(report_id, owner='alice') is None


def test_readiness_fails_closed_and_leaks_no_config(isolated, monkeypatch):
    client = TestClient(app)
    assert client.get('/api/health').json() == {'status': 'healthy'}
    monkeypatch.setattr(database, '_DB_PATH', str(isolated / 'missing' / 'db'))
    response = client.get('/api/health')
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}
    assert client.get('/api/live').status_code == 200


def test_production_registration_closed_and_login_throttled(isolated, monkeypatch):
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


def test_backup_restore_preserves_identity_and_ownership(isolated):
    report_id = database.save_report('PETR4', {'narrative':'durable'}, owner='alice')
    backup = copy_database(Path(database._DB_PATH), isolated / 'backup.db')
    restored = copy_database(backup, isolated / 'restored.db')
    assert restored.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(restored) as conn:
        assert conn.execute('SELECT owner FROM reports WHERE id=?', (report_id,)).fetchone() == ('alice',)
        assert conn.execute('SELECT username FROM users').fetchone() == ('alice',)
    with pytest.raises(FileExistsError):
        copy_database(backup, restored)


def test_exclusive_runtime_recovers_only_unfinished_runs(isolated):
    interrupted = experiments.begin('alice', {'hypothesis':'test'})
    completed = experiments.begin('alice', {'hypothesis':'finished'})
    experiments.finish(completed, result={'value': 1})
    with exclusive_runtime():
        assert experiments.detail('alice', interrupted)['status'] == 'failed'
        assert experiments.detail('alice', completed)['status'] == 'completed'
        live = experiments.begin('alice', {'hypothesis':'active'})
        with pytest.raises(RuntimeError, match='one process'):
            with exclusive_runtime():
                pass
        assert experiments.detail('alice', live)['status'] == 'running'

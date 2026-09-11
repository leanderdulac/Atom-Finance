"""Operational failure contracts: failed uploads never mark backups fresh."""
import importlib.util
import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[2] / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


backup = module('offsite', 'backup-offsite.py')
monitor = module('operations', 'check-operations.py')


def test_failed_upload_preserves_prior_success(tmp_path, monkeypatch):
    monkeypatch.setenv('RESTIC_REPOSITORY', 's3:https://example.test/bucket')
    monkeypatch.setenv('RESTIC_PASSWORD_FILE', '/secret-file')
    monkeypatch.setenv('ATOM_OPS_STATE', str(tmp_path))
    prior = tmp_path / 'backup-success.json'
    prior.write_text('{"completed_at":"2026-01-01T00:00:00+00:00"}')
    calls = []
    def docker(args):
        calls.append(args)
        if 'cp' in args:
            Path(args[-1]).write_bytes(b'test database snapshot')
    monkeypatch.setattr(backup, 'run', docker)
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'restic')
    monkeypatch.setattr(backup.subprocess, 'run', failed)
    with pytest.raises(subprocess.CalledProcessError):
        backup.backup()
    assert json.loads(prior.read_text())['completed_at'].startswith('2026-01-01')
    assert any('Path(sys.argv[1]).unlink()' in arg for arg in calls[-1])


def test_successful_upload_records_freshness(tmp_path, monkeypatch):
    monkeypatch.setenv('RESTIC_REPOSITORY', 's3:https://example.test/bucket')
    monkeypatch.setenv('RESTIC_PASSWORD_FILE', '/secret-file')
    monkeypatch.setenv('ATOM_OPS_STATE', str(tmp_path))
    def docker(args):
        if 'cp' in args:
            Path(args[-1]).write_bytes(b'test database snapshot')
    monkeypatch.setattr(backup, 'run', docker)
    monkeypatch.setattr(backup.subprocess, 'run', lambda *a, **k: None)
    backup.backup()
    stamp = datetime.fromisoformat(json.loads((tmp_path / 'backup-success.json').read_text())['completed_at'])
    assert (datetime.now(UTC) - stamp).total_seconds() < 5


def test_local_repository_rejected_before_snapshot(monkeypatch):
    monkeypatch.setenv('RESTIC_REPOSITORY', '/local/directory')
    monkeypatch.setattr(backup, 'run', lambda _: pytest.fail('must not create a snapshot'))
    with pytest.raises(RuntimeError, match='external'):
        backup.backup()


def test_monitor_detects_missing_backup_low_disk_and_api_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('ATOM_OPS_STATE', str(tmp_path))
    monkeypatch.setattr(monitor, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(monitor.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0,total=100))
    errors = monitor.problems()
    assert len(errors) == 3


def test_monitor_healthy_then_stale(tmp_path, monkeypatch):
    monkeypatch.setenv('ATOM_OPS_STATE', str(tmp_path))
    def response(*a, **k):
        stream = io.BytesIO(b'{"status":"healthy"}')
        stream.status = 200
        return stream
    monkeypatch.setattr(monitor, 'urlopen', response)
    monkeypatch.setattr(monitor.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10*1024**3,total=20*1024**3))
    (tmp_path / 'backup-success.json').write_text('{"completed_at":"2026-09-10T00:00:00+00:00"}')
    assert monitor.problems(datetime(2026,9,10,12,tzinfo=UTC)) == []
    assert monitor.problems(datetime(2026,9,12,tzinfo=UTC)) == ['Offsite backup stale or invalid timestamp']

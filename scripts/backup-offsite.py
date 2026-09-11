#!/usr/bin/env python3
"""Online SQLite snapshot -> encrypted restic repository. Never prune backups."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone
from uuid import uuid4


def run(args):
    subprocess.run(args, check=True, timeout=1800)


def backup():
    repository = os.environ.get('RESTIC_REPOSITORY', '')
    if not repository.startswith(('s3:', 'sftp:', 'rest:https://')):
        raise RuntimeError('An external S3/SFTP/HTTPS restic repository is required')
    if not os.environ.get('RESTIC_PASSWORD_FILE'):
        raise RuntimeError('RESTIC_PASSWORD_FILE is required')
    app_dir = Path(os.environ.get('APP_DIR', '/opt/atom'))
    release = Path(os.environ.get('ATOM_RELEASE_DIR', str(app_dir)))
    env_file = os.environ.get('PROD_ENV', str(app_dir / '.env.prod'))
    state_dir = Path(os.environ.get('ATOM_OPS_STATE', '/var/lib/atom-ops'))
    compose = ['docker', 'compose', '-p', 'atom', '--env-file', env_file,
               '-f', str(release / 'docker-compose.prod.yml')]
    name = 'offsite-' + str(uuid4()) + '.db'
    remote = '/data/' + name
    snapshot_created = False
    try:
        run(compose + ['exec', '-T', 'backend', 'python', '-m', 'app.db.maintenance',
                       'backup', '/data/atom_reports.db', remote])
        snapshot_created = True
        with tempfile.TemporaryDirectory(prefix='atom-backup-') as staging:
            local = Path(staging) / 'atom.db'
            run(compose + ['cp', 'backend:' + remote, str(local)])
            local.chmod(0o600)
            # Stable stdin filename prevents ephemeral paths from splitting history.
            with local.open('rb') as source:
                subprocess.run(['restic', 'backup', '--stdin', '--stdin-filename', 'atom.db',
                                '--tag', 'atom-core'], stdin=source, check=True, timeout=1800)
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Only advance freshness after a fully successful upload.
        target = state_dir / 'backup-success.json'
        temporary = state_dir / ('backup-success-' + str(uuid4()) + '.tmp')
        temporary.write_text(json.dumps({'completed_at': datetime.now(timezone.utc).isoformat()}))
        temporary.chmod(0o600)
        temporary.replace(target)
    finally:
        if snapshot_created:
            run(compose + ['exec', '-T', 'backend', 'python', '-c',
                           'from pathlib import Path; import sys; Path(sys.argv[1]).unlink()', remote])


if __name__ == '__main__':
    backup()

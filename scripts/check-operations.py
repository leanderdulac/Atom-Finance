#!/usr/bin/env python3
"""Exit nonzero on unhealthy API, low disk or stale/missing offsite backup."""
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone
from urllib.request import urlopen


def problems(now=None):
    now = now or datetime.now(timezone.utc)
    failures = []
    try:
        with urlopen(os.environ.get('ATOM_HEALTH_URL', 'http://127.0.0.1:8080/api/health'), timeout=10) as response:
            if response.status != 200 or json.load(response).get('status') != 'healthy':
                failures.append('API unhealthy')
    except Exception:
        failures.append('API unavailable')
    try:
        disk = shutil.disk_usage(os.environ.get('ATOM_DISK_PATH', '/var/lib/docker'))
        if disk.free < 5 * 1024**3 or disk.free / disk.total < 0.10:
            failures.append('Disk free below 5 GiB or 10 percent')
    except OSError:
        failures.append('Disk status unavailable')
    try:
        data = json.loads((Path(os.environ.get('ATOM_OPS_STATE', '/var/lib/atom-ops')) / 'backup-success.json').read_text())
        age = (now - datetime.fromisoformat(data['completed_at'])).total_seconds()
        if age < 0 or age > 26 * 3600:
            failures.append('Offsite backup stale or invalid timestamp')
    except (OSError, ValueError, KeyError, TypeError):
        failures.append('No verified offsite backup recorded')
    return failures


if __name__ == '__main__':
    errors = problems()
    print(json.dumps({'healthy': not errors, 'problems': errors}))
    raise SystemExit(1 if errors else 0)

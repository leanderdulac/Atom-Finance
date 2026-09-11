"""Operator-only SQLite backup, restore to a NEW path, and user provisioning.

Run: python -m app.db.maintenance --help (from backend or container).
"""
import argparse
import getpass
import os
import sqlite3
from pathlib import Path


def copy_database(source: Path, destination: Path):
    source = source.resolve(strict=True)
    destination = destination.absolute()
    # Exclusive creation also rejects symlinks and accidental overwrite.
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Database integrity check failed')
        with destination.open('rb') as handle:
            os.fsync(handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('backup', 'restore'):
        command = commands.add_parser(name)
        command.add_argument('source', type=Path)
        command.add_argument('destination', type=Path)
    user = commands.add_parser('create-user')
    user.add_argument('username')
    user.add_argument('email')
    user.add_argument('--role', choices=['admin', 'analyst'], default='analyst')
    args = parser.parse_args()
    if args.command in ('backup', 'restore'):
        print(copy_database(args.source, args.destination))
    else:
        from app.api.auth import RegisterRequest
        from app.core.security import hash_password
        from app.db.database import create_user
        password = getpass.getpass('Password (12+ characters): ')
        if password != getpass.getpass('Repeat password: '):
            parser.error('Passwords do not match')
        validated = RegisterRequest(username=args.username, email=args.email, password=password)
        if create_user(validated.username, validated.email, hash_password(password), role=args.role) is None:
            parser.error('User creation failed (existing username/email or database unavailable)')
        print('User created')


if __name__ == '__main__':
    main()

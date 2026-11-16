"""Operator-only Postgres backup/restore (thin pg_dump/pg_restore wrappers)
and user provisioning.

Run: python -m app.db.maintenance --help (from backend or container).

Note: most managed Postgres providers (DigitalOcean Managed Databases, RDS,
Cloud SQL, ...) include automated daily backups and point-in-time recovery
out of the box — prefer that over these commands for routine backups. These
exist for ad hoc snapshots (e.g. immediately before a risky migration).
"""
import argparse
import asyncio
import getpass
import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


def _database_url() -> str:
    url = os.getenv("ATOM_DATABASE_URL", "")
    if not url:
        raise RuntimeError("ATOM_DATABASE_URL is not set.")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _passwordless_url_and_env() -> tuple[str, dict[str, str]]:
    """Split the password out of the URL: argv is visible in ps/auditd, env is not.

    Returns (url_without_password, env_with_PGPASSWORD).
    """
    parts = urlsplit(_database_url())
    env = dict(os.environ)
    if parts.password:
        env["PGPASSWORD"] = unquote(parts.password)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    if parts.username:
        netloc = f"{parts.username}@{netloc}"
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return clean, env


def backup(destination: Path) -> Path:
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError(f"{destination} already exists — refusing to overwrite.")
    url, env = _passwordless_url_and_env()
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(destination), url],
        check=True,
        env=env,
    )
    return destination


def restore(source: Path) -> None:
    source = source.resolve(strict=True)
    url, env = _passwordless_url_and_env()
    subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", url, str(source)],
        check=True,
        env=env,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    backup_cmd = commands.add_parser('backup', help='pg_dump to a new custom-format file')
    backup_cmd.add_argument('destination', type=Path)
    restore_cmd = commands.add_parser('restore', help='pg_restore from a custom-format file')
    restore_cmd.add_argument('source', type=Path)
    user = commands.add_parser('create-user')
    user.add_argument('username')
    user.add_argument('email')
    user.add_argument('--role', choices=['admin', 'analyst'], default='analyst')
    args = parser.parse_args()
    if args.command == 'backup':
        print(backup(args.destination))
    elif args.command == 'restore':
        restore(args.source)
        print('Restore complete.')
    else:
        from app.api.auth import RegisterRequest
        from app.core.security import hash_password
        from app.db.database import create_user
        password = getpass.getpass('Password (12+ characters): ')
        if password != getpass.getpass('Repeat password: '):
            parser.error('Passwords do not match')
        validated = RegisterRequest(username=args.username, email=args.email, password=password)
        uid = asyncio.run(create_user(validated.username, validated.email, hash_password(password), role=args.role))
        if uid is None:
            parser.error('User creation failed (existing username/email or database unavailable)')
        print('User created')


if __name__ == '__main__':
    main()

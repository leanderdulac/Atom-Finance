# Contributing to ATOM

> This is a private research pilot (see [docs/PRODUCT-PILOT.md](docs/PRODUCT-PILOT.md)). This guide covers local workflow, not an open external-contribution process.

## Setup

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.lock
cp ../.env.example ../.env   # fill in SECRET_KEY at minimum

# Frontend
cd ..
npm install
```

## Before opening a PR

Run what CI runs ([.github/workflows/ci.yml](.github/workflows/ci.yml)) locally first:

```bash
# Backend — lint, tests + coverage gate
cd backend
ruff check .   # uvx ruff check . if you don't have ruff installed globally
python -m pytest tests/ --tb=short -q --cov=app --cov-report=term-missing --cov-fail-under=40

# Frontend — lint, unit tests, types, build
cd ..
npm run lint
npm test
npx tsc --noEmit
npm run build
```

Ruff config lives in `backend/pyproject.toml`. Before "fixing" a ruff finding with `--unsafe-fixes` or by hand, check whether the flagged name is referenced dynamically (a pytest fixture re-import, or a `unittest.mock.patch("module.Name", ...)` target) — static analysis can't see those, and blindly removing them will break tests. Two instances of exactly this already bit an earlier cleanup pass (see `CHANGELOG.md`).

Backend dependencies are pinned in `backend/requirements.lock`, generated with [uv](https://github.com/astral-sh/uv) from `backend/requirements.txt`:

```bash
uv pip compile backend/requirements.txt --universal --torch-backend cpu --emit-index-url -o backend/requirements.lock
```

Regenerate the lock file whenever you add, remove, or bump a dependency in `requirements.txt` — CI installs strictly from the lock file, not from `requirements.txt`.

## Commit style

The project follows [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`) — see `git log` for examples.

## Adding a new API module

1. Model/logic goes in `backend/app/models/<name>.py`.
2. Routes go in `backend/app/api/<name>.py`, exposing an `APIRouter`.
3. Register it in [backend/main.py](backend/main.py) with `protected.include_router(...)` (or `app.include_router(...)` if it must be reachable without auth, like `/api/auth`).
4. Add tests under `backend/tests/`.
5. If the endpoint touches real trading/execution, read [docs/RESEARCH-POLICY.md](docs/RESEARCH-POLICY.md) and [docs/PRODUCT-PILOT.md](docs/PRODUCT-PILOT.md) first — this pilot does not authorize automated order execution.

## Research submodule

`research/quantmind` is an embedded, independently-tooled library with its own `CONTRIBUTING.md`, `pyproject.toml`, and test suite. Changes inside it should follow its own conventions, not the ones above.

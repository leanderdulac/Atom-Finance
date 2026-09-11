# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this file starts tracking from the cleanup below rather than reconstructing prior history from commits.

## [Unreleased]

### Fixed
- `package.json` name corrected from a leftover placeholder (`quantitative-finance-econophysics-guide`) to `atom-finance`.
- README "Tech Stack", "Configuration", "Project Structure", and "API" sections rewritten to match the actual codebase (SQLite, not PostgreSQL/MongoDB; no `/api/reports/pdf`; accurate module/router list).
- `.env.example` no longer documents a `DATABASE_URL`/`POSTGRES_PASSWORD` pair for a Postgres service that isn't part of any compose stack; replaced with the actual `ATOM_DB_PATH` (SQLite) setting.
- `backend/Dockerfile`: the non-root user is now created and applied via `USER` before `CMD`/`EXPOSE`, and copied app files are `chown`'d to that user.
- ESLint: `@typescript-eslint/no-explicit-any` and `@typescript-eslint/no-unused-vars` re-enabled as `warn` (were silently `off`); `npm run lint` now runs in CI.
- CI: backend test step now enforces a coverage floor (`--cov-fail-under=40`) instead of measuring nothing.

### Removed
- Dead backend dependencies with no import anywhere in `backend/`: `motor`, `pymongo` (no Mongo usage), `passlib` (bcrypt used directly), `sqlalchemy`, `asyncpg` (storage is stdlib `sqlite3`), `celery`, `spacy`, `matplotlib`, `reportlab`, `safetensors`, `websockets`, `aiohttp`, `statsmodels`, `arch`. `backend/requirements.lock` regenerated and the full test suite re-verified against a clean install.

### Added
- `LICENSE` (MIT) — referenced by the README but previously missing from the repo.
- `CONTRIBUTING.md` — local setup, pre-PR checklist, lockfile regeneration steps.
- CI badges in the README.

## [Unreleased] — round 2

### Fixed
- **`app/api/ai_report.py`**: `HTTPException` was used but never imported — any error in `/api/reports/ticker-financials/{ticker}` crashed with an unhandled `NameError` (500 with no useful detail) instead of a proper 404/500 response.
- **`app/models/volatility.py`**: `HestonModel.price_option` ran a full, discarded Monte Carlo simulation (up to 50k paths × 252 steps) before re-simulating the same thing manually — doubling the cost of every Heston pricing call for no reason. Removed the dead call.
- **`docker-compose.yml`**: removed unused Postgres and MongoDB services (backend uses stdlib `sqlite3`, never touches either) and fixed a real bug where the dev container's SQLite file was written outside the mounted volume (`ATOM_DB_PATH` was unset), so data silently vanished on every container restart.
- **19 `zip()` calls** across `portfolio.py`, `research_validation.py`, `ml_models.py`, `ibovespa.py`, and others now use `strict=True` — previously, mismatched-length inputs would silently truncate instead of raising, which is a real risk in code producing risk/return numbers.
- **15 exception re-raises** (`app/core/ai_factory.py`, `app/api/ai_proxy.py`, `ai_report.py`, `copulas.py`, `evt.py`) now chain with `from e`, preserving the original traceback instead of hiding it.
- **`app/services/data_fetcher.py`**: `df["inTheMoney"] == False` replaced with the correct pandas idiom `~df["inTheMoney"]` (the literal `== False` happened to work, but ruff's generic "use `not x`" suggestion would have broken on a pandas Series — used the vectorized form instead).
- Frontend: initial JS bundle cut from 1.54 MB to 432 KB (gzip: 452 KB → 141 KB) by lazy-loading every page route (`React.lazy` + `Suspense`) instead of bundling all 30+ pages eagerly.

### Added
- `backend/pyproject.toml` — ruff configuration (`E`, `F`, `I`, `B`, `UP` rule sets); wired into CI as a blocking step. Fixed ~530 findings (355 auto-fixed: unused imports, import sorting, modern type-hint syntax; the rest by hand).
- Frontend test infrastructure (Vitest + Testing Library, previously zero tests): `AuthContext.test.tsx` (5 tests covering login/logout/session-restore) and `App.test.tsx` (4 routing smoke tests, including a regression guard for the lazy-loading change above). Wired into CI (`npm test`).
- 6 unused-variable findings in quant/agent code (`copulas.py`, `investment_agents.py`, `options_agent.py`, `ai_report.py`) were deliberately left as `# noqa` with `TODO` comments rather than guessed at — they need domain review, not a mechanical fix. Tracked as a follow-up.

### Notes
- Two ruff autofixes were reverted after breaking tests: removing an import that looked unused but was actually a pytest fixture re-import (`tests/test_source_quality.py`), and removing `OptionsExpert` from `options_api.py`, which is a live `unittest.mock.patch()` target proving the retired `/scan` endpoint no longer calls the old model. Both are static-analysis blind spots worth remembering before trusting another autofix pass on this codebase.

## [Unreleased] — round 3: SQLite → PostgreSQL

Fase 1 of the enterprise roadmap. Storage is now PostgreSQL end to end — `ATOM_DB_PATH` is gone, replaced by `ATOM_DATABASE_URL`; schema lives in versioned Alembic migrations (`backend/alembic/versions/`) instead of ad hoc `CREATE TABLE IF NOT EXISTS` calls scattered across route files. Preceded by a time-boxed spike (`docs/POSTGRES-MIGRATION-SPIKE.md`) that validated the approach and estimated the effort before this was committed to.

### Changed
- `app/db/database.py`, `app/db/experiments.py`, and the DB-touching parts of `app/api/{derivatives,market_sources,paper_trades}.py` rewritten from sync `sqlite3` to async `asyncpg` (no ORM — matches the project's existing anti-ORM stance). Every call site that used `asyncio.to_thread(...)` to bridge the old sync DB calls into async route handlers had that wrapper removed; `get_current_user` (used as a dependency on almost every route) is now `async def`.
- `app/core/runtime.py`: removed the `fcntl`-based single-process file lock — it existed only because SQLite can't safely take concurrent writers from multiple processes, a constraint Postgres doesn't have. The crash-recovery logic (mark orphaned `running` experiments as `failed` on startup) stays, with a docstring warning that it isn't yet safe for multiple workers/replicas (a Fase 4 concern, not this one).
- `app/api/paper_trades.py`'s locking: SQLite's `BEGIN IMMEDIATE` (a global write lock) is replaced by a Postgres advisory transaction lock scoped to the owner (`pg_advisory_xact_lock(hashtext(owner))`) — serializes one owner's concurrent writes (what the aggregate risk-budget check needs) without blocking unrelated owners against each other, which the old global lock did unnecessarily.
- `app/db/maintenance.py`: the SQLite-only `sqlite3.Connection.backup()` CLI is replaced by thin `pg_dump`/`pg_restore` wrappers. Documented that a managed Postgres provider's own automated backups (daily + PITR) should be the primary recovery mechanism — these commands are for ad hoc snapshots, not routine backup.
- `scripts/backup-offsite.py`: the restic-backed offsite backup pipeline now dumps Postgres (`pg_dump --format=custom`) instead of copying a SQLite file.
- `docker-compose.yml` (dev): added a `postgres` service back (removed as "dead" in round 1 — now genuinely load-bearing).
- `docker-compose.prod.yml`: deliberately does *not* run its own Postgres — `ATOM_DATABASE_URL` is now a required env var, expected to point at a managed instance. Added a `postgres` service behind a `ci` profile, used only by the CI container smoke test.
- CI (`backend` job): added a Postgres service container, `alembic upgrade head` before the test run, and `postgresql-client` (for the pg_dump/pg_restore test). CI (`containers` job): starts the stack with `--profile ci`, runs migrations against the throwaway Postgres before the smoke test.
- Docs (`PRODUCTION.md`, `PILOT-DEPLOYMENT.md`, `PRODUCT-PILOT.md`, `DATA-INTEGRATIONS.md`, README, `.env.example`, `CONTRIBUTING.md`) updated wherever they described SQLite-specific operational behavior (single-writer lock, WAL, file-path backups) that no longer applies.

### Fixed (found while migrating, not pre-existing SQLite bugs)
- `main.py`'s `/api/health` called the now-async `readiness()` without `await` — the coroutine was created and silently discarded, so the health check could never actually detect a database outage.
- `app/api/derivatives.py` and `app/api/market_sources.py` passed ISO-format *strings* (`datetime.now(UTC).isoformat()`) for `created_at`/`fetched_at` into columns that are now real `TIMESTAMPTZ`; asyncpg rejects that outright (`invalid input ... expected a datetime.date or datetime.datetime instance, got 'str'`). Parsed with `datetime.fromisoformat(...)` before binding.
- `app/db/postgres.py`'s pool is now loop-aware: a `TestClient(app)` used without `with` (several existing tests do this) starts a fresh event loop per call, and asyncpg pools are bound to the loop that created them — reusing one from a dead loop raised `RuntimeError: ... attached to a different loop`. `get_pool()` now detects the loop changed and transparently creates a fresh pool instead of handing back a stale one.
- 3 `sum()` calls in `paper_trades.py` (fees, cash, debit) already had `start=D(0)` from round 2's Decimal fix — ported as-is, and confirmed still necessary: without it, an empty fills list would produce int `0` instead of `Decimal(0)` and crash `.quantize()` downstream.

### Added
- Test isolation: since tests now share one real Postgres instead of each getting an implicit fresh SQLite file, an autouse fixture (`backend/tests/conftest.py`) truncates every table before each test. Uses a standalone connection rather than the app's shared pool, specifically to avoid the loop-mismatch issue above.
- `docs/POSTGRES-MIGRATION-SPIKE.md` findings carried through: the copula/EVT-style "attribute set in `fit()`, used unguarded elsewhere" pattern doesn't apply here, but the DDL-transactionality gotcha documented there recurred verbatim in `readiness()`'s real port and is fixed the same way (`CREATE TABLE` commits on its own, separate from the transaction that gets rolled back).

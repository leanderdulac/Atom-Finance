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

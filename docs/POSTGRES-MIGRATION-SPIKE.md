# Spike: SQLite → PostgreSQL migration

> **Update:** the recommendation below was carried out on `feature/postgres-migration` (see `CHANGELOG.md`). This document is kept as-is for the historical record — the findings and gotchas below are exactly what shaped that follow-up work, including the `paper_trades.py` locking design and the two bugs (DDL transactionality, a CancelledError-shaped one this doc doesn't cover) that came up during the real migration too.

**Branch:** `spike/postgres-migration` (not merged — throwaway by design)
**Goal:** validate the real effort and surface real gotchas before committing Fase 1 of the enterprise roadmap to this migration.
**Time-boxed to:** one focused session.

## What was built

- `backend/alembic/` — Alembic (async template) wired to read `ATOM_DATABASE_URL` from the environment, never from a committed file.
- `backend/alembic/versions/7c1b289837ff_*.py` — initial migration for `users` and `reports`, translating SQLite types to Postgres-native ones.
- `backend/app/db/database_pg.py` — an async, `asyncpg`-based reimplementation of `app/db/database.py`'s public API (same function names/signatures, so call sites barely change). **Not wired into `main.py`.**
- `backend/scripts/spike_postgres_smoke.py` — a standalone script (not part of the pytest suite) that round-trips every function against a real Postgres.
- A local `postgres:16-alpine` container (`docker run`, not added to `docker-compose.yml` — that decision belongs to the real Fase 1 work, not this spike).

Ran the smoke test end to end: user creation, duplicate rejection, JSONB round-trip of a nested report dict, filtered listing, and the `readiness()` probe. All 9 checks pass.

## Verdict

**The migration is real work, not a connection-string swap — but it's tractable, and the original ~6-week Fase 1 estimate (which already bundles staging + secrets vault, not just the DB) holds up.** No surprise big enough to change the roadmap's sequencing. Three concrete things did surprise me enough to write down.

## Findings

### 1. The SQL is not confined to `app/db/` — that changes the surface area

Only `database.py`'s three tables (`users`, `reports`, plus the module-scoped `health_probe`) live behind a clean function API. Everything the pilot feature work added since talks to SQLite directly, with hand-written SQL inline in the route files:

| File | Lines | What it does |
|---|---:|---|
| `app/db/experiments.py` | 76 | Research journal — clean, no SQLite-specific syntax |
| `app/api/derivatives.py` | 48 | Derivatives desk plans — clean |
| `app/api/market_sources.py` | 84 | Source snapshots — uses `json_extract()` |
| `app/api/paper_trades.py` | 237 | Paper trading — uses `BEGIN IMMEDIATE` and implicit `rowid` |
| `app/core/runtime.py` | ~25 | Startup crash recovery — sets `PRAGMA journal_mode=WAL` |

This spike only ported `database.py`. The other four are separate, smaller migrations each — not free follow-on work from this one.

### 2. Three SQLite-specific constructs need real (not mechanical) translation

- **`json_extract(payload, '$.ticker')`** (`market_sources.py`) — the `payload` column is `TEXT` holding a JSON string. In Postgres this becomes a `JSONB` column and the query becomes `payload->>'ticker'`. Straightforward, but requires the column type change, not just a syntax swap.
- **`BEGIN IMMEDIATE`** (`paper_trades.py`) — SQLite's way of taking a write lock upfront in its single-writer model. Postgres's MVCC doesn't have (or need) an equivalent for the same reason, but the application logic that assumed serialized writes needs a real look: does it actually need `SELECT ... FOR UPDATE` on the read that precedes the write, or does normal `READ COMMITTED` already give the right answer once there's no single-writer bottleneck? This needs someone to read the business logic, not just transliterate.
- **`rowid`** (`paper_trades.py`, `ORDER BY rowid`) — SQLite's implicit per-row column. Postgres has no equivalent (`ctid` exists but isn't stable across updates/vacuum and shouldn't be used for ordering). Needs an explicit sequence/serial column added to preserve insertion order.

### 3. A transaction-semantics bug I introduced myself, worth keeping as a warning

My first pass at porting `readiness()` wrapped the `CREATE TABLE IF NOT EXISTS health_probe` and the probe `INSERT` in the same transaction, then rolled that transaction back — because that's what the SQLite version's rollback call looked like it was doing. It silently deleted the table every time, because **DDL is transactional in Postgres** (unlike SQLite's autocommit-per-statement default the original code relied on). Fixed by committing the `CREATE TABLE` on its own and only rolling back the `INSERT`. The lesson: nothing here should be ported by pattern-matching the SQLite code's shape — the transaction boundaries have to be re-derived from what each function is actually trying to guarantee.

## Pleasant surprise

`asyncpg`'s `JSONB` type codec (`conn.set_type_codec(...)`) round-trips Python dicts natively — `save_report`/`get_report_by_id` no longer need the manual `json.dumps`/`json.loads` calls the SQLite version has. One less thing to get wrong, and `full_report` becomes queryable/indexable in Postgres in a way a `TEXT` blob never was in SQLite.

## Revised effort estimate for the rest of Fase 1

| Piece | Estimate | Why |
|---|---|---|
| `experiments.py` port | 2-3h | Same shape as what this spike already proved out |
| `derivatives.py` port | 2-3h | Small, no SQLite-specific syntax |
| `market_sources.py` port | 3-4h | `json_extract` → `JSONB` operators, plus the column type change |
| `paper_trades.py` port | 1-2 days | Needs the locking-semantics review above, not just translation; also the largest file |
| `runtime.py` port | <1h | WAL pragma drops (N/A on Postgres); crash-recovery query is portable as-is |
| `maintenance.py` | 2-4h to decide | `sqlite3.Connection.backup()` has no Postgres equivalent — likely replaced by the managed provider's built-in automated backups (e.g. DigitalOcean Managed Postgres includes daily backups + PITR) rather than ported |
| Call-site updates | 3-4h | ~10 files call today's sync `database.py` via `asyncio.to_thread(...)`; switching to async Postgres means removing those wrappers and `await`-ing directly — mechanical but touches every consumer |
| Test infra | 3-4h | Tests need a real Postgres (or `testcontainers`) instead of an implicit fresh SQLite file; CI needs a Postgres service |
| Prod cutover | 4-6h | Provision managed Postgres, one-time data migration script for the real `atom_reports.db`, `ATOM_DB_PATH` → `ATOM_DATABASE_URL` in deploy scripts/systemd units |

**Total: ~4-6 focused days**, consistent with the roadmap's original "~6 semanas" for the whole of Fase 1 (which also includes the staging environment and secrets vault — not just this).

## Recommendation

Proceed with Fase 1 as sequenced in the roadmap. Suggested order for the actual migration (not this spike): `database.py` (already proven here) → `experiments.py` → `derivatives.py` → `runtime.py` → `market_sources.py` → `paper_trades.py` last, specifically because it's the one that needs a real design conversation about locking, not just an implementation slot.

## Reproducing this spike

```bash
docker run -d --name atom-pg-spike -e POSTGRES_USER=atom -e POSTGRES_PASSWORD=atom_spike \
  -e POSTGRES_DB=atom_spike -p 5544:5432 postgres:16-alpine

cd backend
export ATOM_DATABASE_URL="postgresql+asyncpg://atom:atom_spike@localhost:5544/atom_spike"
alembic upgrade head
python scripts/spike_postgres_smoke.py
```

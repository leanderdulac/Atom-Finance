# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this file starts tracking from the cleanup below rather than reconstructing prior history from commits.

## [Unreleased] — round 18: vetorização (loops em série de preço)

`for i in range(len(df))` com `.iloc[i]` encerra a avaliação numa mesa. Não é estilo: é 50–100× mais lento, look-ahead i vs i-1, e 10 vs 10.000 hipóteses por dia.

### Added
- `POST /api/desk/vectorize/evaluate`: máscara cheap×momentum em loop vs broadcasting, Z-score transversal (`X - mean(axis=1)`), Sharpe no mesmo bar vs t+1. `eligible_for_live_trading` permanece false.
- UI `/vectorize`. Doutrina `ATOM-QUANT-1.0` tenet 5; `analyze_quant` / `ai_proxy` / QuantMind recusam o loop.

## [Unreleased] — round 16: Black-Litterman com pesos de mercado reais

### Changed
- `black_litterman` aceita `market_weights` opcionais (dict por ativo ou sequência alinhada a `asset_names`): o prior de equilíbrio (π = δ·Σ·w) agora ancora-se em capitalizações reais em vez do arbitrário `1/N`. Validação rejeita pesos negativos/zero/comprimento errado; `market_cap_weights` é exposto na resposta. **Fallback seguro para equal-weighted quando omitido** — comportamento legado preservado.
- `POST /api/portfolio/black-litterman` repassa `market_weights` opcionalmente.

## [Unreleased] — round 15: sessão com refresh token HttpOnly

Mover a sessão do JWT de localStorage (exfiltrável por XSS) para um **access token de vida curta em memória** + um **refresh token opaco em cookie HttpOnly (SameSite=Lax, Secure em prod)**, com **rotação** e **revogação**.

### Added
- `refresh_tokens` table (alembic `f8b98626115a`) — só o hash sha256 do token é persistido; `used_at`/`replaced_by_token_hash`/`revoked_at` habilitam rotação e revogação explícita.
- `POST /api/auth/login` agora define o cookie HttpOnly e devolve um access token curto (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 30).
- `POST /api/auth/refresh` — rotaciona o cookie e devolve um access novo; reuso de token (sinal de roubo) **revoga toda a família** do usuário.
- `POST /api/auth/logout` — revoga o refresh token e limpa o cookie.
- Front-end: `AuthContext`/`api.ts` sem localStorage — access token em memória, **refresh automático no 401** (com promise única para evitar rajadas), restauração de sessão via `/auth/refresh` no load.

## [Unreleased] — round 14: doutrina da mesa (treino do modelo)

Não é fine-tune de pesos. Os laboratórios (maldição do vencedor, teste sequencial, preço × retorno, regime, `/ml`) são o currículo; `compose_system` injeta a constituição em todo `complete()`.

### Added
- `backend/app/core/quant_doctrine.py` (`ATOM-QUANT-1.0`): system prompt permanente + tenets com labs. Todo provider em `ai_factory` prefixa a doutrina; `ai_proxy` e `options_api` (bypass da factory) também.
- `GET /api/desk/doctrine` e `GET /api/ml/policy` passam a expor `doctrine_version` e os tenets.
- QuantMind `extra_instructions`: alvo = retorno/regime, relógio sequencial, DSR, K-Fold shuffled inválido.
- UI `/quant-doctrine`. `eligible_for_live_trading` permanece false.

## [Unreleased] — round 13: price is a bad target

### Added
- PETR4 vs BTC on the *same* log-return path (`POST /api/desk/target-choice/evaluate`): R$500 is a different percent, prices fail a unit-root screen, walk-forward Ridge on P_{t+1} prints a fake R² while r_{t+1} and the next vol-regime do not. `eligible_for_live_trading` stays false.
- UI `/target-choice`. Laboratório Quant already labels t+1→t+2 returns; the page makes the scale/stationarity reason visible.

## [Unreleased] — round 12: sequential forward test

### Added
- Locked-spec sequential SMA vs mined TA vs expanding walk-forward (`POST /api/desk/forward-test/evaluate`). Signal at close t uses only prices[0:t]; PnL is the next return. Same-bar scoring is shown as a leak.
- UI `/forward-test`: today's frozen-spec signal (to be scored by a price that does not exist yet), equity of the four clocks, DSR of the mined champion. `eligible_for_live_trading` stays false.

## [Unreleased] — round 11: winner's curse / Deflated Sharpe

### Added
- Zero-edge lottery (`POST /api/desk/winners-curse/simulate`): N iid Gaussian strategies, true E[r]=0, pick the in-sample Sharpe champion, settle out-of-sample. Expected max ≈ σ_SR · √(2 ln N).
- Deflated Sharpe Ratio (`POST /api/desk/winners-curse/deflate`): Bailey & López de Prado DSR = Φ((SR̂ − SR*)/σ̂). Ask how many candidates the print beat before risking capital.
- UI `/winners-curse`: IS×OOS scatter, y=x, hollow naïve-replay circle, live trading stays false.

## [Unreleased] — round 10: live regime books, 4h job, paper flatten, holdout

### Added
- Live public books (`POST /api/desk/regime/live`): Yahoo SPY/QQQ/IWM/EFA/TLT, ^VIX, ^VIX3M, ^IRX/^TNX, FRED HY OAS. Tests inject fetchers; no network in CI.
- 4-hour asyncio job when `ATOM_REGIME_JOB=1` (off in `ATOM_ENV=test`). Optional `ATOM_REGIME_KILL_OWNER` flattens that user's open paper trades on crisis.
- Paper kill switch: `flatten_open_trades` closes simulated positions at last mark. Broker execute stays HTTP 410.
- `P(regime)` softmax from percentile z-scores; walk-forward holdout (predict on `data[:t]`, label next 10 days). Hurst lookback 126 with 5-window smoothing.

## [Unreleased] — round 9: regime classifier (research kill switch)

### Added
- Six-signal regime snapshot (`POST /api/desk/regime/evaluate`): Hurst, VIX term structure, RV−IV, cross-asset correlation, credit spreads, rates curve slope. Each is flagged on a 90-day percentile gate; the label is trending / mean-reverting / high_vol / crisis.
- Strategy mapping + half-Kelly resize recommendations, written as `docs/strategy/*.md` context files.
- Research kill switch: crisis arms `research_risk_off` and flattens tagged strategies. `POST /api/desk/regime/execute` is HTTP 410 — no broker.
- UI at `/regime` with calm / trending / crisis synthetic books.

## [Unreleased] — round 8: security review (Fase 3, part 1)

Read-through of auth, RBAC, and injection surface rather than a fix-everything
pass — most of what this looked for was already solid (parameterized asyncpg
queries throughout, every owner-scoped query keys off the JWT-derived owner
rather than a client-supplied field, timing-safe login via a dummy bcrypt
hash, JWT algorithm pinned + placeholder-secret rejection, per-endpoint rate
limits already tuned on the newer desk.py routes, dependency audits already
wired into CI). One real gap found and closed:

### Added
- `Content-Security-Policy` header on `docker/nginx.conf`: `default-src 'self'`, `script-src 'self'`, `connect-src 'self'` (the frontend only ever calls same-origin `/api/`, confirmed by reading every `fetch()` call site), Google Fonts allowed for `style-src`/`font-src`, `frame-ancestors 'none'` (clickjacking, redundant with the existing `X-Frame-Options: DENY` but the modern equivalent). No `dangerouslySetInnerHTML` anywhere in the frontend, so this is defense-in-depth rather than a fix for a known injection point. Verified against a live app rather than reasoned about in the abstract: registered a real user, logged in, and drove the derivatives desk (heavy MUI forms) and the Ibovespa dashboard (recharts, icon-heavy cards) through the browser with the policy active — zero violations — before writing it into nginx.

### Notes
- Flagged separately (not fixed here): `docker/nginx-local.conf`, `atom-frontend.service`, `atom-backend.service`, and `ops/systemd/atom-*.service` look like a legacy bare-metal deploy path (one hardcodes `/home/exp/Downloads/ATOM/dist`) that isn't referenced anywhere in `docs/PRODUCTION.md`'s Docker-based flow. Spun off as its own follow-up rather than deleting anything without confirming it's actually dead first.
- Next in Fase 3: dependency audit results review (pip-audit/npm audit already run in CI — worth reading what they currently report, not just confirming they run) and a closer look at token-revocation limits: deactivating an account does immediately invalidate its tokens (confirmed — `get_user_by_username` filters `is_active = TRUE`, so `get_current_user` rejects it), but there's no way to revoke one specific leaked token without deactivating the whole account, and no refresh-token rotation — worth deciding if that's acceptable at pilot scale or worth a token-version/blocklist column.

## [Unreleased] — round 7: closing out Fase 1 (real infra provisioning)

The Postgres migration itself (round 3) ported schema and code; this round
closes the operational gaps that were left pointing at the old SQLite-era
setup — found by reading the deploy/provisioning scripts end to end rather
than just the app code.

### Fixed
- `scripts/deploy.sh`'s pre-deploy backup step still ran the *old SQLite* backup one-liner (`sqlite3.connect("file:/data/atom_reports.db...")`) — since round 3, there is no `/data` SQLite file and the backend container has no `/data` volume at all, so every deploy's backup step would have failed outright the first time it actually ran against a live backend. Replaced with `python -m app.db.maintenance backup` (pg_dump) run inside the container, then copied out to `$APP_DIR/backups/` on the host (mode 600) — the container's own filesystem doesn't survive `compose up` replacing it.
- `backend/Dockerfile` never installed `postgresql-client` — `pg_dump`/`pg_restore` (added in round 3) were missing from the actual production image the whole time. CI's backup/restore test passed anyway because it installs `postgresql-client` on the *runner*, not inside the image, so this went undetected. Also dropped the dead `mkdir -p /data` (leftover from the SQLite volume, unused by any service since round 3).
- `scripts/setup-server.sh`'s generated `.env.prod` template never had an `ATOM_DATABASE_URL` line — following it literally produced a production env file with no database configured at all. Added it (with a `REPLACE_WITH_...` placeholder, matching `.env.example`'s convention) plus `SENTRY_DSN`, and added a migrations step to the script's own "next steps" output so `alembic upgrade head` isn't skipped on a fresh host.

### Added
- `scripts/provision-digitalocean.sh`: `doctl`-based provisioning for a managed Postgres cluster (`postgres` subcommand — cluster, database, user, and prints the resulting `ATOM_DATABASE_URL`) and a staging droplet (`staging` subcommand, reuses `setup-server.sh` for the actual host setup). Idempotent — re-running with the same names reuses existing resources instead of creating duplicates. Requires `doctl auth init` and `jq`; creates real, billed DigitalOcean resources, so it prompts for confirmation unless `--yes` is passed, and is never invoked by CI or any other script. Every `doctl` flag used was checked against `doctl <cmd> --help` locally (this environment had no credentials or network access to actually provision anything, so the JSON-parsing logic was instead verified against hand-built fixtures matching doctl's documented output shape).
- `docs/PRODUCTION.md`: new "Staging" section (same compose and setup script, separate droplet and Postgres cluster from production) and a "Segredos" section explaining, explicitly, why this pilot uses a `.env.prod` file rather than a dedicated secrets vault (Vault, AWS Secrets Manager, ...) — single-host, one operator, no rotation requirement the file doesn't already cover; a vault would be an operational dependency without a problem it solves yet at this scale.

### Notes
- This closes every code-side and documentation-side gap in Fase 1. What remains is provisioning itself — actually running `scripts/provision-digitalocean.sh` against a real account — which needs a human with billing authority and DigitalOcean credentials, not something to do from inside this repo.

## [Unreleased] — round 6: observability foundations (Fase 2)

### Added
- `backend/app/core/observability.py`: per-request `X-Request-ID` (middleware, honors an inbound id from a proxy/client or generates a UUID) threaded through every log line of that request via a `contextvars`-backed logging filter — attached at the handler level so it applies to every module's logger, not just the ones that opt in. Verified against a real request: a forced DB-outage 503 shows the same request id on the client response header and on the server's `ERROR ... Database readiness failed` log line.
- Optional Sentry error tracking (`sentry-sdk[fastapi]`), gated entirely on `SENTRY_DSN` — unset (the default in dev/CI/`.env.example`) means `init_sentry()` is a no-op and nothing about the app's behavior changes. `SENTRY_TRACES_SAMPLE_RATE` defaults to `0.0`: this adds error capture, not performance tracing, which isn't worth the event volume at pilot scale yet.
- `docs/PRODUCTION.md` updated: request-id correlation and Sentry documented under "Controles implementados" and "Validação e limites".

### Notes
- Deliberately did not add structured (JSON) logging or a metrics/Prometheus endpoint in this round — the request-id + Sentry combination covers the concrete gap (an operator today has no way to trace one request's story or get paged on an unhandled exception); log-shipping/metrics infrastructure is a decision for whoever stands up the real observability stack, not something to guess at from this repo alone.

## [Unreleased] — round 5: Heston smile, Johansen, live books, EDGAR

### Added
- **Heston smile calibration** (`POST /api/desk/heston/calibrate`) — least-squares on European prices; payload includes smile IV dump and unidentified-parameter `what_broke`.
- **Johansen trace test** (`POST /api/desk/pairs/johansen`); pairs backtest now also reports rank when the sample is long enough.
- **Live unsigned perp mids** (`GET /api/desk/perp-arb/live`) — Binance USDM bookTicker + Hyperliquid L2; no keys, no orders.
- **SEC EDGAR Form 4 pull** (`POST /api/desk/insider-clusters/edgar`) — open-market P/S only; requires `ATOM_SEC_USER_AGENT` with a contact email.
- Desk Lab tabs for calibration, Johansen, live perps, and EDGAR ticker lookup.

## [Unreleased] — round 4: desk math, papers, and production hygiene

### Fixed
- **EVT CVaR** now uses McNeil `(VaR + σ − ξu)/(1−ξ)`; GPD `n_total` is the full loss sample so zeta is not overstated.
- **Parametric VaR** scales the mean by `h` and vol by `√h`; historical multi-day VaR uses overlapping compounded returns; Student-t CVaR is the t expected-shortfall formula, not `1.1×VaR`.
- **Heston `price_option`** uses `n_steps = round(252·T)` instead of a hardcoded 252-step grid of `dt=T/252`; Europeans also have a characteristic-function pricer.
- **GARCH** optimizer no longer floors `β` at 0.5; **EWMA** includes the latest return; **Sortino** uses downside deviation.
- JWT stream, Ibovespa Excel export, and Binance Kelly now send auth / capital correctly; futures-account polling (410) is gone.
- Alpha engine expected returns no longer peek at the held-out last row.
- Placeholder `SECRET_KEY` values are rejected; rate limits key off the JWT subject; AI screener is 2/hour and defaults to 6 tickers.

### Added
- Desk papers at `/api/desk` and `/desk`: Heston CF, Engle–Granger pairs, Avellaneda–Stoikov, Fama–French 5, mean-reversion scanner, perp basis calculator, insider clusters. Each payload includes `what_broke`.
- `docs/WHAT-BROKE.md` — formula bugs and remaining theatre, written the way a reviewer actually reads a quant repo.

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
- `backend/app/db/migrate_legacy_sqlite.py`: one-time data migration for any pre-cutover `atom_reports.db` — copies `users`, `reports`, `experiments`, `experiment_reviews` into the new Postgres schema (the other four tables added by this round never existed in SQLite, so there's nothing to carry over for them). Runs inside one transaction, refuses to run against a target that already has rows unless `--force`, and supports `--dry-run`. Verified end to end against a throwaway Postgres container using the project's real dev `atom_reports.db` (2 experiment rows; no users/reports had been created yet).

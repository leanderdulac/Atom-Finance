# Operation program: oracles, panel, monitors, calibration

How the client operation flow fits together (rounds 29–30). Everything is
paper: no route here sends broker orders, and every probabilistic number
ships with the assumptions that produced it.

## 1. Oracles (`/api/oracle/*`)

One quote per symbol from many providers. Routing: B3 → brapi + yfinance;
crypto → Binance + yfinance; US → yfinance + Tradier (when configured).
The oracle arbitrates by median of the *fresh* lasts, flags disagreement
above 50 bps, and reports staleness per source. Freshness is mode-aware:
realtime keeps the strict bar (30s crypto, 5min equities) while delayed
feeds get 25min on equities (expected ~15min lag + margin). Providers
without a source
timestamp are display-only unless alone (flagged). When every provider
fails the answer is `usable: false` + blockers — never a synthetic price.

`GET /api/oracle/chain` returns normalized multi-expiry US chains for
Heston calibration; `GET /api/oracle/heartbeat` reads the fetch diary
(ok/error/latency) plus configured flags. It never probes providers.

## 2. Panel (`/cliente`)

`POST /api/client/ready-operation` assembles entry/stop/target/size from
explicit rules. `POST /api/client/simulate` runs GBM Monte Carlo over
declared levels: P(profit), P&L percentiles, expected shortfall, the
stop/target/expiry split — conditioned on stated vol, drift 0 and
first-touch fills. The page shows the distribution, the oracle provenance
card, and the `what_broke` list next to every number.

`POST /api/desk/heston/calibrate-live` fits Heston on a live US chain.
`r`/`q` are the operator's assumptions, echoed in the request.

## 3. Monitors (`/cliente/monitores`)

A declared paper operation (ticker, direction, levels, horizon, vol).
Declaration snapshots a simulation baseline conditioned on entry at the
level. Each `/check` reads the oracle spot and evaluates:

- `watching` → `active` on entry touch (first sight within 0.5% fills,
  noted); unfilled at horizon → `expired`.
- `active` → `stopped` / `target_hit` on touch, `expired` at horizon
  (marked to market). A gap crossing both resolves to the stop.
- alerts: near stop/target (25% of initial range), 75% time elapsed,
  stale quote, disagreeing sources. Checks are snapshots: intra-check
  touches are missed — stated on every evaluation.

Tables: `operation_monitors`, `monitor_checks` (migration
`c59e013daef9`). Owner-scoped; writes serialized per owner. The diary
(`paper_trades`) stays the only trade-state writer — monitors never
insert there.

## 4. Calibration (`POST /api/desk/calibration/coverage`)

Walk-forward coverage of GBM forecast intervals: EWMA vol, drift 0,
non-overlapping blocks (step = horizon, so no return counts twice).
Reports coverage vs the nominal level with a binomial 95% band, mean
interval width and block starts for audit. Past coverage does not
promise future calibration.

First measurement (2026-11-17, Yahoo adjusted closes): 90% nominal
intervals covered 83.9–87.9% across PETR4/BTC × 5/21d horizons — inside
the 95% band but systematically below nominal (fat-tail shortfall, as
expected). Full report: `docs/reports/calibration-gbm-20261117.md`.

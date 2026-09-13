# Strategy context

The regime loop writes three snapshots here after evaluate/live
(when `persist=true` / `ATOM_STRATEGY_CONTEXT_DIR`):

- `current-regime.md` — label, P(regime), kill-switch state
- `regime-history.md` — append-only rows
- `position-adjustments.md` — half-Kelly targets, not broker tickets

`signals.md` is the catalog. It is not overwritten by the job.

Live books: `POST /api/desk/regime/live`. Four-hour job: `ATOM_REGIME_JOB=1`.
Crisis flatten of *paper* trades: `?flatten=true` or `ATOM_REGIME_KILL_OWNER`.
`POST /api/desk/regime/execute` remains HTTP 410 (no broker).

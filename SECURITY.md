# Security

## Reporting

Private pilot — report security issues to the operator directly. Do not open public
issues for exploitable vulnerabilities.

## Baseline (2026-11-12)

- Dependency audits run in CI: `pip-audit --strict` (backend) and `npm audit --omit=dev`
  (`--audit-level=moderate`). Both must stay clean for high/critical.
- **Dependabot policy**: pip PRs are **closed on sight** — their CI exercises the committed
  `requirements.lock`, not the proposed bump, so green tells nothing; pip bumps land via manual
  `uv pip compile` + full battery. npm and github-actions PRs are exercised by their own CI
  (npm bumps update the lockfile Dependabot installs from) → merge on green, major toolchain
  upgrades (eslint 10, typescript 7) only if their own CI stays green.
- `pip-audit` audits the whole venv, not just the lockfile: a package installed as a
  stray (e.g. `msgpack`, not in `backend/requirements.lock`) still trips local runs.
  Never ship it in the image; keep the venv clean instead of adding it to the lock.
- CI environment drift is a real failure class now: the runner image rolled to Ubuntu
  26.04 (2026-11-12) twice in one week (apt postgresql-client 16→gone, client majors
  ahead of the service). The CI `postgres` service tag must track the distro's client
  major (18 today) — bump them together (see ci.yml comment).
- Upgrading pinned packages with uv: `-P` alone does not re-resolve against a lock
  whose exact `==` pins are part of the input (uv treats them as hard constraints and
  conflicts, differently from pip-tools). Relax the pin in the input file first, then
  pass `-P "pkg==fixed-version"`. And check `--refresh`/stale-cache before assuming a
  regen "did nothing": uv serves cached index metadata.

## Deferred / tracked

| Item | Severity | Why deferred | Review when |
|------|----------|--------------|-------------|
| katex >=0.11 <0.18.2 (via react-katex 3.1.0, hard-pins katex ^0.16) | low | Fix requires katex 0.19.x (semver major) + react-katex downgrade — risk of breaking the formula renderer for a low-rated advisory | react-katex supports katex >=0.18, or replace react-katex with direct `katex.renderToString` |
| 224 ESLint warnings (≈189 `no-explicit-any`) | hygiene | Warning level only; does not gate CI | Gradual campaign per touched page |

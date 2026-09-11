#!/usr/bin/env bash
# Single-host pilot deploy. Install this script on the host before enabling CI.
set -euo pipefail
[[ $# == 0 ]] || { echo 'Legacy --local deployment is retired; see docs/PRODUCTION.md' >&2; exit 2; }
APP_DIR="${APP_DIR:-/opt/atom}"
PROD_ENV="${PROD_ENV:-$APP_DIR/.env.prod}"
: "${TARGET_SHA:?Provide the exact commit that passed ATOM CI}"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit' >&2; exit 2; }
[[ -f "$PROD_ENV" ]] || { echo 'Missing production env file' >&2; exit 2; }
# Serialize host deployments as well as GitHub jobs.
exec 9>"$APP_DIR/.deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 2; }
git -C "$APP_DIR" fetch origin main
[[ "$(git -C "$APP_DIR" rev-parse origin/main)" == "$TARGET_SHA" ]] || { echo 'Stale or non-main release rejected' >&2; exit 2; }
release="$APP_DIR/releases/$TARGET_SHA"
mkdir -p "$APP_DIR/releases"
[[ -d "$release" ]] || git -C "$APP_DIR" worktree add --detach "$release" "$TARGET_SHA"
[[ -z "$(git -C "$release" status --porcelain)" ]] || { echo 'Release checkout is dirty' >&2; exit 2; }
compose=(docker compose --project-name atom --env-file "$PROD_ENV" -f "$release/docker-compose.prod.yml")
services=(backend frontend redis)
if [[ "${ATOM_ENABLE_EDGE:-false}" == true ]]; then
  compose+=(-f "$release/docker-compose.edge.yml")
  services+=(edge)
fi
"${compose[@]}" config --quiet
"${compose[@]}" build backend frontend
# Online backup using the currently running image, before changing the service.
if [[ -n "$("${compose[@]}" ps --status running -q backend)" ]]; then
  "${compose[@]}" exec -T backend python -c 'import os,sqlite3,sys; p=sys.argv[1]; fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd); src=sqlite3.connect("file:/data/atom_reports.db?mode=ro",uri=True); dst=sqlite3.connect(p); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchall()==[("ok",)]; dst.close(); src.close()' "/data/predeploy-$(date -u +%Y%m%dT%H%M%SZ).db"
fi
# --wait fails the release if any container fails readiness. Retain images/worktrees.
"${compose[@]}" up -d --wait --wait-timeout 180 "${services[@]}"
printf '%s\n' "$TARGET_SHA" > "$APP_DIR/deployed-sha"
echo "Healthy release: $TARGET_SHA"

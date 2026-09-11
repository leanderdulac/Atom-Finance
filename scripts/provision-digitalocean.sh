#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════════
#  ATOM — DigitalOcean provisioning: managed Postgres and/or a staging droplet
#
#  Creates REAL, BILLED DigitalOcean resources on YOUR account. Run this
#  yourself from a machine with `doctl` authenticated (`doctl auth init`) —
#  it is not invoked by CI or by any other ATOM script. Idempotent: re-running
#  with the same names reuses what already exists instead of duplicating it.
#
#  Usage:
#    bash scripts/provision-digitalocean.sh postgres [--yes]
#    bash scripts/provision-digitalocean.sh staging  [--yes]
#
#  --yes skips the confirmation prompt (for non-interactive use). Config is
#  every ATOM_DO_* env var below — override before invoking, e.g.:
#    ATOM_DO_PG_NAME=atom-postgres-staging bash scripts/provision-digitalocean.sh postgres
# ════════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

command -v doctl >/dev/null || error "doctl not found — https://docs.digitalocean.com/reference/doctl/how-to/install/"
command -v jq >/dev/null    || error "jq not found — required to parse doctl's JSON output."
doctl account get >/dev/null 2>&1 || error "doctl is not authenticated — run 'doctl auth init' first."

# ── Config (override via env before invoking) ─────────────────────────────────
REGION="${ATOM_DO_REGION:-nyc1}"

PG_CLUSTER_NAME="${ATOM_DO_PG_NAME:-atom-postgres}"
PG_SIZE="${ATOM_DO_PG_SIZE:-db-s-1vcpu-1gb}"
PG_VERSION="${ATOM_DO_PG_VERSION:-16}"
PG_DB_NAME="${ATOM_DO_PG_DB:-atom_db}"
PG_USER_NAME="${ATOM_DO_PG_USER:-atom}"

STAGING_DROPLET_NAME="${ATOM_DO_STAGING_NAME:-atom-staging}"
STAGING_SIZE="${ATOM_DO_STAGING_SIZE:-s-1vcpu-2gb}"
STAGING_IMAGE="${ATOM_DO_STAGING_IMAGE:-ubuntu-22-04-x64}"
# Comma-separated doctl SSH key IDs or fingerprints — see `doctl compute ssh-key list`.
STAGING_SSH_KEYS="${ATOM_DO_SSH_KEYS:-}"

ASSUME_YES=false
for arg in "$@"; do [[ "$arg" == "--yes" ]] && ASSUME_YES=true; done

confirm() {
  [[ "$ASSUME_YES" == true ]] && return 0
  read -r -p "$1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
}

# doctl wraps both list and create output in a JSON array; fall back to a bare
# object in case a future doctl version changes that for `create`.
first_json_field() { jq -r --arg f "$2" '(if type == "array" then .[0] else . end)[$f]' <<< "$1"; }

provision_postgres() {
  info "Target: Postgres ${PG_VERSION} cluster '${PG_CLUSTER_NAME}' (${PG_SIZE}) in ${REGION}."

  local existing_id cluster_id
  existing_id=$(doctl databases list -o json | jq -r --arg name "$PG_CLUSTER_NAME" '.[] | select(.name == $name) | .id' | head -1)

  if [[ -n "$existing_id" ]]; then
    warn "Cluster '${PG_CLUSTER_NAME}' already exists (id ${existing_id}) — reusing it."
    cluster_id="$existing_id"
  else
    confirm "This creates a real, billed DigitalOcean Postgres cluster (${PG_SIZE} in ${REGION}). Continue?"
    info "Creating cluster (this takes a few minutes with --wait)..."
    local created
    created=$(doctl databases create "$PG_CLUSTER_NAME" \
      --engine pg --version "$PG_VERSION" --region "$REGION" --size "$PG_SIZE" --num-nodes 1 \
      --wait -o json)
    cluster_id=$(first_json_field "$created" id)
    success "Cluster created: ${cluster_id}"
  fi

  if doctl databases db list "$cluster_id" -o json | jq -e --arg n "$PG_DB_NAME" '.[] | select(.name == $n)' >/dev/null; then
    warn "Database '${PG_DB_NAME}' already exists on this cluster."
  else
    info "Creating database '${PG_DB_NAME}'..."
    doctl databases db create "$cluster_id" "$PG_DB_NAME" >/dev/null
    success "Database created."
  fi

  if doctl databases user list "$cluster_id" -o json | jq -e --arg n "$PG_USER_NAME" '.[] | select(.name == $n)' >/dev/null; then
    warn "User '${PG_USER_NAME}' already exists on this cluster."
  else
    info "Creating user '${PG_USER_NAME}'..."
    doctl databases user create "$cluster_id" "$PG_USER_NAME" >/dev/null
    success "User created."
  fi

  local host port password
  host=$(doctl databases connection "$cluster_id" --format Host --no-header)
  port=$(doctl databases connection "$cluster_id" --format Port --no-header)
  password=$(doctl databases user get "$cluster_id" "$PG_USER_NAME" --format Password --no-header)

  echo ""
  echo -e "${GREEN}════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Postgres cluster ready${NC}"
  echo -e "${GREEN}════════════════════════════════════════════════${NC}"
  echo ""
  echo "  Set this in .env.prod (or wherever ATOM_DATABASE_URL is read from):"
  echo ""
  echo "    ATOM_DATABASE_URL=postgresql+asyncpg://${PG_USER_NAME}:${password}@${host}:${port}/${PG_DB_NAME}"
  echo ""
  echo "  Still needed before this is safe to use:"
  echo "  1. Restrict network access to just your app host — a fresh cluster has"
  echo "     no firewall rules, which on DigitalOcean means no inbound access is"
  echo "     allowed until you add one (not the other way around), so this step"
  echo "     is what turns the connection above from refused to reachable:"
  echo "       doctl compute droplet list --format ID,Name  # find your host's ID"
  echo "       doctl databases firewalls append ${cluster_id} --rule droplet:<id>"
  echo "     (use --rule ip_addr:<ip> instead if the app doesn't run on a droplet)"
  echo "  2. Apply migrations against it:"
  echo "       cd backend && ATOM_DATABASE_URL=... alembic upgrade head"
  echo ""
}

provision_staging() {
  [[ -n "$STAGING_SSH_KEYS" ]] || error "Set ATOM_DO_SSH_KEYS to your doctl SSH key ID(s)/fingerprint(s) (comma-separated — see 'doctl compute ssh-key list'). Refusing to create a droplet with no key: DigitalOcean's fallback is emailing a one-time root password, which isn't a safe default for a script."

  info "Target: droplet '${STAGING_DROPLET_NAME}' (${STAGING_SIZE}, ${STAGING_IMAGE}) in ${REGION}."

  local existing_id droplet_id ip
  existing_id=$(doctl compute droplet list -o json | jq -r --arg name "$STAGING_DROPLET_NAME" '.[] | select(.name == $name) | .id' | head -1)

  if [[ -n "$existing_id" ]]; then
    warn "Droplet '${STAGING_DROPLET_NAME}' already exists (id ${existing_id}) — not creating another."
    droplet_id="$existing_id"
  else
    confirm "This creates a real, billed DigitalOcean droplet (${STAGING_SIZE}, ${STAGING_IMAGE} in ${REGION}). Continue?"
    info "Creating staging droplet (this takes a minute with --wait)..."
    local created
    created=$(doctl compute droplet create "$STAGING_DROPLET_NAME" \
      --size "$STAGING_SIZE" --image "$STAGING_IMAGE" --region "$REGION" \
      --ssh-keys "$STAGING_SSH_KEYS" --enable-monitoring --wait -o json)
    droplet_id=$(first_json_field "$created" id)
    success "Droplet created: ${droplet_id}"
  fi

  ip=$(doctl compute droplet get "$droplet_id" --format PublicIPv4 --no-header)

  echo ""
  echo -e "${GREEN}════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Staging droplet ready${NC}"
  echo -e "${GREEN}════════════════════════════════════════════════${NC}"
  echo ""
  echo "  IP: ${ip}"
  echo ""
  echo "  Next: run the same first-time setup used for production, against this box:"
  echo "    ssh root@${ip} 'bash -s' < scripts/setup-server.sh"
  echo ""
  echo "  Give staging its own Postgres cluster and database — don't point it at"
  echo "  production data. e.g.:"
  echo "    ATOM_DO_PG_NAME=atom-postgres-staging bash scripts/provision-digitalocean.sh postgres"
  echo ""
}

case "${1:-}" in
  postgres) provision_postgres ;;
  staging)  provision_staging ;;
  *) error "Usage: $0 {postgres|staging} [--yes]" ;;
esac

#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════════
#  ATOM — Deploy / Update Script
#  Run on the server to pull latest code and restart containers:
#
#    bash /opt/atom/scripts/deploy.sh
#
#  Or trigger automatically via GitHub Actions (see .github/workflows/deploy.yml)
# ════════════════════════════════════════════════════════════════════════════════
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/atom}"
PROD_ENV="${PROD_ENV:-${APP_DIR}/.env.prod}"
COMPOSE="docker compose -f ${APP_DIR}/docker-compose.prod.yml --env-file ${PROD_ENV}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
success() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✓${NC} $*"; }
error()   { echo -e "${RED}[$(date +%H:%M:%S)] ✗${NC} $*"; exit 1; }

[[ -d "$APP_DIR/.git" ]] || error "Repository not found at ${APP_DIR}. Run setup-server.sh first."
[[ -f "$PROD_ENV" ]]     || error ".env.prod not found at ${PROD_ENV}. Run setup-server.sh first."

info "═══════════════════════════════════════════════"
info "  ATOM Deploy — $(date -u '+%Y-%m-%d %H:%M UTC')"
info "═══════════════════════════════════════════════"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
info "1/5 Pulling latest code from GitHub..."
git -C "$APP_DIR" fetch --prune origin
PREV_SHA=$(git -C "$APP_DIR" rev-parse HEAD)
git -C "$APP_DIR" reset --hard origin/main
NEW_SHA=$(git -C "$APP_DIR" rev-parse HEAD)

if [[ "$PREV_SHA" == "$NEW_SHA" ]]; then
    info "Already at latest commit (${NEW_SHA:0:8}). Forcing rebuild anyway."
else
    success "Updated ${PREV_SHA:0:8} → ${NEW_SHA:0:8}"
    git -C "$APP_DIR" log --oneline "$PREV_SHA".."$NEW_SHA"
fi

# ── 2. Build new images ───────────────────────────────────────────────────────
info "2/5 Building Docker images..."
$COMPOSE build --no-cache backend frontend
success "Images built."

# ── 3. Apply DB migrations (if any) ──────────────────────────────────────────
info "3/5 Running database migrations (if any)..."
# SQLite migrations are handled automatically by database.py at startup.
# Uncomment if you switch to Alembic/PostgreSQL:
# $COMPOSE run --rm backend alembic upgrade head
success "Database ready."

# ── 4. Rolling restart ────────────────────────────────────────────────────────
info "4/5 Restarting services with zero-downtime..."

# Restart backend first (stateless workers)
$COMPOSE up -d --no-deps --remove-orphans backend
sleep 5

# Wait for backend health check
RETRIES=0
until $COMPOSE exec backend curl -sf http://localhost:8000/api/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    [[ $RETRIES -ge 15 ]] && error "Backend health check failed after 30s. Check logs: docker compose logs backend"
    info "Waiting for backend... (${RETRIES}/15)"
    sleep 2
done
success "Backend healthy."

# Then restart nginx/frontend
$COMPOSE up -d --no-deps --remove-orphans frontend
success "Frontend updated."

# ── 5. Cleanup old images ─────────────────────────────────────────────────────
info "5/5 Cleaning up unused Docker images..."
docker image prune -f --filter "until=24h" > /dev/null
success "Cleanup done."

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy successful!${NC}"
echo -e "${GREEN}  Commit: ${NEW_SHA:0:8}${NC}"
echo -e "${GREEN}  Time: $(date -u '+%Y-%m-%d %H:%M UTC')${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""

# Show running containers
$COMPOSE ps

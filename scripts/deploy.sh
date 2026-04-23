#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════════
#  ATOM — Deploy / Update Script
#  Suporta dois modos:
#
#  Modo Docker (DigitalOcean + docker-compose.prod.yml):
#    bash /opt/atom/scripts/deploy.sh
#
#  Modo Local (systemd direto, sem Docker):
#    bash /opt/atom/scripts/deploy.sh --local
#
#  Trigger automático via GitHub Actions → .github/workflows/deploy.yml
# ════════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Parse flags ───────────────────────────────────────────────────────────────
MODE="docker"
[[ "${1:-}" == "--local" ]] && MODE="local"

APP_DIR="${APP_DIR:-/opt/atom}"
# Local mode uses the repo in-place
[[ "$MODE" == "local" ]] && APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROD_ENV="${PROD_ENV:-${APP_DIR}/.env.prod}"
# Local mode uses .env in the repo root
[[ "$MODE" == "local" ]] && PROD_ENV="${APP_DIR}/.env"

COMPOSE="docker compose -f ${APP_DIR}/docker-compose.prod.yml --env-file ${PROD_ENV}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
success() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠${NC} $*"; }
error()   { echo -e "${RED}[$(date +%H:%M:%S)] ✗${NC} $*"; exit 1; }

info "═══════════════════════════════════════════════"
info "  ATOM Deploy — $(date -u '+%Y-%m-%d %H:%M UTC')"
info "  Mode: ${MODE}"
info "═══════════════════════════════════════════════"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
info "1/5 Pulling latest code from GitHub..."
PREV_SHA=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")
git -C "$APP_DIR" fetch --prune origin
git -C "$APP_DIR" reset --hard origin/main
NEW_SHA=$(git -C "$APP_DIR" rev-parse HEAD)

if [[ "$PREV_SHA" == "$NEW_SHA" ]]; then
    warn "Already at latest commit (${NEW_SHA:0:8}). Forcing rebuild."
else
    success "Updated ${PREV_SHA:0:8} → ${NEW_SHA:0:8}"
fi

# ══════════════════════════════════════════════════════
# DOCKER MODE
# ══════════════════════════════════════════════════════
if [[ "$MODE" == "docker" ]]; then
    [[ -d "$APP_DIR/.git" ]] || error "Repository not found at ${APP_DIR}. Run setup-server.sh first."
    [[ -f "$PROD_ENV" ]]     || error ".env.prod not found at ${PROD_ENV}. Run setup-server.sh first."

    info "2/5 Building Docker images..."
    $COMPOSE build --no-cache backend frontend
    success "Images built."

    info "3/5 Database auto-migrated at startup (SQLite)."

    info "4/5 Rolling restart..."
    $COMPOSE up -d --no-deps --remove-orphans backend
    sleep 5

    RETRIES=0
    until $COMPOSE exec backend python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" > /dev/null 2>&1; do
        RETRIES=$((RETRIES + 1))
        [[ $RETRIES -ge 15 ]] && error "Backend health check failed. Logs: docker compose logs backend"
        info "Waiting for backend... (${RETRIES}/15)"
        sleep 2
    done
    success "Backend healthy."

    $COMPOSE up -d --no-deps --remove-orphans frontend
    success "Frontend updated."

    info "5/5 Cleaning up old images..."
    docker image prune -f --filter "until=24h" > /dev/null

# ══════════════════════════════════════════════════════
# LOCAL MODE (systemd + venv + nginx)
# ══════════════════════════════════════════════════════
else
    VENV="${APP_DIR}/backend/venv/bin"
    [[ -f "${VENV}/python" ]] || error "Python venv not found at ${VENV}. Run: cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt"

    info "2/5 Installing/updating Python dependencies..."
    "${VENV}/pip" install -q -r "${APP_DIR}/backend/requirements.txt"
    success "Python deps up to date."

    info "3/5 Building Vite production bundle..."
    cd "$APP_DIR"
    npm ci --silent
    npm run build
    success "Frontend built to dist/."

    info "4/5 Reloading systemd services..."
    systemctl daemon-reload

    # Restart backend (uvicorn)
    systemctl restart atom-backend.service
    sleep 3
    systemctl is-active atom-backend.service || error "Backend failed to start. Check: journalctl -u atom-backend -n 50"
    success "Backend restarted."

    # Validate nginx config then restart frontend
    nginx -t -c "${APP_DIR}/docker/nginx-local.conf" || error "nginx config invalid. Check docker/nginx-local.conf"
    systemctl restart atom-frontend.service
    sleep 2
    systemctl is-active atom-frontend.service || error "Frontend failed to start. Check: journalctl -u atom-frontend -n 50"
    success "Frontend (nginx) restarted."

    info "5/5 Health check..."
    sleep 2
    curl -sf http://127.0.0.1:8000/api/health | python3 -m json.tool || warn "Health check failed — check backend logs."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy successful! (${MODE} mode)${NC}"
echo -e "${GREEN}  Commit: ${NEW_SHA:0:8}${NC}"
echo -e "${GREEN}  Time: $(date -u '+%Y-%m-%d %H:%M UTC')${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"

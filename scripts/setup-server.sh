#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════════
#  ATOM — First-time DigitalOcean Droplet Setup
#  Run once as ROOT on a fresh Ubuntu 22.04 LTS droplet:
#
#    curl -fsSL https://raw.githubusercontent.com/leanderdulac/Atom-Finance/main/scripts/setup-server.sh | bash
#
#  Or copy and run manually.
# ════════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
APP_USER="atom"
APP_DIR="/opt/atom"
REPO_URL="https://github.com/leanderdulac/Atom-Finance.git"
BRANCH="main"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "Run this script as root."

info "═══════════════════════════════════════════════"
info "  ATOM — Server Setup (Ubuntu 22.04 LTS)"
info "═══════════════════════════════════════════════"

# ── 1. System update ──────────────────────────────────────────────────────────
info "1/9 Updating system packages..."
apt-get update -qq && apt-get upgrade -yq
apt-get install -yq curl git ufw fail2ban ca-certificates gnupg lsb-release

# ── 2. Create non-root deploy user ────────────────────────────────────────────
info "2/9 Creating deploy user '${APP_USER}'..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -m -s /bin/bash -G sudo "$APP_USER"
    # Copy root's authorized_keys so you can SSH as atom too
    if [[ -f /root/.ssh/authorized_keys ]]; then
        mkdir -p /home/$APP_USER/.ssh
        cp /root/.ssh/authorized_keys /home/$APP_USER/.ssh/
        chown -R $APP_USER:$APP_USER /home/$APP_USER/.ssh
        chmod 700 /home/$APP_USER/.ssh
        chmod 600 /home/$APP_USER/.ssh/authorized_keys
    fi
    success "User '${APP_USER}' created."
else
    warn "User '${APP_USER}' already exists, skipping."
fi

# ── 3. Firewall ───────────────────────────────────────────────────────────────
info "3/9 Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP'
ufw allow 443/tcp   comment 'HTTPS'
ufw --force enable
success "Firewall active. Ports: 22 (SSH), 80 (HTTP), 443 (HTTPS)."

# ── 4. Fail2Ban ───────────────────────────────────────────────────────────────
info "4/9 Enabling Fail2Ban (SSH brute-force protection)..."
systemctl enable --now fail2ban
success "Fail2Ban active."

# ── 5. Docker ─────────────────────────────────────────────────────────────────
info "5/9 Installing Docker..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -yq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    usermod -aG docker "$APP_USER"
    success "Docker $(docker --version) installed."
else
    warn "Docker already installed: $(docker --version)"
fi

# ── 6. Clone repository ───────────────────────────────────────────────────────
info "6/9 Cloning ATOM repository to ${APP_DIR}..."
if [[ -d "$APP_DIR/.git" ]]; then
    warn "Repository already cloned. Running git pull instead."
    git -C "$APP_DIR" pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
    chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
fi
success "Repository ready at ${APP_DIR}."

# ── 7. Production .env ────────────────────────────────────────────────────────
info "7/9 Setting up production .env..."
PROD_ENV="$APP_DIR/.env.prod"

if [[ -f "$PROD_ENV" ]]; then
    warn ".env.prod already exists — skipping generation. Edit manually if needed."
else
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    PG_PASS=$(python3 -c "import secrets; print(secrets.token_hex(16))")

    cat > "$PROD_ENV" << EOF
# ── ATOM Production Environment ──────────────────────────────────
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# IMPORTANT: Fill in your API keys below before starting.

ATOM_ENV=production

# Security (auto-generated — do NOT change after first start)
SECRET_KEY=${SECRET}
POSTGRES_PASSWORD=${PG_PASS}

# Domain (update to your actual domain)
FRONTEND_URL=https://atom.yourdomain.com
ALLOWED_ORIGINS=https://atom.yourdomain.com

# B3 Market Data — https://brapi.dev (free tier: 15 req/min)
BRAPI_TOKEN=

# AI Providers — fill in the keys you have
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=
PERPLEXITY_API_KEY=
BRIDGEWISE_TOKEN=

# Database (auto-configured via docker internal network)
DATABASE_URL=postgresql+asyncpg://atom:${PG_PASS}@postgres:5432/atom_db
REDIS_URL=redis://redis:6379/0
ACCESS_TOKEN_EXPIRE_HOURS=24
EOF

    chmod 600 "$PROD_ENV"
    chown "$APP_USER":"$APP_USER" "$PROD_ENV"

    echo ""
    echo -e "${YELLOW}════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ACTION REQUIRED: Edit your API keys${NC}"
    echo -e "${YELLOW}  nano ${PROD_ENV}${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════${NC}"
    echo ""
fi

# ── 8. Systemd service (manages docker-compose lifecycle) ─────────────────────
info "8/9 Installing systemd service for ATOM..."
cat > /etc/systemd/system/atom.service << EOF
[Unit]
Description=ATOM Quantitative Finance Platform
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
EnvironmentFile=${PROD_ENV}
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml --env-file ${PROD_ENV} up -d --build
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=300
User=${APP_USER}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable atom.service
success "Systemd service 'atom' installed and enabled on boot."

# ── 9. Summary ────────────────────────────────────────────────────────────────
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ATOM Server Setup Complete!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Fill in your API keys:"
echo "     nano ${PROD_ENV}"
echo ""
echo "  2. Start ATOM:"
echo "     systemctl start atom"
echo ""
echo "  3. Check logs:"
echo "     journalctl -u atom -f"
echo "     docker compose -f ${APP_DIR}/docker-compose.prod.yml logs -f"
echo ""
echo "  4. Point your domain to this server:"
echo "     A record → ${SERVER_IP}"
echo ""
echo "  5. (Optional) Set up TLS via Cloudflare or Certbot:"
echo "     bash ${APP_DIR}/scripts/setup-ssl.sh yourdomain.com"
echo ""

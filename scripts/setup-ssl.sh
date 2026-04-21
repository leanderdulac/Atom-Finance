#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════════
#  ATOM — Let's Encrypt SSL Setup (Certbot + nginx)
#  Run AFTER setup-server.sh and AFTER pointing your DNS to the server:
#
#    bash /opt/atom/scripts/setup-ssl.sh atom.yourdomain.com
#
#  If using Cloudflare (recommended), set SSL/TLS → Full (strict) in CF dashboard
#  and skip this script — Cloudflare handles TLS termination for free.
# ════════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DOMAIN="${1:-}"
[[ -z "$DOMAIN" ]] && { echo "Usage: $0 <domain>  (e.g. atom.yourdomain.com)"; exit 1; }

APP_DIR="${APP_DIR:-/opt/atom}"
PROD_ENV="${APP_DIR}/.env.prod"

apt-get install -yq certbot python3-certbot-nginx

# Stop nginx temporarily so certbot can use port 80
docker compose -f "${APP_DIR}/docker-compose.prod.yml" --env-file "$PROD_ENV" stop frontend

# Obtain certificate
certbot certonly --standalone -d "$DOMAIN" \
    --agree-tos --non-interactive \
    --email "admin@${DOMAIN}"

# Write nginx config with TLS
cat > "${APP_DIR}/docker/nginx.conf" << NGINX
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        root /usr/share/nginx/html;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }

    location / {
        root /usr/share/nginx/html;
        try_files \$uri \$uri/ /index.html;
        add_header Cache-Control "no-cache";
    }
}
NGINX

# Update FRONTEND_URL in .env.prod
sed -i "s|FRONTEND_URL=.*|FRONTEND_URL=https://${DOMAIN}|" "$PROD_ENV"
sed -i "s|ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=https://${DOMAIN}|" "$PROD_ENV"

# Restart nginx with new config (mount certs)
docker compose -f "${APP_DIR}/docker-compose.prod.yml" --env-file "$PROD_ENV" up -d frontend

# Auto-renew cron
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && docker compose -f ${APP_DIR}/docker-compose.prod.yml restart frontend") | crontab -

echo "✓ TLS configured for https://${DOMAIN}"
echo "✓ Auto-renewal cron installed (daily at 03:00)"

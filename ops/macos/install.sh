#!/usr/bin/env bash
# Instala os serviços launchd do ATOM neste Mac (idempotente).
# Uso: ./ops/macos/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABELS=(com.atom.backend com.atom.worker com.atom.frontend com.atom.tunnel)
LOGS="${HOME}/Library/Logs/atom"
AGENTS="${HOME}/Library/LaunchAgents"
ENV_FILE="${ATOM_ENV_FILE:-$ROOT/.env}"

mkdir -p "$LOGS" "$AGENTS"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Crie $ENV_FILE a partir de .env.example (SECRET_KEY, ATOM_DATABASE_URL, ATOM_CLIENT_MODE=true)." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
# Só exporta linhas KEY=VALUE; ignora comentários.
# Não imprime o arquivo.
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    ''|\#*) continue ;;
    *=*) export "$line" ;;
  esac
done < "$ENV_FILE"
set +a

CLOUDFLARED="$(command -v cloudflared || true)"
if [[ -z "$CLOUDFLARED" ]]; then
  CLOUDFLARED="/opt/homebrew/bin/cloudflared"
fi
TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"

render() {
  local src="$1" dest="$2"
  sed -e "s|__ATOM_HOME__|$ROOT|g" \
      -e "s|__ATOM_LOGS__|$LOGS|g" \
      -e "s|__CLOUDFLARED__|$CLOUDFLARED|g" \
      -e "s|__TUNNEL_TOKEN__|$TUNNEL_TOKEN|g" \
      "$src" > "$dest"
}

if [[ ! -x "$ROOT/backend/venv/bin/uvicorn" ]]; then
  echo "backend/venv não encontrado. Crie o venv e instale requirements.lock antes." >&2
  exit 1
fi

if [[ ! -d "$ROOT/dist" ]]; then
  echo "Buildando o frontend de produção…"
  (cd "$ROOT" && npm run build)
fi

# Quando o worker separado está no ar, o uvicorn não duplica os loops.
# install.sh grava isso no .env se ainda não existir.
touch "$ENV_FILE"
grep -q '^ATOM_REGIME_JOB=' "$ENV_FILE" || echo 'ATOM_REGIME_JOB=0' >> "$ENV_FILE"
grep -q '^ATOM_CLIENT_JOB=' "$ENV_FILE" || echo 'ATOM_CLIENT_JOB=0' >> "$ENV_FILE"
grep -q '^ATOM_CLIENT_MODE=' "$ENV_FILE" || echo 'ATOM_CLIENT_MODE=true' >> "$ENV_FILE"

uid="$(id -u)"
for label in "${LABELS[@]}"; do
  tpl="$ROOT/ops/macos/${label}.plist.tpl"
  dest="$AGENTS/${label}.plist"
  if [[ "$label" == "com.atom.tunnel" && -z "$TUNNEL_TOKEN" ]]; then
    echo "CLOUDFLARE_TUNNEL_TOKEN vazio — pulando o túnel. Documente o token no .env e rode de novo."
    continue
  fi
  render "$tpl" "$dest"
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$dest"
  launchctl enable "gui/$uid/$label"
  launchctl kickstart -k "gui/$uid/$label"
  echo "ativo: $label"
done

cat <<EOF

ATOM no Mac
  logs:     $LOGS
  backend:  http://127.0.0.1:8000/api/health
  frontend: http://127.0.0.1:4173

Sono: o backend sobe via caffeinate -dims (idle, disco, sistema, display).
Para impedir o sono mesmo com a tampa fechada, na tomada:

  sudo pmset -c sleep 0 disksleep 0 disablesleep 0

Na bateria o Mac pode dormir — deixe ligado na tomada quando servir o público.
Desinstalação: ./ops/macos/uninstall.sh
EOF

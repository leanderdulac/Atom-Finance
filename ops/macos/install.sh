#!/usr/bin/env bash
# Instala os serviços launchd do ATOM neste Mac (idempotente).
# Uso: ./ops/macos/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=ops/macos/lib.sh
source "$ROOT/ops/macos/lib.sh"

LABELS=(com.atom.backend com.atom.worker com.atom.frontend com.atom.tunnel)
LOGS="${HOME}/Library/Logs/atom"
AGENTS="${HOME}/Library/LaunchAgents"
ENV_FILE="${ATOM_ENV_FILE:-$ROOT/.env}"

mkdir -p "$LOGS" "$AGENTS"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Crie $ENV_FILE a partir de .env.example (ATOM_DATABASE_URL, ATOM_CLIENT_MODE=true)." >&2
  echo "SECRET_KEY é gerado automaticamente se estiver ausente." >&2
  exit 1
fi

python3 "$ROOT/ops/macos/ensure_secret.py" "$ENV_FILE"

atom_upsert_env "$ENV_FILE" ATOM_API_HOST "127.0.0.1"
atom_upsert_env "$ENV_FILE" ATOM_API_PORT "8000"
atom_upsert_env "$ENV_FILE" ATOM_UI_HOST "127.0.0.1"
atom_upsert_env "$ENV_FILE" ATOM_UI_PORT "4173"
atom_upsert_env "$ENV_FILE" ATOM_REGIME_JOB "0"
atom_upsert_env "$ENV_FILE" ATOM_CLIENT_JOB "0"
atom_upsert_env "$ENV_FILE" ATOM_CLIENT_MODE "true"

atom_load_env "$ENV_FILE"

VENV="$(atom_resolve_venv "$ROOT")"
if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "venv não encontrado em $VENV." >&2
  echo "Defina ATOM_VENV=/caminho/.venv ou crie backend/venv e instale requirements.lock." >&2
  exit 1
fi

if [[ ! -d "$ROOT/dist" ]]; then
  echo "Buildando o frontend de produção…"
  (cd "$ROOT" && npm run build)
fi

CLOUDFLARED="$(command -v cloudflared || true)"
if [[ -z "$CLOUDFLARED" ]]; then
  for candidate in /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared; do
    if [[ -x "$candidate" ]]; then
      CLOUDFLARED="$candidate"
      break
    fi
  done
fi
if [[ -z "$CLOUDFLARED" || ! -x "$CLOUDFLARED" ]]; then
  echo "cloudflared não encontrado. Instale com: brew install cloudflared" >&2
  exit 1
fi

DOCKER="$(command -v docker || true)"
if [[ -z "$DOCKER" ]]; then
  for candidate in /opt/homebrew/bin/docker /usr/local/bin/docker; do
    if [[ -x "$candidate" ]]; then
      DOCKER="$candidate"
      break
    fi
  done
fi
if [[ "${ATOM_SEARXNG:-}" == "1" ]]; then
  if [[ -z "$DOCKER" || ! -x "$DOCKER" ]]; then
    echo "ATOM_SEARXNG=1 mas docker não encontrado — SearXNG não será instalado." >&2
  else
    LABELS+=(com.atom.searxng)
    atom_upsert_env "$ENV_FILE" SEARXNG_URL "http://127.0.0.1:8888"
  fi
fi

render() {
  local src="$1" dest="$2"
  sed -e "s|__ATOM_HOME__|$ROOT|g" \
      -e "s|__ATOM_LOGS__|$LOGS|g" \
      -e "s|__ATOM_ENV_FILE__|$ENV_FILE|g" \
      -e "s|__ATOM_VENV__|$VENV|g" \
      -e "s|__CLOUDFLARED__|$CLOUDFLARED|g" \
      -e "s|__DOCKER__|${DOCKER:-docker}|g" \
      "$src" > "$dest"
}

uid="$(id -u)"
for label in "${LABELS[@]}"; do
  tpl="$ROOT/ops/macos/${label}.plist.tpl"
  dest="$AGENTS/${label}.plist"
  render "$tpl" "$dest"
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$dest"
  launchctl enable "gui/$uid/$label"
  launchctl kickstart -k "gui/$uid/$label"
  echo "ativo: $label"
done

API_HOST="${ATOM_API_HOST:-127.0.0.1}"
API_PORT="${ATOM_API_PORT:-8000}"
UI_HOST="${ATOM_UI_HOST:-127.0.0.1}"
UI_PORT="${ATOM_UI_PORT:-4173}"
URL_FILE="$LOGS/public-url.txt"

echo "Aguardando URL do túnel em ${URL_FILE}…"
public=""
for _ in $(seq 1 45); do
  if [[ -s "${URL_FILE}" ]]; then
    public="$(tr -d '\r' < "${URL_FILE}" | awk 'NF{print; exit}')"
    break
  fi
  sleep 1
done

cat <<EOF

ATOM no Mac
  logs:     $LOGS
  venv:     $VENV
  backend:  http://${API_HOST}:${API_PORT}/api/health  (loopback; não é a porta pública)
  origem:   http://${UI_HOST}:${UI_PORT}  (UI + proxy /api — um túnel só)
EOF

if [[ -z "$public" ]]; then
  echo "  público:  ainda não gravado — veja $LOGS/tunnel.log"
elif [[ "$public" == "named-tunnel" ]]; then
  echo "  público:  túnel nomeado (CLOUDFLARE_TUNNEL_TOKEN)."
  echo "            No Zero Trust, um origin: http://${UI_HOST}:${UI_PORT}"
  if [[ -n "${ATOM_PUBLIC_URL:-}" ]]; then
    echo "            ATOM_PUBLIC_URL=${ATOM_PUBLIC_URL}"
  fi
else
  echo "  público:  $public"
  echo "            Quick tunnel: este endereço muda a cada reinício."
  echo "            Gravado em ${URL_FILE}"
fi

cat <<EOF

Sono: o backend sobe via caffeinate -dims (idle, disco, sistema, display).
Para impedir o sono mesmo com a tampa fechada, na tomada:

  sudo pmset -c sleep 0 disksleep 0 disablesleep 0

Na bateria o Mac pode dormir — deixe ligado na tomada quando servir o público.
Desinstalação: ./ops/macos/uninstall.sh
EOF

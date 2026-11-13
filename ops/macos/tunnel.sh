#!/usr/bin/env bash
# Túnel Cloudflare: nomeado se houver token; senão quick tunnel.
# Grava a URL pública em $ATOM_LOGS/public-url.txt. Nunca imprime o token.
set -euo pipefail

ROOT="${ATOM_HOME:?ATOM_HOME não definido}"
LOGS="${ATOM_LOGS:?ATOM_LOGS não definido}"
ENV_FILE="${ATOM_ENV_FILE:-$ROOT/.env}"
# shellcheck source=ops/macos/lib.sh
source "$ROOT/ops/macos/lib.sh"
atom_load_env "$ENV_FILE"

mkdir -p "$LOGS"
URL_FILE="$LOGS/public-url.txt"
HOST="${ATOM_UI_HOST:-127.0.0.1}"
PORT="${ATOM_UI_PORT:-4173}"
ORIGIN="http://${HOST}:${PORT}"

CF="${CLOUDFLARED:-}"
if [[ -z "$CF" ]]; then
  CF="$(command -v cloudflared || true)"
fi
if [[ -z "$CF" ]]; then
  for candidate in /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared; do
    if [[ -x "$candidate" ]]; then
      CF="$candidate"
      break
    fi
  done
fi
if [[ -z "$CF" || ! -x "$CF" ]]; then
  echo "cloudflared não encontrado. brew install cloudflared" >&2
  exit 1
fi

TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
if [[ -n "$TOKEN" ]]; then
  {
    echo "named-tunnel"
    if [[ -n "${ATOM_PUBLIC_URL:-}" ]]; then
      echo "$ATOM_PUBLIC_URL"
    fi
  } > "$URL_FILE"
  exec "$CF" tunnel --no-autoupdate run --token "$TOKEN"
fi

: > "$URL_FILE"

fifo="$LOGS/tunnel.fifo"
rm -f "$fifo"
mkfifo "$fifo"

cleanup() {
  if [[ -n "${CF_PID:-}" ]]; then
    kill "$CF_PID" 2>/dev/null || true
    wait "$CF_PID" 2>/dev/null || true
  fi
  rm -f "$fifo"
}
trap cleanup EXIT TERM INT

"$CF" tunnel --no-autoupdate --url "$ORIGIN" >"$fifo" 2>&1 &
CF_PID=$!

while IFS= read -r line || [[ -n "${line:-}" ]]; do
  printf '%s\n' "$line"
  url="$(atom_extract_trycloudflare_url "$line" || true)"
  if [[ -n "${url:-}" ]]; then
    printf '%s\n' "$url" > "$URL_FILE"
  fi
done < "$fifo"

wait "$CF_PID" || true

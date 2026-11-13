#!/usr/bin/env bash
# Sobe o uvicorn só em loopback, porta do .env. Chamado pelo launchd.
set -euo pipefail

ROOT="${ATOM_HOME:?ATOM_HOME não definido}"
ENV_FILE="${ATOM_ENV_FILE:-$ROOT/.env}"
# shellcheck source=ops/macos/lib.sh
source "$ROOT/ops/macos/lib.sh"
atom_load_env "$ENV_FILE"

VENV="$(atom_resolve_venv "$ROOT")"
HOST="${ATOM_API_HOST:-127.0.0.1}"
PORT="${ATOM_API_PORT:-8000}"
UVICORN="$VENV/bin/uvicorn"

if [[ ! -x "$UVICORN" ]]; then
  echo "uvicorn não encontrado em $UVICORN (ATOM_VENV=$VENV)" >&2
  exit 1
fi

cd "$ROOT/backend"
exec /usr/bin/caffeinate -dims "$UVICORN" main:app \
  --host "$HOST" \
  --port "$PORT" \
  --env-file "$ENV_FILE"

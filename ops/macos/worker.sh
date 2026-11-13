#!/usr/bin/env bash
# Worker de regime + cache. Chamado pelo launchd.
set -euo pipefail

ROOT="${ATOM_HOME:?ATOM_HOME não definido}"
ENV_FILE="${ATOM_ENV_FILE:-$ROOT/.env}"
# shellcheck source=ops/macos/lib.sh
source "$ROOT/ops/macos/lib.sh"
atom_load_env "$ENV_FILE"

VENV="$(atom_resolve_venv "$ROOT")"
PY="$VENV/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "python do venv não encontrado em $PY (ATOM_VENV=$VENV)" >&2
  exit 1
fi

export ATOM_WORKER_REGIME="${ATOM_WORKER_REGIME:-1}"
export ATOM_WORKER_CLIENT="${ATOM_WORKER_CLIENT:-1}"
cd "$ROOT/backend"
exec "$PY" -m app.services.client_worker

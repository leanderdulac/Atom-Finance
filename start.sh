#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  ATOM — Quantitative Finance Platform
#  Script de inicialização: Backend (FastAPI) + Frontend (Vite)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ── Cores ─────────────────────────────────────────────────────
RESET='\033[0m'
BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'

# ── Caminhos ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR"

# The project venv lives at the repo root (.venv); backend/venv is only a
# legacy fallback. Resolved once here so every message shows the real path.
if [[ -f "$SCRIPT_DIR/.venv/bin/python" ]]; then
  BACKEND_PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
  BACKEND_PYTHON="$BACKEND_DIR/venv/bin/python"
fi
BACKEND_PORT=8000
FRONTEND_PORT=5173

LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# PIDs
BACKEND_PID=""
FRONTEND_PID=""
TAIL_PID=""

# ── Funções de utilidade ───────────────────────────────────────
log()     { echo -e "${BOLD}[ATOM]${RESET} $*"; }
success() { echo -e "${GREEN}${BOLD}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}${BOLD}[!]${RESET} $*"; }
error()   { echo -e "${RED}${BOLD}[✗]${RESET} $*"; }

header() {
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}${BOLD}║   ATOM — Quantitative Finance Platform       ║${RESET}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════╝${RESET}"
  echo ""
}

# Portable listener lookup (ss is Linux-only; macOS has lsof; nc as last resort).
# Prints "PID COMMAND" of the process listening on a TCP port, or nothing.
port_listener() {
  local port=$1 line pid pname
  if command -v lsof >/dev/null 2>&1; then
    line=$(lsof -iTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | awk 'NR==2 {print $2, $1}')
    [[ -n "$line" ]] && echo "$line" && return 0
    return 1
  fi
  if command -v ss >/dev/null 2>&1; then
    # Portable pid extraction (no grep -P): pid=NNNN inside users:(("..",pid=..,fd=..)).
    pid=$(ss -tlnp 2>/dev/null | grep ":$port " | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
    if [[ -n "$pid" ]]; then
      pname=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d ' ' | head -1)
      echo "$pid ${pname:-unknown}"
      return 0
    fi
    return 1
  fi
  if nc -z 127.0.0.1 "$port" 2>/dev/null; then
    echo "unknown nc-probe"
    return 0
  fi
  return 1
}

port_free() {
  ! port_listener "$1" >/dev/null 2>&1
}

kill_port() {
  local port=$1 listener pid pname
  listener=$(port_listener "$port") || return 0
  pid=$(echo "$listener" | awk '{print $1}')
  pname=$(echo "$listener" | awk '{print $2}')
  # Never kill processes we cannot identify, or that are not our stack.
  case "$pname" in
    python*|uvicorn*|node*|npm*|vite*)
      ;;
    *)
      error "Porta $port ocupada por '$pname' (PID ${pid:-?}) — libere a porta e rode de novo."
      exit 1
      ;;
  esac
  if [[ -n "$pid" && "$pid" != "unknown" ]]; then
    warn "Porta $port em uso pelo PID $pid ($pname) — encerrando..."
    kill "$pid" 2>/dev/null || true
    sleep 1
  fi
}

# ── Shutdown limpo (Ctrl+C) ────────────────────────────────────
cleanup() {
  echo ""
  log "Encerrando serviços..."

  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
    success "Backend encerrado (PID $BACKEND_PID)"
  fi

  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null
    success "Frontend encerrado (PID $FRONTEND_PID)"
  fi

  if [[ -n "$TAIL_PID" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
    kill "$TAIL_PID" 2>/dev/null
  fi

  echo ""
  log "ATOM encerrado. Até logo! 👋"
  exit 0
}

trap cleanup SIGINT SIGTERM

# ── Pré-verificações ──────────────────────────────────────────
check_requirements() {
  if [[ ! -f "$BACKEND_PYTHON" ]]; then
    error "Python do venv não encontrado em: $BACKEND_PYTHON"
    error "Crie o venv na raiz: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.lock"
    exit 1
  fi

  if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
    error "package.json não encontrado em: $FRONTEND_DIR"
    exit 1
  fi

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    warn "node_modules não encontrado — rodando npm install..."
    npm install --prefix "$FRONTEND_DIR" --silent
  fi
}

# ── Backend ───────────────────────────────────────────────────
start_backend() {
  log "Iniciando ${BOLD}Backend FastAPI${RESET} (porta $BACKEND_PORT)..."

  if ! port_free "$BACKEND_PORT"; then
    kill_port "$BACKEND_PORT"
  fi

  mkdir -p "$LOG_DIR"

  cd "$BACKEND_DIR"
  "$BACKEND_PYTHON" -m uvicorn main:app \
    --host 127.0.0.1 \
    --port "$BACKEND_PORT" \
    --log-level info \
    >> "$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  # Aguarda o backend responder (até 15s). /api/live prova liveness sem
  # exigir banco; /api/health (readiness, 503 sem Postgres) vem depois.
  local retries=0
  while [[ $retries -lt 30 ]]; do
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/live" > /dev/null 2>&1; then
      success "Backend pronto em ${CYAN}http://127.0.0.1:$BACKEND_PORT${RESET} (PID $BACKEND_PID)"
      if ! curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
        warn "/api/health retornou 503: backend no ar, mas sem banco (ATOM_DATABASE_URL?)."
      fi
      return 0
    fi
    sleep 0.5
    retries=$((retries + 1))
  done

  error "Backend não respondeu em 15s. Verifique: $BACKEND_LOG"
  exit 1
}

# ── Frontend ──────────────────────────────────────────────────
start_frontend() {
  log "Iniciando ${BOLD}Frontend Vite${RESET} (porta $FRONTEND_PORT)..."

  if ! port_free "$FRONTEND_PORT"; then
    kill_port "$FRONTEND_PORT"
  fi

  mkdir -p "$LOG_DIR"

  cd "$FRONTEND_DIR"
  npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 \
    >> "$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!

  # Aguarda o frontend responder (até 15s)
  local retries=0
  while [[ $retries -lt 30 ]]; do
    if curl -sf "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
      success "Frontend pronto em ${CYAN}http://localhost:$FRONTEND_PORT${RESET} (PID $FRONTEND_PID)"
      return 0
    fi
    sleep 0.5
    retries=$((retries + 1))
  done

  error "Frontend não respondeu em 15s. Verifique: $FRONTEND_LOG"
  exit 1
}

# ── Sumário ───────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${GREEN}${BOLD}═══════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}${BOLD}  ✓ ATOM rodando com sucesso!${RESET}"
  echo -e "${GREEN}${BOLD}═══════════════════════════════════════════════${RESET}"
  echo ""
  echo -e "  🌐 Frontend : ${CYAN}${BOLD}http://localhost:$FRONTEND_PORT${RESET}"
  echo -e "  ⚡ Backend  : ${CYAN}${BOLD}http://127.0.0.1:$BACKEND_PORT${RESET}"
  echo -e "  📖 API Docs : ${CYAN}${BOLD}http://127.0.0.1:$BACKEND_PORT/docs${RESET}"
  echo ""
  echo -e "  📄 Logs     : ${YELLOW}$LOG_DIR/${RESET}"
  echo -e "    ├─ backend.log"
  echo -e "    └─ frontend.log"
  echo ""
  echo -e "  ${YELLOW}Pressione ${BOLD}Ctrl+C${RESET}${YELLOW} para encerrar todos os serviços.${RESET}"
  echo ""
}

# ── Tail de logs em tempo real ────────────────────────────────
follow_logs() {
  tail -f "$BACKEND_LOG" "$FRONTEND_LOG" 2>/dev/null &
  TAIL_PID=$!
  # Aguarda qualquer processo filho terminar
  wait "$BACKEND_PID" "$FRONTEND_PID"
}

# ── Main ──────────────────────────────────────────────────────
main() {
  header
  check_requirements
  start_backend
  start_frontend
  print_summary
  follow_logs
}

main "$@"

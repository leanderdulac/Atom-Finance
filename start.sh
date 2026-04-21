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

BACKEND_PYTHON="$BACKEND_DIR/venv/bin/python"
BACKEND_PORT=8000
FRONTEND_PORT=5174

LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# PIDs
BACKEND_PID=""
FRONTEND_PID=""

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

port_free() {
  ! ss -tlnp 2>/dev/null | grep -q ":$1 "
}

kill_port() {
  local port=$1
  local pid
  pid=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1)
  if [[ -n "$pid" ]]; then
    warn "Porta $port em uso pelo PID $pid — encerrando..."
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

  echo ""
  log "ATOM encerrado. Até logo! 👋"
  exit 0
}

trap cleanup SIGINT SIGTERM

# ── Pré-verificações ──────────────────────────────────────────
check_requirements() {
  if [[ ! -f "$BACKEND_PYTHON" ]]; then
    error "Python do venv não encontrado em: $BACKEND_PYTHON"
    error "Certifique-se de ter criado o venv: cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
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

  # Aguarda o backend responder (até 15s)
  local retries=0
  while [[ $retries -lt 30 ]]; do
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
      success "Backend pronto em ${CYAN}http://127.0.0.1:$BACKEND_PORT${RESET} (PID $BACKEND_PID)"
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
  npm run dev -- --port "$FRONTEND_PORT" --host \
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

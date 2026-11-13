#!/usr/bin/env bash
# Remove os LaunchAgents do ATOM (idempotente). Não apaga Postgres, Redis nem o código.
set -euo pipefail

LABELS=(com.atom.backend com.atom.worker com.atom.frontend com.atom.tunnel)
AGENTS="${HOME}/Library/LaunchAgents"
uid="$(id -u)"

for label in "${LABELS[@]}"; do
  launchctl bootout "gui/$uid/$label" 2>/dev/null || true
  rm -f "$AGENTS/${label}.plist"
  echo "removido: $label"
done

echo "Logs em ~/Library/Logs/atom/ foram preservados."
echo "pmset não foi revertido — se você alterou o sono, revise com pmset -g."

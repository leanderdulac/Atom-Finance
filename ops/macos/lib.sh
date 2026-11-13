# Funções compartilhadas do install launchd. Não executa nada ao ser sourced.
# Uso: # shellcheck source=ops/macos/lib.sh
#      source "$ROOT/ops/macos/lib.sh"

atom_upsert_env() {
  # atom_upsert_env FILE KEY VALUE — grava KEY=VALUE se KEY ainda não existir.
  local file="$1" key="$2" value="$3"
  touch "$file"
  grep -q "^${key}=" "$file" || printf '%s=%s\n' "$key" "$value" >> "$file"
}

atom_env_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  awk -F= -v k="$key" '$1==k {print substr($0, index($0,$2)); exit}' "$file"
}

atom_load_env() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|\#*) continue ;;
      *=*) export "$line" ;;
    esac
  done < "$file"
}

atom_resolve_venv() {
  local root="$1"
  local raw="${ATOM_VENV:-$root/backend/venv}"
  case "$raw" in
    ~/*) raw="$HOME/${raw#~/}" ;;
  esac
  printf '%s\n' "$raw"
}

atom_extract_trycloudflare_url() {
  local line="$1"
  if [[ "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
}

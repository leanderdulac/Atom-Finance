# ATOM neste Mac (launchd)

O ATOM público roda **neste Mac**: FastAPI em loopback, worker de cache, UI com proxy `/api` na mesma origem, túnel Cloudflare. Paper only — nenhuma ordem real.

O acesso público é **só pelo túnel**. Backend e UI escutam em `127.0.0.1` por padrão — não na LAN.

## O que sobe

| Label | Função |
| --- | --- |
| `com.atom.backend` | `uvicorn` em `ATOM_API_HOST:ATOM_API_PORT` (default `127.0.0.1:8000`), envolvido em `caffeinate -dims` |
| `com.atom.worker` | `python -m app.services.client_worker` — regime + cache dos ativos do cliente |
| `com.atom.frontend` | `ops/macos/serve.py` em `ATOM_UI_HOST:ATOM_UI_PORT` (default `127.0.0.1:4173`): `dist/` + **proxy `/api`** |
| `com.atom.tunnel` | Cloudflare: token → túnel nomeado; sem token → **quick tunnel** |

Logs: `~/Library/Logs/atom/`. URL pública: `~/Library/Logs/atom/public-url.txt`. Reinício automático (`KeepAlive`). Login/boot: `RunAtLoad`.

Um túnel para **uma porta** (a da UI) basta: o browser fala com a origem do túnel, `/api` é encaminhado ao backend.

## Portas

A 8000 deste Mac pode já estar ocupada. No `.env`:

```
ATOM_API_HOST=127.0.0.1
ATOM_API_PORT=8081          # qualquer porta livre; default 8000
ATOM_UI_HOST=127.0.0.1
ATOM_UI_PORT=4173
```

Não use `0.0.0.0` no host do backend: o túnel aponta para o loopback. O `install.sh` grava esses defaults se a chave ainda não existir.

## Instalar

```bash
# 1. Postgres e Redis nativos (Homebrew)
brew services start postgresql@16 redis

# 2. Banco
createdb atom_dev || true
cd backend && alembic upgrade head

# 3. .env na raiz do repo (a partir de .env.example)
#    ATOM_CLIENT_MODE=true
#    ATOM_ENV=production
#    ATOM_DATABASE_URL=postgresql+asyncpg://…
#    REDIS_URL=redis://127.0.0.1:6379/0
#    ATOM_API_PORT=8081          # se 8000 estiver ocupada
#    ATOM_VENV=/caminho/.venv    # se o venv não for backend/venv
#    OLLAMA_HOST=http://127.0.0.1:11434
#    OLLAMA_MODEL=llama3.2:3b
#    ATOM_COMPUTE_WORKERS=8
#    ATOM_IO_WORKERS=12
#    ATOM_DB_POOL_MIN=4
#    ATOM_DB_POOL_MAX=16
#    ATOM_TORCH_DEVICE=mps
#    CLOUDFLARE_TUNNEL_TOKEN=    # vazio → quick tunnel
#    ATOM_PUBLIC_URL=            # hostname do túnel nomeado, opcional

#    SECRET_KEY: o install gera um se estiver ausente ou for o placeholder
#    do .env.example. O valor não é impresso.

# 4. venv — default backend/venv; ou aponte ATOM_VENV para um já pronto
# python3 -m venv backend/venv
# backend/venv/bin/pip install -r backend/requirements.lock

# 5. frontend
npm install && npm run build

# 6. cloudflared
brew install cloudflared

# 7. launchd
chmod +x ops/macos/install.sh ops/macos/uninstall.sh
./ops/macos/install.sh
```

O `install.sh` é idempotente: gera os plists em `~/Library/LaunchAgents`, dá `bootstrap` de novo e `kickstart`. No final imprime a URL pública (quick tunnel) ou lembra o origin do túnel nomeado.

## Cloudflare

### Quick tunnel (sem token)

O launchd sobe `cloudflared tunnel --url http://127.0.0.1:<ATOM_UI_PORT>`. A URL `https://….trycloudflare.com` vai para `~/Library/Logs/atom/public-url.txt` e para o output do install.

**Esse endereço muda a cada reinício** do `com.atom.tunnel` (KeepAlive, reboot, `kickstart`). Quem precisa de hostname estável usa o túnel nomeado.

### Túnel nomeado (com token)

No Zero Trust, um origin só:

- `https://seu.dominio` → `http://127.0.0.1:<ATOM_UI_PORT>`

Não é preciso um segundo origin para `/api`. Cole o token em `CLOUDFLARE_TUNNEL_TOKEN` (o plist **não** recebe o token; o `tunnel.sh` lê o `.env`). Opcional: `ATOM_PUBLIC_URL=https://seu.dominio` para o install ecoar o hostname.

## Sono do Mac

O backend já chama `caffeinate -dims` (não idle, não disco, não sistema, não display **enquanto o processo vive**).

Com a tampa fechada, na **tomada**:

```bash
sudo pmset -c sleep 0 disksleep 0 disablesleep 0
```

Isso não é revertido pelo `uninstall.sh`. Confira com `pmset -g`. Na bateria o Mac pode dormir — deixe ligado na tomada quando o túnel estiver público.

Ollama (`http://127.0.0.1:11434`) e Postgres/Redis nativos precisam estar no ar (brew services ou os próprios launchd). Redis é o cache compartilhado entre o worker e o uvicorn — sem ele cada processo cai no dicionário em memória e o pré-aquecimento não chega na API. Se o Ollama cair, a operação pronta continua: o «por quê» vira o texto-padrão.

## Desinstalar

```bash
./ops/macos/uninstall.sh
```

Não apaga o código, o banco, os logs, `public-url.txt` nem o `pmset`.

# ATOM neste Mac (launchd)

O ATOM público roda **neste Mac**: FastAPI, worker de cache, frontend estático e túnel Cloudflare. Paper only — nenhuma ordem real.

## O que sobe

| Label | Função |
| --- | --- |
| `com.atom.backend` | `uvicorn` em `0.0.0.0:8000`, envolvido em `caffeinate -dims` |
| `com.atom.worker` | `python -m app.services.client_worker` — regime + cache dos ativos do cliente |
| `com.atom.frontend` | `npx serve -s dist -l 4173` (build de produção) |
| `com.atom.tunnel` | `cloudflared tunnel run --token …` (só se `CLOUDFLARE_TUNNEL_TOKEN` estiver no `.env`) |

Logs: `~/Library/Logs/atom/`. Reinício automático (`KeepAlive`). Login/boot: `RunAtLoad`.

## Instalar

```bash
# 1. Postgres e Redis nativos (Homebrew)
brew services start postgresql@16 redis

# 2. Banco
createdb atom_dev || true
cd backend && alembic upgrade head

# 3. .env na raiz do repo (a partir de .env.example)
#    obrigatório no túnel público:
#    ATOM_CLIENT_MODE=true
#    ATOM_ENV=production
#    SECRET_KEY=… (32+ bytes)
#    ATOM_DATABASE_URL=postgresql+asyncpg://…
#    REDIS_URL=redis://127.0.0.1:6379/0
#    OLLAMA_HOST=http://127.0.0.1:11434
#    OLLAMA_MODEL=llama3.2:3b
#    ATOM_COMPUTE_WORKERS=8
#    ATOM_IO_WORKERS=12
#    ATOM_DB_POOL_MIN=4
#    ATOM_DB_POOL_MAX=16
#    ATOM_TORCH_DEVICE=mps          # ou cpu
#    CLOUDFLARE_TUNNEL_TOKEN=…

# 4. venv
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.lock

# 5. frontend
npm install && npm run build

# 6. launchd
chmod +x ops/macos/install.sh ops/macos/uninstall.sh
./ops/macos/install.sh
```

O `install.sh` é idempotente: gera os plists em `~/Library/LaunchAgents`, dá `bootstrap` de novo e `kickstart`.

## Cloudflare

No Zero Trust, crie um túnel e aponte:

- `https://seu.dominio` → `http://127.0.0.1:4173` (UI)
- `/api` → `http://127.0.0.1:8000` (API)

Cole o token em `CLOUDFLARE_TUNNEL_TOKEN` e rode o install de novo.

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

Não apaga o código, o banco, os logs nem o `pmset`.

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
| `com.atom.searxng` | **Opcional** (`ATOM_SEARXNG=1`): `docker compose -f docker-compose.searxng.yml up` na porta 8888 |

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
#    OLLAMA_AGENT_MODEL=gpt-oss:20b
#    ATOM_AGENT_LLM=ollama          # padrão; cloud só com chave (ver abaixo)
#    XAI_API_KEY=                   # já no .env local; NÃO commitar. Liga Grok na busca
#    XAI_MODEL=grok-4.3             # ou grok-4.20-0309-reasoning
#    ATOM_XAI_MAX_CALLS_PER_HOUR=60
#    OPENAI_API_KEY=                # já no .env local; NÃO commitar. Segunda fonte (web/notícias)
#    OPENAI_MODEL=gpt-5-mini
#    ATOM_OPENAI_MAX_CALLS_PER_HOUR=60
#    GEMINI_API_KEY=                # já no .env local; NÃO commitar. Terceira fonte (Google Search/News)
#    GEMINI_MODEL=gemini-2.5-flash  # ou gemini-2.5-pro / gemini-3.1-pro-preview
#    ATOM_GEMINI_MAX_CALLS_PER_HOUR=60
#    ATOM_RISK_PROVIDER=            # vazio = OpenAI se houver chave, senão Ollama
#    ATOM_SENTIMENT_WEIGHT=0.2      # termômetro; só subir com evidência
#    SEARXNG_URL=                   # vazio = sem busca web; ver «Contexto»
#    BRAVE_API_KEY=
#    TAVILY_API_KEY=
#    ATOM_SEARXNG=                  # 1 → launchd sobe SearXNG na 8888 (precisa Docker)
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

Ollama (`http://127.0.0.1:11434`) e Postgres/Redis nativos precisam estar no ar (brew services ou os próprios launchd). Redis é o cache compartilhado entre o worker e o uvicorn — sem ele cada processo cai no dicionário em memória e o pré-aquecimento não chega na API. Se o Ollama cair, a operação pronta continua: o «por quê» vira o texto-padrão. Sem fonte de busca, o contexto some — o arsenal ainda monta entrada/stop/alvo.

## Contexto em tempo real (agentes locais)

O arsenal continua decidindo direção, entrada, stop, alvo e tamanho. Agentes locais só leem notícias/macro/funding e podem **reduzir** tamanho/confiança ou **recusar** o paper. Nunca movem preço.

O worker (`com.atom.worker`) pré-aquece PETR4/VALE3/ITUB4/BTC/ETH no Redis (`ATOM_WORKER_CONTEXT=1` por omissão no processo worker). `ATOM_CONTEXT_JOB=1` no uvicorn só se você não usar o worker.

### Provedores de busca (degradação silenciosa)

| Ligar | Como |
| --- | --- |
| SearXNG local (padrão se a URL existir) | `docker compose -f docker-compose.searxng.yml up -d` e `SEARXNG_URL=http://127.0.0.1:8888`. No Mac: `ATOM_SEARXNG=1` no `.env` e rode de novo `install.sh` (precisa Docker). |
| Brave News | `BRAVE_API_KEY=…` |
| Tavily | `TAVILY_API_KEY=…` |

RSS (Google News pt-BR/en, CoinDesk, BBC Business), calendário (Copom BCB + FOMC/CPI/payroll com URL da fonte) e funding/OI (Binance/OKX públicos; mempool.space no BTC) não precisam de chave. Timeout curto (`ATOM_CONTEXT_TIMEOUT=4`), cache Redis (`ATOM_CONTEXT_TTL=300`). Sem fonte = sem contexto, nunca inventa.

### LLM dos agentes

Ordem do **agente de notícias**: xAI (X + trends), OpenAI (web/notícias) e Gemini (Google Search/News, pt-BR na B3) **em paralelo** quando as chaves existem → consenso ponderado das que responderam → Ollama → pacote determinístico. Sem citações/URLs, o JSON é descartado. Se um provedor falhar, os outros votam. Dispersão alta entre fontes reduz a confiança.

O **agente de risco** (advogado do diabo) usa **OpenAI** quando a chave existe (padrão). `ATOM_RISK_PROVIDER=openai|xai|gemini|ollama`. Sem chave, cai no Ollama.

| Ligar | Como |
| --- | --- |
| xAI / Grok (X+trends) | `XAI_API_KEY` no `.env` local (**não commitar**). `POST https://api.x.ai/v1/responses` com `web_search` e `x_search`. `XAI_MODEL=grok-4.3` (padrão). Teto: `ATOM_XAI_MAX_CALLS_PER_HOUR=60`. |
| OpenAI (web/notícias + risco) | `OPENAI_API_KEY` no `.env` local (**não commitar**). `POST https://api.openai.com/v1/responses` com `web_search`. `OPENAI_MODEL=gpt-5-mini`. Teto: `ATOM_OPENAI_MAX_CALLS_PER_HOUR=60`. Teste pago: `ATOM_OPENAI_LIVE=1 pytest -m openai`. |
| Gemini (Google Search/News, pt-BR B3) | `GEMINI_API_KEY` no `.env` local (**não commitar**). SDK `google-genai` (v1beta) com grounding `google_search`. `GEMINI_MODEL=gemini-2.5-flash` (padrão; `gemini-2.5-pro` ou `gemini-3.1-pro-preview`). Teto: `ATOM_GEMINI_MAX_CALLS_PER_HOUR=60`. Teste pago: `ATOM_GEMINI_LIVE=1 pytest -m gemini`. |
| Ollama (fallback notícias + risco) | `OLLAMA_ENABLED=1`, `OLLAMA_HOST=http://127.0.0.1:11434`, `OLLAMA_AGENT_MODEL=gpt-oss:20b`. |
| Risco via Grok | `ATOM_RISK_PROVIDER=xai` **e** `XAI_API_KEY` (chat `/v1/chat/completions`, sem search). |
| Anthropic | `ATOM_AGENT_LLM=anthropic` **e** `ANTHROPIC_API_KEY=…` |
| Perplexity | `ATOM_AGENT_LLM=perplexity` **e** `PERPLEXITY_API_KEY=…` |

Sem a chave, nenhuma chamada sai. JSON inválido ou notícia sem `fontes` é descartado. O cliente vê o **termômetro** e as fontes; objeções e o custo estimado ficam no diário (`GET /api/desk/context-audits`, `GET /api/desk/llm-costs`, modo operador).

### Termômetro (direção, não só risco)

O clima (X do Grok + web da OpenAI + Google Search do Gemini) entra na direção e na confiança com peso `ATOM_SENTIMENT_WEIGHT` (padrão **0.2**). O sinal final é o **consenso ponderado das fontes disponíveis**; a **dispersão** entre elas reduz a confiança. Concordância com o arsenal sobe a confiança; desacordo forte recusa o paper. **Entrada, stop e alvo continuam só do arsenal.** O worker grava a série em Postgres (`sentiment_snapshots`). Relatório honesto: `GET /api/desk/sentiment-skill?ticker=BTC&horizon=weeks`. O peso **não sobe sozinho**.

## Desinstalar

```bash
./ops/macos/uninstall.sh
```

Não apaga o código, o banco, os logs, `public-url.txt` nem o `pmset`.

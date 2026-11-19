> Produção: consulte [o runbook do piloto privado](docs/PRODUCTION.md) antes de implantar. Planejamento condicional não autoriza negociação real.

> **Mac público (túnel Cloudflare):** o cliente vê só [Operação pronta](/cliente) e [Meu plano](/cliente/plano). Um túnel para a porta da UI basta (`/api` é proxy na mesma origem). Portas, `ATOM_VENV`, quick tunnel e `SECRET_KEY` automático: [ops/macos/README.md](ops/macos/README.md). Paper only — sem ordens reais.

> **Produto atual: ATOM Research — piloto local.** A jornada principal é hipótese → avaliação temporal → diário → decisão de pesquisa. Veja [escopo, limites e critérios do piloto](docs/PRODUCT-PILOT.md). Descrições legadas abaixo não representam validação institucional nem autorização de negociação.

> **Pesquisa vs corretora.** O modo pesquisa (labs, paper, Laboratório Quant) continua só paper. O conector Hyperliquid é opt-in, testnet por padrão; mainnet exige confirmação dupla e teto por ordem. Ver [docs/HYPERLIQUID-TRADING.md](docs/HYPERLIQUID-TRADING.md).

# ATOM - Advanced Trading & Options Modeler

[![ATOM CI](https://github.com/leanderdulac/Atom-Finance/actions/workflows/ci.yml/badge.svg)](https://github.com/leanderdulac/Atom-Finance/actions/workflows/ci.yml)
[![Deploy](https://github.com/leanderdulac/Atom-Finance/actions/workflows/deploy.yml/badge.svg)](https://github.com/leanderdulac/Atom-Finance/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A comprehensive quantitative finance platform integrating pricing engines, risk analytics, ML predictions, portfolio optimization, and advanced market microstructure analysis.

![ATOM](public/atom.svg)

## Integração QuantMind

A área **Pesquisa QuantMind** (`/research`) adiciona extração estruturada de artigos e histórico por usuário. A biblioteca está incorporada em `research/quantmind`, com ambiente independente. Consulte [análise da fusão e execução local](docs/LOCAL-MERGE.md).

## Features

### Options Pricing
- **Black-Scholes** — Analytical European option pricing with full Greeks
- **Monte Carlo** — Simulation-based pricing with antithetic variates
- **Binomial Tree** — CRR model for American & European options
- **Finite Difference** — Crank-Nicolson PDE solver
- **Volatility Surface** — Strike/maturity surface construction
- **Options Strategies** — Straddle, Iron Condor, Butterfly, Custom combos

### Volatility Modeling
- **GARCH(1,1)** — MLE with α,β ∈ [0,1) and α+β<1 (no silent β≥0.5 floor)
- **Heston 1993** — characteristic-function European pricing (Albrecher branch) plus Euler MC with a calendar time grid
- **EWMA** — RiskMetrics recursion that includes the latest return

### Quant desk papers (`/desk`)
- **Heston 1993** — CF Europeans, Euler MC, multiexpiry calibration (vega weights, restarts, per-expiry RMSE, calendar diagnostics; chain→quotes adapter for live chains)
- **Engle–Granger pairs** — residual ADF, expanding z-score, fill at t+1, PnL on gross two-leg notional with β frozen at entry, costs on both legs
- **Pares + meta-rótulo** (`POST /api/desk/pairs/meta-label`) — barreiras triplas líquidas de custo, RF com purga/embargo, registro de tentativas e portão de Sharpe deflacionado (≥ 0,95) antes de considerar paper. Relatório sintético: [docs/reports/pairs-meta-label-oos.md](docs/reports/pairs-meta-label-oos.md). Relatório em dados reais (B3 + ETH/SOL, N honesto): [docs/reports/pairs-meta-label-oos-real.md](docs/reports/pairs-meta-label-oos-real.md). Auditoria ETH/SOL (unidades, overlap, funding, features, veto de regime): [docs/reports/pairs-eth-sol-audit-oos.md](docs/reports/pairs-eth-sol-audit-oos.md). Never sends orders.
- **ETH/SOL paper stat-arb** (`POST /api/desk/pairs/eth-sol-paper`) — one-pair paper loop: EG gate, OU half-life, rolling z, bid/ask fills, kill-switch flatten. Public marks from Binance, OKX, or Hyperliquid; paper PnL splits price vs accrued funding. Never sends orders. See [docs/ETH-SOL-PAPER-PIPELINE.md](docs/ETH-SOL-PAPER-PIPELINE.md).
- **Johansen 1991** — trace test and cointegration rank on a price panel
- **Avellaneda–Stoikov** — reservation price and inventory-skewed quotes
- **Fama–French 5** — OLS loadings; caller supplies factor returns
- **Mean-reversion scanner** — OU half-life, Hurst, ADF
- **Perp basis** — after-fee calculator plus unsigned Binance USDM / OKX / Hyperliquid top-of-book (no orders)
- **Insider clusters** — CMP-style bursts; optional Form 4 P/S via EDGAR (`ATOM_SEC_USER_AGENT` required)
- **Regime classifier** (`/regime`) — live Yahoo+FRED books, 4h job, softmax P(regime), holdout, paper flatten at last mark (no broker)
- **Winner's curse** (`/winners-curse`) — N zero-edge Sharpes, IS×OOS scatter, Deflated Sharpe (Bailey & López de Prado). The champion of a search is a lottery ticket until DSR says otherwise.
- **Sequential forward test** (`/forward-test`) — frozen SMA spec scored one bar later vs mined TA on the same history vs walk-forward refits. Backtest is research; the sequential series is the evidence clock.
- **Price vs return vs regime** (`/target-choice`) — identical log-returns at PETR4 and BTC levels; R$500 is not a feature; ADF on the print vs the return; the protocol predicts r_{t+1} or the next vol state, never the next price.
- **Error maximizer** (`/error-maximizer`) — analytical GMV on the sample covariance vs Ledoit–Wolf shrinkage. Marchenko–Pastur crushes small eigenvalues; inverting Σ is how a textbook Markowitz book explodes. `eligible_for_live_trading` stays false.
- **Desk doctrine** (`/quant-doctrine`) — constitution loaded into every LLM `complete()` (not weight fine-tuning). Winner's curse, sequential clock, purged CV, returns-not-prices, regime, Ledoit–Wolf before inverting Σ, vectorization. Labs are the curriculum.
- **Vectorization** (`/vectorize`) — `for i in range(len(df))` / `.iloc[i]` vs NumPy broadcast; same-bar i vs delayed i+1; cross-sectional z-score. Speed is how many hypotheses you test, not aesthetics.

Every desk endpoint returns a `what_broke` list. See [docs/WHAT-BROKE.md](docs/WHAT-BROKE.md). Signal catalog: [docs/strategy/signals.md](docs/strategy/signals.md).

### Risk Analysis
- **Value at Risk (VaR)** — Historical, Parametric, Monte Carlo methods
- **Conditional VaR (CVaR / Expected Shortfall)**
- **Stress Testing** — Pre-built scenarios (2008 Crisis, COVID, Flash Crash, etc.)

### Portfolio Optimization
- **Markowitz Efficient Frontier** — Mean-variance optimization
- **Maximum Sharpe Ratio** — Tangent portfolio
- **Minimum Variance** — Global minimum variance portfolio
- **Risk Parity** — Equal risk contribution
- **Black-Litterman** — Bayesian views-based allocation

### Machine Learning
- **Laboratório Quant** — Hipótese econômica, features causais de retornos e risco
- **Ridge e Random Forest reais** — Comparação com previsão zero e momentum
- **Validação purgada por grupos** — Walk-forward mensal, intervalo antes do teste e normalização apenas no treino
- **Risco líquido** — Drawdown, alvo de volatilidade, custos, turnover e estabilidade por janela
- **Uso de pesquisa** — Sem autorização automática de execução; veja [regras de negócio](docs/RESEARCH-POLICY.md)

### Black Swan Detection
- Tail risk analysis (kurtosis, Hill estimator, GPD)
- Regime change detection (rolling-vol percentile; use `/api/desk/regime` for the live classifier)
- Composite risk scoring (0–100)

> Removidas por falta de dados reais (ver [docs/WHAT-BROKE.md](docs/WHAT-BROKE.md)): análise de "ghost liquidity" (o output era função dos próprios campos do formulário, sem feed L2) e sentimento de notícias por contagem de palavras (`POST /api/black-swan/news-sentiment` responde 410).

### Backtesting Engine
- SMA Crossover, Mean Reversion, Momentum, RSI strategies
- Performance metrics: Sharpe, Sortino, Calmar, Max Drawdown, Win Rate
- Trade-level analytics

### Mathematical Foundations
- **Stochastic Calculus / Itô** — Continuous-time asset dynamics and hedge-aware state transitions
- **Black-Scholes-Merton** — PDE-based option pricing and analytical Greeks
- **Extreme Value Theory** — Tail-risk estimation for crashes and rare systemic events
- **Copula-style Dependence Modeling** — Stress dependence and contagion-aware multi-factor analysis
- **Monte Carlo Simulation** — Pathwise valuation and scenario generation for high-dimensional products
- **Machine Learning / Reinforcement Learning** — Non-linear prediction, signal extraction and adaptive execution policies

### Convergence Layer
- AI-assisted calibration of stochastic and volatility models
- EVT-informed Monte Carlo scenarios for realistic tail-loss distributions
- Quant infrastructure adaptable to climate derivatives, catastrophe insurance and systemic tipping-point analysis

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite 7, MUI 7 |
| Backend | Python 3.12, FastAPI, NumPy, SciPy, Pandas |
| ML | PyTorch, torchsde, scikit-learn |
| Storage | PostgreSQL (asyncpg, no ORM), Redis (optional cache, falls back to in-memory) |
| Deployment | Docker, docker-compose |
| Auth | JWT (HS256) + bcrypt |

---

## Quick Start

### Prerequisites
- Node.js 22+
- Python 3.12+
- Docker & Docker Compose (optional)

### Option 1: Docker (Recommended)

```bash
# Clone and start all services
docker-compose up --build
```

The app will be available at `http://localhost:5173` with the API at `http://localhost:8000`.

### Option 2: Manual Setup

**Backend:** needs a Postgres instance — `docker run -d -e POSTGRES_USER=atom -e POSTGRES_PASSWORD=atom_dev -e POSTGRES_DB=atom_dev -p 5432:5432 postgres:16-alpine` works for local dev.

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.lock   # pinned, reproducible — matches CI
export ATOM_DATABASE_URL=postgresql+asyncpg://atom:atom_dev@localhost:5432/atom_dev
alembic upgrade head                # apply the schema
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Project Structure

```
Atom-Finance/
├── backend/
│   ├── main.py             # FastAPI entry point — wires every router below
│   ├── requirements.txt    # Direct dependencies (backend/requirements.lock is the pinned, uv-compiled lockfile)
│   ├── Dockerfile
│   ├── app/
│   │   ├── api/            # One module per router (auth, pricing, risk, portfolio, ml, ...)
│   │   ├── core/           # Security (JWT/bcrypt), cache, rate limiter, AI provider factory
│   │   ├── db/             # Postgres access layer (asyncpg, no ORM) — schema in alembic/versions/
│   │   ├── models/         # Quantitative models: pricing, volatility, risk, portfolio,
│   │   │                   # backtesting, black swan, CAPM, EVT, copulas, Kronos (ML)
│   │   └── services/       # External data providers (Brapi/B3, Binance, OpenBB, live quotes)
│   └── tests/               # pytest suite (unit tests, no external network calls)
├── src/
│   ├── main.tsx             # React entry point
│   ├── App.tsx              # Routing
│   ├── theme/               # MUI theme (dark/light)
│   ├── services/api.ts      # API client
│   ├── components/
│   └── pages/                # One page per feature area (pricing, risk, portfolio, ML,
│                              # backtesting, black swan, derivatives, paper trading, ...)
├── research/quantmind/       # Embedded QuantMind research library (own README/tests/tooling)
├── docs/                     # Product scope, pilot rules, production runbook, research policy
├── docker-compose*.yml       # dev / prod / edge stacks
└── package.json
```

For the exhaustive, always-current list of files and endpoints, browse the tree directly or use the interactive API docs below — a hand-written list here would just go stale again.

---

## API

Every router is mounted under `/api` in [backend/main.py](backend/main.py); most require a bearer token (see `/api/auth/register` and `/api/auth/login`). With the backend running, the full interactive reference is at:

- **Swagger UI** — `http://localhost:8000/docs`
- **ReDoc** — `http://localhost:8000/redoc`

| Prefix | Area |
|--------|------|
| `/api/auth` | Registration & JWT login |
| `/api/pricing` | Black-Scholes, Monte Carlo, Binomial, Finite Difference, vol surface, strategies |
| `/api/risk` | VaR, CVaR, stress testing, GARCH |
| `/api/hedge` | Dynamic hedging |
| `/api/portfolio` | Markowitz, max Sharpe, min variance, risk parity, Black-Litterman |
| `/api/ml` | Research protocol (purged walk-forward, real estimators) |
| `/api/neural-sde` | Neural SDE simulation |
| `/api/black-swan` | Tail risk, regime change, composite risk score |
| `/api/market-data` | Quotes & history |
| `/api/ibovespa` | Ibovespa dashboard data |
| `/api/backtesting` | Strategy backtests |
| `/api/capm` | CAPM & Kelly sizing |
| `/api/evt` | Extreme Value Theory (tail risk) |
| `/api/copulas` | Dependence / contagion modeling |
| `/api/reports` | CSV/JSON export, AI-generated analysis |
| `/api/screener` | Multi-AI B3 screener |
| `/api/autopilot` | Options playbook generation |
| `/api/binance` | Binance crypto market data |
| `/api/derivatives` | Derivatives desk planner |
| `/api/sources` | Market data source quality/monitoring |
| `/api/research` | QuantMind paper history & extraction |
| `/api/desk` | Heston CF/calibrate/live, Engle–Granger, Johansen, Avellaneda–Stoikov, FF5, live perp books, EDGAR Form 4, regime classifier, interval calibration |
| `/api/oracle` | Arbitrated spot, provider heartbeat, US option chains |
| `/api/client` | Ready operation, paper register, Monte Carlo simulate, thesis monitors |
| `/api/metrics` | Prometheus metrics (JWT or `ATOM_METRICS_PUBLIC` on a trusted network) |
| `/api/paper-trades` | Simulated paper-trading ledger (no broker execution) |

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key environment variables:
- `SECRET_KEY` — JWT signing key (required in production, 32+ bytes)
- `ATOM_DATABASE_URL` — Postgres connection string (`postgresql+asyncpg://user:pass@host:5432/db`); run `alembic upgrade head` from `backend/` after pointing it at a fresh database
- `REDIS_URL` — Redis connection string (optional; falls back to an in-memory cache when unset or unreachable)
- `ATOM_SEC_USER_AGENT` — SEC fair-access header for Form 4 pulls; must include a contact email (e.g. `ATOM Research desk@yourdomain.com`)

**Context / thermometer (paper only).** Keys live in the local `.env` — never commit them.
- `XAI_API_KEY` + `XAI_MODEL` (default `grok-4.3`) — Grok Responses API with `web_search` and `x_search` (X/trends + web). Cap: `ATOM_XAI_MAX_CALLS_PER_HOUR=60`.
- `OPENAI_API_KEY` + `OPENAI_MODEL` (default `gpt-5-mini`) — OpenAI Responses API with `web_search` (web/news). Cap: `ATOM_OPENAI_MAX_CALLS_PER_HOUR=60`. Live test: `ATOM_OPENAI_LIVE=1 pytest -m openai`.
- `GEMINI_API_KEY` + `GEMINI_MODEL` (default `gemini-2.5-flash`; optional `gemini-2.5-pro` or `gemini-3.1-pro-preview`) — Gemini v1beta / `google-genai` with Google Search grounding (Google News, pt-BR for B3). Cap: `ATOM_GEMINI_MAX_CALLS_PER_HOUR=60`. Live test: `ATOM_GEMINI_LIVE=1 pytest -m gemini`.
- All three are optional and independent: if one fails, consensus uses the rest. The thermometer score is the **weighted consensus**; high dispersion lowers confidence. Cache 15 min Redis. Estimated USD: `GET /api/desk/llm-costs`. `ATOM_SENTIMENT_WEIGHT=0.2`.
- Devil's advocate: `ATOM_RISK_PROVIDER` empty → OpenAI when the key exists, otherwise Ollama. Force `openai`, `xai`, `gemini`, or `ollama`.
- The LLM never picks entry, stop, or target. Never commit API keys.

See [.env.example](.env.example) for the full list, including AI provider keys and market data providers. Mac tunnel: [ops/macos/README.md](ops/macos/README.md).

---

## Paper Trading

O acompanhamento manual de [operações simuladas](docs/PAPER-TRADING.md) registra entrada, evolução e saída dos planos de derivativos, com custos e histórico por usuário.

---

## License

[MIT](LICENSE) — © 2026 Leander Dulac. `research/quantmind` incorpora código de
terceiros sob sua própria licença MIT ([research/quantmind/LICENSE](research/quantmind/LICENSE),
© 2025 LLMQuant), preservada no local original.

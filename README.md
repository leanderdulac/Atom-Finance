> Produção: consulte [o runbook do piloto privado](docs/PRODUCTION.md) antes de implantar. Planejamento condicional não autoriza negociação real.

> **Produto atual: ATOM Research — piloto local.** A jornada principal é hipótese → avaliação temporal → diário → decisão de pesquisa. Veja [escopo, limites e critérios do piloto](docs/PRODUCT-PILOT.md). Descrições legadas abaixo não representam validação institucional nem autorização de negociação.

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
- **GARCH(1,1)** — Maximum Likelihood Estimation with forecasting
- **Heston Stochastic Volatility** — Monte Carlo simulation & option pricing
- **EWMA** — Exponentially Weighted Moving Average

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

### Ghost Liquidity Analysis
- Cross-venue duplicate detection
- HFT phantom order identification
- Flickering quote analysis
- Market quality metrics (effective spread, depth ratio, order flow toxicity)

### Black Swan Detection
- Tail risk analysis (kurtosis, Hill estimator, GPD)
- Regime change detection (Hidden Markov Model-inspired)
- NLP sentiment analysis for financial news
- Composite risk scoring (0–100)

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
| Frontend | React 18, TypeScript, Vite 5, MUI 7 |
| Backend | Python 3.12, FastAPI, NumPy, SciPy, Pandas |
| ML | PyTorch, torchsde, scikit-learn |
| Storage | SQLite (file-based), Redis (optional cache, falls back to in-memory) |
| Deployment | Docker, docker-compose |
| Auth | JWT (HS256) + bcrypt |

---

## Quick Start

### Prerequisites
- Node.js 20+
- Python 3.12+
- Docker & Docker Compose (optional)

### Option 1: Docker (Recommended)

```bash
# Clone and start all services
docker-compose up --build
```

The app will be available at `http://localhost:5173` with the API at `http://localhost:8000`.

### Option 2: Manual Setup

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.lock   # pinned, reproducible — matches CI
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
│   │   ├── db/             # SQLite access layer (stdlib sqlite3, no ORM)
│   │   ├── models/         # Quantitative models: pricing, volatility, risk, portfolio,
│   │   │                   # backtesting, ghost liquidity, black swan, CAPM, EVT, copulas, Kronos (ML)
│   │   └── services/       # External data providers (Brapi/B3, Binance, OpenBB, live quotes)
│   └── tests/               # pytest suite (unit tests, no external network calls)
├── src/
│   ├── main.tsx             # React entry point
│   ├── App.tsx              # Routing
│   ├── theme/               # MUI theme (dark/light)
│   ├── services/api.ts      # API client
│   ├── components/
│   └── pages/                # One page per feature area (pricing, risk, portfolio, ML,
│                              # backtesting, ghost liquidity, black swan, derivatives, paper trading, ...)
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
| `/api/ghost-liquidity` | Cross-venue duplicate & phantom order detection |
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
| `/api/paper-trades` | Manual paper-trading journal |

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key environment variables:
- `SECRET_KEY` — JWT signing key (required in production, 32+ bytes)
- `ATOM_DB_PATH` — path to the SQLite database file (optional, defaults to `atom_reports.db` at the repo root)
- `REDIS_URL` — Redis connection string (optional; falls back to an in-memory cache when unset or unreachable)

See [.env.example](.env.example) for the full list, including AI provider keys and market data providers.

---

## Paper Trading

O acompanhamento manual de [operações simuladas](docs/PAPER-TRADING.md) registra entrada, evolução e saída dos planos de derivativos, com custos e histórico por usuário.

---

## License

[MIT](LICENSE)

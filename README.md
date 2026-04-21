# ATOM - Advanced Trading & Options Modeler

A comprehensive quantitative finance platform integrating pricing engines, risk analytics, ML predictions, portfolio optimization, and advanced market microstructure analysis.

![ATOM](public/atom.svg)

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
- **LSTM** — Sequence prediction for price forecasting
- **Random Forest** — Ensemble-based directional prediction
- **ARIMA** — Autoregressive time series modeling
- **DQN (Reinforcement Learning)** — Trading signal generation

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
| Backend | Python 3.11, FastAPI, NumPy, SciPy, Pandas |
| Databases | PostgreSQL, MongoDB, Redis |
| Deployment | Docker, docker-compose |
| Auth | JWT (HMAC-SHA256) |

---

## Quick Start

### Prerequisites
- Node.js 20+
- Python 3.11+
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
pip install -r requirements.txt
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
ATOM/
├── backend/
│   ├── main.py                    # FastAPI entry point
│   ├── requirements.txt           # Python dependencies
│   ├── Dockerfile
│   └── app/
│       ├── api/                   # API route handlers
│       │   ├── auth.py            # JWT authentication
│       │   ├── pricing.py         # Options pricing endpoints
│       │   ├── risk.py            # Risk analysis endpoints
│       │   ├── portfolio.py       # Portfolio optimization
│       │   ├── ml.py              # ML prediction endpoints
│       │   ├── ghost_liquidity.py # Ghost liquidity analysis
│       │   ├── black_swan.py      # Black swan detection
│       │   ├── market_data.py     # Market data (synthetic)
│       │   ├── reports.py         # PDF/CSV export
│       │   └── backtesting.py     # Backtesting endpoints
│       └── models/                # Core quantitative models
│           ├── pricing.py         # BS, MC, Binomial, FD
│           ├── volatility.py      # GARCH, Heston, EWMA
│           ├── risk.py            # VaR, CVaR, Stress Test
│           ├── portfolio.py       # Portfolio optimization
│           ├── ml_models.py       # LSTM, RF, ARIMA, DQN
│           ├── ghost_liquidity.py # Ghost liquidity analyzer
│           ├── black_swan.py      # Black swan detector
│           └── backtesting.py     # Backtesting engine
├── src/
│   ├── main.tsx                   # React entry point
│   ├── App.tsx                    # Main app with routing
│   ├── theme/ThemeProvider.tsx     # MUI theme (dark/light)
│   ├── services/api.ts            # API client
│   └── pages/                     # Feature pages
│       ├── Dashboard.tsx
│       ├── PricingPage.tsx
│       ├── RiskPage.tsx
│       ├── PortfolioPage.tsx
│       ├── MLPage.tsx
│       ├── GhostLiquidityPage.tsx
│       ├── BlackSwanPage.tsx
│       ├── BacktestingPage.tsx
│       └── StrategiesPage.tsx
├── docker-compose.yml
├── Dockerfile.frontend
├── vite.config.ts
├── index.html
└── package.json
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Register new user |
| `/api/auth/login` | POST | Login & get JWT |
| `/api/pricing/black-scholes` | POST | Black-Scholes pricing |
| `/api/pricing/monte-carlo` | POST | Monte Carlo pricing |
| `/api/pricing/binomial` | POST | Binomial tree pricing |
| `/api/pricing/finite-difference` | POST | FD pricing |
| `/api/pricing/volatility-surface` | POST | Vol surface generation |
| `/api/pricing/strategy` | POST | Options strategy analysis |
| `/api/risk/var` | POST | Value at Risk |
| `/api/risk/stress-test` | POST | Stress testing |
| `/api/risk/garch` | POST | GARCH volatility |
| `/api/portfolio/optimize` | POST | Portfolio optimization |
| `/api/ml/predict` | POST | ML price prediction |
| `/api/ghost-liquidity/analyze` | POST | Ghost liquidity analysis |
| `/api/black-swan/analyze` | POST | Black swan detection |
| `/api/backtesting/run` | POST | Run backtest |
| `/api/market-data/quote/{symbol}` | GET | Real-time quote |
| `/api/market-data/history/{symbol}` | GET | Historical data |
| `/api/reports/pdf` | POST | Generate PDF report |
| `/api/reports/csv` | POST | Generate CSV export |

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key environment variables:
- `SECRET_KEY` — JWT signing key
- `DATABASE_URL` — PostgreSQL connection string
- `MONGODB_URL` — MongoDB connection string
- `REDIS_URL` — Redis connection string

---

## License

MIT

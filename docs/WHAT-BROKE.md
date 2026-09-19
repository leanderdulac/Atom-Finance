# What broke

Honest failure catalog for the quantitative stack. Recruiters and reviewers
should read this before the feature list. Nothing below is live-trading eligible.

## Formula bugs that were in production math (fixed this round)

| Model | What was wrong | What it did to numbers |
|---|---|---|
| EVT CVaR | Numerator used `VaR + σ + ξ(VaR−u)` over `(1−ξ)` | Inflated expected shortfall whenever ξ>0 |
| EVT zeta | GPD fitted on positive losses only, `n_total = N_positive` | Overstated exceedance rate, understated VaR |
| Parametric VaR | Scaled the mean by `√h` instead of `h` | Inconsistent 10-day VaR vs Monte Carlo |
| Student-t CVaR | `1.1 × VaR` | Not a formula |
| Heston `price_option` | Always 252 steps of `dt = T/252` | Wrong grid for T≠1 |
| GARCH(1,1) | Optimizer forced `β ≥ 0.5` | Could not fit low-persistence series |
| EWMA | Last return never entered `σ_t` | Stale "current vol" |
| Sortino | Std of negative days, not `√E[min(r,0)²]` | Optimistic Sortino |
| Historical CVaR | `mean([])` on empty tail | Silent NaN |

## Removed rather than fixed

- **Ghost liquidity** — deleted. The output was the input: `ghost = consolidated × hft_cancel_rate × 0.4 + consolidated × 0.15 + duplicates × cross_venue_duplication`, and the two rates were the page's own form fields. The UI always posted an empty book, so every run scored a seeded random book with invented venues. There was no path for real L2 data.
- **Black swan news sentiment** — deleted. Keyword counts over eight hardcoded headlines with invented dates attributed to Reuters, Bloomberg, FT and CoinDesk, weighted 35% into the headline score. `POST /api/black-swan/news-sentiment` now 410s.
- **`RandomForestPredictor` / `TradingDQN` / `ARIMAForecast`** — deleted, unreferenced. The RF never fit a tree and returned `np.random.dirichlet` as feature importances; the DQN's "Q-values" were a momentum/vol expression reporting a costless backtest's Sharpe.

## What still is not a desk model

- **Tail risk score** — real EVT diagnostics (skew, kurtosis, σ-exceedances, Hill index) plus a 15% rolling-vol threshold. The threshold is not a regime model; use `/regime` for the percentile classifier.
- **Neural SDE** — correct integration of untrained networks; σ forced into (0,1). A numerical demo, not a fitted model, and the page says so.
- **`ml_models` forecasts** — exponential smoothing labelled as a baseline, not LSTM.
- **AI report "recommendation"** — research narrative, never an order.
- **Alpha engine OOS** — synthetic returns; the holdout row is now excluded from E[r].

## Desk papers (now implemented, with the same honesty)

| Paper / tool | Implemented | What broke |
|---|---|---|
| Heston 1993 | CF Europeans, Euler MC, **smile calibration** | 5 params on one expiry are unidentified; price RMSE not vega-weighted |
| Engle–Granger 1987 | OLS hedge, ADF residual, lagged pairs backtest | Full-sample β leaks; ADF low power |
| ETH/SOL paper stat-arb | EG gate on warmup prefix + OU half-life + rolling z + paper bid/ask book + kill flatten | Prefix gate is still research, not a rolling live rank test; synthesized book is not firm; **no broker** |
| Johansen 1991 | Trace test, rank, first β̂ | Asymptotic 5% table; lag p is not AIC-selected |
| Avellaneda–Stoikov 2008 | Reservation price, optimal spread, Poisson inventory | Constant σ; unidentified A,k; no queue |
| Fama–French 2015 | Five-factor OLS | You supply factors; no HAC; alpha ≠ tradable residual |
| Mean-reversion scanner | OU half-life, Hurst, ADF | Ranking on the same sample is selection bias |
| Perp basis | After-fee calculator **+ live Binance USDM / Hyperliquid books** | Top-of-book is not firm; no orders |
| Insider clusters (CMP 2012) | Windowed bursts **+ Form 4 P/S via EDGAR** | Needs `ATOM_SEC_USER_AGENT`; drops 10b5-1 / awards |
| Regime classifier | Live Yahoo+FRED books, 4h job, softmax P(regime), holdout, **paper flatten at last mark** | Delayed prints; ^IRX is 13-week not 2y; softmax is not an HMM; **no broker** |
| Winner's curse / DSR | N iid zero-edge trials, IS×OOS cloud, Bailey–López de Prado deflated Sharpe | Trials modelled as independent; √(2 ln N) is the leading EVT term; DSR is not a tradable edge |
| Sequential forward test | Locked SMA scored at t+1, mined TA grid, walk-forward refit | Synthetic GBM clock; SMA is one family; walk-forward still searches; **no broker** |
| Price vs return | Same log-return path at two levels; ADF; walk-forward Ridge on P, r, vol-regime | Toy DGP; regime is trailing vol vs expanding median, not the six-signal classifier |
| Desk doctrine | `compose_system` on every LLM `complete()`; GET `/api/desk/doctrine`; UI `/quant-doctrine` | Prompt prefix, not weight fine-tuning; bypass surfaces must opt in (`ai_proxy`, `options_api`, QuantMind) |

## Protocol that was already honest

`POST /api/ml/evaluate` (purged walk-forward, train-only scaler, costs, `eligible_for_live_trading: false`) remains the only path that is allowed to talk about evidence. See `docs/RESEARCH-POLICY.md`.

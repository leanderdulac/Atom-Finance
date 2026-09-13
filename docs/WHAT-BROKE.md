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

## What still is not a desk model

- **Ghost liquidity** — fractions of a synthetic book, not L2 measurement.
- **Black swan "HMM/NLP"** — rolling-vol threshold + keyword counts. Use `/regime` for the actual percentile classifier.
- **Neural SDE** — untrained networks; σ forced into (0,1).
- **`ml_models` forecasts** — exponential smoothing labelled as a baseline, not LSTM.
- **AI report "recommendation"** — research narrative, never an order.
- **Alpha engine OOS** — synthetic returns; the holdout row is now excluded from E[r].

## Desk papers (now implemented, with the same honesty)

| Paper / tool | Implemented | What broke |
|---|---|---|
| Heston 1993 | CF Europeans, Euler MC, **smile calibration** | 5 params on one expiry are unidentified; price RMSE not vega-weighted |
| Engle–Granger 1987 | OLS hedge, ADF residual, lagged pairs backtest | Full-sample β leaks; ADF low power |
| Johansen 1991 | Trace test, rank, first β̂ | Asymptotic 5% table; lag p is not AIC-selected |
| Avellaneda–Stoikov 2008 | Reservation price, optimal spread, Poisson inventory | Constant σ; unidentified A,k; no queue |
| Fama–French 2015 | Five-factor OLS | You supply factors; no HAC; alpha ≠ tradable residual |
| Mean-reversion scanner | OU half-life, Hurst, ADF | Ranking on the same sample is selection bias |
| Perp basis | After-fee calculator **+ live Binance USDM / Hyperliquid books** | Top-of-book is not firm; no orders |
| Insider clusters (CMP 2012) | Windowed bursts **+ Form 4 P/S via EDGAR** | Needs `ATOM_SEC_USER_AGENT`; drops 10b5-1 / awards |
| Regime classifier | Live Yahoo+FRED books, 4h job, softmax P(regime), holdout, **paper flatten at last mark** | Delayed prints; ^IRX is 13-week not 2y; softmax is not an HMM; **no broker** |

## Protocol that was already honest

`POST /api/ml/evaluate` (purged walk-forward, train-only scaler, costs, `eligible_for_live_trading: false`) remains the only path that is allowed to talk about evidence. See `docs/RESEARCH-POLICY.md`.

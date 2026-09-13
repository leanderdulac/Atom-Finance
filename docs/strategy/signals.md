# Regime signals

These six series are the only inputs the classifier is allowed to use.
Live pulls: Yahoo (`SPY/QQQ/IWM/EFA/TLT`, `^VIX`, `^VIX3M`/`^VXV`, `^IRX`, `^TNX`)
and FRED `BAMLH0A0HYM2` (ICE BofA HY OAS). Delayed public prints.

The job body is `backend/app/models/regime.py`. `ATOM_REGIME_JOB=1` starts a
4-hour asyncio loop from the API lifespan. `POST /api/desk/regime/live` is the
on-demand tick. Paper flatten (last mark) is `flatten=true` or
`ATOM_REGIME_KILL_OWNER` on the job. No broker.

| Signal | Definition used here | Stress direction |
|---|---|---|
| Hurst exponent | 126-day R/S on the first equity series, 5-window mean | High → trending; low → mean-reverting |
| VIX term structure | `VIX_back / VIX_front` | Low (backwardation) → stress |
| RV vs IV spread | 20-day realized vol (ann.) minus VIX/100 | High → vol selling is losing |
| Cross-asset correlation | Mean upper-triangle corr of 20-day equity returns | High → risk-off / one-factor market |
| Credit spreads | FRED HY OAS (or a series you supply) | High → stress |
| Rates curve slope | `^TNX − ^IRX` (10y minus 13-week, not 2y) | Low / inverted → recession / crisis lean |

## Percentile gate

For a trailing window of 90 observations including today (nowcast):

```
p = 100 · #{ x_{t-89…t} ≤ x_t } / 90
```

Flag `high` if `p ≥ 90`, `low` if `p ≤ 10`. Holdout predicts at `t` on `data[:t]`
and labels the next 10 days — that is the purged check.

## Classifier (priority)

Hard rule (kill switch):

1. **crisis** if (credit high ∧ correlation high) ∨ (VIX backwardation ∧ ≥2 stress flags) ∨ ≥3 stress flags.
2. **high_vol** if RV−IV is high.
3. **trending** if Hurst is high (else Hurst ≥ 0.5 when unflagged).
4. **mean_reverting** otherwise.

`P(regime)` is softmax of percentile z-scores (stress signs on VIX term and curve).
The kill switch follows the hard rule, not a 51% softmax.

## What this file is not

- Not Reuters/Bloomberg. Yahoo and FRED are delayed.
- Not an HMM / LSTM. Softmax is a z-score map.
- Not a broker OMS. Paper flatten only. `eligible_for_live_trading` stays `false`.

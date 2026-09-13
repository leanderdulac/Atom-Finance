# Current regime

> Research snapshot. Not a live market feed.

- As of: `2026-09-13T18:00:00+00:00`
- Regime: **crisis**
- Kill switch: `ARMED — research_risk_off`
- Broker orders sent: `0`
- `eligible_for_live_trading`: `False`

## Flags

- `hurst`: 1.052 (p91 · high)
- `vix_term_structure`: 0.6304 (p1 · low)
- `rv_iv_spread`: -0.1326 (p8 · low)
- `cross_asset_corr`: 0.7554 (p100 · high)
- `credit_spread`: 785 (p100 · high)
- `rates_curve_slope`: -0.6 (p1 · low)

## Strategy book

- **stat_arb**: `flatten` (live in ['mean_reverting'])
- **momentum**: `flatten` (live in ['trending'])
- **vol_selling**: `flatten` (live in ['mean_reverting'])

## Math

For each signal x_t, p = 100 · #{x_{t−89…t} ≤ x_t} / 90. Flag high if p≥90, low if p≤10. Crisis if (credit high ∧ corr high) ∨ (VIX backwardation ∧ ≥2 stress flags) ∨ ≥3 stress flags. Else high_vol if RV−IV high; else Hurst high → trending, low → mean-reverting.

## What broke

- Percentiles use a window that includes today — this is a snapshot, not a purged holdout.
- Decile flags are not a model of P(regime | data); they are a rule on six series you supplied.
- Hurst on 64 log-prices is noisy; a single window does not 'predict a shift'.
- There is no 4-hour live job here. Wire cron yourself; ATOM will not scrape VIX/OAS/UST.
- Kill switch is a research_risk_off flag. Broker orders sent: always 0.
- Strategy tags are priors, not evidence that stat-arb 'works' in mean-reversion.
- Half-Kelly by regime is a haircut table, not an estimated edge.

# Position adjustments

Regime: **crisis**. These are research sizes, not tickets.

| id | strategy | current | target | delta | action | reason |
|---|---|---|---|---|---|---|
| stat_arb | stat_arb | 0.08 | 0.0 | -0.08 | `flatten` | stat_arb tagged kill_in=['crisis'] under crisis |
| momentum | momentum | 0.08 | 0.0 | -0.08 | `flatten` | momentum tagged kill_in=['crisis'] under crisis |
| vol_selling | vol_selling | 0.08 | 0.0 | -0.08 | `flatten` | vol_selling tagged kill_in=['crisis', 'high_vol'] under crisis |

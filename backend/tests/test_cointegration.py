"""Lock in the expanding-hedge fix to cointegration.pairs_backtest.

The hedge ratio β_t that defines the traded spread and the PnL attribution must
be estimated on data[:t+1] only — never the full-sample OLS beta. These tests
prove causality and that the backtest still runs.
"""

import numpy as np
import pytest

from app.models.cointegration import _expanding_hedge, frozen_spread_return, pairs_backtest


def _coint_pair(n=400, seed=5):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 1, n)) + 50
    y = 2.0 * x + 3.0 + rng.normal(0, 0.2, n)
    return y, x


def test_expanding_hedge_causal():
    """β_t must equal an OLS fit on the window [:t+1] alone — no future data."""
    y, x = _coint_pair()
    alpha, beta, resid = _expanding_hedge(y, x, 20)
    for t in (49, 99, 199, 300):
        wy, wx = y[: t + 1], x[: t + 1]
        coef = np.linalg.lstsq(np.column_stack([np.ones(t + 1), wx]), wy, rcond=None)[0]
        assert alpha[t] == pytest.approx(coef[0], abs=1e-8)
        assert beta[t] == pytest.approx(coef[1], abs=1e-8)
        assert resid[t] == pytest.approx(wy[-1] - (coef[0] + coef[1] * wx[-1]), abs=1e-8)


def test_expanding_hedge_nan_before_min_est():
    y, x = _coint_pair()
    _, _, resid = _expanding_hedge(y, x, 30)
    assert np.isnan(resid[:29]).all()
    assert np.isfinite(resid[29:]).all()


def test_pairs_backtest_still_runs_causally():
    y, x = _coint_pair()
    bt = pairs_backtest(y, x)
    assert bt["eligible_for_live_trading"] is False
    assert "what_broke" in bt
    assert bt["pnl_unit"] == "gross_two_leg_notional"
    assert bt["hedge"] == "expanding_ols_frozen_at_entry"
    assert bt["total_return_pct"] == pytest.approx(
        (bt["final_equity"] / 100_000.0 - 1.0) * 100, abs=5e-4  # report rounds to 4 decimals
    )


def test_frozen_spread_return_is_not_share_beta_times_percent():
    """OLS share-count β applied to percent returns would print −99% on this bar."""
    r = frozen_spread_return(100.0, 10.0, 101.0, 11.0, beta0=10.0)
    dollar = (101.0 - 100.0) - 10.0 * (11.0 - 10.0)
    assert r == pytest.approx(dollar / 200.0)
    old = (101.0 / 100.0 - 1.0) - 10.0 * (11.0 / 10.0 - 1.0)
    assert abs(old) > 0.5
    assert abs(r) < 0.1


def test_pairs_backtest_does_not_wipe_a_share_beta_ten_book():
    """Regression: r_y − β_shares r_x with β≈10 detonates equity; gross notional does not."""
    rng = np.random.default_rng(0)
    n = 400
    x = np.maximum(10.0 + np.cumsum(rng.normal(0.0, 0.2, n)), 1.0)
    y = 50.0 + 10.0 * x + rng.normal(0.0, 0.3, n)
    bt = pairs_backtest(y, x)
    assert bt["eligible_for_live_trading"] is False
    assert bt["final_equity"] > 1.0
    assert bt["total_return_pct"] > -99.0
    assert bt["annualized_vol_pct"] < 80.0
    # Old formula on this DGP printed vol in the hundreds and often wiped the book.

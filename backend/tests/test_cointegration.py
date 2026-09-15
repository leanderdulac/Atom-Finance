"""Lock in the expanding-hedge fix to cointegration.pairs_backtest.

The hedge ratio β_t that defines the traded spread and the PnL attribution must
be estimated on data[:t+1] only — never the full-sample OLS beta. These tests
prove causality and that the backtest still runs.
"""

import numpy as np
import pytest

from app.models.cointegration import _expanding_hedge, pairs_backtest


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
    assert bt["total_return_pct"] == pytest.approx(
        (bt["final_equity"] / 100_000.0 - 1.0) * 100, abs=5e-4  # report rounds to 4 decimals
    )

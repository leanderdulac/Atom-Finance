"""Lock in the expanding-window fix to mean_reversion.py.

The z-score / AR(1) half-life must never consume t+1…T moments, per the module
contract. These tests prove that an interior request uses only the data before
`end`, and that the present-bar value is consistent with the whole series.
"""

import numpy as np
import pytest

from app.models.mean_reversion import _ar1_half_life, _expanding_z, score_series


def _ou_walk(n, phi, sigma, seed=7):
    """Generate a stationary OU-ish AR(1) level series (mean-reverting)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0.0, sigma)
    return x


def test_expanding_z_uses_only_data_before_end():
    """Querying end=t must equal computing on data[:t] exactly — future data is dropped."""
    prices = np.exp(_ou_walk(300, 0.9, 0.02))
    for t in (60, 100, 150, 250):
        by_window = _expanding_z(prices, end=t)
        on_slice = _expanding_z(prices[:t])
        assert by_window == on_slice, f"end={t}"


def test_expanding_z_equals_official_full_call_at_present():
    prices = np.exp(_ou_walk(300, 0.9, 0.02))
    assert _expanding_z(prices) == _expanding_z(prices, end=len(prices))


def test_ar1_half_life_uses_only_window():
    prices = np.exp(_ou_walk(300, 0.9, 0.02))
    for t in (60, 120, 200):
        phi_w, hl_w = _ar1_half_life(prices, end=t)
        phi_s, hl_s = _ar1_half_life(prices[:t])
        assert phi_w == phi_s and hl_w == hl_s, f"end={t}"


def test_score_series_report_matches_expanding_z():
    prices = np.exp(_ou_walk(300, 0.9, 0.02))
    result = score_series(prices)
    # score_series works in log space, like _expanding_z
    assert result["z_score"] == pytest.approx(_expanding_z(np.log(prices)), abs=1e-3)


def test_z_starts_at_zero_for_level_slice():
    """A flat level slice has σ≈0 → z=0, not NaN."""
    prices = np.ones(100) * 100.0
    assert _expanding_z(prices) == 0.0

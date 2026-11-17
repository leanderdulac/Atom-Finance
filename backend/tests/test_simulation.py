"""Simulator: determinism, martingale check, mirrors, costs, validation."""
import pytest

from app.models.simulation import simulate_levels


def _base(**kw):
    args = dict(S0=100.0, direction="long", entry=100.0, stop=95.0,
                target=110.0, horizon_days=21, vol_annual=0.3,
                n_paths=4000, seed=11)
    args.update(kw)
    return simulate_levels(**args)


def test_deterministic_under_seed():
    assert _base() == _base()
    assert _base(seed=12) != _base(seed=11)


def test_percentiles_ordered_and_split_sums():
    out = _base()
    qs = [out[f"pnl_p{p}"] for p in (5, 25, 50, 75, 95)]
    assert qs == sorted(qs)
    assert out["p_stop"] + out["p_target"] + out["p_expiry"] == pytest.approx(
        out["p_enter"], abs=1e-6)


def test_immediate_entry_when_s0_equals_entry():
    out = _base()
    assert out["p_enter"] == 1.0
    assert out["n_entered"] == out["n_paths"]


def test_distant_entry_may_never_fill():
    out = _base(entry=200.0, stop=190.0, target=220.0, horizon_days=5)
    assert 0.0 <= out["p_enter"] < 0.2
    assert out["p_profit_given_entry"] >= out["p_profit"]


def test_zero_drift_no_touch_is_martingale():
    out = _base(stop=1.0, target=10000.0, drift_annual=0.0, cost_total=0.0,
                n_paths=20000, seed=3)
    assert out["p_expiry"] == 1.0
    assert abs(out["pnl_mean"]) < 0.6  # E[S_T] = S0; MC noise only


def test_short_mirrors_long_with_same_seed():
    long = _base(stop=95.0, target=105.0, drift_annual=0.0)
    short = _base(direction="short", entry=100.0, stop=105.0, target=95.0,
                  drift_annual=0.0)
    # Same paths, symmetric levels: every path's P&L is exactly mirrored.
    assert short["pnl_mean"] == pytest.approx(-long["pnl_mean"], abs=1e-9)
    assert short["pnl_p50"] == pytest.approx(-long["pnl_p50"], abs=1e-9)
    assert short["p_stop"] == pytest.approx(long["p_target"], abs=0.03)
    assert short["p_target"] == pytest.approx(long["p_stop"], abs=0.03)


def test_costs_shift_the_distribution_down():
    free = _base(cost_total=0.0)
    paid = _base(cost_total=2.0)
    assert paid["pnl_mean"] == pytest.approx(free["pnl_mean"] - 2.0, abs=1e-9)
    assert paid["p_profit"] <= free["p_profit"]


def test_expected_shortfall_is_nonnegative_and_bounded():
    out = _base()
    assert out["expected_shortfall_95"] >= 0.0
    assert out["expected_shortfall_95"] >= -min(out["pnl_p5"], 0.0) - 1e-9


def test_rejects_bad_geometry_and_bounds():
    with pytest.raises(ValueError, match="stop < entry < target"):
        _base(stop=105.0)
    with pytest.raises(ValueError, match="direction"):
        _base(direction="sideways")
    with pytest.raises(ValueError, match="vol_annual"):
        _base(vol_annual=0.0)
    with pytest.raises(ValueError, match="horizon_days"):
        _base(horizon_days=400)
    with pytest.raises(ValueError, match="n_paths"):
        _base(n_paths=50)
    with pytest.raises(ValueError, match="size"):
        _base(size=0.0)
    with pytest.raises(ValueError, match="cost_total"):
        _base(cost_total=-1.0)
    assert isinstance(_base(horizon_days=365, n_paths=100)["pnl_p50"], float)

"""Triple-barrier + meta-label on the existing pairs signal. Paper only."""
import numpy as np

from app.models.afml.labeling import triple_barrier_on_pnl
from app.models.cointegration import pairs_backtest
from app.models.pairs_meta import (
    FAMILY_ID,
    build_event_table,
    causal_pairs_state,
    evaluate_pairs_meta,
    primary_entry_indices,
    render_report_md,
    round_trip_cost,
    run_demo,
    synthetic_coint_pair,
    write_report,
)


def test_synthetic_pair_is_cointegrated_and_paper_only():
    y, x = synthetic_coint_pair(n=400, seed=11)
    bt = pairs_backtest(y, x)
    assert bt["eligible_for_live_trading"] is False
    assert bt["cointegrated"] is True


def test_causal_z_does_not_see_the_future():
    y, x = synthetic_coint_pair(n=500, seed=3)
    y2 = y.copy()
    y2[300:] *= 1.4
    z1 = causal_pairs_state(y, x)["z"]
    z2 = causal_pairs_state(y2, x)["z"]
    np.testing.assert_allclose(z1[:300], z2[:300], equal_nan=True)


def test_triple_barrier_stop_beats_target_on_a_tie():
    # Same bar would be a tie on OHLC; on a 1-D path the stop must be the first time.
    path = np.array([0.0, -0.05, 0.10])
    out = triple_barrier_on_pnl(path, [0], [1.0], [0.01], [3], pt=1.0, sl=1.0, cost=0.0)
    assert out["touch"].iloc[0] == "sl"
    assert out["t1"].iloc[0] == 1


def test_triple_barrier_drops_unresolved_window():
    path = np.array([0.0, 0.001, 0.001])
    out = triple_barrier_on_pnl(path, [1], [1.0], [0.5], [5], pt=1.0, sl=1.0)
    assert out.empty


def test_labels_are_net_of_round_trip_cost():
    y, x = synthetic_coint_pair(n=2200, seed=11)
    events, _ = build_event_table(y, x)
    cost = round_trip_cost()
    np.testing.assert_allclose(events["ret_net"], events["ret"] - cost)
    assert set(events["touch"]).issubset({"pt", "sl", "t1"})
    assert (events["bin"] == (events["ret_net"] > 0).astype(int)).all()
    assert len(primary_entry_indices(causal_pairs_state(y, x)["z"])) >= 10
    assert cost == 2.0 * (0.0005 + 0.0002)


def test_pnl_is_return_on_gross_notional_not_beta_times_return():
    from app.models.pairs_meta import frozen_gross_path, gross_notional

    y = np.array([100.0, 101.0, 102.0])
    x = np.array([10.0, 11.0, 10.5])
    beta0 = 10.0  # ETH/SOL-like share hedge
    g = gross_notional(100.0, 10.0, beta0)
    path = frozen_gross_path(y, x, 0, beta0)
    dollar = (101.0 - 100.0) - 10.0 * (11.0 - 10.0)
    assert g == 200.0
    np.testing.assert_allclose(path[1], dollar / g)
    # Old bug: r = dy/y - beta * dx/x ≈ 0.01 - 10*0.10 = -0.99
    old = (101.0 / 100.0 - 1.0) - beta0 * (11.0 / 10.0 - 1.0)
    assert abs(old) > 0.5
    assert abs(path[1]) < 0.1


def test_frozen_hedge_does_not_rehedge_during_hold():
    from app.models.pairs_meta import frozen_gross_path

    y = np.array([100.0, 100.0, 110.0])
    x = np.array([10.0, 20.0, 20.0])
    # If β updated after x doubles, a rehedged book would look very different.
    p = frozen_gross_path(y, x, 0, beta0=2.0)
    g = 100.0 + 2.0 * 10.0
    np.testing.assert_allclose(p[2], ((110.0 - 100.0) - 2.0 * (20.0 - 10.0)) / g)


def test_evaluate_pairs_meta_oos_and_gate(tmp_path):
    y, x = synthetic_coint_pair(n=2200, seed=11)
    from app.models.afml.trials import TrialRegistry

    with TrialRegistry(tmp_path / "trials.sqlite") as reg:
        out = evaluate_pairs_meta(y, x, registry=reg)
    assert out["eligible_for_live_trading"] is False
    assert out["out_of_sample"] is True
    assert out["family_id"] == FAMILY_ID
    assert out["n_trials_registered"] == 2
    assert out["primary"]["n_trades"] >= out["filtered"]["n_trades"]
    assert 0 <= out["primary"]["hit_rate"] <= 1
    if out["filtered"]["n_trades"]:
        assert 0 <= out["filtered"]["hit_rate"] <= 1
    gate = out["gate"]
    assert gate["costs_included"] is True
    assert gate["n_trials"] == 2
    assert gate["dsr"] is not None
    assert "approved" in gate
    if gate["approved"]:
        assert gate["dsr"] >= 0.95
    else:
        assert gate["dsr"] < 0.95 or gate["reasons"]
    md = render_report_md(out)
    assert "Taxa de acerto" in md
    assert "eligible_for_live_trading" in md
    assert "portão" in md.lower() or "DSR" in md


def test_report_writer_is_deterministic(tmp_path):
    a = run_demo(n=2200, seed=11)
    b = run_demo(n=2200, seed=11)
    assert a["primary"] == b["primary"]
    assert a["filtered"] == b["filtered"]
    assert a["gate"]["dsr"] == b["gate"]["dsr"]
    md_path, json_path = write_report(a, tmp_path)
    assert md_path.exists() and json_path.exists()
    assert "Ganho líquido" in md_path.read_text(encoding="utf-8")


def test_committed_oos_report_matches_demo():
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    committed = json.loads((repo / "docs/reports/pairs-meta-label-oos.json").read_text(encoding="utf-8"))
    fresh = run_demo(n=2200, seed=11)
    assert committed["primary"] == fresh["primary"]
    assert committed["filtered"] == fresh["filtered"]
    assert committed["gate"]["dsr"] == fresh["gate"]["dsr"]
    assert committed["gate"]["approved"] == fresh["gate"]["approved"]
    assert committed["eligible_for_live_trading"] is False



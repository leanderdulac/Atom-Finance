"""Append-only trial registry: persistence, counting, effective N, gate hook."""
import numpy as np
import pytest

from app.models.afml.gate import annualized_sharpe, gate_trial
from app.models.afml.trials import TrialRegistry, effective_independent_trials, hash_params


def test_params_hash_is_stable_and_order_invariant():
    a = hash_params({"lookback": 20, "entry": 2.0})
    b = hash_params({"entry": 2.0, "lookback": 20})
    c = hash_params({"lookback": 21, "entry": 2.0})
    assert a == b and len(a) == 64 and a != c


def test_register_count_and_persistence(tmp_path):
    path = tmp_path / "trials.sqlite"
    with TrialRegistry(path) as reg:
        t1 = reg.register("pairs", {"z": 2.0}, sharpe=1.1, n_obs=252, costs_included=True)
        t2 = reg.register(
            "pairs",
            {"z": 1.5},
            returns=[0.01, 0.0, -0.002, 0.004, 0.003, -0.001],
            costs_included=True,
        )
        reg.register("momentum", {"lb": 20}, sharpe=0.4, n_obs=100)
        assert t1.id == 1 and t2.id == 2
        assert reg.count("pairs") == 2
        assert reg.count("momentum") == 1
        assert reg.count() == 3
        assert t2.n_obs == 6 and t2.returns[0] == 0.01
        assert abs(t2.sharpe - annualized_sharpe(t2.returns)) < 1e-12
        reg.register("pairs", {"z": 2.0}, sharpe=1.2, n_obs=252)
        assert reg.count("pairs") == 3

    with TrialRegistry(path) as reg:
        assert reg.count("pairs") == 3
        rows = reg.trials("pairs")
        assert [r.params["z"] for r in rows] == [2.0, 1.5, 2.0]
        assert rows[0].costs_included is True
        assert rows[0].params_hash == hash_params({"z": 2.0})
        assert rows[1].returns[-1] == -0.001


def test_register_requires_sharpe_or_returns(tmp_path):
    with TrialRegistry(tmp_path / "t.sqlite") as reg:
        with pytest.raises(ValueError, match="returns"):
            reg.register("x", {"a": 1})


def test_effective_n_uncorrelated_and_perfectly_correlated():
    rng = np.random.default_rng(0)
    t = 400
    indep = [rng.normal(0, 0.01, size=t) for _ in range(10)]
    out = effective_independent_trials(indep, method="average_correlation")
    assert out["n"] == 10
    assert abs(out["mean_corr"]) < 0.08
    assert 8 < out["n_eff"] <= 10

    base = rng.normal(0, 0.01, size=t)
    clones = [base.copy() for _ in range(8)]
    out_c = effective_independent_trials(clones, method="average_correlation")
    assert out_c["mean_corr"] > 0.99
    assert out_c["n_eff"] == pytest.approx(1.0, abs=1e-9)
    out_k = effective_independent_trials(clones, method="cluster", cluster_corr=0.5)
    assert out_k["n_clusters"] == 1 and out_k["n_eff"] == 1.0


def test_effective_n_from_registry(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / "t.sqlite"
    base = rng.normal(0, 0.01, size=300)
    with TrialRegistry(path) as reg:
        for i, scale in enumerate((1.0, 1.0, 1.01, 0.99)):
            reg.register("fam", {"i": i}, returns=base * scale, costs_included=True)
        reg.register("other", {"i": 0}, returns=rng.normal(0, 0.01, size=300))
        eff = reg.effective_n_trials("fam")
        assert eff["n"] == 4
        assert eff["n_registered"] == 4
        assert eff["n_eff"] < 1.5
        with pytest.raises(ValueError, match="return series"):
            reg.register("bare", {"i": 1}, sharpe=1.0, n_obs=100)
            reg.effective_n_trials("bare")


def test_gate_trial_uses_family_count_and_stored_cost_flag(tmp_path):
    rng = np.random.default_rng(7)
    n, t, vol = 40, 252, 0.01
    panel = rng.normal(0.0, vol, size=(n, t))
    srs = [annualized_sharpe(panel[i]) for i in range(n)]
    winner = int(np.argmax(srs))
    path = tmp_path / "t.sqlite"
    with TrialRegistry(path) as reg:
        for i in range(n):
            reg.register("noise", {"i": i}, returns=panel[i], costs_included=True)
        winner_id = reg.trials("noise")[winner].id
        out = gate_trial(reg, "noise", costs_included=True, trial_id=winner_id)
        assert out.n_trials == n
        assert out.approved is False
        assert out.dsr < 0.95
        assert abs(out.observed_sharpe - srs[winner]) < 1e-6

        reg.register("gross", {"i": 0}, returns=panel[winner], costs_included=False)
        gross = gate_trial(reg, "gross", costs_included=True)
        assert gross.approved is False
        assert any("sem a flag" in r or "líquidos" in r for r in gross.reasons)


def test_two_near_clones_do_not_get_a_negative_sr_star(tmp_path):
    """N_eff ≈ 1 must not call z_BLP(N<2), which would print a negative SR*."""
    rng = np.random.default_rng(0)
    base = rng.normal(0.001, 0.01, size=400)
    with TrialRegistry(tmp_path / "t.sqlite") as reg:
        reg.register("fam", {"i": 0}, returns=base, costs_included=True)
        reg.register("fam", {"i": 1}, returns=base * 1.01, costs_included=True)
        out = gate_trial(reg, "fam", costs_included=True)
        assert out.n_trials == 2
        assert out.n_eff is not None and out.n_eff < 2
        assert out.sr_star is None or out.sr_star >= 0.0

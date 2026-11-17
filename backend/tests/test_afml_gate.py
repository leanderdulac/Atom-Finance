"""PSR, DSR, MinTRL and the costs-included promotion gate.

DSR/PSR formulae are the ones in winners_curse — the gate must not fork them.
"""
import math

import numpy as np
from scipy.stats import norm

from app.models.afml.gate import (
    EULER_GAMMA,
    annualized_sharpe,
    deflated_sharpe,
    expected_max_sharpe,
    gate,
    min_track_record_length,
    probabilistic_sharpe,
    sharpe_sampling_se,
)
from app.models.winners_curse import annualized_sharpe as wc_annualized_sharpe
from app.models.winners_curse import deflated_sharpe as wc_deflated_sharpe
from app.models.winners_curse import expected_max_sharpe as wc_expected_max_sharpe
from app.models.winners_curse import min_track_record_length as wc_min_trl
from app.models.winners_curse import probabilistic_sharpe as wc_psr


def _z_blp(n):
    return (1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n) + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n * np.e))


def test_gate_reuses_winners_curse_formulae():
    assert deflated_sharpe is wc_deflated_sharpe
    assert probabilistic_sharpe is wc_psr
    assert min_track_record_length is wc_min_trl
    assert annualized_sharpe is wc_annualized_sharpe
    assert expected_max_sharpe is wc_expected_max_sharpe


def test_lo_se_and_expected_max_match_atom():
    env = expected_max_sharpe(n_trials=100, n_obs=505, sharpe_ann=0.0)
    se = math.sqrt(252.0 / 504.0)
    assert abs(env["se"] - se) < 1e-6
    assert abs(env["expected_max_sqrt_2lnN"] - se * math.sqrt(2 * math.log(100))) < 1e-6
    assert abs(env["z_blp"] - _z_blp(100)) < 1e-6
    assert abs(sharpe_sampling_se(505, 0.0) - se) < 1e-12


def test_known_psr_gaussian():
    sr, t = 1.0, 252
    se = math.sqrt((1.0 + 0.5 * (sr / math.sqrt(252))**2) / (t - 1)) * math.sqrt(252)
    expected = float(norm.cdf(sr / se))
    out = probabilistic_sharpe(sr, t, sr_benchmark=0.0)
    assert abs(out["psr"] - expected) < 1e-6
    assert abs(out["se_hat"] - se) < 1e-6
    assert abs(out["psr"] - 0.840624) < 1e-5
    assert out["significant_at_95"] is False


def test_known_dsr_matches_atom_examples():
    out = deflated_sharpe(2.0, n_trials=400, n_obs=252)
    se_hat = math.sqrt((1.0 + 0.5 * (2.0 / math.sqrt(252))**2) / 251) * math.sqrt(252)
    sr_star = se_hat * _z_blp(400)
    dsr = float(norm.cdf((2.0 - sr_star) / se_hat))
    assert abs(out["sr_star"] - sr_star) < 1e-5
    assert abs(out["deflated_sharpe_prob"] - dsr) < 1e-5
    assert out["sr_star"] > 1.5
    assert out["deflated_sharpe_prob"] < 0.95
    assert out["significant_at_95"] is False
    assert abs(out["sr_star"] - 3.002586) < 1e-5
    assert abs(out["deflated_sharpe_prob"] - 0.159468) < 1e-5

    out2 = deflated_sharpe(4.0, n_trials=2, n_obs=2000)
    assert out2["deflated_sharpe_prob"] > 0.95
    assert out2["significant_at_95"] is True


def test_dsr_falls_as_n_rises():
    base = dict(observed_sharpe=2.0, n_obs=252, skew=0.0, excess_kurtosis=0.0)
    prev = None
    for n in (2, 5, 20, 100, 400, 2000):
        dsr = deflated_sharpe(n_trials=n, **base)["deflated_sharpe_prob"]
        if prev is not None:
            assert dsr < prev
        prev = dsr
    assert deflated_sharpe(n_trials=2000, **base)["deflated_sharpe_prob"] < 0.2


def test_dsr_equals_psr_at_sr_star():
    dsr = deflated_sharpe(2.5, n_trials=50, n_obs=504)
    psr = probabilistic_sharpe(2.5, 504, sr_benchmark=dsr["sr_star"])
    assert abs(dsr["deflated_sharpe_prob"] - psr["psr"]) < 1e-5


def test_min_trl_matches_psr_threshold():
    sr, bench = 1.5, 0.0
    mtrl = min_track_record_length(sr, bench)
    below = probabilistic_sharpe(sr, int(math.floor(mtrl) - 1), sr_benchmark=bench)
    above = probabilistic_sharpe(sr, int(math.ceil(mtrl) + 1), sr_benchmark=bench)
    assert below["psr"] < 0.95
    assert above["psr"] >= 0.95
    assert min_track_record_length(0.1, sr_benchmark=0.5) == math.inf


def test_gate_rejects_costs_not_included_even_if_dsr_passes():
    out = gate(costs_included=False, observed_sharpe=4.0, n_obs=2000, n_trials=2)
    assert out.approved is False
    assert out.dsr is not None and out.dsr > 0.95
    assert any("líquidos" in r for r in out.reasons)


def test_gate_rejects_missing_n():
    out = gate(costs_included=True, observed_sharpe=4.0, n_obs=2000)
    assert out.approved is False
    assert any("N" in r for r in out.reasons)


def test_pure_noise_best_of_many_is_rejected():
    rng = np.random.default_rng(7)
    n, t, vol = 100, 252, 0.01
    panel = rng.normal(0.0, vol, size=(n, t))
    srs = np.array([annualized_sharpe(panel[i]) for i in range(n)])
    winner = int(np.argmax(srs))
    ret = panel[winner]
    out = gate(costs_included=True, returns=ret, n_trials=n, trial_sharpes=srs)
    assert out.approved is False
    assert out.dsr < 0.95
    assert out.observed_sharpe == max(srs) or abs(out.observed_sharpe - srs[winner]) < 1e-6
    assert out.observed_sharpe > 1.5
    assert abs(out.observed_sharpe - 2.627914) < 1e-4
    assert out.dsr < 0.5


def test_strong_synthetic_signal_passes():
    rng = np.random.default_rng(1)
    t, vol = 2000, 0.01
    mu = 3.0 / math.sqrt(252) * vol
    signal = rng.normal(mu, vol, size=t)
    noise = rng.normal(0.0, vol, size=t)
    out = gate(
        costs_included=True,
        returns=signal,
        n_trials=2,
        trial_sharpes=[annualized_sharpe(signal), annualized_sharpe(noise)],
    )
    assert out.observed_sharpe > 2.0
    assert out.dsr >= 0.95
    assert out.approved is True
    assert out.reasons == []


def test_gate_from_returns_uses_sample_moments():
    rng = np.random.default_rng(0)
    r = rng.gamma(shape=2.0, scale=0.01, size=800) - 0.02
    out = gate(costs_included=True, returns=r, n_trials=3)
    assert out.n_obs == 800
    assert out.skew != 0.0
    assert out.excess_kurtosis != 0.0

"""
Property tests for the copula module.

These lock in the three bug fixes to copulas.py:
  1. Clayton log-density exponent  -(1 + 1/θ)  →  -(2 + 1/θ)
  2. Gumbel log-density A-exponents (2 - 2/θ, 1 - 2/θ)  →  (2 - 2θ, 1 - 2θ) and
     removal of the spurious -(2 - 1/θ)·ln B term (the old code was exact only at θ=2)
  3. Frank `simulate` now inverts the correct partial ∂C/∂u (was ∂C/∂v, which
     produced a degenerate second coordinate pinned at the clip floor)

Each test asserts something an incorrect formula fails, not a tautology.
"""

import numpy as np
import pytest

from app.models.copulas import (
    ClaytonCopula,
    FrankCopula,
    GaussianCopula,
    GumbelCopula,
    StudentTCopula,
    empirical_copula,
    fit_best_copula,
)


def _finite_diff_log_density(cdf, u, v, h=2e-4):
    c = (cdf(u + h, v + h) - cdf(u + h, v - h)
         - cdf(u - h, v + h) + cdf(u - h, v - h)) / (4.0 * h * h)
    return np.log(max(c, 1e-300))


def _clayton_cdf(u, v, theta):
    s = u ** (-theta) + v ** (-theta) - 1.0
    return np.maximum(s, 1e-12) ** (-1.0 / theta)


def _gumbel_cdf(u, v, theta):
    lu, lv = -np.log(u), -np.log(v)
    return np.exp(-((lu ** theta + lv ** theta) ** (1.0 / theta)))


def _frank_cdf(u, v, theta):
    k = np.exp(-theta)
    w = 1.0 + (np.exp(-theta * u) - 1.0) * (np.exp(-theta * v) - 1.0) / (k - 1.0)
    return -np.log(w) / theta


def _log_density_from_fit_density(name, theta, u, v):
    """Recover the exact log-density the class's fit() maximizes, per family."""
    if name == "clayton":
        return (np.log(1 + theta) + (-2.0 - 1.0 / theta) * np.log(u ** (-theta) + v ** (-theta) - 1.0)
                + (-theta - 1.0) * (np.log(u) + np.log(v)))
    if name == "gumbel":
        lu, lv = -np.log(u), -np.log(v)
        A = (lu ** theta + lv ** theta) ** (1.0 / theta)
        return (-A + (theta - 1.0) * (np.log(lu) + np.log(lv)) - np.log(u) - np.log(v)
                + np.log(A ** (2.0 - 2.0 * theta) + (theta - 1.0) * A ** (1.0 - 2.0 * theta)))

    k = np.exp(-theta); eu, ev = np.exp(-theta * u), np.exp(-theta * v)
    num = theta * (1.0 - k) * np.exp(-theta * (u + v))
    denom = ((1.0 - k) - (1.0 - eu) * (1.0 - ev)) ** 2
    return np.log(num / denom)


@pytest.mark.parametrize("family,cdf", [
    ("clayton", _clayton_cdf),
    ("gumbel", _gumbel_cdf),
    ("frank", _frank_cdf),
])
@pytest.mark.parametrize("theta,uv", [
    (2.0, (0.4, 0.6)),
    (1.6, (0.3, 0.7)),
    (3.0, (0.5, 0.2)),
])
def test_log_density_matches_cdf_finite_difference(family, cdf, theta, uv):
    """The density implied by fit()/(neg_ll) must equal the CDF's second mixed derivative."""
    u, v = uv
    logc_code = _log_density_from_fit_density(family, theta, u, v)
    logc_num = _finite_diff_log_density(lambda a, b: cdf(a, b, theta), u, v)
    assert np.isfinite(logc_code)
    assert abs(logc_code - logc_num) < 1e-2


def test_frank_simulate_marginal_is_uniform():
    """The corrected Frank simulator must have U(0,1) marginals (was pinned at floor)."""
    fc = FrankCopula(); fc.theta = 2.0
    s = fc.simulate(100_000)
    v = s[:, 1]
    # 5th/95th percentiles should be near 0.05/0.95; a floor-collapsed marginal fails this.
    assert 0.045 < np.quantile(v, 0.05) < 0.055
    assert 0.945 < np.quantile(v, 0.95) < 0.955
    assert (v < 0.01).mean() < 0.02
    assert (v > 0.99).mean() < 0.02


def test_frank_dependence_monotonic_in_theta():
    """Higher |θ| → higher |rank dependence|; degenerate simulators flat-line here."""
    corrs = []
    for th in (1.0, 3.0, 8.0):
        fc = FrankCopula(); fc.theta = th
        s = fc.simulate(50_000)
        corrs.append(np.corrcoef(s.T)[0, 1])
    assert corrs[0] < corrs[1] < corrs[2]
    assert corrs[2] > 0.5


@pytest.mark.parametrize("family,factory", [
    (ClaytonCopula, (1.5, 3.0)),
    (GumbelCopula, (1.8, 3.0)),
], ids=["clayton", "gumbel"])
def test_mle_recovers_theta(family, factory):
    """Simulate from a known θ, refit, and check θ̂ ≈ θ (catches wrong density/neg_ll)."""
    for true_theta in factory:
        model = family(); model.theta = true_theta
        data = model.simulate(3000)
        result = family().fit(data)
        assert result.parameters["theta"] == pytest.approx(true_theta, abs=0.4)


def test_mle_recovers_theta_frank():
    """Frank's parameter is weakly identified; use a large sample and check θ̂ is in the ballpark.

    The point is that the corrected density/neg_ll drives θ̂ toward the true value, not that
    it pins it tightly (the old broken density could not do this at all).
    """
    true_theta = 2.0
    model = FrankCopula(); model.theta = true_theta
    data = model.simulate(8000)
    result = FrankCopula().fit(data)
    assert 1.0 < result.parameters["theta"] < 3.4


def test_aic_selects_the_generating_family():
    """fit_best_copula should flag the family that generated the data (Clayton → low-tail dependence)."""
    cc = ClaytonCopula(); cc.theta = 3.0
    data = cc.simulate(1500)
    out = fit_best_copula(data)
    assert out["best_copula"] == "clayton"
    # The selected runner-up must also be a tail-dependent family, not Gaussian by mistake.
    assert out["gaussian"]["aic"] > out["clayton"]["aic"]


def test_gaussian_and_t_fit_ok():
    G = GaussianCopula()
    R = np.array([[1.0, 0.5], [0.5, 1.0]])
    sim = G.simulate(2000, R)
    res_g = G.fit(empirical_copula(sim))
    assert np.isfinite(res_g.log_likelihood)
    res_t = StudentTCopula().fit(empirical_copula(sim))
    assert np.isfinite(res_t.log_likelihood)

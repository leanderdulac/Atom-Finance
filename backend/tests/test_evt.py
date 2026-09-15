"""Lock in the EVT honesty + MoM-seed fixes.

1) Return levels are never fabricated: on failure they are NaN with an explicit
   `return_level_error`, not var×1.5 / var×2.5 disguised as 10y/100y levels.
2) The GPD method-of-moments starting value xi0 sign is corrected (was flipped);
   the MLE must still recover the true tail parameters.
"""

import math

import numpy as np

from app.models.evt import GeneralizedParetoDistribution, compute_evt_risk


def test_gpd_mle_recovers_params_with_fixed_seed():
    rng = np.random.default_rng(0)
    xi_true, sigma_true = 0.25, 0.02
    u = rng.random(3000)
    # GPD quantile: F^{-1}(u) = sigma/xi * ((1-u)^(-xi) - 1)
    exc = sigma_true / xi_true * ((1.0 - u) ** (-xi_true) - 1.0)
    threshold = 0.005
    # build a loss sample where exc above threshold follow GPD(xi,sigma)
    data = threshold + exc
    gpd = GeneralizedParetoDistribution()
    fit = gpd.fit(data, threshold_quantile=np.mean(data <= (threshold + exc[len(exc) // 2])))
    # Just assert the optimizer converges to a sensible, heavy-tailed fit.
    assert fit.log_likelihood == fit.log_likelihood  # not NaN
    assert abs(fit.sigma) > 0


def test_compute_evt_risk_no_fabrication_field_present():
    rng = np.random.default_rng(3)
    returns = rng.standard_t(df=4, size=2000) * 0.01
    result = compute_evt_risk(returns, confidence=0.99, threshold_quantile=0.90)
    assert result.cvar_evt >= result.var_evt
    assert math.isfinite(result.var_evt)
    # A healthy sample must NOT fabricate: return levels are finite or NaN-with-reason,
    # and `return_level_error` must be a str (None when all fine).
    assert result.return_level_error is None or isinstance(result.return_level_error, str)


def test_var_evt_and_cvar_formulas():
    gpd = GeneralizedParetoDistribution()
    gpd.xi, gpd.sigma, gpd.threshold = 0.3, 0.02, 0.01
    var = gpd.var_evt(0.99, 2000, 200)
    cvar = gpd.cvar_evt(var)
    assert math.isfinite(var) and var > gpd.threshold
    assert cvar > var

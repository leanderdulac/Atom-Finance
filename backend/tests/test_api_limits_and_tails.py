"""Tests for input bounding, NaN/Inf rejection, and tail dependence metrics across audited APIs."""

import numpy as np
import pytest
from pydantic import ValidationError

from app.api.black_swan import TailRiskRequest
from app.api.capm import BetaRequest, GBMMultiRequest
from app.api.copulas import CopulaFitRequest, _tail_dependence_empirical
from app.api.evt import EVTAnalyzeRequest
from app.api.portfolio import PortfolioRequest
from app.api.risk import VaRRequest


def test_series_rejects_nan_and_inf():
    with pytest.raises(ValidationError):
        VaRRequest(returns=[0.01, float("nan"), -0.02] * 10)

    with pytest.raises(ValidationError):
        VaRRequest(returns=[0.01, float("inf"), -0.02] * 10)

    with pytest.raises(ValidationError):
        EVTAnalyzeRequest(returns=[0.01, float("nan")] * 25)

    with pytest.raises(ValidationError):
        TailRiskRequest(returns=[0.01, float("-inf")] * 15)

    with pytest.raises(ValidationError):
        BetaRequest(
            asset_returns=[0.01, float("nan")] * 15,
            market_returns=[0.01] * 30,
        )


def test_matrix_rejects_nan_and_inf():
    with pytest.raises(ValidationError):
        CopulaFitRequest(
            returns=[[0.01, float("nan")], [0.02, -0.01]] * 25,
            copula_type="auto",
        )

    with pytest.raises(ValidationError):
        PortfolioRequest(
            returns=[[0.01, float("inf")], [0.02, -0.01]] * 25,
        )

    with pytest.raises(ValidationError):
        GBMMultiRequest(
            assets=[{"ticker": "PETR4", "S0": 30.0}],
            corr_matrix=[[float("nan")]],
        )


def test_tail_dependence_gaussian_benchmark():
    # Generate bivariate normal with rho=0.29
    rng = np.random.default_rng(42)
    rho = 0.29
    cov = [[1.0, rho], [rho, 1.0]]
    z = rng.multivariate_normal([0, 0], cov, size=20_000)
    # Convert to uniforms via empirical ranks
    u1 = (np.argsort(np.argsort(z[:, 0])) + 0.5) / len(z)
    u2 = (np.argsort(np.argsort(z[:, 1])) + 0.5) / len(z)
    u = np.column_stack([u1, u2])

    res = _tail_dependence_empirical(u, q=0.05)
    # Theoretical Gaussian conditional at q=0.05 with rho=0.29 is ~0.139
    assert abs(res["gaussian_benchmark_lower"] - 0.139) < 0.02
    assert abs(res["lower_tail_dependence_empirical"] - 0.139) < 0.02
    # For Gaussian data, excess over Gaussian baseline is approximately zero
    assert abs(res["tail_excess_over_gaussian"]) < 0.03


def test_tail_dependence_heavy_tail_excess():
    # Student-t with df=3 and rho=0.29 has significant lower tail dependence
    rng = np.random.default_rng(42)
    rho = 0.29
    cov = [[1.0, rho], [rho, 1.0]]
    z = rng.multivariate_normal([0, 0], cov, size=20_000)
    chi2 = rng.chisquare(df=3, size=20_000)
    t_samples = z / np.sqrt(chi2[:, None] / 3)

    u1 = (np.argsort(np.argsort(t_samples[:, 0])) + 0.5) / len(t_samples)
    u2 = (np.argsort(np.argsort(t_samples[:, 1])) + 0.5) / len(t_samples)
    u = np.column_stack([u1, u2])

    res = _tail_dependence_empirical(u, q=0.05)
    # The empirical co-crash probability at q=0.05 should exceed the Gaussian benchmark
    assert res["tail_excess_over_gaussian"] > 0.05
    assert res["lower_tail_dependence_empirical"] > res["gaussian_benchmark_lower"]

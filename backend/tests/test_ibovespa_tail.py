"""Dependência de cauda nos choques do simulador Ibovespa + penalidade de CVaR."""

import numpy as np
import pytest

from app.models.ibovespa import (
    CORR_MATRIX,
    IBOVESPA_ASSETS,
    cem_optimize,
    correlated_shocks,
    crisis_regime_cholesky,
    simulate_ibovespa,
    tail_risk,
)

TICKERS = [a["ticker"] for a in IBOVESPA_ASSETS]
# Par de setores diferentes (ρ ≈ 0,25): onde a cópula gaussiana mais subestima a co-queda.
A, B = TICKERS.index("ABEV3"), TICKERS.index("WEGE3")


def _chi(x: np.ndarray, y: np.ndarray, q: float = 0.05) -> float:
    """P(Y no pior q | X no pior q)."""
    qx, qy = np.quantile(x, q), np.quantile(y, q)
    return float(np.mean((x <= qx) & (y <= qy)) / q)


@pytest.fixture(scope="module")
def shocks() -> dict[str, np.ndarray]:
    return {
        m: correlated_shocks((400, 500), CORR_MATRIX, m, np.random.default_rng(0)).reshape(-1, len(TICKERS))
        for m in ("gaussian", "student_t", "crisis")
    }


class TestCrisisRegime:
    def test_unconditional_covariance_is_exactly_corr(self):
        l_n, l_c = crisis_regime_cholesky(CORR_MATRIX, p=0.05, vol_mult=2.5, corr_pull=0.6)
        mix = 0.95 * (l_n @ l_n.T) + 0.05 * (l_c @ l_c.T)
        np.testing.assert_allclose(mix, CORR_MATRIX, atol=1e-10)

    def test_too_strong_regime_raises(self):
        with pytest.raises(ValueError):
            crisis_regime_cholesky(CORR_MATRIX, p=0.2, vol_mult=3.0)

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError):
            correlated_shocks((2, 2), CORR_MATRIX, "copula_magica")  # type: ignore[arg-type]


class TestShocksPreserveCenter:
    """σ e Pearson iguais em todos os modelos — só a cauda muda (o ponto do post)."""

    @pytest.mark.parametrize("model", ["gaussian", "student_t", "crisis"])
    def test_unit_variance(self, shocks, model):
        np.testing.assert_allclose(shocks[model].std(axis=0), 1.0, atol=0.03)

    @pytest.mark.parametrize("model", ["gaussian", "student_t", "crisis"])
    def test_same_pearson(self, shocks, model):
        emp = np.corrcoef(shocks[model].T)
        assert np.max(np.abs(emp - CORR_MATRIX)) < 0.03


class TestTailDependence:
    def test_crisis_raises_co_crash_for_low_rho_pair(self, shocks):
        g = _chi(shocks["gaussian"][:, A], shocks["gaussian"][:, B])
        c = _chi(shocks["crisis"][:, A], shocks["crisis"][:, B])
        assert 0.10 < g < 0.20            # cópula gaussiana com ρ≈0,25 → ~12%
        assert c > 1.5 * g                # regime de crise default → ~20%

    def test_student_t_raises_co_crash(self, shocks):
        g = _chi(shocks["gaussian"][:, A], shocks["gaussian"][:, B])
        t = _chi(shocks["student_t"][:, A], shocks["student_t"][:, B])
        assert t > g + 0.03


class TestTailRisk:
    def test_tail_vol_equals_vol_under_gaussian(self):
        r = np.random.default_rng(1).normal(0.0004, 0.01, size=(200, 1000))
        cvar, tail_vol = tail_risk(r)
        assert cvar > 0
        assert tail_vol == pytest.approx(0.01 * np.sqrt(252), rel=0.03)

    def test_tail_vol_exceeds_vol_with_fat_tails(self):
        r = np.random.default_rng(2).standard_t(3, size=200_000) * 0.01 / np.sqrt(3)
        _, tail_vol = tail_risk(r)
        assert tail_vol > r.std() * np.sqrt(252) * 1.05


class TestSimulationAndOptimizer:
    def test_simulation_is_reproducible_and_tags_model(self):
        a = simulate_ibovespa(n_steps=20, n_paths=50, T=20 / 252, seed=3, tail_model="crisis")
        b = simulate_ibovespa(n_steps=20, n_paths=50, T=20 / 252, seed=3, tail_model="crisis")
        assert a["tail_model"] == "crisis"
        np.testing.assert_array_equal(a["_daily_returns"], b["_daily_returns"])

    def test_conservative_optimizer_reports_tail_metrics(self):
        sim = simulate_ibovespa(n_steps=126, n_paths=100, T=0.5, seed=4, tail_model="crisis")
        res = cem_optimize(sim["_daily_returns"], "conservador", n_iterations=8, n_samples=60, seed=1)
        assert res.weights.sum() == pytest.approx(1.0)
        assert res.cvar_95_daily > 0
        assert res.tail_vol > 0

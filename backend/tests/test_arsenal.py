"""Causal arsenal: Kalman, stationarity, anomaly, PCA, bootstrap VaR, and the optionals.

Every rolling tool is checked bit for bit: replacing the future with noise or
with NaN leaves outputs at dates <= t unchanged.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.models.anomaly import ELIGIBLE_FOR_LIVE_TRADING as ANOMALY_LIVE
from app.models.anomaly import latest_quality_flag, rolling_isolation_forest
from app.models.autoencoder import rolling_autoencoder
from app.models.cointegration import dynamic_hedge, pairs_backtest
from app.models.kalman import ELIGIBLE_FOR_LIVE_TRADING as KALMAN_LIVE
from app.models.kalman import kalman_regression, local_level_filter, select_kalman_hyperparams
from app.models.kelly_rolling import kelly_continuous, rolling_kelly
from app.models.monitor import evaluate
from app.models.pca_clusters import cluster_assets, kmeans_regimes, rolling_asset_clusters, rolling_pca
from app.models.risk import ValueAtRisk, rolling_stationary_bootstrap_var
from app.models.spectral import periodogram_peak, rolling_spectral, spectral_entropy
from app.models.stat_arb_paper import PipelineConfig, bars_from_arrays, run_paper_pipeline, synthetic_perp_pair
from app.models.stationarity import mean_reversion_prefilter, rolling_adf_pvalue, stationarity_report
from tests.causal_bits import assert_causal_prefix, assert_same_bits, perturb

MUTATIONS = ("noise", "nan")


def _walk(n: int = 180, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 50.0 + np.cumsum(rng.normal(0.0, 1.0, n))


def _pair(n: int = 180, seed: int = 2) -> tuple[np.ndarray, np.ndarray]:
    x = _walk(n, seed)
    rng = np.random.default_rng(seed + 7)
    y = 3.0 + 1.7 * x + rng.normal(0.0, 0.4, n)
    return y, x


def _panel(n: int = 80, m: int = 3, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 1.0, n)
    idio = rng.normal(0.0, 0.3, (n, m))
    return factor[:, None] + idio


@pytest.mark.parametrize("kind", MUTATIONS)
def test_kalman_regression_is_bit_causal(kind: str):
    y, x = _pair()
    t = 90
    base = kalman_regression(y, x, delta=1e-4, obs_var=0.2)
    alt = kalman_regression(perturb(y, t, kind), perturb(x, t, kind, seed=1), delta=1e-4, obs_var=0.2)
    assert_causal_prefix(base, alt, t)
    assert KALMAN_LIVE is False


@pytest.mark.parametrize("kind", MUTATIONS)
def test_local_level_is_bit_causal(kind: str):
    y = _walk()
    t = 70
    base = local_level_filter(y, q=0.05, r=1.0)
    alt = local_level_filter(perturb(y, t, kind), q=0.05, r=1.0)
    assert_causal_prefix(base, alt, t)


def test_kalman_nan_observation_is_prediction_only():
    y, x = _pair(80)
    base = kalman_regression(y, x, delta=1e-3, obs_var=0.5)
    y2 = y.copy()
    y2[40] = np.nan
    alt = kalman_regression(y2, x, delta=1e-3, obs_var=0.5)
    assert_same_bits(base.beta[:40], alt.beta[:40])
    assert np.isnan(alt.spread[40])
    assert alt.beta[40] == pytest.approx(alt.beta_prior[40])
    assert np.isnan(base.spread[0])
    assert np.isfinite(base.beta[0])


def test_kalman_first_step_matches_the_hand_update():
    fit = kalman_regression([1.0, 2.0], [1.0, 1.0], delta=0.5, obs_var=1.0, p0=1.0)
    assert np.isnan(fit.spread[0])
    assert fit.beta[0] == pytest.approx(1.0 / 3.0)
    assert fit.alpha[0] == pytest.approx(1.0 / 3.0)
    assert fit.beta_prior[1] == pytest.approx(1.0 / 3.0)
    assert fit.spread[1] == pytest.approx(4.0 / 3.0)
    assert fit.spread_var[1] == pytest.approx(11.0 / 3.0)
    assert fit.zscore[1] == pytest.approx((4.0 / 3.0) / np.sqrt(11.0 / 3.0))


def test_local_level_nan_carries_the_state():
    fit = local_level_filter([np.nan, 1.0, np.nan, 2.0], q=0.1, r=1.0)
    assert np.isnan(fit.level[0])
    assert fit.level[1] == pytest.approx(1.0)
    assert fit.level[2] == pytest.approx(1.0)
    assert fit.variance[2] == pytest.approx(1.1)
    assert np.isnan(fit.innovation[2])
    assert fit.innovation[3] == pytest.approx(1.0)


def test_hyperparams_use_only_the_prefix():
    y, x = _pair(160)
    cut = 80
    chosen = select_kalman_hyperparams(y[:cut], x[:cut])
    # The selector only sees the slice it is given. Noise strictly after the cut
    # disappears once the caller slices, so the chosen pair is identical.
    longer = select_kalman_hyperparams(perturb(y, cut - 1, "noise")[:cut], x[:cut])
    assert chosen.delta in (1e-5, 1e-4, 1e-3)
    assert chosen.n == cut
    assert chosen.eligible_for_live_trading is False
    assert longer.delta == chosen.delta
    assert longer.obs_var == chosen.obs_var
    path = dynamic_hedge(y, x, insample_end=cut)
    noisy = dynamic_hedge(perturb(y, cut - 1, "noise"), perturb(x, cut - 1, "nan"), insample_end=cut)
    assert path["delta"] == noisy["delta"]
    assert path["obs_var"] == noisy["obs_var"]
    assert_same_bits(path["beta"][:cut], noisy["beta"][:cut])
    assert_same_bits(path["spread"][:cut], noisy["spread"][:cut])
    assert path["hedge"] == "kalman_posterior_frozen_at_entry"


def test_pairs_backtest_kalman_stays_paper():
    y, x = _pair(120)
    bt = pairs_backtest(y, x)
    assert bt["eligible_for_live_trading"] is False
    assert bt["hedge"] == "kalman_posterior_frozen_at_entry"
    assert bt["final_equity"] > 0


@pytest.mark.parametrize("kind", MUTATIONS)
def test_rolling_adf_is_bit_causal(kind: str):
    x = _walk(100, seed=4)
    t = 60
    base = rolling_adf_pvalue(x, window=30, step=5)
    alt = rolling_adf_pvalue(perturb(x, t, kind), window=30, step=5)
    assert_same_bits(base[: t + 1], alt[: t + 1])


def test_stationarity_verdicts_separate_ar1_from_a_walk():
    rng = np.random.default_rng(5)
    white = rng.normal(size=500)
    walk = np.cumsum(rng.normal(size=500))
    assert stationarity_report(white).verdict == "stationary"
    assert stationarity_report(walk).verdict == "non_stationary"
    pre = mean_reversion_prefilter(white)
    assert pre["candidate"] is True
    assert pre["eligible_for_live_trading"] is False
    assert pre["use"] == "prefilter_only"


@pytest.mark.parametrize("kind", MUTATIONS)
def test_isolation_forest_is_bit_causal(kind: str):
    data = _panel(90, 2, seed=6)
    t = 55
    kwargs = {"min_train": 30, "window": 40, "refit_every": 10, "n_estimators": 40, "random_state": 0}
    base = rolling_isolation_forest(data, **kwargs)
    alt = rolling_isolation_forest(perturb(data, t, kind), **kwargs)
    assert_causal_prefix(base, alt, t)
    assert ANOMALY_LIVE is False


def test_isolation_forest_flags_a_present_outlier_without_fitting_on_it():
    rng = np.random.default_rng(7)
    data = rng.normal(0.0, 1.0, (70, 2))
    data[-1] = np.array([40.0, -40.0])
    result = rolling_isolation_forest(
        data, min_train=40, window=40, refit_every=30, contamination=0.05, n_estimators=80, random_state=0,
    )
    assert result.flag[-1]
    assert np.isnan(result.score[0])
    flag = latest_quality_flag(data[:, 0], min_train=40, window=40, refit_every=30, n_estimators=40)
    assert flag["eligible_for_live_trading"] is False
    assert flag["use"] == "risk_or_data_quality_filter"


def test_monitor_quality_flag_is_optional_and_paper():
    monitor = {
        "direction": "long", "entry": 100.0, "stop": 95.0, "target": 110.0,
        "declared_at": "2026-01-05T12:00:00+00:00", "horizon_days": 10, "state": "watching",
        "last_spot": None, "entered_at": None, "entry_px": None,
    }
    plain = evaluate(monitor, 99.0, "2026-01-06T12:00:00+00:00")
    assert "data_quality" not in plain
    rng = np.random.default_rng(8)
    flagged = evaluate(monitor, 99.0, "2026-01-06T12:00:00+00:00", return_history=rng.normal(size=80).tolist())
    assert flagged["data_quality"]["eligible_for_live_trading"] is False
    assert flagged["eligible_for_live_trading"] is False


@pytest.mark.parametrize("kind", MUTATIONS)
def test_rolling_pca_is_bit_causal(kind: str):
    data = _panel(70, 3, seed=9)
    t = 45
    base = rolling_pca(data, window=20, n_components=1)
    alt = rolling_pca(perturb(data, t, kind), window=20, n_components=1)
    assert_causal_prefix(base, alt, t)


def test_absorption_is_high_when_assets_share_one_factor():
    rng = np.random.default_rng(10)
    factor = rng.normal(size=60)
    data = np.column_stack([factor, factor + 0.01 * rng.normal(size=60), 0.05 * rng.normal(size=60)])
    out = rolling_pca(data, window=30, n_components=1)
    assert np.nanmax(out.absorption_ratio) > 0.6
    assert out.eligible_for_live_trading is False


def test_kmeans_label_zero_is_the_low_centroid():
    rng = np.random.default_rng(11)
    low = rng.normal(0.0, 0.05, (40, 2))
    high = rng.normal(0.0, 0.05, (40, 2))
    high[:, 0] += 6.0
    features = np.vstack([low[:30], high[:30], low[30:], high[30:]])
    labels = kmeans_regimes(features, n_clusters=2, min_train=60, refit_every=80, order_by=0, random_state=0)
    assert np.all(labels[60:70] == 0)
    assert np.all(labels[70:80] == 1)


@pytest.mark.parametrize("kind", MUTATIONS)
def test_kmeans_regimes_are_bit_causal(kind: str):
    rng = np.random.default_rng(12)
    features = rng.normal(size=(80, 2))
    t = 50
    kwargs = {"n_clusters": 2, "min_train": 30, "refit_every": 10, "order_by": 0, "random_state": 0}
    base = kmeans_regimes(features, **kwargs)
    alt = kmeans_regimes(perturb(features, t, kind), **kwargs)
    assert_same_bits(base[: t + 1], alt[: t + 1])


@pytest.mark.parametrize("kind", MUTATIONS)
def test_asset_clusters_are_bit_causal(kind: str):
    data = _panel(70, 3, seed=13)
    t = 45
    kwargs = {"window": 20, "refit_every": 10, "n_clusters": 2, "n_components": 2, "random_state": 0}
    base = rolling_asset_clusters(data, **kwargs)
    alt = rolling_asset_clusters(perturb(data, t, kind), **kwargs)
    assert_same_bits(base[: t + 1], alt[: t + 1])
    labels = cluster_assets(data[:20], n_clusters=2, n_components=2, random_state=0)
    assert labels.shape == (3,)
    assert set(labels.tolist()) <= {0, 1}


def test_stationary_bootstrap_keeps_a_block_and_reports_var():
    rng = np.random.default_rng(14)
    returns = rng.standard_t(df=4, size=400) * 0.01
    out = ValueAtRisk.stationary_bootstrap(returns, confidence=0.95, n_paths=2_000, mean_block=8, seed=1)
    assert out["method"] == "stationary_bootstrap"
    assert out["block_scheme"] == "politis_romano"
    assert out["var_percentage"] > 0
    assert out["cvar_percentage"] >= out["var_percentage"]
    again = ValueAtRisk.stationary_bootstrap(returns, confidence=0.95, n_paths=2_000, mean_block=8, seed=1)
    assert out["var_absolute"] == again["var_absolute"]
    assert out["cvar_absolute"] == again["cvar_absolute"]
    with pytest.raises(ValueError):
        ValueAtRisk.stationary_bootstrap(returns, mean_block=0.5)


@pytest.mark.parametrize("kind", MUTATIONS)
def test_rolling_bootstrap_var_is_bit_causal(kind: str):
    rng = np.random.default_rng(15)
    returns = rng.normal(0.0, 0.01, 50)
    t = 35
    kwargs = {"window": 20, "n_paths": 80, "mean_block": 4.0, "seed": 3, "step": 1}
    base = rolling_stationary_bootstrap_var(returns, **kwargs)
    alt = rolling_stationary_bootstrap_var(perturb(returns, t, kind), **kwargs)
    assert_same_bits(base[: t + 1], alt[: t + 1])


@pytest.mark.parametrize("kind", MUTATIONS)
def test_autoencoder_is_bit_causal(kind: str):
    data = _panel(48, 3, seed=16)
    t = 32
    kwargs = {
        "latent_dim": 1, "min_train": 24, "window": 24, "refit_every": 12,
        "activation": "identity", "max_iter": 200, "random_state": 0,
    }
    base = rolling_autoencoder(data, **kwargs)
    alt = rolling_autoencoder(perturb(data, t, kind), **kwargs)
    assert_causal_prefix(base, alt, t)
    scored = np.isfinite(base.residual)
    if np.any(scored):
        np.testing.assert_allclose(
            (base.reconstruction + base.residual)[scored],
            data[scored],
            atol=1e-8,
        )
    assert base.eligible_for_live_trading is False


def test_spectral_peak_and_entropy_and_causality():
    t = np.arange(256)
    sine = np.sin(2.0 * np.pi * t / 16.0)
    noise = np.random.default_rng(17).normal(size=256)
    assert periodogram_peak(sine) == pytest.approx(16.0, abs=1.0)
    assert spectral_entropy(sine) < spectral_entropy(noise)
    rolled = rolling_spectral(sine, window=64)
    assert rolled.dominant_period[-1] == pytest.approx(16.0, abs=1.0)
    assert rolled.eligible_for_live_trading is False
    cut = 100
    for kind in MUTATIONS:
        alt = rolling_spectral(perturb(sine, cut, kind), window=64)
        assert_causal_prefix(rolled, alt, cut)


@pytest.mark.parametrize("kind", MUTATIONS)
def test_rolling_kelly_is_bit_causal(kind: str):
    rng = np.random.default_rng(18)
    returns = rng.normal(0.002, 0.01, 80)
    t = 50
    base = rolling_kelly(returns, window=20, fraction=0.5, cap=0.5)
    alt = rolling_kelly(perturb(returns, t, kind), window=20, fraction=0.5, cap=0.5)
    assert_same_bits(base[: t + 1], alt[: t + 1])
    assert np.nanmax(np.abs(base[np.isfinite(base)])) <= 0.5


def test_kelly_haircut_rejects_full_kelly_and_clips():
    with pytest.raises(ValueError):
        rolling_kelly(np.ones(10) * 0.01, window=5, fraction=1.0, cap=0.5)
    mu, sigma = 0.01, 0.02
    assert kelly_continuous(mu, sigma) == pytest.approx(mu / sigma**2)
    # Half-Kelly on a high-Sharpe window sits above the hard cap.
    rich = np.full(12, mu)
    rich = rich + np.linspace(-0.001, 0.001, 12)
    out = rolling_kelly(rich, window=6, fraction=0.5, cap=0.5)
    assert out[-1] == pytest.approx(0.5)
    poor = np.full(12, -0.01) + np.linspace(-0.001, 0.001, 12)
    negative = rolling_kelly(poor, window=6, fraction=0.5, cap=0.5, long_only=True)
    assert negative[-1] == pytest.approx(0.0)


def test_stat_arb_kalman_hyperparams_ignore_the_suffix():
    bars = synthetic_perp_pair(n=400, seed=11, half_life=8.0, resid_vol=3.5)
    cfg = PipelineConfig(warmup=200, entry_z=1.5, entry_cost_k=0.0)
    out = run_paper_pipeline(bars, cfg, source="synthetic")
    assert out["eligible_for_live_trading"] is False
    assert out["broker_orders_sent"] == 0
    assert out["signal"]["hedge"] == "kalman_posterior_frozen_at_entry"
    cut = int(out["signal"]["kalman_insample_end"])
    y = np.array([b.y_mid for b in bars])
    x = np.array([b.x_mid for b in bars])
    y2, x2 = perturb(y, cut - 1, "noise"), perturb(x, cut - 1, "noise", seed=4)
    # Keep marks positive so the bar builder's quotes stay on the same side of zero.
    y2 = np.maximum(y2, 1.0)
    x2 = np.maximum(x2, 1.0)
    ts = [b.ts_ms for b in bars]
    alt_bars, _ = bars_from_arrays(ts, y2, x2, half_spread_bps=cfg.half_spread_bps)
    alt = run_paper_pipeline(alt_bars, cfg, source="synthetic")
    assert alt["signal"]["kalman_delta"] == out["signal"]["kalman_delta"]
    assert alt["signal"]["kalman_obs_var"] == out["signal"]["kalman_obs_var"]
    assert alt["eligible_for_live_trading"] is False

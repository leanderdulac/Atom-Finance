"""Adversarial tests of chronology, causal features and net execution."""
from datetime import date, timedelta
from unittest.mock import patch
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sklearn.preprocessing import StandardScaler
from app.api.ml import ExperimentRequest, router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.models.research_validation import PurgedGroupWalkForward, build_features, evaluate_experiment, portfolio_metrics
from app.models.backtesting import BacktestEngine


def dataset(n=800):
    rng = np.random.default_rng(12)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    current, dates = date(2020, 1, 1), []
    while len(dates) < n:
        if current.weekday() < 5: dates.append(current.isoformat())
        current += timedelta(days=1)
    return prices.tolist(), dates


def test_purge_removes_overlapping_labels_without_gap():
    groups = np.repeat(np.arange(12), 30); times = np.arange(len(groups))
    for train, test in PurgedGroupWalkForward(3, 4, 0).split(groups, times, times + 40):
        assert max(times[train] + 40) < min(times[test])
        assert not set(groups[train]) & set(groups[test])


def test_whole_groups_and_embargo():
    groups = np.repeat(np.arange(15), 25); times = np.arange(len(groups))
    for train, test in PurgedGroupWalkForward(4, 6, 1).split(groups, times, times + 2):
        assert max(groups[train]) <= min(groups[test]) - 2
        for group in set(groups[test]):
            assert set(np.flatnonzero(groups == group)) <= set(test)
    with pytest.raises(ValueError, match='contiguous'):
        list(PurgedGroupWalkForward().split([1, 2, 1], [1, 2, 3], [2, 3, 4]))


def test_future_changes_cannot_change_past_features():
    prices, _ = dataset(); old, labels, times, vol = build_features(prices)
    changed = np.array(prices); changed[401:] *= 1.8
    new, _, _, new_vol = build_features(changed)
    np.testing.assert_array_equal(old[times <= 400], new[times <= 400])
    np.testing.assert_array_equal(vol[times <= 400], new_vol[times <= 400])
    np.testing.assert_allclose(labels, np.array(prices)[times + 2] / np.array(prices)[times + 1] - 1)


def test_flat_market_pays_entry_and_liquidation():
    result = portfolio_metrics([0, 0, 0], [1, 1, 1], 10)
    expected = (1 - 0.001) / (1 + 0.001)
    assert result['equity'][-1] == pytest.approx(expected)
    assert result['cost_paid_pct_initial'] == pytest.approx((1 - expected) * 100)
    assert result['turnover_total'] > 1.9
    assert result['net_return_pct'] < result['gross_return_pct'] == 0


def test_turnover_drift_and_risk_brake():
    result = portfolio_metrics([0.10, 0], [0.5, 0.5], 10)
    assert result['turnover_total'] > 1.0
    loss = portfolio_metrics([-0.30, 0.50, 0.50], [1, 1, 1], 0, 0.20)
    assert loss['drawdown_brake_triggered']
    assert loss['weights'] == [1, 0, 0]
    assert loss['max_drawdown_pct'] == pytest.approx(30)


def test_scaler_train_only_and_deterministic_report():
    prices, dates = dataset(); fits = []; original = StandardScaler.fit
    def record_fit(self, x, y=None, **kwargs):
        fits.append(x.copy()); return original(self, x, y, **kwargs)
    config = dict(model='ridge', hypothesis='Momentum must outperform costs and the zero forecast.', data_source='synthetic_demo', price_basis='unverified')
    with patch.object(StandardScaler, 'fit', record_fit):
        report = evaluate_experiment(prices, dates, **config)
    features, _, times, _ = build_features(prices)
    for fit, (train, test) in zip(fits, PurgedGroupWalkForward().split([dates[t][:7] for t in times], times, times + 2)):
        np.testing.assert_array_equal(fit, features[train])
        assert len(fit) < len(features)
    assert report == evaluate_experiment(prices, dates, **config)
    assert report['status'] == 'research_only'
    assert report['eligible_for_live_trading'] is False
    assert report['assessment'] == 'insufficient_evidence'
    assert any('sintéticos' in reason for reason in report['reasons'])
    for metric in report['results'].values():
        assert np.isfinite(metric['sharpe_net'])
        assert len(metric['equity']) == len(report['oos_dates']) + 1


def test_evaluate_accepts_date_objects():
    prices, dates = dataset()
    parsed = [date.fromisoformat(day) for day in dates]
    report = evaluate_experiment(
        prices, parsed, model='ridge',
        hypothesis='Economic hypothesis for a controlled unit test.',
        data_source='synthetic_demo', price_basis='unverified',
    )
    assert report['eligible_for_live_trading'] is False
    assert report['oos_dates'][0].count('-') == 2


def test_forest_and_baselines_compare_identical_periods():
    prices, dates = dataset()
    report = evaluate_experiment(prices, dates, model='random_forest', hypothesis='Economic hypothesis for unit test only.', data_source='synthetic_demo', price_basis='unverified')
    assert set(report['results']) == {'ridge', 'random_forest', 'zero', 'momentum', 'buy_hold'}
    assert report['results']['random_forest']['mse_oos'] >= 0
    assert len({len(m['equity']) for m in report['results'].values()}) == 1


def test_api_rejects_bad_data_and_legacy_predictions():
    prices, dates = dataset()
    base = dict(prices=prices, dates=dates, hypothesis='Economic hypothesis for a controlled unit test.', data_source='synthetic_demo')
    for update in ({'dates': dates[::-1]}, {'prices': [0] + prices[1:]}, {'dates': dates[:-1]}, {'hypothesis': 'LSTM'}, {'model': 'lstm'}, {'commission_bps': float('nan')}):
        with pytest.raises(ValueError): ExperimentRequest(**(base | update))
    app = FastAPI(); app.state.limiter = limiter; app.include_router(router, prefix='/api/ml'); client = TestClient(app)
    assert client.post('/api/ml/predict').status_code == 401
    app.dependency_overrides[get_current_user] = lambda: 'test'
    assert client.post('/api/ml/predict').status_code == 410
    assert client.get('/api/ml/policy').json()['eligible_for_live_trading'] is False
    response = client.post('/api/ml/evaluate', json=base)
    assert response.status_code == 200, response.text
    assert response.json()['eligible_for_live_trading'] is False


def test_backtest_lags_signal_and_reports_final_costs():
    prices = np.array([100., 100., 150., 150., 150.]); signals = np.array([0., 0., 1., 1., 1.])
    with patch.object(BacktestEngine, '_momentum', return_value=signals):
        result = BacktestEngine.run_strategy(prices, 'momentum', initial_capital=10000, commission=0.001, slippage=0.001)
    assert result['trades'][0]['day'] == 3
    assert result['trades'][-1]['reason'] == 'final_liquidation'
    assert result['performance']['total_return_pct'] < 0
    assert result['performance']['final_value'] == result['portfolio_values'][-1]
    assert result['performance']['transaction_costs'] > 0
    assert result['validation']['out_of_sample'] is False


def test_downsampled_equity_keeps_terminal_value():
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    result = BacktestEngine.run_strategy(prices, 'momentum', initial_capital=10_000)
    assert result['performance']['final_value'] == result['portfolio_values'][-1]
    assert result['buy_hold_values'][-1] == round(float(10_000 * prices[-1] / prices[0]), 2)


def test_sma_signal_uses_current_close():
    prices = np.concatenate([np.full(50, 100.0), np.full(20, 120.0)])
    signals = BacktestEngine._sma_crossover(prices, {"short_window": 5, "long_window": 20})
    assert signals[49] == 0
    assert signals[50] == 1
    result = BacktestEngine.run_strategy(prices, 'sma_crossover', params={"short_window": 5, "long_window": 20})
    assert result['trades'][0]['day'] == 51


def test_registered_ml_research_route():
    from main import app
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/ml/evaluate" in paths

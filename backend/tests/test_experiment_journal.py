from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.binance import router as binance_router
from app.api.ml import router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db import database, experiments


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, '_DB_PATH', str(tmp_path / 'journal.db'))
    app = FastAPI(); app.state.limiter = limiter
    app.include_router(router, prefix='/ml'); app.include_router(binance_router, prefix='/binance')
    app.dependency_overrides[get_current_user] = lambda: 'alice'
    return TestClient(app)

def inputs():
    from datetime import date, timedelta
    return dict(prices=[100 + i / 100 for i in range(500)], dates=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(500)],
                hypothesis='Momentum should survive transaction costs across different regimes.', data_source='synthetic_demo', model='ridge')

def test_journal_ownership_and_append_only_review(client):
    payload = inputs()
    with patch('app.api.ml.evaluate_experiment', return_value={'assessment': 'insufficient_evidence'}):
        response = client.post('/ml/evaluate', json=payload)
    assert response.status_code == 200
    run_id = response.json()['run_id']
    record = client.get(f'/ml/experiments/{run_id}').json()
    assert record['inputs']['prices'] == payload['prices']
    assert record['status'] == 'completed'
    for decision in ['discard', 'investigate']:
        assert client.post(f'/ml/experiments/{run_id}/reviews', json={'decision':decision,'rationale':'Independent data is required before further research.'}).status_code == 200
    assert len(client.get(f'/ml/experiments/{run_id}').json()['reviews']) == 2
    assert client.put(f'/ml/experiments/{run_id}', json={}).status_code == 405
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/ml/experiments').json()['total'] == 0
    assert client.get(f'/ml/experiments/{run_id}').status_code == 404
    assert client.post(f'/ml/experiments/{run_id}/reviews', json={'decision':'discard','rationale':'Trying to alter another researcher record.'}).status_code == 404

def test_failures_and_repeated_attempts_preserved(client):
    with patch('app.api.ml.evaluate_experiment', side_effect=ValueError('Insufficient temporal groups')):
        assert client.post('/ml/evaluate', json=inputs()).status_code == 422
        assert client.post('/ml/evaluate', json=inputs()).status_code == 422
    rows = client.get('/ml/experiments').json()
    assert rows['total'] == 2
    a,b = rows['items']
    assert a['id'] != b['id'] and a['input_hash'] == b['input_hash']
    assert a['status'] == b['status'] == 'failed'
    experiments.finish(a['id'], result={'overwrite': True})
    assert client.get(f"/ml/experiments/{a['id']}").json()['status'] == 'failed'

def test_exchange_routes_never_touch_private_account(client):
    with patch('app.api.binance.BinanceService.get_account_info', new_callable=AsyncMock) as account, patch('app.api.binance.BinanceService.get_futures_account', new_callable=AsyncMock) as futures, patch('app.api.binance.BinanceService.change_leverage', new_callable=AsyncMock) as leverage, patch('app.api.binance.BinanceService.calculate_kelly_sizing', new_callable=AsyncMock) as kelly:
        assert client.get('/binance/account').status_code == 410
        assert client.get('/binance/futures/account').status_code == 410
        assert client.post('/binance/futures/leverage', json={'symbol':'BTCUSDT','leverage':20}).status_code == 410
        assert client.post('/binance/kelly-sizing', json={'symbol':'BTCUSDT','win_prob':0.5,'payout_ratio':2}).status_code == 422
        for service in (account, futures, leverage, kelly): service.assert_not_called()
    client.app.dependency_overrides.clear()
    assert client.get('/binance/account').status_code == 401
    assert client.get('/ml/experiments').status_code == 401

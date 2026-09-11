from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.derivatives import router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db import database
from app.models.derivatives_planner import PlanRequest, make_plans

NOW = datetime(2026, 9, 8, 15, tzinfo=UTC)

def payload(direction='bullish'):
    kind = 'call' if direction == 'bullish' else 'put'
    strikes = [100,110] if kind == 'call' else [100,90]
    return dict(source='synthetic unit test', provenance='synthetic', as_of=NOW.isoformat(), capital=10000,
        fee_per_contract_side=0.05, theses=[dict(ticker='DEMO', spot=100, direction=direction,
        rationale='Hypothesis provided for synthetic scenario testing only.', entry=101 if kind=='call' else 99,
        invalidation=95 if kind=='call' else 105, target=115 if kind=='call' else 85, holding_days=15, events_checked=True,
        options=[dict(symbol=f'DEMO{i}', kind=kind, strike=k, expiry='2026-10-23', exercise='european',
                      bid=4.9 if i==0 else 1.9, ask=5 if i==0 else 2, bid_size=1000,ask_size=1000,multiplier=1,lot_size=1)
                 for i,k in enumerate(strikes)])])

@pytest.mark.parametrize('direction', ['bullish','bearish'])
def test_payoff_bounds_quantity_and_direction(direction):
    req = PlanRequest(**payload(direction)); report = make_plans(req, NOW)
    assert report['status'] == 'simulation'
    plan = report['plans'][0]
    assert plan['direction'] == ('long_bias' if direction=='bullish' else 'short_bias')
    assert plan['modeled_max_loss_brl'] <= 100
    assert plan['quantity_per_leg'] <= 1000
    assert report['eligible_for_live_trading'] is False
    assert plan['legs'][0]['side'] == 'buy'
    assert plan['expiry'] == '2026-10-23'
    assert plan['close_by'] == '2026-09-23'
    assert all(p['net_pnl_brl'] >= -plan['modeled_max_loss_brl'] - .01 for p in plan['payoff_at_expiry'])
    if plan['modeled_max_profit_brl'] is not None:
        assert all(p['net_pnl_brl'] <= plan['modeled_max_profit_brl'] + .01 for p in plan['payoff_at_expiry'])

def test_spread_uses_ask_buy_bid_sell_exact_fees():
    data=payload(); data['theses'][0]['options'][1].update(bid=4.0, ask=4.1)
    report=make_plans(PlanRequest(**data), NOW); plan=report['plans'][0]
    assert plan['strategy']=='bull_call_spread'
    assert plan['entry']['max_net_debit_per_unit']==1.0
    assert plan['breakeven_at_expiry']==101.2
    assert plan['modeled_max_loss_brl']==round(plan['quantity_per_leg']*1.2,2)

@pytest.mark.parametrize('mutation', ['stale','future','events','no_book','wide_spread','expiry','risk','invalidated','lot'])
def test_no_trade_when_constraints_fail(mutation):
    data=payload(); t=data['theses'][0]
    if mutation=='stale': data['as_of']=(NOW-timedelta(minutes=16)).isoformat()
    if mutation=='future': data['as_of']=(NOW+timedelta(minutes=2)).isoformat()
    if mutation=='events': t['events_checked']=False
    if mutation=='no_book':
        for q in t['options']: q['bid_size']=0
    if mutation=='wide_spread':
        for q in t['options']: q['bid']=.1
    if mutation=='expiry':
        for q in t['options']: q['expiry']='2026-09-25'
    if mutation=='risk': data['existing_risk_brl']=300
    if mutation=='invalidated': t['spot']=94
    if mutation=='lot':
        for q in t['options']: q['lot_size']=10000
    report=make_plans(PlanRequest(**data), NOW)
    assert report['status']=='no_trade' and report['rejected']

def test_american_short_excluded_and_no_contract_invented():
    data=payload()
    for q in data['theses'][0]['options']: q['exercise']='american'
    report=make_plans(PlanRequest(**data), NOW)
    assert report['plans']
    assert all(leg['side']=='buy' for p in report['plans'] for leg in p['legs'])
    assert {leg['symbol'] for p in report['plans'] for leg in p['legs']} <= {'DEMO0','DEMO1'}

def test_aggregate_risk_and_units():
    data=payload();data['total_risk_pct']=1;data['existing_risk_brl']=20
    t=dict(data['theses'][0]);t['ticker']='OTHER'; t['options']=[dict(q,symbol=q['symbol']+'X') for q in t['options']]
    data['theses'].append(t)
    report=make_plans(PlanRequest(**data),NOW)
    assert report['allocated_risk_brl'] <= 80
    data=payload()
    for q in data['theses'][0]['options']: q['multiplier']=100
    assert make_plans(PlanRequest(**data),NOW)['status']=='no_trade'

def test_schema_rejects_ambiguous_or_invalid_data():
    data=payload();data['as_of']='2026-09-08T15:00:00'
    with pytest.raises(ValueError): PlanRequest(**data)
    data=payload();data['theses'][0]['target']=80
    with pytest.raises(ValueError): PlanRequest(**data)
    data=payload();data['theses'][0]['options'][0]['bid']=10
    with pytest.raises(ValueError): PlanRequest(**data)

def test_saved_plan_owner_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(database,'_DB_PATH',str(tmp_path/'plans.db'))
    app=FastAPI();app.state.limiter=limiter;app.include_router(router,prefix='/derivatives')
    client=TestClient(app)
    assert client.get('/derivatives/plans').status_code==401
    app.dependency_overrides[get_current_user]=lambda:'alice'
    data=payload();data['as_of']=datetime.now(UTC).isoformat()
    response=client.post('/derivatives/plan',json=data)
    assert response.status_code==200
    run_id=response.json()['id']
    record=client.get('/derivatives/plans/'+run_id).json()
    assert record['inputs']['theses'][0]['rationale']==data['theses'][0]['rationale']
    app.dependency_overrides[get_current_user]=lambda:'bob'
    assert client.get('/derivatives/plans/'+run_id).status_code==404
    assert client.get('/derivatives/plans').json()==[]

def test_legacy_scanner_retired_without_model_call():
    from unittest.mock import AsyncMock, patch

    from app.api.options_api import router as old_router
    app=FastAPI();app.include_router(old_router)
    client=TestClient(app)
    assert client.post('/scan',json={}).status_code==401
    app.dependency_overrides[get_current_user]=lambda:'alice'
    with patch('app.api.options_api.OptionsExpert.scan_market', new_callable=AsyncMock) as scan:
        assert client.post('/scan',json={}).status_code==410
        scan.assert_not_called()

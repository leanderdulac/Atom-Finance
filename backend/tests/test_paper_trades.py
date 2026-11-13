import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.derivatives import save
from app.api.paper_trades import flatten_open_trades, router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.models.derivatives_planner import PlanRequest, make_plans


@pytest.fixture
def client():
    limiter.reset()
    app = FastAPI(); app.state.limiter = limiter
    app.include_router(router, prefix='/paper')
    app.dependency_overrides[get_current_user] = lambda:'alice'
    return TestClient(app)


def plan(total_risk=3):
    now = datetime.now(UTC)
    req = PlanRequest(source='Synthetic test data', provenance='synthetic', as_of=now, capital=10000,
        total_risk_pct=total_risk, theses=[dict(ticker='DEMO',spot=100,direction='bullish',
        rationale='Synthetic trend for an isolated test of the lifecycle.',entry=101,invalidation=95,target=115,
        holding_days=15,events_checked=True,options=[dict(symbol=f'DEMOC{k}',kind='call',strike=k,
        expiry=(now+timedelta(days=50)).date(),exercise='european',bid=b,ask=a,bid_size=1000,ask_size=1000,multiplier=1,lot_size=1)
        for k,b,a in [(100,4.9,5),(110,4,4.1)]] )])
    return asyncio.run(save('alice',req,make_plans(req)))


def tracked(client, total_risk=3):
    saved=plan(total_risk)
    response=client.post('/paper',json={'plan_id':saved['id'],'plan_index':0})
    assert response.status_code==201
    return response.json()


def event(action='open', **changes):
    return dict(request_id=str(uuid4()),action=action,as_of=datetime.now(UTC).isoformat(),
                source='Synthetic test book',note='Test observation; no market order.',underlying=101,
                quotes=[dict(symbol='DEMOC100',bid=4.9,ask=5,bid_size=1000,ask_size=1000),
                        dict(symbol='DEMOC110',bid=4,ask=4.1,bid_size=1000,ask_size=1000)]) | changes


def send(client, trade, payload):
    return client.post(f"/paper/{trade['id']}/events",json=payload)


def test_spread_lifecycle_costs_and_immutability(client):
    trade=tracked(client)
    assert trade['status']=='watching' and not trade['events']
    assert trade['plan']['strategy']=='bull_call_spread'
    opened=send(client,trade,event()).json()
    assert opened['status']=='open'
    qty=opened['plan']['quantity_per_leg']
    assert opened['events'][0]['result']['entry_debit_brl']==qty
    mark=event('mark')
    mark['quotes'][0].update(bid=6,ask=6.1)
    mark['quotes'][1].update(bid=3.9,ask=4)
    marked=send(client,trade,mark).json()
    # Entry: 5 - 4 = 1; exit: 6 - 4 = 2; four side fees of 0.05.
    assert marked['events'][-1]['result']['net_pnl_brl']==round(qty*.8,2)
    closed=send(client,trade,mark | dict(action='close',request_id=str(uuid4()))).json()
    assert closed['status']=='closed' and closed['eligible_for_live_trading'] is False
    assert closed['events'][-1]['result']['pnl_kind']=='realized_simulated'
    assert send(client,trade,event('mark')).status_code==409
    assert client.delete(f"/paper/{trade['id']}").status_code==405


def test_idempotency_and_private_records(client):
    trade=tracked(client);payload=event()
    first=send(client,trade,payload).json()
    repeated=send(client,trade,payload).json()
    assert len(first['events'])==len(repeated['events'])==1
    assert send(client,trade,payload | {'note':'Different data under the same request id.'}).status_code==409
    again=client.post('/paper',json={'plan_id':trade['plan_id'],'plan_index':0}).json()
    assert again['id']==trade['id']
    client.app.dependency_overrides[get_current_user]=lambda:'bob'
    assert client.get('/paper').json()==[]
    assert client.get(f"/paper/{trade['id']}").status_code==404
    assert send(client,trade,event()).status_code==404
    assert client.post('/paper',json={'plan_id':trade['plan_id'],'plan_index':0}).status_code==404


def test_gate_trigger_price_liquidity_and_timestamp(client):
    trade=tracked(client)
    assert send(client,trade,event(underlying=100)).status_code==422
    assert send(client,trade,event(underlying=115)).status_code==422
    assert send(client,trade,event(as_of=(datetime.now(UTC)-timedelta(minutes=16)).isoformat())).status_code==422
    high=event();high['quotes'][0]['ask']=6
    assert send(client,trade,high).status_code==422
    thin=event();thin['quotes'][0]['ask_size']=0
    assert send(client,trade,thin).status_code==422
    missing=event();missing['quotes'].pop()
    assert send(client,trade,missing).status_code==422
    assert not client.get(f"/paper/{trade['id']}").json()['events']


def test_aggregate_risk_includes_other_open_paper_positions(client):
    one=tracked(client,1);two=tracked(client,1)
    assert send(client,one,event()).status_code==200
    denied=send(client,two,event())
    assert denied.status_code==422 and 'agregado' in denied.json()['detail']
    assert send(client,one,event('close')).status_code==200
    assert send(client,two,event()).status_code==200


def test_cancel_and_auth_boundary(client):
    trade=tracked(client)
    assert send(client,trade,event('cancel',quotes=[])).json()['status']=='cancelled'
    assert send(client,trade,event()).status_code==409
    client.app.dependency_overrides.clear()
    assert client.get('/paper').status_code==401


def test_long_option_and_multiplier_accounting(client):
    saved=plan()
    # A separate immutable plan with one purchased contract leg, quoted per unit.
    async def _rewrite_plan():
        report=saved.copy();p=report['plans'][0].copy()
        p.update(strategy='long_call',legs=[dict(symbol='DEMOC100',side='buy',quantity=2,limit_reference=5)],
                 quantity_per_leg=2,multiplier=10)
        p['entry']=p['entry'] | {'max_net_debit_per_unit':5}
        report['plans']=[p]
        pool = await get_pool()
        await pool.execute('UPDATE derivative_plans SET result=$1 WHERE id=$2', report, saved['id'])
    asyncio.run(_rewrite_plan())
    trade=client.post('/paper',json={'plan_id':saved['id'],'plan_index':0}).json()
    entry=event();entry['quotes']=entry['quotes'][:1]
    assert send(client,trade,entry).json()['events'][0]['result']['entry_debit_brl']==100
    out=event('close');out['quotes']=out['quotes'][:1];out['quotes'][0].update(bid=6,ask=6.1)
    assert send(client,trade,out).json()['events'][-1]['result']['net_pnl_brl']==19.8


def test_regime_kill_flattens_open_paper(client):
    trade = tracked(client)
    opened = send(client, trade, event()).json()
    assert opened['status'] == 'open'
    out = asyncio.run(flatten_open_trades('alice', reason='test_crisis'))
    assert out['broker_orders_sent'] == 0
    assert out['eligible_for_live_trading'] is False
    assert trade['id'] in out['closed']
    rec = client.get(f"/paper/{trade['id']}").json()
    assert rec['status'] == 'closed'
    assert rec['events'][-1]['result']['flatten'] == 'regime_kill'


def test_operations_state_tracks_bands_fill_alerts_and_budget(client):
    trade = tracked(client)
    snap = client.get('/paper/operations').json()
    assert snap['aggregate'] == {'open_count': 0, 'watching_count': 1, 'reserved_risk_brl': 0.0}
    row = snap['trades'][0]
    assert row['id'] == trade['id'] and row['status'] == 'watching'
    assert row['ticker'] == 'DEMO' and row['direction'] == 'long_bias'
    assert row['entry']['trigger'] == 101 and row['entry']['comparison'] == '>='
    assert row['exit']['invalidation'] == 95 and row['exit']['target'] == 115
    assert row['last'] is None and row['reserved_risk_brl'] is None
    assert row['eligible_for_live_trading'] is False

    opened: dict = send(client, trade, event()).json()
    snap = client.get('/paper/operations').json()
    assert snap['aggregate']['open_count'] == 1 and snap['aggregate']['watching_count'] == 0
    assert snap['aggregate']['reserved_risk_brl'] == opened['events'][0]['result']['reserved_risk_brl']
    row = next(r for r in snap['trades'] if r['id'] == trade['id'])
    assert row['entry']['filled'] is True
    assert row['entry']['debit_brl'] == opened['events'][0]['result']['entry_debit_brl']
    assert row['reserved_risk_brl'] == opened['events'][0]['result']['reserved_risk_brl']
    assert row['last']['kind'] == 'open' and row['last']['underlying'] == 101
    assert row['risk_budget_brl'] == 300.0  # capital 10000 × total_risk 3% (helper do branch)

    mark: dict = event('mark')
    mark['quotes'][0].update(bid=6, ask=6.1)
    mark['quotes'][1].update(bid=3.9, ask=4)
    marked: dict = send(client, trade, mark).json()
    snap = client.get('/paper/operations').json()
    row = next(r for r in snap['trades'] if r['id'] == trade['id'])
    assert row['last']['kind'] == 'mark'
    assert row['last']['net_pnl_brl'] == marked['events'][-1]['result']['net_pnl_brl']
    # invalidação abaixo do gatilho de alta dispara o alerta da tese
    invalidated = send(client, trade, event('mark', underlying=94, request_id=str(uuid4())))
    assert invalidated.status_code == 200
    row = next(r for r in client.get('/paper/operations').json()['trades'] if r['id'] == trade['id'])
    assert any('invalidada' in a for a in row['last']['alerts'])

    # fronteira de usuário: bob não vê nada de alice
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/paper/operations').json()['trades'] == []
    client.app.dependency_overrides[get_current_user] = lambda: 'alice'
    assert client.get('/paper/operations').status_code == 200

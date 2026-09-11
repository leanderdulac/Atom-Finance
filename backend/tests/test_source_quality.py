from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api import market_sources
from app.core.security import get_current_user
from app.services.source_quality import assess

from .test_paper_trades import client, tracked  # noqa: F401 — `client` is a pytest fixture


def snapshot(trade, now=None):
    now=now or datetime.now(UTC)
    plan=trade['plan']
    return {'snapshot_id':str(uuid4()),'provider':'oplab','ticker':plan['ticker'],
            'data_mode':'unverified','fetched_at':now.isoformat(),'blockers':['Licença pendente.'],
            'contracts':[dict(symbol=leg['symbol'],kind=leg['kind'],strike=leg['strike'],
                expiry=plan['expiry'],exercise=leg['exercise'],multiplier=plan['multiplier'],
                lot_size=plan['lot_size'],bid=4,ask=5,bid_size=1000,ask_size=1000,
                observed_at=now.isoformat()) for leg in plan['legs']]}


def test_clean_structure_never_certifies_feed_or_synthetic_plan(client):
    trade=tracked(client);data=snapshot(trade)
    report=assess(trade,data)
    assert all(l['structural_checks_passed'] for l in report['legs'])
    assert not report['eligible_for_observation'] and not report['eligible_for_live_trading']
    assert any('fictício' in b for b in report['blockers'])
    assert any('Latência' in b for b in report['blockers'])


def test_original_time_not_replaced_by_fetch_time_and_eod_remains_blocked(client):
    trade=tracked(client);now=datetime.now(UTC);data=snapshot(trade,now)
    data['data_mode']='eod'
    old=(now-timedelta(days=1)).isoformat()
    data['contracts'][0]['observed_at']=old
    report=assess(trade,data,now)
    assert report['legs'][0]['observed_at']==old
    assert report['legs'][0]['age_seconds']==86400
    assert any('15 minutos' in issue for issue in report['legs'][0]['issues'])
    assert any('fechamento' in issue for issue in report['blockers'])


@pytest.mark.parametrize('change,expected',[
    ({'observed_at':None},'Horário'),
    ({'observed_at':'2035-01-01T00:00:00+00:00'},'futuro'),
    ({'observed_at':'2026-09-10T12:00:00'},'Horário'),
    ({'bid':6,'ask':5},'Livro'),
    ({'ask':None},'Livro'),
    ({'ask_size':0},'Quantidade'),
    ({'ask_size':1000.5},'Quantidade'),
    ({'multiplier':None,'lot_reported':100},'multiplicador'),
    ({'lot_size':None,'lot_reported':100},'lote de negociação'),
    ({'strike':999},'preço de exercício'),
    ({'expiry':'2030-01-01'},'vencimento'),
])
def test_contract_defects_fail_closed(client,change,expected):
    trade=tracked(client);data=snapshot(trade);data['contracts'][0].update(change)
    report=assess(trade,data)
    assert any(expected in issue for issue in report['legs'][0]['issues'])
    assert not report['legs'][0]['structural_checks_passed']


def test_missing_duplicate_ticker_and_liquidation_side(client):
    trade=tracked(client);data=snapshot(trade)
    data['contracts']=[data['contracts'][0]]*2;data['ticker']='OTHER'
    result=assess(trade,data)
    assert 'duplicado' in result['legs'][0]['issues'][0]
    assert 'ausente' in result['legs'][1]['issues'][0]
    assert any('ação do snapshot' in b for b in result['blockers'])
    data=snapshot(trade);data['contracts'][0]['bid_size']=0
    assert assess(trade,data)['legs'][0]['structural_checks_passed']
    trade['status']='open'
    assert any('Quantidade' in i for i in assess(trade,data)['legs'][0]['issues'])


def test_api_is_owner_scoped_read_only_and_list_omits_raw(client):
    client.app.include_router(market_sources.router,prefix='/sources')
    trade=tracked(client)
    own=market_sources.save('alice',snapshot(trade))
    other=market_sources.save('bob',snapshot(trade))
    path=f"/paper/{trade['id']}/source-check/"
    before=client.get('/paper/'+trade['id']).json()
    response=client.get(path+own['snapshot_id'])
    assert response.status_code==200,response.text
    assert response.json()['snapshot_id']==own['snapshot_id']
    assert client.get('/paper/'+trade['id']).json()==before
    assert client.get(path+other['snapshot_id']).status_code==404
    listed=client.get('/sources/snapshots?ticker=DEMO').json()
    assert [row['snapshot_id'] for row in listed]==[own['snapshot_id']]
    assert 'contracts' not in listed[0] and 'raw' not in listed[0]
    assert client.get('/sources/snapshots?ticker=OTHER').json()==[]
    client.app.dependency_overrides[get_current_user]=lambda:'bob'
    assert client.get(path+other['snapshot_id']).status_code==404
    client.app.dependency_overrides.clear()
    assert client.get(path+own['snapshot_id']).status_code==401

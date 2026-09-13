import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.market_sources import router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.services import market_sources as sources


@pytest.fixture
def client():
    app=FastAPI();app.state.limiter=limiter;app.include_router(router,prefix='/sources')
    app.dependency_overrides[get_current_user]=lambda:'alice'
    return TestClient(app)

def test_eod_is_not_relabelled_live_and_snapshot_is_private(client):
    original={'series':[{'symbol':'PETRJ100','side':'call','strike':30,'expirationDate':'2026-10-16',
        'optionStyle':'european','date':1788490800,'bid':1.0,'ask':1.1,'close':1.05,'volume':1000,'allocationRoundLot':100}]}
    with patch.object(sources,'get_json',AsyncMock(return_value=original)):
        response=client.get('/sources/chain?provider=brapi&ticker=PETR4&expiry=2026-10-16')
    assert response.status_code==200,response.text
    data=response.json();q=data['contracts'][0]
    assert data['data_mode']=='eod' and data['eligible_for_planning'] is False
    assert q['observed_at']!=data['fetched_at']
    assert q['bid_size'] is None and q['multiplier'] is None
    assert data['raw']==original
    assert client.get('/sources/snapshots/'+data['snapshot_id']).status_code==200
    client.app.dependency_overrides[get_current_user]=lambda:'bob'
    assert client.get('/sources/snapshots/'+data['snapshot_id']).status_code==404

@pytest.mark.parametrize('provider',['oplab','cedro'])
def test_personal_credentials_do_not_leak_or_cross_accounts(client,monkeypatch,provider):
    key='OPLAB_ACCESS_TOKEN' if provider=='oplab' else 'CEDRO_SESSION_COOKIE'
    monkeypatch.setenv(key,'secret-not-for-clients');monkeypatch.setenv(provider.upper()+'_OWNER','bob')
    with patch.object(sources,'get_json',AsyncMock()) as upstream:
        assert client.get(f'/sources/chain?provider={provider}&ticker=PETR4').status_code==403
        upstream.assert_not_called()
    assert 'secret-not-for-clients' not in client.get('/sources/status').text
    assert client.get('/sources/status').json()[provider]['configured'] is False

def test_oplab_preserves_missing_units_and_declares_unverified(client,monkeypatch):
    monkeypatch.setenv('OPLAB_ACCESS_TOKEN','test-token');monkeypatch.setenv('OPLAB_OWNER','alice')
    row={'symbol':'PETRJ100','category':'CALL','strike':30,'due_date':'2026-10-16','contract_size':100,'time':1788490800000,'bid_volume':0,'ask_volume':5}
    with patch.object(sources,'get_json',AsyncMock(return_value=[row])) as upstream:
        data=client.get('/sources/chain?provider=oplab&ticker=PETR4').json()
        assert upstream.call_args.kwargs['headers']=={'Access-Token':'test-token'}
    assert data['contracts'][0]['bid_size']==0
    assert data['contracts'][0]['ask'] is None
    assert data['contracts'][0]['multiplier'] is None
    assert data['data_mode']=='unverified'

def test_selic_daily_unit_and_cvm_safe_resource_links(client):
    with patch.object(sources,'get_json',AsyncMock(return_value=[{'data':'08/09/2026','valor':'0.05'}])):
        data=client.get('/sources/selic').json()
    assert data['unit']=='percent_per_business_day' and data['value']==.05
    assert data['annualized_252_pct']==pytest.approx(((1+.05/100)**252-1)*100,abs=1e-6)
    raw={'success':True,'result':{'name':'itr','resources':[{'url':'https://evil.test/private'},{'url':'https://dados.cvm.gov.br/dados/itr.zip','name':'ITR','format':'ZIP'}]}}
    with patch.object(sources,'get_json',AsyncMock(return_value=raw)):
        data=client.get('/sources/cvm').json()
    assert len(data['resources'])==1

def test_auth_ticker_validation_and_sanitized_error(client):
    assert client.get('/sources/chain?provider=brapi&ticker=..%2Fsecret').status_code==422
    with patch.object(sources,'get_json',AsyncMock(side_effect=sources.SourceError(503,'Limite atingido.'))):
        response=client.get('/sources/selic')
        assert response.status_code==503
    client.app.dependency_overrides.clear()
    assert client.get('/sources/selic').status_code==401

@pytest.mark.parametrize('code',[302,401,429,500])
def test_upstream_errors_do_not_expose_body_or_follow_redirects(code):
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(code,json={'secret':'do-not-show'},headers={'Location':'https://evil.test'}))
    def factory(**kwargs):return original(transport=transport,**kwargs)
    with patch.object(sources.httpx,'AsyncClient',factory):
        with pytest.raises(sources.SourceError) as error:
            asyncio.run(sources.get_json('https://brapi.dev/api/v2/options/chain'))
    assert 'do-not-show' not in error.value.message

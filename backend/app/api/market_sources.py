"""Owner-scoped, read-only source integration endpoints."""
import os
from datetime import date, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.services import market_sources as sources

router=APIRouter(dependencies=[Depends(get_current_user)])

async def save(owner,data):
    run_id=str(uuid4());data['snapshot_id']=run_id
    pool = await get_pool()
    await pool.execute(
        'INSERT INTO source_snapshots (id, owner, provider, created_at, payload) VALUES ($1,$2,$3,$4,$5)',
        run_id, owner, data['provider'], datetime.fromisoformat(data['fetched_at']), data,
    )
    return data

async def call(task):
    try: return await task
    except sources.SourceError as exc: raise HTTPException(exc.status,exc.message) from None

@router.get('/status')
def status(owner: str=Depends(get_current_user)):
    return {'tradier':{'configured':sources.configured('TRADIER_ACCESS_TOKEN') and os.getenv('TRADIER_OWNER','').strip()==owner,'access':'US equities/options','data_mode':'delayed' if os.getenv('TRADIER_ENV','sandbox')=='sandbox' else 'account_dependent'},'yfinance':{'access':'public','data_mode':'unverified'},'brapi':{'configured':sources.configured('BRAPI_TOKEN'),'access':'PETR4 sem token; demais ativos dependem do plano','data_mode':'eod'},
            'oplab':{'configured':sources.configured('OPLAB_ACCESS_TOKEN') and os.getenv('OPLAB_OWNER')==owner,'data_mode':'unverified'},
            'cedro':{'configured':sources.configured('CEDRO_SESSION_COOKIE') and os.getenv('CEDRO_OWNER')==owner,'data_mode':'unverified'},
            'bcb':{'access':'public'},'cvm':{'access':'public_catalog'},'b3_up2data':{'access':'requires_contract','implemented':False}}

@router.get('/expirations')
@limiter.limit('15/minute')
async def expirations(request:Request,ticker:str=Query(pattern=r'^[A-Z]{4}[0-9]{1,2}$')):
    return await call(sources.expirations(ticker))

@router.get('/chain')
@limiter.limit('10/minute')
async def chain(request:Request,provider:Literal['brapi','oplab','cedro'],ticker:str=Query(pattern=r'^[A-Z]{4}[0-9]{1,2}$'),expiry:date|None=None,owner:str=Depends(get_current_user)):
    data=await call(sources.chain(provider,ticker,expiry.isoformat() if expiry else None,owner))
    return await save(owner,data)

@router.get('/snapshots')
async def snapshots(ticker: str = Query(min_length=1, max_length=30), owner: str = Depends(get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id,provider,created_at,payload FROM source_snapshots "
        "WHERE owner=$1 AND (payload ->> 'ticker')=$2 ORDER BY created_at DESC LIMIT 20",
        owner, ticker,
    )
    return [{'snapshot_id':row['id'], 'provider':row['provider'], 'fetched_at':row['created_at'],
             'data_mode':row['payload'].get('data_mode', 'unverified')} for row in rows]


@router.get('/snapshots/{run_id}')
async def snapshot(run_id:str,owner:str=Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow('SELECT payload FROM source_snapshots WHERE id=$1 AND owner=$2',run_id,owner)
    if row is None: raise HTTPException(404,'Snapshot não encontrado.')
    return row['payload']

@router.get('/selic')
@limiter.limit('10/minute')
async def selic(request:Request): return await call(sources.selic())

@router.get('/cvm')
@limiter.limit('10/minute')
async def cvm(request:Request,kind:Literal['itr','dfp']='itr'): return await call(sources.cvm_catalog(kind))


@router.get('/quote')
@limiter.limit('20/minute')
async def latest_quote(request: Request, provider: Literal['yfinance','tradier'],
                       symbol: str = Query(min_length=1,max_length=25), owner: str = Depends(get_current_user)):
    from app.services.live_quotes import quote
    return await call(quote(provider,symbol.strip().upper(),owner))

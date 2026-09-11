"""Provider-based latest quotes, inspired by OpenBB's connector architecture.

Independent implementation: Yahoo via yfinance and Tradier's documented REST API.
Polling is not an exchange stream; feed entitlement and quote age are distinct.
"""
import asyncio
import os
import re
from datetime import UTC, datetime

from app.services.market_sources import SourceError, get_json, number, timestamp

_yahoo_slots = asyncio.Semaphore(2)


def yahoo_info(symbol):
    import yfinance as yf
    return yf.Ticker(symbol).get_info()


def health(row, now):
    fields = ('last_timestamp', 'bid_timestamp', 'ask_timestamp')
    ages = {field: (now-datetime.fromisoformat(row[field])).total_seconds() if row[field] else None for field in fields}
    row['age_seconds'] = ages
    row['last_status'] = ('unknown' if ages['last_timestamp'] is None else
                          'future' if ages['last_timestamp'] < -60 else
                          'stale' if ages['last_timestamp'] > 60 else 'recent')
    row['book_status'] = ('invalid' if row['bid'] is None or row['ask'] is None or row['bid'] < 0 or row['ask'] <= 0 or row['bid'] > row['ask'] else
                          'unknown_time' if any(ages[f] is None for f in fields[1:]) else
                          'recent' if all(-60 <= ages[f] <= 60 for f in fields[1:]) else 'stale_or_future')
    return row


async def quote(provider, symbol, owner):
    if provider == 'yfinance':
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-^=]{0,24}', symbol):
            raise SourceError(422, 'Símbolo Yahoo inválido. Para B3, use o sufixo .SA, como PETR4.SA.')
        try:
            async with _yahoo_slots:
                raw = await asyncio.to_thread(yahoo_info, symbol)
        except Exception:
            raise SourceError(502, 'Yahoo indisponível, limite atingido ou símbolo não encontrado.') from None
        if not isinstance(raw, dict) or raw.get('symbol', '').upper() != symbol:
            raise SourceError(502, 'Yahoo retornou um símbolo ausente ou diferente.')
        row = {'symbol':symbol, 'currency':raw.get('currency'), 'exchange':raw.get('exchange'),
               'asset_type':raw.get('quoteType'), 'last':number(raw.get('regularMarketPrice')),
               'bid':number(raw.get('bid')), 'ask':number(raw.get('ask')),
               'bid_size_reported':number(raw.get('bidSize')), 'ask_size_reported':number(raw.get('askSize')),
               'last_timestamp':timestamp(raw.get('regularMarketTime')), 'bid_timestamp':None, 'ask_timestamp':None}
        mode='delayed' if (number(raw.get('exchangeDataDelayedBy')) or 0)>0 else 'unverified'
        delay=number(raw.get('exchangeDataDelayedBy'))
        note='Yahoo não oferece garantia de tempo real neste conector. Bid/ask não têm horário individual confirmado.'
        environment='public'
    elif provider == 'tradier':
        if not re.fullmatch(r'[A-Z]{1,6}(?:/[A-Z])?(?:\d{6}[CP]\d{8})?', symbol):
            raise SourceError(422, 'Tradier aceita símbolos dos EUA ou opções OCC; não use tickers B3/.SA.')
        if os.getenv('TRADIER_OWNER','').strip() != owner:
            raise SourceError(403, 'Conector Tradier não autorizado para este usuário ATOM.')
        token=os.getenv('TRADIER_ACCESS_TOKEN','').strip()
        if not token:
            raise SourceError(503, 'Configure TRADIER_ACCESS_TOKEN no servidor.')
        environment=os.getenv('TRADIER_ENV','sandbox')
        if environment not in ('sandbox','live'):
            raise SourceError(503, 'TRADIER_ENV deve ser sandbox ou live.')
        base='https://api.tradier.com' if environment=='live' else 'https://sandbox.tradier.com'
        raw=await get_json(base+'/v1/markets/quotes',params={'symbols':symbol,'greeks':'false'},
                           headers={'Authorization':f'Bearer {token}','Accept':'application/json'})
        data=raw.get('quotes',{}).get('quote') if isinstance(raw,dict) and isinstance(raw.get('quotes'),dict) else None
        if isinstance(data,list): data=data[0] if len(data)==1 else None
        if not isinstance(data,dict) or data.get('symbol')!=symbol:
            raise SourceError(502, 'Tradier retornou cotação ausente, ambígua ou de outro símbolo.')
        row={'symbol':symbol,'currency':'USD','exchange':data.get('exch'),'asset_type':data.get('type'),
             'last':number(data.get('last')),'bid':number(data.get('bid')),'ask':number(data.get('ask')),
             'bid_size_reported':number(data.get('bidsize')),'ask_size_reported':number(data.get('asksize')),
             'last_timestamp':timestamp(data.get('trade_date'),milliseconds=True),
             'bid_timestamp':timestamp(data.get('bid_date'),milliseconds=True),
             'ask_timestamp':timestamp(data.get('ask_date'),milliseconds=True)}
        mode='realtime' if environment=='live' else 'delayed'
        delay=0 if environment=='live' else 15
        note='Feed Tradier dos EUA; acesso real depende da conta autorizada. A idade de cada preço permanece visível, inclusive fora do pregão.'
    else:
        raise SourceError(422, 'Provedor não suportado.')
    if row['last'] is None and row['bid'] is None and row['ask'] is None:
        raise SourceError(502, 'Fonte não retornou preços utilizáveis.')
    now=datetime.now(UTC)
    return {'provider':provider,'environment':environment,'data_mode':mode,'delay_minutes_reported':delay,
            'fetched_at':now.isoformat(),'quote':health(row,now),'note':note,
            'transport':'rest_snapshot','eligible_for_planning':False,'eligible_for_live_trading':False,
            'size_unit':'provider_reported_not_reconciled'}

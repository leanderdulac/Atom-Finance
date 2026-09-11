"""Read-only upstream adapters. Observation time is never replaced by retrieval time."""
import json
import math
import os
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx


class SourceError(Exception):
    def __init__(self, status, message): self.status=status; self.message=message

async def get_json(url, *, params=None, headers=None):
    # Fixed URLs selected by adapters, no user-controlled origin or redirects.
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            async with client.stream('GET', url, params=params, headers=headers) as response:
                if response.status_code in (401,403): raise SourceError(424, 'A fonte recusou o acesso. Confira credencial, plano e permissões no servidor.')
                if response.status_code == 429: raise SourceError(503, 'Limite da fonte atingido. Tente novamente mais tarde.')
                if response.status_code != 200: raise SourceError(502, 'A fonte não retornou os dados solicitados.')
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>8_000_000: raise SourceError(502, 'Resposta excedeu o limite de tamanho.')
                return json.loads(body)
    except SourceError: raise
    except (httpx.HTTPError, ValueError): raise SourceError(502, 'Fonte indisponível ou resposta inválida.') from None

def configured(name): return bool(os.getenv(name, '').strip())

def licensed_headers(provider, owner):
    # Personal subscription data must not be shared with other ATOM accounts.
    if os.getenv(f'{provider}_OWNER', '').strip() != owner:
        raise SourceError(403, 'Este conector exige um usuário autorizado configurado no servidor.')
    variable = 'OPLAB_ACCESS_TOKEN' if provider=='OPLAB' else 'CEDRO_SESSION_COOKIE'
    if not configured(variable): raise SourceError(503, f'{provider}: credencial não configurada no servidor.')
    return {'Access-Token' if provider=='OPLAB' else 'Cookie': os.environ[variable]}

def number(value):
    if value is None or isinstance(value, bool): return None
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError): return None

def timestamp(value, *, milliseconds=False):
    try:
        if isinstance(value,(int,float)) and value>0:
            return datetime.fromtimestamp(value/(1000 if milliseconds else 1),UTC).isoformat()
        if isinstance(value,str):
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.isoformat() if parsed.tzinfo else None
    except (ValueError,OverflowError,OSError): pass
    return None

def normalize(row, provider):
    oplab=provider=='oplab'
    return {
        'symbol':row.get('symbol'), 'kind': str((row.get('category') if oplab else row.get('side')) or '').lower(),
        'strike':number(row.get('strike')), 'expiry':row.get('due_date') if oplab else row.get('expirationDate'),
        'exercise':str((row.get('maturity_type') if oplab else row.get('optionStyle')) or '').lower(),
        'bid':number(row.get('bid')), 'ask':number(row.get('ask')), 'close':number(row.get('close')),
        'bid_size':number(row.get('bid_volume')) if oplab else None,
        'ask_size':number(row.get('ask_volume')) if oplab else None,
        'open_interest':number(row.get('openInterest')) if not oplab else None,
        'volume':number(row.get('volume')),
        'observed_at':timestamp(row.get('time'),milliseconds=True) if oplab else timestamp(row.get('date')),
        'lot_reported':number(row.get('contract_size') if oplab else row.get('allocationRoundLot')),
        'multiplier':None, # Provider minimum contract size is not necessarily a quotation multiplier.
    }

async def expirations(ticker):
    token=os.getenv('BRAPI_TOKEN','').strip()
    data=await get_json('https://brapi.dev/api/v2/options/expirations',params={'underlying':ticker},headers={'Authorization':f'Bearer {token}'} if token else {})
    if not isinstance(data,dict) or not isinstance(data.get('expirations'),list): raise SourceError(502,'Formato de vencimentos inesperado.')
    return {'provider':'brapi','data_mode':'eod','expirations':data['expirations'],'fetched_at':datetime.now(UTC).isoformat()}

async def chain(provider, ticker, expiry, owner):
    if provider=='brapi':
        if not expiry: raise SourceError(422,'Escolha um vencimento para consultar a brapi.')
        token=os.getenv('BRAPI_TOKEN','').strip()
        raw=await get_json('https://brapi.dev/api/v2/options/chain',params={'underlying':ticker,'expirationDate':expiry},headers={'Authorization':f'Bearer {token}'} if token else {})
        rows=raw.get('series') if isinstance(raw,dict) else None
        mode='eod'
        blockers=['Dados de fechamento: não podem alimentar gatilhos de entrada atuais.', 'Quantidades de bid/ask e multiplicador de cotação não confirmados.']
    elif provider=='oplab':
        headers=licensed_headers('OPLAB',owner)
        raw=await get_json(f'https://api.oplab.com.br/v3/market/options/{ticker}',headers=headers)
        rows=raw
        mode='unverified'
        blockers=['Latência e licença da assinatura ainda não verificadas.', 'Multiplicador e unidade do lote precisam ser reconciliados com a especificação B3.']
    else:
        headers=licensed_headers('CEDRO',owner)
        raw=await get_json(f'https://webfeeder.cedrotech.com/services/quotes/optionsQuote/{ticker}',headers=headers)
        # Public documentation does not provide a complete response contract.
        # Retain payload for homologation instead of guessing financial units.
        return {'provider':'cedro','ticker':ticker,'data_mode':'unverified','fetched_at':datetime.now(UTC).isoformat(),
                'eligible_for_planning':False,'blockers':['Resposta Cedro coletada para homologação; esquema, latência e unidades ainda não validados.'],
                'contracts':[],'raw':raw}
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows): raise SourceError(502,'Formato de cadeia inesperado.')
    contracts=[normalize(row,provider) for row in rows]
    if expiry: contracts=[c for c in contracts if c['expiry']==expiry]
    return {'provider':provider,'ticker':ticker,'data_mode':mode,'fetched_at':datetime.now(UTC).isoformat(),
            'eligible_for_planning':False,'blockers':blockers,'contracts':contracts,'raw':raw}

async def selic():
    data=await get_json('https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1',params={'formato':'json'})
    try:
        row=data[-1]; value=float(row['valor']); observed=datetime.strptime(row['data'],'%d/%m/%Y').date().isoformat()
        if not math.isfinite(value): raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError): raise SourceError(502,'Formato SGS inesperado.') from None
    return {'provider':'bcb','series':11,'observed_date':observed,'value':value,'unit':'percent_per_business_day',
            'annualized_252_pct':round(((1+value/100)**252-1)*100,6),
            'fetched_at':datetime.now(UTC).isoformat(),
            'note':'Selic efetiva diária. Anualização composta em 252 dias é derivada; não é meta Selic nem curva de desconto por vencimento.'}

async def cvm_catalog(kind):
    raw=await get_json('https://dados.cvm.gov.br/api/3/action/package_show',params={'id':f'cia_aberta-doc-{kind}'})
    if not isinstance(raw,dict) or raw.get('success') is not True or not isinstance(raw.get('result'),dict): raise SourceError(502,'Catálogo CVM inválido.')
    data=raw['result']; resources=[]
    for row in data.get('resources',[]):
        url=row.get('url',''); parsed=urlparse(url)
        if parsed.scheme=='https' and parsed.hostname=='dados.cvm.gov.br':
            resources.append({'name':row.get('name'),'format':row.get('format'),'url':url,'last_modified':row.get('last_modified')})
    return {'provider':'cvm','dataset':data.get('name'),'metadata_modified':data.get('metadata_modified'),
            'fetched_at':datetime.now(UTC).isoformat(),'resources':resources,
            'note':'Catálogo oficial de arquivos ITR/DFP; não é calendário futuro de resultados. O conteúdo contábil dos ZIPs ainda não foi ingerido.'}

"""Auditable paper positions from saved plans. Never sends broker orders."""
import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, Field, model_validator

from app.api.derivatives import setup as setup_plans
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.database import _get_conn
from app.models.derivatives_planner import Nonnegative, Positive, StrictModel

router = APIRouter(dependencies=[Depends(get_current_user)])


def setup(conn):
    setup_plans(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_trades (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, plan_id TEXT NOT NULL,
        plan_index INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
        plan TEXT NOT NULL, context TEXT NOT NULL,
        UNIQUE(owner, plan_id, plan_index))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS paper_events (
        id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, request_id TEXT NOT NULL,
        payload_hash TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL,
        payload TEXT NOT NULL, result TEXT NOT NULL, UNIQUE(trade_id, request_id))''')
    conn.execute('CREATE INDEX IF NOT EXISTS paper_owner ON paper_trades(owner, created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS paper_event_trade ON paper_events(trade_id, created_at)')
    conn.commit()


class TrackRequest(StrictModel):
    plan_id: UUID
    plan_index: int = Field(ge=0, le=19)


class Book(StrictModel):
    symbol: str = Field(min_length=3, max_length=30)
    bid: Nonnegative
    ask: Positive
    bid_size: int = Field(ge=0, le=100000000)
    ask_size: int = Field(ge=0, le=100000000)

    @model_validator(mode='after')
    def coherent(self):
        if self.bid > self.ask:
            raise ValueError('Bid não pode superar ask.')
        return self


class Observation(StrictModel):
    request_id: UUID
    action: Literal['open', 'mark', 'close', 'cancel']
    source: str = Field(min_length=3, max_length=200)
    note: str = Field(min_length=10, max_length=2000)
    as_of: AwareDatetime
    underlying: Positive
    quotes: list[Book] = Field(default_factory=list, max_length=2)


def D(x):
    return Decimal(str(x))


def money(value):
    return float(value.quantize(Decimal('0.01')))


def reject(detail, code=422):
    raise HTTPException(code, detail)


def read_record(conn, owner, trade_id):
    row = conn.execute('SELECT * FROM paper_trades WHERE id=? AND owner=?', (trade_id, owner)).fetchone()
    if not row:
        reject('Operação simulada não encontrada.', 404)
    result = dict(row)
    result['plan'] = json.loads(result['plan'])
    result['context'] = json.loads(result['context'])
    result['events'] = [dict(event) | {'payload': json.loads(event['payload']), 'result': json.loads(event['result'])}
                        for event in conn.execute('SELECT * FROM paper_events WHERE trade_id=? ORDER BY rowid', (trade_id,))]
    result['eligible_for_live_trading'] = False
    return result


@router.post('', status_code=201)
def track(req: TrackRequest, owner: str = Depends(get_current_user)):
    with _get_conn() as conn:
        setup(conn)
        conn.execute('BEGIN IMMEDIATE')
        saved = conn.execute('SELECT payload,result FROM derivative_plans WHERE id=? AND owner=?', (str(req.plan_id), owner)).fetchone()
        if saved is None:
            reject('Plano não encontrado.', 404)
        report, inputs = json.loads(saved['result']), json.loads(saved['payload'])
        if req.plan_index >= len(report['plans']):
            reject('O plano não contém essa operação.')
        existing = conn.execute('SELECT id FROM paper_trades WHERE owner=? AND plan_id=? AND plan_index=?',
                                (owner, str(req.plan_id), req.plan_index)).fetchone()
        trade_id = existing['id'] if existing else str(uuid4())
        if not existing:
            context = {k: inputs[k] for k in ('source','provenance','capital','total_risk_pct','existing_risk_brl','fee_per_contract_side')}
            conn.execute('INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?)',
                         (trade_id, owner, str(req.plan_id), req.plan_index, 'watching', datetime.now(UTC).isoformat(),
                          json.dumps(report['plans'][req.plan_index]), json.dumps(context)))
        conn.commit()
        return read_record(conn, owner, trade_id)


@router.get('')
def history(owner: str = Depends(get_current_user)):
    with _get_conn() as conn:
        setup(conn)
        rows = conn.execute('SELECT id,status,created_at,plan,context FROM paper_trades WHERE owner=? ORDER BY created_at DESC LIMIT 100', (owner,))
        return [dict(row) | {'plan':json.loads(row['plan']), 'context':json.loads(row['context'])} for row in rows]


@router.get('/{trade_id}')
def detail(trade_id: UUID, owner: str = Depends(get_current_user)):
    with _get_conn() as conn:
        setup(conn)
        return read_record(conn, owner, str(trade_id))


@router.post('/{trade_id}/events')
@limiter.limit('30/minute')
def observe(request: Request, trade_id: UUID, req: Observation, owner: str = Depends(get_current_user)):
    now = datetime.now(UTC)
    payload = req.model_dump_json()
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    with _get_conn() as conn:
        setup(conn)
        conn.execute('BEGIN IMMEDIATE')
        record = read_record(conn, owner, str(trade_id))
        previous = next((e for e in record['events'] if e['request_id'] == str(req.request_id)), None)
        if previous:
            if previous['payload_hash'] != fingerprint:
                reject('Identificador já usado com outros dados.', 409)
            return record
        status, plan, context = record['status'], record['plan'], record['context']
        allowed = {'watching': {'open','cancel'}, 'open': {'mark','close'}}
        if req.action not in allowed.get(status, set()):
            reject('Transição inválida para o estado atual.', 409)
        age = (now - req.as_of).total_seconds()
        if not -60 <= age <= 900:
            reject('Observação futura ou com mais de 15 minutos.')
        if record['events'] and req.as_of < datetime.fromisoformat(record['events'][-1]['payload']['as_of']):
            reject('Observação anterior ao último evento.')
        if req.as_of < datetime.fromisoformat(record['created_at']):
            reject('Observação anterior à criação do acompanhamento.')
        result = {'mode':'paper_only', 'eligible_for_live_trading':False, 'alerts':[]}
        if req.action == 'cancel':
            new_status = 'cancelled'
        else:
            books = {q.symbol:q for q in req.quotes}
            if len(books) != len(req.quotes) or set(books) != {l['symbol'] for l in plan['legs']}:
                reject('Informe uma cotação única para cada perna do plano.')
            fills = []
            for leg in plan['legs']:
                book = books[leg['symbol']]
                buying = (leg['side'] == 'buy') == (req.action == 'open')
                price, size = (book.ask, book.ask_size) if buying else (book.bid, book.bid_size)
                if size < leg['quantity']:
                    reject('Livro insuficiente para simular todas as pernas; não há preenchimento parcial.')
                fills.append({'symbol':leg['symbol'], 'price':price, 'quantity':leg['quantity'], 'side':'buy' if buying else 'sell'})
            multiplier = D(plan['multiplier'])
            fees = sum(D(l['quantity']) * D(context['fee_per_contract_side']) for l in fills)
            # Open: debit; close/mark: liquidation credit (can be negative).
            cash = sum(D(l['price']) * D(l['quantity']) * multiplier * (1 if l['side'] == ('buy' if req.action == 'open' else 'sell') else -1) for l in fills)
            result.update(fills=fills, fees_brl=money(fees))
            if req.action == 'open':
                if now > datetime.fromisoformat(plan['entry']['quote_valid_until']):
                    reject('Plano expirou para entrada; gere um novo plano com cotações atualizadas.')
                if now.date().isoformat() >= plan['close_by']:
                    reject('Prazo de encerramento do plano já alcançado.')
                bullish = plan['direction'] == 'long_bias'
                trigger = plan['entry']['underlying_trigger']
                if (bullish and req.underlying < trigger) or (not bullish and req.underlying > trigger):
                    reject('Gatilho de entrada ainda não alcançado.')
                low, high = sorted([plan['exit']['underlying_invalidation'], plan['exit']['underlying_target']])
                if not low < req.underlying < high:
                    reject('Tese invalidada ou alvo já alcançado.')
                limit = D(plan['entry']['max_net_debit_per_unit']) * D(plan['quantity_per_leg']) * multiplier
                if cash <= 0 or cash > limit + D('0.000001'):
                    reject('Débito simulado inválido ou acima do limite do plano.')
                risk = cash + 2 * fees
                open_risk = D(0)
                for active in conn.execute("SELECT id FROM paper_trades WHERE owner=? AND status='open'", (owner,)):
                    first = conn.execute("SELECT result FROM paper_events WHERE trade_id=? AND kind='open'", (active['id'],)).fetchone()
                    open_risk += D(json.loads(first['result'])['reserved_risk_brl'])
                budget = D(context['capital']) * D(context['total_risk_pct']) / 100 - D(context['existing_risk_brl'])
                if open_risk + risk > budget:
                    reject('A entrada excede o orçamento agregado, considerando outras simulações abertas.')
                result.update(entry_debit_brl=money(cash), reserved_risk_brl=float(risk.quantize(Decimal('0.01'), rounding=ROUND_UP)))
                new_status = 'open'
            else:
                entry = next(e['result'] for e in record['events'] if e['kind'] == 'open')
                # Recompute the exact entry cost from immutable per-leg fills, avoiding intermediate rounding.
                debit = sum(D(l['price'])*D(l['quantity'])*multiplier*(1 if l['side']=='buy' else -1) for l in entry['fills'])
                pnl = cash - debit - 2 * fees
                result.update(liquidation_credit_brl=money(cash), net_pnl_brl=money(pnl),
                              pnl_kind='realized_simulated' if req.action == 'close' else 'estimated_if_closed')
                bullish = plan['direction'] == 'long_bias'
                inv, target = plan['exit']['underlying_invalidation'], plan['exit']['underlying_target']
                if (bullish and req.underlying <= inv) or (not bullish and req.underlying >= inv): result['alerts'].append('Tese invalidada')
                if (bullish and req.underlying >= target) or (not bullish and req.underlying <= target): result['alerts'].append('Alvo do ativo alcançado')
                if pnl <= -D(plan['exit']['stop_loss_net_brl']): result['alerts'].append('Limite de perda alcançado')
                if pnl >= D(plan['exit']['take_profit_net_brl']): result['alerts'].append('Limite de ganho alcançado')
                if now.date().isoformat() >= plan['close_by']: result['alerts'].append('Data-limite de saída alcançada')
                if now.date().isoformat() >= plan['expiry']: result['alerts'].append('Vencimento alcançado: registro contábil simulado; exercício e liquidação não modelados')
                new_status = 'closed' if req.action == 'close' else 'open'
        conn.execute('INSERT INTO paper_events VALUES (?,?,?,?,?,?,?,?)',
                     (str(uuid4()), str(trade_id), str(req.request_id), fingerprint, now.isoformat(), req.action, payload, json.dumps(result)))
        conn.execute('UPDATE paper_trades SET status=? WHERE id=?', (new_status, str(trade_id)))
        conn.commit()
        return read_record(conn, owner, str(trade_id))


@router.get('/{trade_id}/source-check/{snapshot_id}')
def source_check(trade_id: UUID, snapshot_id: UUID, owner: str = Depends(get_current_user)):
    from app.api.market_sources import setup as setup_sources
    from app.services.source_quality import assess
    with _get_conn() as conn:
        setup(conn)
        record = read_record(conn, owner, str(trade_id))
        setup_sources(conn)
        row = conn.execute('SELECT payload FROM source_snapshots WHERE id=? AND owner=?',
                           (str(snapshot_id), owner)).fetchone()
        if row is None:
            reject('Snapshot não encontrado.', 404)
        return assess(record, json.loads(row['payload']))

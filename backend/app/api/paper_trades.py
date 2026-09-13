"""Auditable paper positions from saved plans. Never sends broker orders.

Locking note (see docs/POSTGRES-MIGRATION-SPIKE.md): the SQLite version used
BEGIN IMMEDIATE to serialize all writes globally (SQLite only ever has one
writer). Postgres has real per-row MVCC, so instead of a global lock we take
a Postgres advisory transaction lock keyed by owner
(pg_advisory_xact_lock(hashtext(owner))) — it serializes only one owner's
concurrent writes against each other (what the aggregate risk-budget check
below actually needs), not unrelated owners against each other.
"""
import hashlib
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal
from typing import Literal, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, Field, model_validator

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.postgres import get_pool
from app.models.derivatives_planner import Nonnegative, Positive, StrictModel

router = APIRouter(dependencies=[Depends(get_current_user)])


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


def reject(detail, code=422) -> NoReturn:
    raise HTTPException(code, detail)


async def lock_owner(conn, owner: str) -> None:
    """Serializes this owner's concurrent writes within the current transaction."""
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", owner)


async def read_record(conn, owner, trade_id):
    row = await conn.fetchrow('SELECT * FROM paper_trades WHERE id=$1 AND owner=$2', trade_id, owner)
    if not row:
        reject('Operação simulada não encontrada.', 404)
    result = dict(row)
    events = await conn.fetch('SELECT * FROM paper_events WHERE trade_id=$1 ORDER BY seq', trade_id)
    result['events'] = [dict(event) for event in events]
    result['eligible_for_live_trading'] = False
    return result


@router.post('', status_code=201)
async def track(req: TrackRequest, owner: str = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await lock_owner(conn, owner)
        saved = await conn.fetchrow(
            'SELECT payload,result FROM derivative_plans WHERE id=$1 AND owner=$2', str(req.plan_id), owner,
        )
        if saved is None:
            reject('Plano não encontrado.', 404)
        report, inputs = saved['result'], saved['payload']
        if req.plan_index >= len(report['plans']):
            reject('O plano não contém essa operação.')
        existing = await conn.fetchrow(
            'SELECT id FROM paper_trades WHERE owner=$1 AND plan_id=$2 AND plan_index=$3',
            owner, str(req.plan_id), req.plan_index,
        )
        trade_id = existing['id'] if existing else str(uuid4())
        if not existing:
            context = {k: inputs[k] for k in ('source','provenance','capital','total_risk_pct','existing_risk_brl','fee_per_contract_side')}
            await conn.execute(
                'INSERT INTO paper_trades (id, owner, plan_id, plan_index, status, created_at, plan, context) '
                'VALUES ($1,$2,$3,$4,$5,$6,$7,$8)',
                trade_id, owner, str(req.plan_id), req.plan_index, 'watching', datetime.now(UTC),
                report['plans'][req.plan_index], context,
            )
        return await read_record(conn, owner, trade_id)


@router.get('')
async def history(owner: str = Depends(get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch(
        'SELECT id,status,created_at,plan,context FROM paper_trades WHERE owner=$1 ORDER BY created_at DESC LIMIT 100',
        owner,
    )
    return [dict(row) for row in rows]


@router.get('/{trade_id}')
async def detail(trade_id: UUID, owner: str = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await read_record(conn, owner, str(trade_id))


@router.post('/{trade_id}/events')
@limiter.limit('30/minute')
async def observe(request: Request, trade_id: UUID, req: Observation, owner: str = Depends(get_current_user)):
    now = datetime.now(UTC)
    payload = req.model_dump(mode='json')
    fingerprint = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await lock_owner(conn, owner)
        record = await read_record(conn, owner, str(trade_id))
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
        if req.as_of < record['created_at']:
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
            # start=D(0): sum() over an empty sequence otherwise returns the
            # literal int 0, not Decimal(0), and breaks .quantize() downstream.
            fees = sum((D(l['quantity']) * D(context['fee_per_contract_side']) for l in fills), start=D(0))
            # Open: debit; close/mark: liquidation credit (can be negative).
            cash = sum((D(l['price']) * D(l['quantity']) * multiplier * (1 if l['side'] == ('buy' if req.action == 'open' else 'sell') else -1) for l in fills), start=D(0))
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
                # Safe from races: lock_owner() above holds this owner's
                # advisory lock for the whole transaction, so no concurrent
                # "open" for this owner can be mid-flight right now.
                active_trades = await conn.fetch("SELECT id FROM paper_trades WHERE owner=$1 AND status='open'", owner)
                for active in active_trades:
                    first = await conn.fetchrow(
                        "SELECT result FROM paper_events WHERE trade_id=$1 AND kind='open'", active['id'],
                    )
                    open_risk += D(first['result']['reserved_risk_brl'])
                budget = D(context['capital']) * D(context['total_risk_pct']) / 100 - D(context['existing_risk_brl'])
                if open_risk + risk > budget:
                    reject('A entrada excede o orçamento agregado, considerando outras simulações abertas.')
                result.update(entry_debit_brl=money(cash), reserved_risk_brl=float(risk.quantize(Decimal('0.01'), rounding=ROUND_UP)))
                new_status = 'open'
            else:
                entry = next(e['result'] for e in record['events'] if e['kind'] == 'open')
                # Recompute the exact entry cost from immutable per-leg fills, avoiding intermediate rounding.
                debit = sum((D(l['price'])*D(l['quantity'])*multiplier*(1 if l['side']=='buy' else -1) for l in entry['fills']), start=D(0))
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
        await conn.execute(
            'INSERT INTO paper_events (id, trade_id, request_id, payload_hash, created_at, kind, payload, result) '
            'VALUES ($1,$2,$3,$4,$5,$6,$7,$8)',
            str(uuid4()), str(trade_id), str(req.request_id), fingerprint, now, req.action, payload, result,
        )
        await conn.execute('UPDATE paper_trades SET status=$1 WHERE id=$2', new_status, str(trade_id))
        return await read_record(conn, owner, str(trade_id))


def _last_quotes(record: dict) -> list[dict] | None:
    for event in reversed(record.get("events") or []):
        quotes = (event.get("payload") or {}).get("quotes")
        if quotes:
            return quotes
    return None


async def flatten_open_trades(owner: str, *, reason: str) -> dict:
    """Close every open paper trade at last mark. No broker, no 15-minute quote window."""
    now = datetime.now(UTC)
    pool = await get_pool()
    closed: list[str] = []
    skipped: list[dict] = []
    async with pool.acquire() as conn, conn.transaction():
        await lock_owner(conn, owner)
        rows = await conn.fetch(
            "SELECT id FROM paper_trades WHERE owner=$1 AND status='open'", owner,
        )
        for row in rows:
            record = await read_record(conn, owner, row["id"])
            quotes = _last_quotes(record)
            if not quotes:
                skipped.append({"id": row["id"], "detail": "no last mark to flatten against"})
                continue
            plan, context = record["plan"], record["context"]
            books = {q["symbol"]: q for q in quotes}
            if set(books) != {leg["symbol"] for leg in plan["legs"]}:
                skipped.append({"id": row["id"], "detail": "last mark missing a leg"})
                continue
            fills = []
            for leg in plan["legs"]:
                book = books[leg["symbol"]]
                opening_buy = leg["side"] == "buy"
                buying = not opening_buy
                price = book["ask"] if buying else book["bid"]
                fills.append({
                    "symbol": leg["symbol"],
                    "price": price,
                    "quantity": leg["quantity"],
                    "side": "buy" if buying else "sell",
                })
            multiplier = D(plan["multiplier"])
            fees = sum((D(f["quantity"]) * D(context["fee_per_contract_side"]) for f in fills), start=D(0))
            cash = sum(
                (
                    D(f["price"]) * D(f["quantity"]) * multiplier * (1 if f["side"] == "sell" else -1)
                    for f in fills
                ),
                start=D(0),
            )
            entry = next(e["result"] for e in record["events"] if e["kind"] == "open")
            debit = sum(
                (
                    D(l["price"]) * D(l["quantity"]) * multiplier * (1 if l["side"] == "buy" else -1)
                    for l in entry["fills"]
                ),
                start=D(0),
            )
            pnl = cash - debit - 2 * fees
            result = {
                "mode": "paper_only",
                "eligible_for_live_trading": False,
                "flatten": "regime_kill",
                "reason": reason,
                "fills": fills,
                "fees_brl": money(fees),
                "liquidation_credit_brl": money(cash),
                "net_pnl_brl": money(pnl),
                "pnl_kind": "realized_simulated",
                "alerts": ["Flattened by regime kill switch at last mark"],
            }
            payload = {
                "action": "close",
                "source": "regime_kill_switch",
                "note": reason[:2000],
                "as_of": now.isoformat(),
                "quotes": quotes,
            }
            request_id = str(uuid4())
            fingerprint = hashlib.sha256(f"{row['id']}:{request_id}:{reason}".encode()).hexdigest()
            await conn.execute(
                "INSERT INTO paper_events (id, trade_id, request_id, payload_hash, created_at, kind, payload, result) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                str(uuid4()), row["id"], request_id, fingerprint, now, "close", payload, result,
            )
            await conn.execute("UPDATE paper_trades SET status=$1 WHERE id=$2", "closed", row["id"])
            closed.append(row["id"])
    return {
        "owner": owner,
        "closed": closed,
        "skipped": skipped,
        "broker_orders_sent": 0,
        "eligible_for_live_trading": False,
        "reason": reason,
    }


@router.get('/{trade_id}/source-check/{snapshot_id}')
async def source_check(trade_id: UUID, snapshot_id: UUID, owner: str = Depends(get_current_user)):
    from app.services.source_quality import assess
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await read_record(conn, owner, str(trade_id))
        row = await conn.fetchrow(
            'SELECT payload FROM source_snapshots WHERE id=$1 AND owner=$2', str(snapshot_id), owner,
        )
        if row is None:
            reject('Snapshot não encontrado.', 404)
        return assess(record, row['payload'])

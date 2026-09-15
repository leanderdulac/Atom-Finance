"""Conditional option plans from explicit quotes and theses; no invented contracts or probabilities."""
from datetime import UTC, date, datetime, timedelta
from math import floor
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class OptionQuote(StrictModel):
    symbol: str = Field(min_length=3, max_length=30)
    kind: Literal['call', 'put']
    strike: Positive
    expiry: date
    exercise: Literal['european', 'american']
    bid: Nonnegative
    ask: Positive
    bid_size: int = Field(ge=0)
    ask_size: int = Field(ge=0)
    multiplier: Positive
    lot_size: int = Field(ge=1, le=100000)

    @model_validator(mode='after')
    def valid_book(self):
        if self.bid > self.ask: raise ValueError('Bid não pode superar ask.')
        return self

class Thesis(StrictModel):
    # Ticker is interpolated into the OPLAB/CEDRO URL path — a character
    # whitelist prevents path/query injection on the licensed hosts.
    ticker: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9.\-^=]{3,20}$")
    spot: Positive
    direction: Literal['bullish', 'bearish']
    rationale: str = Field(min_length=30, max_length=2000)
    entry: Positive
    invalidation: Positive
    target: Positive
    holding_days: int = Field(ge=2, le=180)
    events_checked: bool = False
    next_event: date | None = None
    options: list[OptionQuote] = Field(min_length=1, max_length=60)

    @model_validator(mode='after')
    def coherent(self):
        if self.direction == 'bullish' and not self.invalidation < self.entry < self.target:
            raise ValueError('Alta exige invalidação < entrada < alvo.')
        if self.direction == 'bearish' and not self.target < self.entry < self.invalidation:
            raise ValueError('Baixa exige alvo < entrada < invalidação.')
        if len({q.symbol for q in self.options}) != len(self.options): raise ValueError('Contratos duplicados no ativo.')
        return self

class PlanRequest(StrictModel):
    source: str = Field(min_length=3, max_length=200)
    provenance: Literal['synthetic', 'user_supplied']
    as_of: datetime
    capital: Positive
    risk_per_trade_pct: float = Field(default=1, gt=0, le=5, allow_inf_nan=False)
    total_risk_pct: float = Field(default=3, gt=0, le=10, allow_inf_nan=False)
    existing_risk_brl: Nonnegative = 0
    fee_per_contract_side: Nonnegative = 0.05
    min_scenario_reward_risk: float = Field(default=1, ge=0.1, le=10, allow_inf_nan=False)
    max_spread_pct: float = Field(default=15, gt=0, le=30, allow_inf_nan=False)
    take_profit_pct: float = Field(default=50, gt=0, le=500, allow_inf_nan=False)
    stop_loss_pct: float = Field(default=40, gt=0, le=100, allow_inf_nan=False)
    theses: list[Thesis] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def coherent(self):
        if self.as_of.tzinfo is None: raise ValueError('Timestamp deve incluir fuso horário.')
        if len({t.ticker for t in self.theses}) != len(self.theses): raise ValueError('Ativos duplicados.')
        symbols = [q.symbol for t in self.theses for q in t.options]
        if len(set(symbols)) != len(symbols): raise ValueError('Contrato não pode pertencer a dois ativos.')
        return self


def intrinsic(q, spot):
    return max(spot - q.strike, 0) if q.kind == 'call' else max(q.strike - spot, 0)


def make_plans(req: PlanRequest, now: datetime | None = None):
    now = now or datetime.now(UTC)
    rejected, candidates = [], []
    response = {'version': 'ATOM-DERIVATIVES-1.0', 'created_at': now.isoformat(), 'source': req.source,
                'as_of': req.as_of.isoformat(), 'provenance': req.provenance, 'eligible_for_live_trading': False,
                'status': 'no_trade', 'plans': [], 'rejected': rejected,
                'ranking_method': 'Maior lucro no cenário-alvo no vencimento / perda máxima modelada. Não é retorno esperado nem probabilidade.',
                'limitations': [
                    'Teses, alvos, eventos e cotações são fornecidos pelo solicitante; não há feed de opções auditado conectado.',
                    'O motor seleciona estruturas condicionais; não prevê preços nem comprova vantagem estatística.',
                    'Payoffs são no vencimento. Antes dele, volatilidade, tempo e liquidez alteram o preço de saída.',
                    'Stops e saída antecipada não garantem execução. Revalidar livro, custos e calendário antes de enviar ordens.',
                    'Dimensionamento usa perda do prêmio e reserva de taxas. Exercício, entrega física e falha em encerrar pernas podem exigir capital adicional.',
                    'Orçamento agregado soma riscos informados; não estima correlações ou posições omitidas. Não há envio de ordens nem monitoramento contínuo.'
                ]}
    age = (now - req.as_of).total_seconds()
    if age < -60 or age > 900:
        rejected.append({'ticker': '*', 'reason': 'Snapshot futuro ou com mais de 15 minutos. Atualize todas as cotações.'})
        return response
    today = now.date()
    remaining = max(0, req.capital * req.total_risk_pct / 100 - req.existing_risk_brl)
    for thesis in req.theses:
        if not thesis.events_checked:
            rejected.append({'ticker': thesis.ticker, 'reason': 'Calendário de eventos não conferido.'}); continue
        close_date = today + timedelta(days=thesis.holding_days)
        if thesis.next_event and thesis.next_event < today:
            rejected.append({'ticker': thesis.ticker, 'reason': 'Evento informado está no passado; atualize o calendário.'}); continue
        if thesis.next_event and thesis.next_event <= close_date:
            rejected.append({'ticker': thesis.ticker, 'reason': 'Evento no horizonte; esta versão não monta operações direcionais sobre eventos.'}); continue
        if (thesis.direction == 'bullish' and (thesis.spot <= thesis.invalidation or thesis.spot >= thesis.target)) or (thesis.direction == 'bearish' and (thesis.spot >= thesis.invalidation or thesis.spot <= thesis.target)):
            rejected.append({'ticker': thesis.ticker, 'reason': 'Tese invalidada ou alvo já alcançado.'}); continue
        kind = 'call' if thesis.direction == 'bullish' else 'put'
        quotes = [q for q in thesis.options if q.kind == kind and q.bid > 0 and q.bid_size > 0 and q.ask_size > 0
                  and (q.ask - q.bid) / ((q.ask + q.bid) / 2) * 100 <= req.max_spread_pct
                  and (q.expiry - close_date).days >= 7]
        eligible = []
        for long in quotes:
            structures = [(long, None)]
            structures += [(long, short) for short in quotes if short.symbol != long.symbol
                           and short.expiry == long.expiry and short.multiplier == long.multiplier and short.lot_size == long.lot_size
                           and short.exercise == long.exercise == 'european'
                           and ((kind == 'call' and short.strike > long.strike) or (kind == 'put' and short.strike < long.strike))]
            for buy, sell in structures:
                debit = (buy.ask - (sell.bid if sell else 0)) * buy.multiplier
                if debit <= 0: continue
                width = abs(buy.strike - sell.strike) * buy.multiplier if sell else None
                if width is not None and debit >= width: continue
                legs_count = 2 if sell else 1
                fees = 2 * legs_count * req.fee_per_contract_side
                risk = debit + fees
                scenario_payoff = (intrinsic(buy, thesis.target) - (intrinsic(sell, thesis.target) if sell else 0)) * buy.multiplier
                scenario_pnl = scenario_payoff - risk
                ratio = scenario_pnl / risk
                if ratio < req.min_scenario_reward_risk: continue
                book_qty = min(buy.ask_size, buy.bid_size, sell.bid_size if sell else buy.ask_size, sell.ask_size if sell else buy.bid_size)
                max_profit = width - risk if width is not None else (buy.strike * buy.multiplier - risk if kind == 'put' else None)
                # A profit-taking rule must be reachable even at the payoff cap.
                if max_profit is not None and max_profit < req.take_profit_pct / 100 * debit: continue
                eligible.append((ratio, risk, thesis, buy, sell, debit, fees, book_qty, max_profit))
        if eligible:
            candidates.append(max(eligible, key=lambda c: (c[0], -c[1], c[3].symbol)))
        else:
            rejected.append({'ticker': thesis.ticker, 'reason': 'Nenhuma estrutura atende spread, livro, vencimento, alvo, ganho mínimo e tipo de exercício.'})
    for ratio, risk, thesis, buy, sell, debit, fees, book_qty, max_profit in sorted(candidates, key=lambda c: (-c[0], c[2].ticker)):
        budget = min(req.capital * req.risk_per_trade_pct / 100, remaining)
        quantity = floor(min(budget / risk, book_qty) / buy.lot_size) * buy.lot_size
        if quantity < buy.lot_size:
            rejected.append({'ticker': thesis.ticker, 'reason': 'Orçamento ou quantidade no livro insuficiente para um lote.'}); continue
        remaining -= quantity * risk
        legs = [{'symbol': buy.symbol, 'side': 'buy', 'kind': buy.kind, 'strike': buy.strike, 'limit_reference': buy.ask, 'quantity': quantity, 'exercise': buy.exercise}]
        if sell: legs.append({'symbol': sell.symbol, 'side': 'sell', 'kind': sell.kind, 'strike': sell.strike, 'limit_reference': sell.bid, 'quantity': quantity, 'exercise': sell.exercise})
        response['plans'].append({
            'ticker': thesis.ticker, 'direction': 'long_bias' if thesis.direction == 'bullish' else 'short_bias',
            'strategy': ('bull_call_spread' if buy.kind == 'call' else 'bear_put_spread') if sell else 'long_' + buy.kind,
            'rationale': thesis.rationale, 'legs': legs, 'expiry': buy.expiry.isoformat(), 'holding_days': thesis.holding_days,
            'close_by': (today + timedelta(days=thesis.holding_days)).isoformat(), 'calendar_basis': 'dias corridos; antecipar ao pregão anterior se não houver sessão',
            'entry': {'underlying_trigger': thesis.entry, 'comparison': '>=' if thesis.direction == 'bullish' else '<=',
                      'max_net_debit_per_unit': round(debit / buy.multiplier, 6), 'quote_valid_until': (req.as_of + timedelta(minutes=15)).isoformat(),
                      'instruction': 'Aguardar gatilho e revalidar snapshot e estrutura. Usar ordem limitada conjunta; não executar pernas separadamente.'},
            'exit': {'underlying_invalidation': thesis.invalidation, 'underlying_target': thesis.target,
                     'take_profit_net_brl': round(quantity * debit * req.take_profit_pct / 100, 2),
                     'stop_loss_net_brl': round(quantity * debit * req.stop_loss_pct / 100, 2),
                     'instruction': 'Encerrar todas as pernas no primeiro evento: invalidação, alvo, limite de ganho/perda líquido ou data-limite. Limiares não garantem preço.'},
            'quantity_per_leg': quantity, 'multiplier': buy.multiplier, 'lot_size': buy.lot_size,
            'premium_outlay_brl': round(quantity * debit, 2), 'fees_reserved_brl': round(quantity * fees, 2),
            'modeled_max_loss_brl': round(quantity * risk, 2), 'modeled_max_profit_brl': round(quantity * max_profit, 2) if max_profit is not None else None,
            'target_scenario_reward_risk': round(ratio, 3),
            'breakeven_at_expiry': round(buy.strike + (risk / buy.multiplier if buy.kind == 'call' else -risk / buy.multiplier), 6),
            'payoff_at_expiry': [{'underlying': round(s, 4), 'net_pnl_brl': round(quantity * ((intrinsic(buy, s) - (intrinsic(sell, s) if sell else 0)) * buy.multiplier - risk), 2)}
                                 for s in sorted({0, thesis.invalidation, thesis.entry, thesis.target, buy.strike, sell.strike if sell else buy.strike, thesis.target * 1.2})]
        })
    response['status'] = ('simulation' if req.provenance == 'synthetic' else 'conditional_review') if response['plans'] else 'no_trade'
    response['allocated_risk_brl'] = round(sum(p['modeled_max_loss_brl'] for p in response['plans']), 2)
    response['remaining_risk_budget_brl'] = round(remaining, 2)
    return response

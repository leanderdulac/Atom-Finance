"""Read-only reconciliation of a saved source snapshot with a paper plan.

Passing structural checks is not feed certification and cannot create fills.
"""
from datetime import UTC, datetime

from app.services.market_sources import number, timestamp


def assess(record, snapshot, now=None):
    now = now or datetime.now(UTC)
    plan = record['plan']
    labels = {'kind':'tipo da opção', 'strike':'preço de exercício', 'exercise':'estilo de exercício',
              'expiry':'vencimento', 'multiplier':'multiplicador de cotação', 'lot_size':'lote de negociação'}
    blockers = list(snapshot.get('blockers', []))
    if snapshot.get('ticker') != plan['ticker']:
        blockers.append('A ação do snapshot difere da ação do plano.')
    if record['context']['provenance'] == 'synthetic':
        blockers.append('Plano fictício: dados de mercado não podem validar esta simulação.')
    mode = snapshot.get('data_mode')
    if mode == 'eod':
        blockers.append('Fonte de fechamento não serve para uma observação atual.')
    elif mode != 'verified_live':
        blockers.append('Latência e cobertura da fonte não homologadas.')
    # No adapter currently supplies a verified underlying quote or certified units.
    blockers.append('Cotação atual do ativo-objeto e homologação do conector ainda pendentes.')
    rows = snapshot.get('contracts', [])
    legs = []
    for leg in plan['legs']:
        matches = [row for row in rows if row.get('symbol') == leg['symbol']]
        issues = []
        observed_at = None
        age = None
        if len(matches) != 1:
            issues.append('Contrato ausente na fonte.' if not matches else 'Contrato duplicado: correspondência ambígua.')
        else:
            row = matches[0]
            for field, expected in [('kind', leg['kind']), ('strike', leg['strike']),
                                    ('exercise', leg['exercise']), ('expiry', plan['expiry'])]:
                if row.get(field) != expected:
                    issues.append(f'Especificação divergente ou ausente: {labels[field]}.')
            # lot_reported is intentionally NOT treated as the verified trading lot.
            for field in ('multiplier', 'lot_size'):
                if number(row.get(field)) != plan[field]:
                    issues.append(f'Unidade não reconciliada: {labels[field]}.')
            observed_at = timestamp(row.get('observed_at'))
            if observed_at is None:
                issues.append('Horário original ausente ou sem fuso.')
            else:
                age = (now - datetime.fromisoformat(observed_at)).total_seconds()
                if age > 900:
                    issues.append('Cotação com mais de 15 minutos.')
                elif age < -60:
                    issues.append('Cotação no futuro.')
            bid, ask = number(row.get('bid')), number(row.get('ask'))
            if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
                issues.append('Livro ausente, inválido ou cruzado.')
            buying = (leg['side'] == 'buy') == (record['status'] == 'watching')
            size = number(row.get('ask_size' if buying else 'bid_size'))
            if size is None or size < leg['quantity'] or not size.is_integer():
                issues.append('Quantidade insuficiente ou não confirmada no lado necessário do livro.')
        legs.append({'symbol': leg['symbol'], 'observed_at': observed_at,
                     'age_seconds': round(age, 3) if age is not None else None,
                     'issues': issues, 'structural_checks_passed': not issues})
    return {'snapshot_id': snapshot['snapshot_id'], 'trade_id': record['id'],
            'provider': snapshot['provider'], 'checked_at': now.isoformat(),
            'fetched_at': snapshot['fetched_at'], 'data_mode': mode,
            'operation_status': record['status'], 'legs': legs,
            'blockers': list(dict.fromkeys(blockers)), 'eligible_for_observation': False,
            'eligible_for_live_trading': False,
            'note': 'Diagnóstico somente: não atualiza cotações do formulário, não cria eventos e não atesta execução.'}

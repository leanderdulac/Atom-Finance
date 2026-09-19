# Pipeline paper ETH/SOL — arbitragem estatística

Pesquisa / diário simulado. **Não envia ordens, não assina chaves privadas de corretora e não autoriza capital.** `eligible_for_live_trading` permanece `false`.

Par padrão: perpétuos `ETHUSDT` (y) e `SOLUSDT` (x), nomenclatura Binance USDM. Um único par.

## Seis camadas

| Camada | O que faz | Default |
|---|---|---|
| 1. Dados | Alinha marcas por timestamp; recusa NaN/Inf; documenta buracos (nunca interpola) | intervalo 1h; livro = mid ± 2 bps se o caller não mandar bid/ask |
| 2. Sinal | Engle–Granger (ADF / MacKinnon), β de hedge, half-life OU no residual, z rolante causal | p ≤ 0,05; half-life ≤ 48 barras; janela z = 60 |
| 3. Decisão | Entra se \|z\| > entry; sai se \|z\| < exit. +1 = long spread (long y / short x) | entry 2,0; exit 0,5 |
| 4. Risco | Teto de posição, teto de drawdown, kill switch que **achata o livro paper antes de qualquer fill seguinte** | \|pos\| ≤ 1; DD ≤ 15% |
| 5. Execução paper | Compra no ask, venda no bid; taxa taker; inventário nas duas pernas; reconciliação | 4 bps taker; sem OMS |
| 6. Monitoração | PnL líquido de custos, inventário, drawdown, flags de gap/latência, motivo do kill | curva amostrada |

O sinal no fecho `t` usa só informação ≤ `t`. O fill paper é o bid/ask da barra `t+1`. Um furo entre `t` e `t+1` é flag, não um mid inventado; não se abre posição através do buraco.

A porteira Engle–Granger + half-life corre só no prefixo de warmup (`gate_n = max(60, min(warmup, n/2))`, default 200), antes de qualquer fill. O hedge e o z **dentro** do loop são expansivos / rolantes — sem olhar o futuro da barra. Símbolos fora de `{ETHUSDT, SOLUSDT}` são recusados (não viram proxy Binance). ADF em 60 barras quase não tem poder — daí o default 200, ainda sem ver a metade que se transaciona.

## O que nunca acontece

- Ordem real, conta Binance, `BINANCE_API_KEY` / secret para trading.
- OMS, DEX, broker execute. O kill switch só zera o livro **paper**.
- Promoção a evidência: isso não é `POST /api/ml/evaluate`. Backtest é pesquisa.
- `eligible_for_live_trading=true`, em qualquer ramo (aceito, rejeitado, kill, demo).

## Como correr

Sintético (sem rede; é o caminho dos testes):

```bash
cd backend
python -m app.models.stat_arb_paper --demo
```

API autenticada, mesmo DGP sintético:

```http
POST /api/desk/pairs/eth-sol-paper
{"demo": true, "n": 400, "seed": 2}
```

Séries do caller (mids alinhados, timestamps opcionais em ms):

```http
POST /api/desk/pairs/eth-sol-paper
{"y_mid": [...], "x_mid": [...], "timestamps": [...]}
```

Histórico público de *mark price* (unsigned `fapi/v1/markPriceKlines`, sem chaves):

```bash
cd backend
python -m app.models.stat_arb_paper --fetch --interval 1h --limit 500
```

```http
POST /api/desk/pairs/eth-sol-paper
{"fetch_public": true, "interval": "1h", "limit": 500}
```

Se a porteira falhar (não cointegrado, ou half-life > 48 barras), a resposta vem com `accepted=false`, `rejection.reason` e **zero fills**. Não é um 500.

## Testes

```bash
cd backend
ATOM_SKIP_DB=1 pytest tests/test_stat_arb_paper.py -q
```

Cobrem half-life OU, portas de z, entry/exit, PnL com custo, flatten do kill switch, recusa de NaN e rejeição quando a cointegração / half-life falha. CI não precisa de rede.

## Relação com o que já existia

- `app/models/cointegration.py` — EG, ADF, hedge expansivo, `_half_life`.
- `app/models/mean_reversion.py` — half-life AR(1) reportado como checagem.
- `app/models/perp_arb.py` / `perp_collector.py` — basis cross-venue; este pipeline é **um** par, duas pernas, mesmo venue conceptual.
- `app/api/paper_trades.py` — diário manual de planos de opções. Este loop é um backtest paper fechado, não grava no diário.

Ver também [PAPER-TRADING.md](PAPER-TRADING.md) e [RESEARCH-POLICY.md](RESEARCH-POLICY.md).

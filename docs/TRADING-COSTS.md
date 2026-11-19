# Custos de execução (paper)

Pesquisa e simulação. Nenhum destes caminhos envia ordem, assina chave de corretora ou autoriza capital. `eligible_for_live_trading` permanece `false`.

O modelo vive em `backend/app/models/trading_costs.py`. Backtest, forward test, pares, meta-label e o loop paper ETH/SOL chamam esse módulo. Não há uma segunda fórmula de taxa.

## O que entra no custo de um fill

Contra o mid, o custo de um fill é

```
fee + half_spread + slippage − spread_capture
```

| Peça | De onde vem | Quando não há livro |
|---|---|---|
| `fee` | Agenda maker/taker do venue (`VENUE_FEES`). Dá para sobrepor em bps. | A taxa continua a ser cobrada. |
| `half_spread` | `(ask − mid)` numa compra, `(mid − bid)` numa venda, no toque da barra. | Estimativa `fallback_half_spread_bps` (default 2 bps, o antigo “slippage” dos pares). `spread_source = "estimate"` e `flagged_estimate = true`. Um bid/ask sintético (mid ± bps) também é estimativa, mesmo que o número venha do quote. |
| `slippage` | `impact_bps × (quantidade / profundidade do lado agredido)`. Default `impact_bps = 10`: 10 bps extra quando a ordem empata o tamanho visível no toque. | Sem profundidade não se inventa uma caminhada. `fallback_slippage_bps` default 0, `slippage_source = "estimate"`, flag ligado. |
| `spread_capture` | Só no maker: melhora do limite contra o mid. Reduz o custo total. | Limite sem livro descansa no mid; captura 0. |

Cada fill guarda `fee`, `half_spread` e `slippage` separados. O PnL líquido sai dessas peças, não de um desconto único no fim.

Agenda usada na pesquisa (não é um pull ao vivo da corretora):

| Venue | Maker bps | Taker bps |
|---|---|---|
| `binance_usdm` | 2 | 4 |
| `okx` | 2 | 5 |
| `hyperliquid` | 1,5 | 3,5 |
| `b3` | 5 | 5 |
| `crypto_spot` | 10 | 10 |

Nos relógios que já cobravam `commission + slippage` como fração (backtest de um nome, forward test, `pairs_backtest`), a soma das peças continua igual a esse total. A novidade é a separação e, no paper, o slippage que cresce com o tamanho.

## Quatro pernas

Num par, cada perna paga a taxa do seu próprio nocional. Os dois nocionais somam o nocional bruto, e o livro paga isso para entrar e de novo para sair:

```
custo_4_pernas = 2 × (fee + half_spread + slippage) / 10_000
```

do nocional bruto. O limiar de entrada tem de cobrir esse custo, não o de uma perna só.

## Entrada

Só se entra quando

```
ganho_esperado ≥ k × custo_de_ida_e_volta
```

`k` default 2. `k ≤ 0` desliga a porteira (para repetir um caminho antigo). Entrada não finita não abre.

Em pares, o ganho esperado é a reversão de \|z\| até o `exit_z`, em retorno sobre o nocional bruto: `max(|z| − exit_z, 0) × (desvio_do_residual / nocional_bruto)`. No paper ETH/SOL a mesma conta é em dólares, contra `2 × (custo_y + custo_x)` cotados no livro da barra de fill.

## Liquidez

`max_spread_bps` default 25 (spread cheio, não a meia). `min_volume` default 0 desliga o piso. Se o piso é positivo e o volume não veio na barra, o motivo é `volume_unavailable` — a barra não é tratada como líquida. Sinais pulados ficam em `skipped_signals` com o motivo (`spread`, `volume`, `volume_unavailable`, `expected_gain`).

Um livro sintético de 2 bps de meia-spread tem ~4 bps de spread cheio, abaixo do default 25, por isso o filtro de spread não apaga o demo.

## Limite (maker)

`execution="maker"` no paper, ou `order_style="limit"` no simulador de níveis e no `BacktestEngine`. O limite só preenche quando o preço cruza o nível (estar em cima do nível no início não conta). `limit_timeout_bars` default 5, inclusivo. O resultado traz `fill_rate`, `n_filled`, `n_expired` e `n_unfilled`. No par, as duas pernas têm de cruzar dentro do timeout; se uma falha, a ordem expira inteira (não fica inventário parcial). Kill e o flatten de fim de amostra continuam taker: o livro paper tem de poder ficar flat.

## Rótulos e DSR

As barreiras triplas e o registo de trials usam o retorno já líquido desse custo. `costs_included=True` só quando o modelo foi aplicado e o custo de ida e volta é positivo. Série bruta, custo zero, ou um stub de zeros não leva o flag.

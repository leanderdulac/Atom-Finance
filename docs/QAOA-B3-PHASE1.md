# Fase 1 — seleção de subconjunto na carteira small cap da B3

Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`. Passar o critério abaixo continuaria paper.

Este estudo não altera a carteira de paper A (núcleo passivo) nem a carteira B (small caps de peso igual travada no PR #67). A regra de universo é lida; o livro de paper não é reescrito.

A pergunta é se um subconjunto de K nomes, peso igual `1/K`, escolhido só com dados até 2018-12-31, supera o critério fora da amostra. O QAOA no simulador clássico Aer é um dos solvers. Este repositório não o executa: publica o painel causal, confere a seleção que volta e marca todos os solvers no mesmo simulador de custos do PR #67.

## Universo, travado

Em cada rebalanceamento trimestral o universo é o da manga escolhida no PR #67 (`backend/app/models/equal_weight.py`):

| Peça | Valor |
|---|---|
| Universo | `small`: 30% menor valor de mercado point-in-time, financeiro de fora |
| Piso de ADV | R$ 200 mil, mediana de 60 pregões, pelo menos 20 negócios, negócio nos últimos 5 pregões |
| Emissor | 1 ticker, o de maior ADV |
| Piso de nomes | menos de 15 e o livro fica em caixa |
| Sinal | último pregão de março, junho, setembro e dezembro |
| Execução | pregão seguinte. Quem permanece é redimensionado, sem vender e recomprar o bloco |
| Custo | taxa taker B3, meio spread e slippage de participação, teto de 5.000 bps (`trading_costs` via `price_fill`) |
| Provento | dividendo com rótulo isento; JCP com rótulo retém 15%; evento sem rótulo retém 15% |
| Deslistagem | 10 pregões sem negócio: venda no último preço |
| Caixa parado | rende zero. O CDI é só o custo de oportunidade |

O primeiro sinal publicado da família é 2012-05-02. O calendário desta fase é o trimestral, então o primeiro `t_r` é o fim de junho de 2012. 2012-05-02 não é um rebalanceamento. 31/03/2012 fica de fora porque é anterior a 2012-05-02. Não há rebalanceamento em 2010, mesmo que o cache de preços comece em 2011.

Desenho: mês a mês até 2018-12-31, no mínimo 36 meses. Fora da amostra: 2019-01-01 até o último pregão do cache (no estudo de peso igual, 2026-11-19). A regra não é reotimizada depois do corte. O caminho não é zerado no corte: a carteira entra em 2019 com as posições que já tinha.

## O que cada arquivo contém

O exportador oficial é `scripts/export_qaoa_b3_snapshots.py`. O esquema é o mesmo que o Quantum Lighting lê em `/workspace/qaoa-b3/inputs/`.

| Arquivo | Quem usa | Conteúdo |
|---|---|---|
| `YYYY-MM-DD.parquet` | seleção | só informação com data ≤ `t_r` |
| `YYYY-MM-DD.json` | seleção | o mesmo painel em JSON, com `mu`, `Sigma` e o hash |
| `holdout/YYYY-MM-DD_fwd.parquet` | ninguém na seleção | retornos realizados em `(t_r, próximo t_r]` |
| `/workspace/qaoa-b3/outputs/selections.parquet` | validador | a carteira escolhida em cada data |

O painel da amostra inteira fica em `docs/reports/qaoa-b3/snapshots/` e não entra no git. O exemplo versionado está em `docs/reports/qaoa-b3/fixtures/`. Sem o cache de preços o exportador não inventa a amostra: ele avisa e sai.

`schema_version` do painel: `qaoa-b3-snapshot-1`. Da seleção: `qaoa-b3-selection-1`. Do holdout: `qaoa-b3-holdout-1`.

### Colunas do parquet de seleção

Uma linha por (ticker, pregão com retorno). Ticker sem nenhum retorno diário ganha uma linha com `adj_return` nulo, só para permanecer no universo. Livro em caixa: uma linha com `ticker` vazio.

| Coluna | Sentido |
|---|---|
| `rebalance_date`, `as_of` | `t_r`, iguais |
| `estimation_end` | último pregão que entra em μ e Σ. Fica 5 pregões antes de `t_r` |
| `session_date` | data do retorno. Nunca depois de `t_r` |
| `ticker`, `cnpj` | papel e emissor |
| `adv_brl`, `adv_shares`, `mcap` | ADV e valor de mercado em `t_r` |
| `close`, `bid`, `ask` | cotação usada no custo, em `t_r` |
| `adj_return` | retorno diário ajustado. Nulo na linha de presença |
| `in_estimation` | `session_date` ≤ `estimation_end` |
| `in_mu_window` | dentro das últimas 252 sessões até `estimation_end`. É o que entra em μ e Σ |
| `n_history` | retornos válidos até `t_r` |
| `n_estimation` | retornos com `in_mu_window` |
| `estimable` | `n_estimation` ≥ 60 |
| `mu` | média desses retornos, ou nulo |
| `sigma_index` | linha em Σ, ticker em ordem alfabética entre os estimáveis. −1 se de fora |
| `cost_*_bps_aum_100k`, `cost_*_bps_aum_1m` | ida, volta e ida-e-volta em bps |
| `cost_notional_aum_*` | AUM / N do universo naquele dia |
| `k_min`, `k_max` | 15 e 20 |
| `lambda_grid` | `0.5,1,2,5` |
| `embargo_sessions`, `mu_window_sessions`, `mu_min_obs`, `holding_sessions` | 5, 252, 60, 63 |
| `universe_rule` | texto da regra |
| `snapshot_hash` | SHA-256 do payload canônico |
| `eligible_for_live_trading` | `false` |

R$ 100 mil é a AUM de capacidade folgada. R$ 1 milhão é a AUM de seleção do PR #67. O bps do arquivo usa notional = AUM / N do universo. Não é o custo de um subconjunto de K nomes: esse custo escala a quantidade e pode bater no teto de slippage. Quem penaliza custo dentro do objetivo recalcula com notional = 1.000.000 / K, pela função `quote_cost` (mesmos `close`, `bid`, `ask`, `adv_brl`, `adv_shares`).

### JSON irmão

`payload` é o objeto hasheado. `definitions` repete as fórmulas em texto. `snapshot_hash` é o SHA-256 hex de `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. Floats entram com 10 casas. O campo do hash não entra no hash.

`payload.sigma.tickers` é a ordem das linhas. `payload.sigma.matrix` é Σ. `payload.sigma.method` é `ledoit_wolf_constant_correlation`, `diagonal_fallback`, `single_name` ou `none`.

### Holdout

Colunas: `rebalance_date`, `next_rebalance_date`, `session_date`, `ticker`, `adj_return`, `selection_snapshot_hash`, `holdout_hash`, `purpose` = `not_for_selection`. Toda `session_date` é posterior a `t_r`. O último trimestre do cache corre até o último pregão e `next_rebalance_date` fica vazio.

O holdout não é o PnL oficial. O PnL oficial é o `simulate_book` do PR #67, com custo, provento, desdobramento confirmado, resize e saída de papel sem negócio.

## Retorno, μ, Σ e objetivo

Retorno diário ajustado, só quando o papel negocia em `t` e no pregão de mercado imediatamente anterior:

```text
r_t = f_t * (P_t + d_t) / P_{t-1} - 1
```

`f_t` é o fator de desdobramento confirmado por protocolo de capital; sem confirmação, `f_t = 1` e o salto de preço fica no retorno. `d_t` é o provento depois do imposto, em reais por ação corrente. Dividendo com rótulo: alíquota 0. JCP com rótulo: 15%. Evento sem rótulo: 15%. Valor por ação maior que o fechamento anterior é descartado. Um buraco de mais de um pregão não vira retorno diário: o movimento do buraco não entra em μ nem em Σ.

μ e Σ usam só as linhas `in_mu_window`. A janela é de no máximo 252 pregões e termina em `estimation_end`. Nome com menos de 60 retornos nessa janela fica no universo (o peso igual do universo pode carregá-lo) e fica de fora de μ, de Σ e dos otimizadores.

Σ é Ledoit–Wolf com alvo de correlação constante, `Σ_LW = α* F + (1−α*) S`, S a covariância amostral 1/T nos pregões em que todos os nomes estimáveis têm retorno. Se sobram menos de 8 pregões completos, Σ é diagonal: variância MLE de cada nome, covariância zero.

Objetivo, em unidades do trimestre, com `H = 63` pregões fixos (não se conta o número realizado de pregões até o próximo rebalanceamento):

```text
score(x) = (H/K) x·μ − λ (H/K²) x′Σx − (1/K) x·c
```

`x` é binário, soma K, e só nome estimável entra. `c_i` é a fração de ida e volta em notional = R$ 1.000.000 / K. A grade travada, antes de ler 2019–2026, é:

- K ∈ {15, 16, 17, 18, 19, 20}
- λ ∈ {0.5, 1, 2, 5}

## Solvers

O nome canônico é o da esquerda. O da direita é o alias aceito na leitura.

| Canônico | Alias | Quem gera neste PR |
|---|---|---|
| `equal_weight37` | `equal_weight_universe` | sim. Universo inteiro do dia. K = N do dia, que varia (mediana histórica ~37). Não é K fixo |
| `equal_weight_k` | — | sim. Os K de maior ADV, desempate por ticker. Não usa λ |
| `random_K` | `random_k` | sim. Amostra sem reposição, seeds 7 e 11, população em ordem de ticker, gerador PCG64. Não usa λ |
| `milp_exact` | — | sim, se o HiGHS do SciPy resolver o MIP. Linearização de `x_i x_j`. Uma data sem ótimo vira caixa |
| `sa` | `simulated_annealing` | sim. Annealing determinístico, seed 7, 400 passos, T0 0,02, resfriamento 0,995 |
| `qaoa_aer` | — | não. Slot de validação. `p` ∈ {1, 2} |

`equal_weight37` é a baseline do PR #67 nesse calendário. Não é candidata a ser "a regra escolhida": é o comparador. As outras são candidatas. `equal_weight_k` é baseline da mesa, fora da grade λ.

Se o arquivo de seleções já traz um solver, o harness usa essas linhas e não gera outra grade para o mesmo solver. Solver ausente, exceto `qaoa_aer`, é preenchido pela implementação clássica. Cada especificação tem de cobrir todas as datas de rebalanceamento, com uma linha por data. Data sem nome (lista vazia) é caixa. Data faltando rejeita o arquivo.

## Como devolver as seleções

Um parquet (ou um JSON com uma lista) em `/workspace/qaoa-b3/outputs/selections.parquet`. Uma linha por (`rebalance_date`, solver, K, λ, p, seed).

| Coluna | Obrigatória | Regra |
|---|---|---|
| `rebalance_date` | sim | uma das datas do painel |
| `solver` | sim | nome canônico ou alias |
| `K` | sim para subconjunto | 15–20. Em `equal_weight37`, o N daquele dia, ou nulo |
| `lambda` | sim para `milp_exact`, `sa`, `qaoa_aer` | 0,5, 1, 2 ou 5. Nulo nos outros |
| `p` | sim para `qaoa_aer` | 1 ou 2. Nulo nos outros |
| `tickers` | sim | lista de strings, ou texto separado por vírgula. Subconjunto do universo daquela data. A ordem não importa |
| `n_trials_total` | não | informativo. O DSR não usa este número |
| `seed` | não | inteiro ≥ 0. Distingue dois `random_K` do mesmo K |

Não incluir retorno realizado, coluna com `oos`, `holdout`, `forward` ou `future`, nem ler o diretório `holdout/` para escolher o papel. Ticker ausente do universo daquela data é rejeitado. `equal_weight37` com K = 37 quando o universo do dia tem outro tamanho é rejeitado.

O validador é `scripts/validate_qaoa_b3_selections.py --selections <arquivo>`.

## Walk-forward, critério e N

A estimação de μ e Σ para o sinal `t_r` termina 5 pregões antes. O negócio sai no pregão seguinte a `t_r`. O mês fechado até 2018-12-31 escolhe a regra. O mês fechado a partir de 2019-01-01 avalia. Empate na janela de desenho: maior CAGR de desenho, menor giro, menor K, menor λ, nome do solver, menor `p`, menor seed.

Critério, o mesmo do PR #67: DSR ≥ 0,95 **e** excesso de CAGR líquido sobre o CDI > 0, os dois fora da amostra. Cumprir os dois ainda é paper.

O N do DSR, do PSR e do MinTRL soma:

1. os trials novos deste estudo, um por caminho registrado no `TrialRegistry` (`b3_qaoa_portfolio`);
2. os 32 trials rejeitados do net-net, gravados em todo registry;
3. os 55 trials da família `b3_equal_weight`. Se o sqlite dessa família não está acessível, entra a contagem publicada em `docs/reports/equal-weight-b3.json`;
4. os trials de fatores do PR #56 **somente** quando um registry acessível tem uma família cujo nome contém `factor`. Esse bloco não está no registry do PR #67. Enquanto não aparecer, o N da decisão não soma os 24. O relatório guarda a coluna de transparência `n_decision + 24` e deixa escrito que ela não é o N do DSR.

N efetivo por correlação não substitui o N.

O relatório também traz, para cada caminho e para a regra escolhida: CAGR bruto e líquido, Sharpe, max drawdown, giro de mão única, capacidade a 10% do ADV, excesso líquido contra o CDI e contra `equal_weight37`, PSR, DSR, MinTRL e os anos com retorno líquido negativo. A AUM de R$ 100 mil da regra escolhida é auditoria: entra no N e não pode ser a regra escolhida.

## O que este PR já fecha

- Contrato do painel, do holdout e da seleção, com hash.
- Exportador e validador.
- Baselines clássicas determinísticas: `equal_weight37`, `equal_weight_k`, `random_K`, `milp_exact`, `sa`.
- Testes sem rede: causalidade, embargo, ticker fora do universo, walk-forward que ignora o fora da amostra, N com os trials anteriores, e o universo inteiro reproduzindo o `simulate_book` do PR #67.

## O que espera o Quantum Lighting

Seleções `qaoa_aer` com `p` em {1, 2}, na grade K × λ, cobrindo cada `t_r`, no parquet de saída. Se `milp_exact`, `sa` ou `random_K` também forem devolvidos, o harness usa essas linhas no lugar da grade gerada aqui.

## Veredito parcial

**Inconclusivo.** O cache de preços não está disponível neste ambiente, então nenhum caminho de 2012 a 2026 foi marcado. Não há seleção `qaoa_aer` para validar. As baselines existem e os testes offline passam no exemplo de esquema. Isso não é evidência de prêmio.

Números de contrato e a contagem de trials anteriores: `docs/reports/qaoa-b3/phase1.json`.

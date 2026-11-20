# Fatores de horizonte longo na B3 (paper)

Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`.

Pergunta: momentum 12-1, qualidade, baixa volatilidade, ou um composto de rank igual, com rebalanceamento mensal ou trimestral, sobrevive a custo, ao deflacionamento por todas as variações, e a um excesso líquido sobre o CDI fora da amostra?

Resposta deste estudo: **não**. A manga escolhida na janela de desenho foi baixa volatilidade mensal, com PL de R$ 1 milhão. Fora da amostra o DSR é 0,14 (o corte é 0,95, com N = 24) e o CAGR líquido fica 4,9 pontos abaixo do CDI. Nenhuma das oito mangas a R$ 1 milhão tem excesso líquido positivo sobre o CDI fora da amostra.

## Regra, fixada antes de ler o resultado

Quatro fatores, dois calendários, três patrimônios. São 24 trials da família `b3_long_horizon_factors`. O DSR de cada um usa N = 24, pela via de `gate` com `n_eff` nulo. O N efetivo por correlação (1,13, correlação média 0,88) fica no JSON e não é o N do DSR.

| Fator | Definição | Direção |
|---|---|---|
| `momentum_12_1` | fechamento ajustado do fim do mês t−1 sobre o fim do mês t−12, menos um | maior é melhor |
| `quality` | média dos percentis de ROE, ROIC, margem e patrimônio/ativo, com pelo menos dois | maior é melhor |
| `low_vol` | desvio-padrão de até 252 retornos de fechamento, mínimo 120, buraco de no máximo 5 dias, vezes √252 | menor é melhor |
| `composite` | média dos três percentis, refeita dentro da interseção | maior é melhor |

O mês do sinal não entra no momentum. ROE é lucro dos doze meses sobre o patrimônio. ROIC é EBIT dos doze meses vezes `(1 − alíquota)` sobre patrimônio + dívida − caixa. A alíquota é `(EBT − lucro) / EBT`, cortada entre 0 e 0,45; se o EBT não serve, usa-se 0,34. Margem é EBIT sobre receita, ou lucro bruto sobre receita se o EBIT falta. Dívida é a soma de `2.01.04` e `2.02.01`; se só uma conta veio, a outra entra como zero; se nenhuma veio, o ROIC fica de fora. Caixa ausente também tira o ROIC. Número negativo é score. Ausente não vira zero.

Financeiro (o mesmo conjunto do estudo de net-net) sai da qualidade e, por isso, do composto. Continua no momentum, na baixa volatilidade e no peso igual do universo.

Carteira: peso igual no quintil superior. Menos de 25 nomes com score e o livro fica em caixa. Um papel por companhia, o de maior ADV. Liquidez: mediana de 60 pregões do volume em reais pelo menos R$ 1 milhão, e negócio nos últimos 5 dias. O sinal é o fechamento do fim do mês, ou do fim do trimestre (março, junho, setembro, dezembro). O fill é o pregão seguinte. O caixa parado rende zero. O CDI é benchmark, não crédito dentro do livro.

O relógio é o do momentum: o primeiro sinal só existe quando há doze meses de formação. As quatro mangas usam esse mesmo calendário, então são um experimento.

## Custo e capacidade

O fill é o de `trading_costs.quote_fill`, o mesmo do net-net: taxa taker B3 de 5 bps, meio spread, slippage de participação com profundidade de 1% do volume mediano em ações e teto de 5.000 bps. Nome que continua na carteira muda de tamanho. Não é vendido e recomprado. Bruto e líquido carregam as mesmas ações. O bruto gira ao mid.

Capacidade, em cada rebalanceamento com nome, é `10% × ADV × N`. “Típica” usa o ADV mediano. “Tênue” usa o menor ADV. O número do relatório é a mediana desses rebalanceamentos. Giro de mão única é a média de metade da distância L1 dos pesos, depois da montagem inicial, vezes 12 ou vezes 4.

## Fora da amostra

Não é walk-forward. Um corte só, marcado antes de ler resultado.

- Desenho: retornos mensais com fim de mês até 2018-12-31. São 96 meses. O primeiro ano é caixa, porque a formação de doze meses ainda não existe.
- Escolha: entre as 8 mangas (4 fatores × 2 frequências) com PL de R$ 1 milhão, o maior Sharpe líquido de desenho. Empate vai para o maior CAGR de desenho, depois o menor giro, depois mensal, depois o nome do fator. Precisa de pelo menos 36 meses.
- Avaliação: essa manga, de 2019-01-01 até o fim da amostra (95 meses). O caminho não é zerado no corte. As variantes de PL (R$ 100 mil e R$ 10 milhões) entram no N e não podem ser escolhidas.
- Critério: DSR ≥ 0,95 nos retornos líquidos mensais fora da amostra, com N = 24, e CAGR líquido fora da amostra menos o CAGR do CDI no mesmo intervalo > 0.

A manga escolhida foi `low_vol` mensal. Sharpe de desenho 0,61, CAGR de desenho 7,6%.

## Dados

O mesmo painel point-in-time do net-net. COTAHIST 2011-01-03 a 2026-11-19, 3.941 pregões, inclusive quem deixou de negociar. Fundamental da CVM visível só com `DT_RECEB` no dia do sinal ou antes. Quantidade de ações do FRE e de `composicao_capital`. 178 sinais mensais e 59 trimestrais.

Qualidade usa as contas `1` (ativo), `2.03.01` (patrimônio), `1.01.01` (caixa), `2.01.04` e `2.02.01` (dívida), `3.01` (receita), `3.03` (lucro bruto), `3.05` (EBIT), `3.07` (EBT) e `3.11` ou `3.09` (lucro). Uma linha de fluxo só gruda numa linha que já tem lucro. Um balanço só vira ponto se tiver ativo circulante, passivo circulante e passivo não circulante, a mesma exigência do net-net: um protocolo incompleto não pode virar um ponto mais novo e apagar o anterior.

CDI: série 12 do SGS (Banco Central), de 2010-01-04 a 2026-11-19. O campo `valor` é percentual ao dia (`0,043739` é 0,043739%) e entra dividido por 100. O crescimento no intervalo é o produto de `(1 + taxa)` nos dias úteis `(início, fim]`.

Ibovespa: nível oficial diário. A metodologia da B3 define o índice como retorno total bruto, então o dividendo em dinheiro já está na série. Sem dividendo extra e sem custo de investidor. A série deste corte vai até 2026-11-17.

Estados Unidos: não estimado. Não há painel gratuito de ação e ETF americano que seja point-in-time e mantenha o nome cancelado. Uma lista de sobreviventes de uma API de gráfico não é este estudo. Nenhum número americano entra no relatório.

## Resultado a R$ 1 milhão

Amostra de preço 2011-01-03 a 2026-11-19. Trilha cheia de 191 meses. PSR contra Sharpe zero. MinTRL infinito em todas as linhas: o Sharpe observado não supera o Sharpe de referência do DSR com N = 24.

| Fator | Rebal. | CAGR bruto | CAGR líq. | Sharpe | Max DD líq. | PSR | DSR | Giro | Cap. típica / tênue | OOS CAGR líq. | OOS DSR | OOS − CDI |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| momentum 12-1 | mês | 4,0% | 2,2% | 0,21 | −54,6% | 0,79 | 0,12 | 2,89 | R$ 44 mi / R$ 3,4 mi | 5,1% | 0,13 | −4,5 pp |
| momentum 12-1 | trim. | 4,0% | 3,0% | 0,25 | −54,1% | 0,83 | 0,16 | 1,66 | R$ 44 mi / R$ 3,1 mi | 6,7% | 0,16 | −2,9 pp |
| qualidade | mês | −0,8% | −2,0% | 0,01 | −54,6% | 0,51 | 0,03 | 1,09 | R$ 31 mi / R$ 3,2 mi | −3,9% | 0,02 | −13,5 pp |
| qualidade | trim. | −1,3% | −2,0% | 0,00 | −54,7% | 0,51 | 0,02 | 0,73 | R$ 31 mi / R$ 3,1 mi | −3,1% | 0,02 | −12,7 pp |
| baixa vol. | mês | 6,9% | 6,1% | 0,45 | −39,3% | 0,95 | 0,39 | 1,27 | R$ 61 mi / R$ 3,6 mi | 4,6% | 0,14 | −4,9 pp |
| baixa vol. | trim. | 6,2% | 5,8% | 0,44 | −37,1% | 0,95 | 0,37 | 0,81 | R$ 66 mi / R$ 3,6 mi | 5,7% | 0,17 | −3,9 pp |
| composto | mês | 5,1% | 3,9% | 0,32 | −41,1% | 0,88 | 0,21 | 2,07 | R$ 62 mi / R$ 3,3 mi | 4,3% | 0,12 | −5,3 pp |
| composto | trim. | 3,5% | 3,0% | 0,26 | −41,0% | 0,84 | 0,17 | 1,22 | R$ 62 mi / R$ 3,3 mi | 5,7% | 0,17 | −3,9 pp |

A linha escolhida é a baixa volatilidade mensal. Fora da amostra o PSR é 0,82, o DSR é 0,14, o CAGR líquido é 4,6% e o CDI no mesmo intervalo é 9,6%. O critério não passa. Passar ainda seria paper. Não autoriza capital.

Nos três patrimônios o CAGR líquido da baixa volatilidade mensal é 6,4% (R$ 100 mil), 6,1% (R$ 1 milhão) e 3,8% (R$ 10 milhões). O excesso fora da amostra sobre o CDI é −4,6, −4,9 e −7,3 pontos. A perna tênue da capacidade fica em torno de R$ 3 milhões a R$ 4 milhões, então R$ 10 milhões já passa do nome mais fino a 10% do ADV. A R$ 1 milhão nenhum fill dessa grade bateu no teto de 5.000 bps. A mediana de nomes fica entre 19 e 22, e nenhum rebalanceamento ficou em caixa.

## Benchmarks

Não são trials.

| Benchmark | CAGR | Sharpe | Max DD |
|---|---:|---:|---:|
| CDI, amostra cheia (SGS 12) | 9,9% | — | — |
| CDI, janela fora da amostra | 9,6% | — | — |
| Ibovespa, retorno total oficial, diário, sem custo | 5,7% | 0,37 | −47,7% |
| Peso igual do universo líquido, mensal, líquido | 11,7% | 0,52 | −51,5% |
| Peso igual do universo líquido, trimestral, líquido | 10,5% | 0,48 | −50,4% |

O peso igual mensal, no bruto, faz 12,2%. O giro de mão única é 0,35 ao ano no mensal e 0,26 no trimestral, com mediana de 111 nomes. O fator perde para o peso igual do próprio universo e para o CDI. A baixa volatilidade líquida (6,1%) fica perto do Ibovespa (5,7%) na amostra cheia e abaixo do CDI.

## Limites

Retorno de ação e do peso igual é retorno de preço. Dividendo não está na fita. O Ibovespa oficial já reinveste o dividendo, e o CDI é juros. A comparação do fator com esses dois benchmarks é mais dura do que uma comparação de preço contra preço. O peso igual do universo é a comparação justa: também não tem dividendo.

Quem para de negociar sai no último negócio, no pregão seguinte. Isso viesa para cima se a quebra vem depois do pregão congelado. Cancelada sem preço não recebe preço zero. O mesmo viés do estudo de net-net vale aqui.

O ajuste de grupamento ou desdobramento usa um protocolo de capital que pode ser posterior ao pregão do salto (até 250 dias) como registro do evento, não como informação do sinal. Salto sem esse protocolo continua no retorno.

Qualidade não vê protocolo sem lucro, nem balanço sem as três contas que o net-net exige. Financeiro fica de fora da qualidade e do composto. O composto só existe para quem tem os três fatores ao mesmo tempo.

O primeiro ano da janela de desenho é caixa. Isso puxa o Sharpe de desenho para zero e está dentro da regra: a manga ainda não tinha formação.

Números completos, inclusive a série mensal de cada trial: `docs/reports/long-horizon-factors.json`.

# Net-net de Graham na B3 (paper)

Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`.

Pergunta: a regra de net-net de Graham, no desenho testado por Greenblatt, Pzena e Newberg (Journal of Portfolio Management, 1981), sobrevive a custo realista e ao deflacionamento por todas as variações quando aplicada à B3?

Resposta deste estudo: **não**. Nos quatro filtros primários o CAGR líquido fica entre −21% e −24% ao ano, o Sharpe líquido é negativo, o DSR com N = 32 é essencialmente zero e o MinTRL é infinito. O livro de 1981 (melhor filtro, 42% a.a. bruto e 29% líquido, OTC americano, 1972–1978) não se reproduz aqui.

Em 2026-11-20 a mesa descartou a regra. As 32 variações entram no `TrialRegistry` (família `b3_graham_net_net`, status `rejected`) com Sharpe, PSR, DSR, MinTRL, CAGR bruto e líquido e as datas da amostra. É o mesmo registro que o DSR consulta: `gate_trial` de outra família soma essas 32 à contagem bruta de trials. `eligible_for_live_trading` permanece `false`. O código do backtest não faz parte deste registro; fica no branch `cursor/b3-net-net-graham-a7b2`.

## Regra

Valor de liquidação por ação ordinária:

```
LV = (ativo circulante − passivo circulante − passivo não circulante − preferencial) / ON em circulação
```

No Brasil a preferencial não é um passivo. Lei 6.404/76 e o CPC colocam PN no patrimônio líquido. O direito medido aqui é o capital social realizado (conta `2.03.01`) vezes a fração das ações preferenciais subscritas no total subscrito. Se existe PN e o capital social não veio no balanço, o nome fica de fora: não se assume preferencial zero. Passivo negativo, ativo circulante negativo ou LV que não dá para calcular também ficam de fora. LV negativo é um número real e não passa no filtro.

O teto de P/L de 1981 é um piso de earnings yield de duas vezes o rendimento do título, não “P/L ≤ 2 × o yield em pontos percentuais”. Com yield `y` em decimal, `P/L ≤ 1 / (2y)`. Um pré de 8% limita o P/L a 6,25. O filtro `pe5` usa P/L ≤ 5. Prejuízo nos doze meses anteriores elimina o nome. Quem não tem lucro publicado não entra: ausência não é lucro.

Quatro filtros, peso igual, saída em +100% ou 2 anos, rebalanceamento a cada 4 meses. O sinal usa o fechamento do pregão; a compra e a venda saem no pregão seguinte. Entre saídas o caixa rende zero.

| Filtro | P/LV | Teto de P/L |
|---|---|---|
| `plv1_ey` | ≤ 1,0 | `1 / (2 × pré)` |
| `plv085_ey` | ≤ 0,85 | `1 / (2 × pré)` |
| `plv1_pe5` | ≤ 1,0 | 5 |
| `plv085_pe5` | ≤ 0,85 | 5 |

## Dados

Fundamentals point-in-time da CVM (DFP e ITR em dados.cvm.gov.br), inclusive companhias com situação `CANCELADA`. Uma demonstração só entra quando `DT_RECEB` ≤ a data do sinal. Retificação substitui o número anterior só depois do protocolo dela. O preço do filtro é o fechamento desse pregão.

Contas, sem somar filhas: `1.01` ativo circulante, `2.01` passivo circulante, `2.02` passivo não circulante (não o passivo total, que inclui o patrimônio em `2.03`). Lucro: `3.11`, ou `3.09` se `3.11` não vier. Escala `MIL` multiplica por 1.000. Lucro por ação (`3.99.01`, reais por ação) não leva essa escala.

O lucro dos doze meses é a soma de quatro trimestres publicados em sequência (vão de 70 a 120 dias entre fins de período, e o último fim tem no máximo 200 dias). Sem isso, usa-se o anual cujo período acabou há no máximo 450 dias. O quarto trimestre, quando falta, é o anual menos o acumulado de nove meses, e só depois que os dois protocolos existem. Um acumulado de nove meses não vira um trimestre.

Quantidade de ações. O DFP traz `composicao_capital` a partir do arquivo de 2020. Antes disso a quantidade vem do Formulário de Referência (capital integralizado; se não houver, subscrito; se não houver, emitido). Capital autorizado é teto, não ação em circulação. A quantidade do FRE vale a partir do `DT_RECEB` daquela versão. Tesouraria do DFP sai das ações em circulação. No FRE, sai o saldo final do exercício mais recente no quadro de movimentação, quando esse saldo é menor que a classe. O direito do preferencialista continua sendo a quantidade integralizada, não a quantidade fora de tesouraria.

Parte dos emissores protocola a quantidade em milhares de ações e parte em unidades, no mesmo arquivo, sem coluna de escala. Quando `|lucro| / LPA / ações` cai entre 400 e 2.500, a quantidade é multiplicada por 1.000. Quando o lucro por ação não decide e o capital social por ação passa de R$ 2.000, a mesma correção é aplicada. Errar para cima tira o nome do filtro; errar para baixo fabricaria net-net. Neste corte, 5.798 pontos de capital foram reescalados.

Preços: COTAHIST, registro 01, lote padrão (BDI 02), mercado à vista (TPMERC 010), de 2011 a 2026. Inclui papéis que deixaram de negociar. Não há ajuste contínuo de proventos. O código passou a usar `backend/app/models/corporate_actions.py`. A janela de 250 dias foi retirada: um protocolo posterior ao pregão não confirma o salto. Os 71 pregões ajustados e os números deste arquivo são a corrida anterior e não foram recalculados.

Setores financeiros da CVM (bancos, seguradoras, arrendamento, intermediação, securitização, crédito imobiliário, bolsas, factoring e as holdings desses setores) ficam de fora. Holding de atividade real permanece.

## Custo

O fill usa `quote_fill` de `backend/app/models/trading_costs.py` (PR #53): taxa taker B3 de 5 bps, mais meio spread, mais slippage. O livro é o bid/ask do COTAHIST quando a largura está entre 0 e 2.000 bps. Sem livro utilizável, o spread cheio em bps é `min(500, max(10, 250.000 / sqrt(ADV em R$)))`: cerca de 25 bps com ADV de R$ 100 milhões, 250 bps com R$ 1 milhão, teto de 500 bps abaixo disso. A profundidade do toque é 1% do volume mediano em ações dos 20 pregões anteriores. O slippage é `10 bps × quantidade / profundidade`, com teto de 5.000 bps. Sem profundidade, o fallback é 200 bps. O filtro de 1981 não descarta nome por custo; o custo é ex post. Bruto e líquido carregam as mesmas ações. O bruto gira ao mid, sem taxa. O líquido paga o fill.

## O que foi registrado

Família `b3_graham_net_net` no `TrialRegistry`. 32 variações, definidas antes de ler resultado: os 4 filtros no pré de ~5 anos, fase 0, lag 0, PL de R$ 1 milhão; os mesmos 4 no pré mais longo; os 4 com lag extra de 63 dias; os 4 nas fases 1, 2 e 3; os 4 com PL de R$ 10 milhões e de R$ 50 milhões. Caminho bruto não entra no registro. O benchmark de small cap também não entra.

O DSR de cada uma usa N = 32, pela via de `gate` com `n_eff` nulo (erro-padrão teórico vezes z de N). O N efetivo por correlação (1,77, correlação média 0,55) fica no JSON e não é o N do DSR. PSR contra Sharpe zero. MinTRL em meses. `approved_for_paper` exige custo dentro do retorno, DSR ≥ 0,95 e trilha pelo menos tão longa quanto o MinTRL. Nenhum trial passou.

Proxies de yield, os dois do Tesouro Transparente (prefixado, taxa média de compra e venda da manhã). `pre_5y` é o prefixado com vencimento mais perto de 5 anos. `pre_long` é o prefixado mais longo do dia. IPCA+ é taxa real e não foi usado cru. Curva de debênture de alto grau (ANBIMA) não entrou: a série pública gratuita cobre poucos dias e a API pede `client_id`. Não se inventou spread de crédito.

## Resultado

Amostra de preço: 2011-01-03 a 2026-11-19. Primeiro sinal em ou depois de 2012-05-02. Na fase 0 o primeiro sinal efetivo é 2012-08-01. Trilha de 191 meses. PL inicial dos filtros primários: R$ 1 milhão.

No calendário primário (43 sinais) a mediana do universo com preço e fundamental é 183 nomes. A mediana com LV positivo é 45. A mediana com P/LV ≤ 1 é 4; com P/LV ≤ 0,85 é 3. Depois do teto de P/L a mediana cai para 0 (`plv1_ey`) ou 1 (`plv1_pe5`). O filtro de lucro, com yield prefixado entre cerca de 6% e 16%, é o que esvazia a carteira. Na maior parte dos rebalanceamentos o livro fica em caixa.

| Filtro | CAGR bruto | CAGR líq. | Sharpe líq. | Max DD líq. | PSR | DSR | MinTRL | Nomes (mediana, mín–máx) | Sinais com nome | Capacidade típica / tênue |
|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|
| `plv1_ey` | 2,5% | −24,3% | −0,29 | −99,3% | 0,13 | 0,0006 | infinito | 0 (0–2) | 20/43 | R$ 228 mil / R$ 20 mil |
| `plv085_ey` | 2,5% | −20,9% | −0,24 | −98,7% | 0,17 | 0,0012 | infinito | 0 (0–2) | 17/43 | R$ 386 mil / R$ 17 mil |
| `plv1_pe5` | 3,4% | −23,6% | −0,32 | −98,9% | 0,10 | 0,0004 | infinito | 1 (0–2) | 27/43 | R$ 168 mil / R$ 61 mil |
| `plv085_pe5` | 2,5% | −22,6% | −0,29 | −98,9% | 0,13 | 0,0007 | infinito | 1 (0–2) | 22/43 | R$ 272 mil / R$ 87 mil |

MinTRL infinito: o Sharpe observado não supera o Sharpe de referência do DSR, então não há trilha finita que aprove. 191 meses não resolvem isso. O melhor DSR da grade inteira é 0,010 (`plv085_ey`, fase 2), com CAGR líquido de −13%.

Capacidade é a mediana, entre os rebalanceamentos com algum nome, de `10% × ADV × N`. “Típica” usa o ADV mediano; “tênue” usa o menor ADV. R$ 1 milhão já passa da perna tênue. A R$ 10 milhões e a R$ 50 milhões o CAGR líquido do `plv1_ey` vai a −31% e −36%.

Saídas no `plv1_ey` primário: 6 por último negócio (nome que parou de negociar enquanto estava no livro), 2 por alta de 100%, 5 por prazo de 2 anos.

## Benchmarks

Small cap de peso igual, construído no mesmo universo point-in-time: 30% menores por valor de mercado, reconstituição total a cada 4 meses, os mesmos custos, PL de R$ 1 milhão, fase 0. Não é um trial. CAGR bruto 19,6%, líquido 6,6%, Sharpe líquido 0,41, max DD líquido −96%. O drawdown líquido muito pior que o bruto (−29%) é custo de girar small cap ilíquida, não uma queda de preço dessa magnitude.

Ibovespa, série de preço do índice (sem dividendo, sem custo de investidor): CAGR 5,6%, Sharpe 0,37, max DD −48%, na mesma janela. O SMLL não foi usado. Ele é ponderado por capitalização e não é este universo.

O net-net líquido perde para os dois. O bruto do net-net (2% a 3%) também perde, em parte porque o caixa parado rende zero na maior parte dos meses.

## Limites, sem tapá-los

Cobertura do cadastro CVM neste corte: 2.533 registros, 1.866 `CANCELADA`, 387 financeiros excluídos, 985 operacionais com balanço, 401 com ticker de ordinária na FCA, 334 com preço no COTAHIST.

67 companhias têm ordinária na FCA e balanço, e nenhum negócio no COTAHIST. Dessas, 16 são `CANCELADA` e 50 estão `ATIVO`. Não se imputou preço zero. Se as canceladas sem preço eram net-nets que foram a zero, o resultado aqui está viesado para cima. 584 operacionais com balanço não têm ordinária na FCA (301 `CANCELADA`): não chegaram a ser nome negociável neste corte, não são um preço faltante.

Quem está no livro e para de negociar sai no último negócio, no pregão seguinte. São as 6 saídas acima. Isso pode viesar para cima se a quebra vem depois do pregão congelado, e para baixo se um leilão de fechamento teria saído acima do último negócio.

Dividendos não entram. Isso empurra para baixo o net-net, o small cap e, no mesmo sentido, o Ibovespa de preço. O caixa a zero entre as raras posições empurra o net-net para zero antes mesmo do custo, e é mais duro do que render CDI.

A corrida publicada deste arquivo ajustou 71 pregões com um protocolo de capital que podia chegar depois do salto. Esse caminho saiu do código. A regra vigente está em `corporate_actions.py` e estes números não foram refeitos.

Números completos, inclusive a série mensal e o censo por sinal: `docs/reports/net-net-b3.json`. Esse arquivo é a evidência que o registro de trials relê. Não se recalcula o DSR publicado: a assimetria e a curtose da série mensal não são colunas do registro, então o PSR, o DSR e o MinTRL guardados são os deste relatório, com N = 32.

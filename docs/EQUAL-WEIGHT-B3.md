# Carteira de peso igual na B3 (paper)

Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`.

Pergunta: uma carteira de peso igual, com o universo, o piso de liquidez e o calendário escolhidos só na janela de desenho, sobrevive a custo, a provento com a regra fiscal travada, ao deflacionamento por todas as variações e a um excesso líquido sobre o CDI fora da amostra?

Resposta deste estudo: **reprovado**. A manga escolhida na janela de desenho foi `small` com piso de ADV de R$ 200 mil, rebalanceamento quarterly, patrimônio de R$ 1 milhão. Fora da amostra o DSR é 0,30 (o corte é 0,95, com N = 87) e o excesso de CAGR líquido sobre o CDI é 14,0%.

O critério é DSR ≥ 0,95 e excesso líquido sobre o CDI > 0 no período fora da amostra. Passar ainda seria paper. Não autoriza capital.

## Regra, fixada antes de ler o resultado fora da amostra

Among the eight sleeves at R$ 1 million (liquid or small, two ADV floors, monthly or quarterly), choose the highest net Sharpe on month-ends through 2018-12-31, with at least 36 months. Ties break to higher design CAGR, lower turnover, monthly, a higher ADV floor, then liquid. Wealth variants and audit variants are registered and counted in N, and cannot be chosen. The path is not flattened at the split.

| Universo | Piso de ADV | O que entra |
|---|---:|---|
| `liquid` | R$ 1 milhão e R$ 5 milhões | todo emissor acima do piso, inclusive financeiro |
| `small` | R$ 50 mil e R$ 200 mil | 30% menor por valor de mercado point-in-time, financeiro de fora |

Um papel por emissor, o de maior ADV. Classes ordinária, preferencial e unit. Sinal no fechamento do fim do mês, ou do fim do trimestre. Fill no pregão seguinte. Caixa parado rende zero. Menos de 20 nomes no líquido, ou menos de 15 no small, e o livro fica em caixa.

## Proventos, desdobramento e quem saiu da bolsa

O caixa do provento entra para quem tinha o papel no fechamento anterior. Dividendo com rótulo não paga imposto. JCP com rótulo retém 15%. O feed público não separa os dois, então o evento sem rótulo retém 15% na manga escolhida. Uma sensibilidade registrada não retém nada no evento sem rótulo. Valor por ação maior que o fechamento anterior é descartado.

Salto de preço de pelo menos 45% com razão redonda só muda a quantidade quando um protocolo de capital posterior confirma a variação inversa das ações.

Papel sem negócio por 10 pregões é vendido no último preço no caminho base. Uma sensibilidade registrada marca essa saída como perda total.

O formulário cadastral só traz o ticker a partir da safra de 2018, e a linha pode ter início anterior. Todo lote padrão do COTAHIST que o formulário não nomeia continua no universo, do primeiro ao último negócio. Raiz de 4 letras já ligada a uma companhia herda essa companhia. Raiz sem protocolo não tem quantidade de ações: entra no líquido e não entra no small. Não se inventa provento para quem parou de negociar e não tem evento.

Cobertura de proventos: 936 de 2089 papéis têm ao menos um evento (44,8%). Papéis que pararam de negociar: 1721, dos quais 1107 não têm evento. A name that stopped trading and has no event understates the total return if it paid cash before it left. No cash is invented for that gap. The price-only rows are the lower bound that ignores every distribution.

Eventos descartados porque o valor por ação superava o fechamento anterior, ou R$ 10 mil quando não havia fechamento: 75.
- PDGR3 em 2011-04-27: R$ 190,9 mi contra fechamento 9,77
- PDGR3 em 2012-05-09: R$ 168,6 mi contra fechamento 5,17
- PDGR3 em 2010-04-30: R$ 116,2 mi contra fechamento —
- PDGR3 em 2009-05-04: R$ 28,3 mi contra fechamento —
- CTAX3 em 2009-04-08: R$ 84 mil contra fechamento —
- CTAX3 em 2013-04-30: R$ 8 mil contra fechamento 26,99
- CTAX3 em 2011-07-12: R$ 3 mil contra fechamento 24,00
- CTAX3 em 2012-04-13: R$ 3 mil contra fechamento 24,10

Yahoo Finance chart events, grossed up by splits that the same feed reports after the ex-date. The feed does not label interest on equity separately from dividends, so those rows are kind=unknown.

## Resultado a R$ 1 milhão, regra de seleção

| Universo | Piso | Calendário | CAGR bruto | CAGR líq. | Sharpe | Max DD | Desenho Sharpe | OOS CAGR líq. | OOS DSR | OOS − CDI | Giro | Cap. tênue |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| liquid | R$ 1,0 mi | monthly | 15,5% | 15,0% | 0,65 | -50,6% | 0,61 | 17,8% | 0,27 | 8,2% | 0,39 | R$ 16,3 mi |
| liquid | R$ 1,0 mi | quarterly | 14,0% | 13,6% | 0,61 | -47,8% | 0,57 | 16,1% | 0,24 | 6,5% | 0,28 | R$ 16,4 mi |
| liquid | R$ 5,0 mi | monthly | 9,6% | 9,3% | 0,48 | -50,9% | 0,52 | 10,2% | 0,12 | 0,6% | 0,45 | R$ 62,1 mi |
| liquid | R$ 5,0 mi | quarterly | 7,6% | 7,4% | 0,42 | -48,3% | 0,44 | 8,3% | 0,09 | -1,3% | 0,31 | R$ 62,2 mi |
| small | R$ 50 mil | monthly | 47,1% | 26,5% | 0,49 | -86,1% | 0,55 | 7,4% | 0,14 | -2,1% | 0,93 | R$ 277 mil |
| small | R$ 50 mil | quarterly | 42,3% | 25,2% | 0,49 | -79,5% | 0,53 | 11,1% | 0,16 | 1,6% | 0,61 | R$ 282 mil |
| small | R$ 200 mil | monthly | 38,5% | 25,3% | 0,58 | -64,5% | 0,60 | 20,2% | 0,24 | 10,6% | 1,07 | R$ 814 mil |
| small | R$ 200 mil | quarterly | 36,7% | 25,3% | 0,58 | -64,2% | 0,66 | 23,5% | 0,30 | 14,0% | 0,72 | R$ 807 mil |

## Patrimônio da manga escolhida

| Patrimônio | CAGR líq. | OOS CAGR líq. | OOS − CDI | OOS DSR | Fills no teto | Sharpe | Max DD | Max DD OOS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R$ 100 mil | 38,4% | 44,6% | 35,0% | 0,64 | 6/2864 | 0,73 | -61,3% | -61,3% |
| R$ 1,0 mi | 25,3% | 23,5% | 14,0% | 0,30 | 35/2812 | 0,58 | -64,2% | -64,2% |
| R$ 10,0 mi | 11,3% | 12,1% | 2,6% | 0,16 | 79/2782 | 0,42 | -68,0% | -68,0% |

Giro de mão única da manga escolhida: 0,72 ao ano. Capacidade típica a 10% do ADV mediano: R$ 5,8 mi. Capacidade limitada pelo papel menos líquido: R$ 807 mil. Mediana de nomes: 37.

## Anos da manga escolhida

| Ano | Retorno líquido | CDI | Excesso | Ano ruim |
|---:|---:|---:|---:|---|
| 2011 | -8,0% | 11,7% | -19,7% | sim |
| 2012 | 14,5% | 8,4% | 6,1% |  |
| 2013 | -12,1% | 8,0% | -20,1% | sim |
| 2014 | -25,5% | 10,8% | -36,3% | sim |
| 2015 | 129,5% | 13,2% | 116,3% |  |
| 2016 | 51,8% | 14,0% | 37,8% |  |
| 2017 | 109,0% | 10,0% | 99,0% |  |
| 2018 | 34,9% | 6,4% | 28,5% |  |
| 2019 | 148,2% | 5,9% | 142,3% |  |
| 2020 | 17,1% | 2,8% | 14,4% |  |
| 2021 | -27,6% | 4,4% | -32,0% | sim |
| 2022 | -33,6% | 12,4% | -46,0% | sim |
| 2023 | 105,8% | 13,1% | 92,7% |  |
| 2024 | 43,0% | 10,8% | 32,2% |  |
| 2025 | 157,1% | 14,3% | 142,7% |  |
| 2026 | -49,9% | 14,2% | -64,1% | sim |

Anos com retorno líquido negativo: 2011, 2013, 2014, 2021, 2022, 2026.

Um mês acima de 100% num livro de cerca de 37 nomes tem o tamanho de um grupamento não confirmado por protocolo de capital. Em 29/05/2025, AMOB3 foi de R$ 0,24 para R$ 13,42, e o ADV mediano dos 60 pregões anteriores era R$ 2,2 milhões, acima do piso da manga escolhida. Esse salto fica no retorno enquanto o protocolo não confirma a quantidade. O excesso fora da amostra convive com saltos dessa classe.

## Benchmarks

CDI, amostra cheia (SGS 12): 9,9%. CDI is the opportunity cost. The book does not earn it on idle cash.

Ibovespa, retorno total oficial, sem custo de investidor: CAGR 5,6%, Sharpe 0,37, max DD -47,7%.

## DSR, PSR e MinTRL

Trials desta família: 55. Trials rejeitados do net-net, já no registro: 32. N da decisão: 87. N de transparência, somando os 24 trials de fatores de horizonte longo: 111. N efetivo da família, por correlação, fica em 1,80 e não é o N do DSR.

Fora da amostra, na manga escolhida: PSR 0,98, DSR 0,30, MinTRL — (infinito). Com os 24 trials de fatores no N: DSR 0,28, PSR 0,98, MinTRL — (infinito).

Amostra cheia da mesma manga: Sharpe 0,58, PSR 1,00, DSR 0,71, max DD -64,2% (líquido) e -49,1% (bruto). Max DD fora da amostra: -64,2%.

## Auditoria do 17,5% ao ano das small caps

Non-financial issuers with a point-in-time balance sheet, one ordinary listing, the most liquid line, bottom 30% by market capitalisation, phase-0 calendar (first session of every fourth month) from 2012-05-02, price return, R$ 1 million, resize rather than a round trip. This is the published path.

O simulador publicado, só preço, imprime CAGR bruto 32,8% e líquido 17,5%. Max DD bruto -31,8%, líquido -89,4%. O mesmo livro neste simulador, com resize, imprime líquido 17,5% e bruto 32,8%.

Vender e recomprar quem ficou no livro muda o líquido para 6,6% e o bruto para 19,6%. A correção de resize é o caminho base. O bug não é a origem do 17,5% líquido: esse número já é o caminho corrigido.

Sem o ajuste de desdobramento confirmado por protocolo de capital, o líquido vai a 20,1% e o bruto a 34,6%. Saltos confirmados como split: 40. Saltos de pelo menos 45% sem confirmação: 864, dos quais 826 têm razão redonda de grupamento ou desdobramento. Salto sem protocolo continua no retorno.

Com provento tributado na regra travada, o líquido vai a 18,5% e o caixa de provento somado é R$ 2,0 mi.

Marcar a saída sem negócio recente como perda total leva o líquido a 11,5%. O contador de saída do simulador publicado, que só incrementa no modo de carregar até o dobro, fica em 0. A saída de quem para de negociar, neste livro de substituição, acontece no rebalanceamento, no último negócio. Neste simulador isso aparece como 137 vendas com preço velho.

Liquidez do livro publicado: mediana de nomes small 55, ADV mediano R$ 152 mil, percentil 10 R$ 3 mil, fração de vagas com ADV abaixo de R$ 10 mil 24,1%, abaixo de R$ 100 mil 45,6%. Fills no teto de 5.000 bps: 600 de 2546. Slippage R$ 72,7 mi dentro de taxa R$ 116 mil e meio spread R$ 4,4 mi.

Negócios por dia, nos papéis que passaram pelo livro: mediana das medianas 213,0, fração de pregões com no máximo um negócio 3,9%.

Maiores saltos sem confirmação de capital, preço final sobre preço anterior:

- TOYB3 em 2015-08-27: razão 270,00
- GPCP3 em 2020-11-13: razão 210,00
- MNDL3 em 2013-05-06: razão 117,78
- PDGR3 em 2025-11-17: razão 112,00
- NUTR3 em 2016-02-26: razão 111,43
- SEQL3 em 2026-11-03: razão 102,25
- MNPR3 em 2016-06-06: razão 89,50
- VIVR3 em 2016-05-02: razão 80,00

Leitura: o 17,5% líquido e o 32,8% bruto publicados são o par preço-apenas depois da correção de não vender quem continua na carteira. Esta corrida mede 32,8% bruto e 17,5% líquido nesse desenho. A distância entre bruto e líquido é custo, e o slippage no teto é a maior peça quando o ADV do nome é pequeno diante da fatia igual do patrimônio. Desdobramento não confirmado e saída no último negócio empurram o bruto para cima se o salto ou o último negócio não são econômicos. Os números das variantes acima são o tamanho desse efeito, não um segundo estudo para escolher regra.

## Limites

O N da decisão soma esta família e os 32 trials rejeitados do net-net. Os 24 trials de fatores entram só na coluna de transparência, porque esse bloco não está neste registro. N efetivo não substitui o N. `eligible_for_live_trading` é false.

Números completos, inclusive a série mensal de cada trial: `docs/reports/equal-weight-b3.json`.

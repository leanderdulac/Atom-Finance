# Carteira de peso igual na B3 (paper)

Pesquisa. Nenhum caminho envia ordem. `eligible_for_live_trading` permanece `false`.

Pergunta: uma carteira de peso igual, com o universo, o piso de liquidez e o calendário escolhidos só na janela de desenho, sobrevive a custo, a provento com a regra fiscal travada, ao deflacionamento por todas as variações e a um excesso líquido sobre o CDI fora da amostra?

Resposta deste estudo: **reprovado**. A manga escolhida na janela de desenho foi `small` com piso de ADV de R$ 200 mil, rebalanceamento quarterly, patrimônio de R$ 1 milhão. Fora da amostra o DSR é 0,10 (o corte é 0,95, com N = 142) e o excesso de CAGR líquido sobre o CDI é 1,4%.

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

A regra vigente está em corporate_actions.py. Um evento oficial da B3 ou da CVM entra só quando a data de conhecimento é anterior ou igual à data-ex. A janela de 250 dias depois do salto foi retirada. Sem evento oficial, a heurística pede razão de preço perto de um inteiro ou de 1/n e volume em ações na mesma proporção, no mesmo pregão. Um par de saltos que se desfaz em até 5 pregões é dado ruim e sai do retorno.

Papel sem negócio por 10 pregões é vendido no último preço no caminho base. Uma sensibilidade registrada marca essa saída como perda total.

O formulário cadastral só traz o ticker a partir da safra de 2018, e a linha pode ter início anterior. Todo lote padrão do COTAHIST que o formulário não nomeia continua no universo, do primeiro ao último negócio. Raiz de 4 letras já ligada a uma companhia herda essa companhia. Raiz sem protocolo não tem quantidade de ações: entra no líquido e não entra no small. Não se inventa provento para quem parou de negociar e não tem evento.

Cobertura de proventos: 940 de 2089 papéis têm ao menos um evento (45,0%). Papéis que pararam de negociar: 1721, dos quais 1106 não têm evento. A name that stopped trading and has no event understates the total return if it paid cash before it left. No cash is invented for that gap. The price-only rows are the lower bound that ignores every distribution.

Eventos descartados porque o valor por ação superava o fechamento anterior, ou R$ 10 mil quando não havia fechamento: 11.
- B1DX34 em 2026-02-10: R$ 2 mil contra fechamento 233,93
- HONB34 em 2026-06-15: R$ 1 mil contra fechamento 899,76
- D1EL34 em 2021-11-03: R$ 659 contra fechamento 623,00
- GEOO34 em 2024-04-02: R$ 603 contra fechamento 335,99
- EAIN34 em 2026-08-05: R$ 516 contra fechamento 320,10
- DDNB34 em 2025-10-22: R$ 494 contra fechamento 279,20
- C1TV34 em 2026-10-01: R$ 337 contra fechamento 79,87
- W1DC34 em 2025-02-21: R$ 267 contra fechamento 174,44

Yahoo Finance chart events, grossed up by splits that the same feed reports after the ex-date. The feed does not label interest on equity separately from dividends, so those rows are kind=unknown.

## Resultado a R$ 1 milhão, regra de seleção

| Universo | Piso | Calendário | CAGR bruto | CAGR líq. | Sharpe | Max DD | Desenho Sharpe | OOS CAGR líq. | OOS DSR | OOS − CDI | Giro | Cap. tênue |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| liquid | R$ 1,0 mi | monthly | 5,9% | 5,4% | 0,35 | -50,7% | 0,37 | 5,2% | 0,04 | -4,4% | 0,39 | R$ 16,3 mi |
| liquid | R$ 1,0 mi | quarterly | 6,7% | 6,4% | 0,39 | -47,9% | 0,37 | 7,2% | 0,06 | -2,4% | 0,28 | R$ 16,4 mi |
| liquid | R$ 5,0 mi | monthly | 5,7% | 5,4% | 0,35 | -51,0% | 0,37 | 5,4% | 0,04 | -4,2% | 0,45 | R$ 62,1 mi |
| liquid | R$ 5,0 mi | quarterly | 5,6% | 5,4% | 0,35 | -48,4% | 0,30 | 6,9% | 0,05 | -2,7% | 0,31 | R$ 62,2 mi |
| small | R$ 50 mil | monthly | 13,0% | 5,6% | 0,30 | -66,2% | 0,46 | 0,5% | 0,03 | -9,1% | 0,89 | R$ 278 mil |
| small | R$ 50 mil | quarterly | 15,0% | 8,3% | 0,36 | -61,8% | 0,41 | 7,1% | 0,06 | -2,5% | 0,58 | R$ 282 mil |
| small | R$ 200 mil | monthly | 3,8% | 0,9% | 0,20 | -71,3% | 0,22 | -0,6% | 0,02 | -10,2% | 1,04 | R$ 814 mil |
| small | R$ 200 mil | quarterly | 15,3% | 10,5% | 0,40 | -61,5% | 0,41 | 11,0% | 0,10 | 1,4% | 0,69 | R$ 807 mil |

## Patrimônio da manga escolhida

| Patrimônio | CAGR líq. | OOS CAGR líq. | OOS − CDI | OOS DSR | Fills no teto | Sharpe | Max DD | Max DD OOS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R$ 100 mil | 15,3% | 17,8% | 8,2% | 0,21 | 0/2875 | 0,49 | -60,7% | -60,7% |
| R$ 1,0 mi | 10,5% | 11,0% | 1,4% | 0,10 | 1/2871 | 0,40 | -61,5% | -61,5% |
| R$ 10,0 mi | 2,1% | 4,3% | -5,3% | 0,05 | 9/2852 | 0,24 | -67,9% | -64,1% |

Giro de mão única da manga escolhida: 0,69 ao ano. Capacidade típica a 10% do ADV mediano: R$ 5,3 mi. Capacidade limitada pelo papel menos líquido: R$ 807 mil. Mediana de nomes: 37.

## Anos da manga escolhida

| Ano | Retorno líquido | CDI | Excesso | Ano ruim |
|---:|---:|---:|---:|---|
| 2011 | -8,3% | 11,7% | -20,0% | sim |
| 2012 | 14,6% | 8,4% | 6,2% |  |
| 2013 | -9,9% | 8,0% | -17,9% | sim |
| 2014 | -25,8% | 10,8% | -36,7% | sim |
| 2015 | -6,3% | 13,2% | -19,5% | sim |
| 2016 | 52,8% | 14,0% | 38,8% |  |
| 2017 | 55,9% | 10,0% | 45,9% |  |
| 2018 | 37,8% | 6,4% | 31,4% |  |
| 2019 | 77,9% | 5,9% | 72,0% |  |
| 2020 | -8,9% | 2,8% | -11,6% | sim |
| 2021 | -23,4% | 4,4% | -27,8% | sim |
| 2022 | -27,9% | 12,4% | -40,3% | sim |
| 2023 | 38,2% | 13,1% | 25,2% |  |
| 2024 | 35,3% | 10,8% | 24,5% |  |
| 2025 | 114,7% | 14,3% | 100,4% |  |
| 2026 | -36,8% | 14,2% | -51,0% | sim |

Anos com retorno líquido negativo: 2011, 2013, 2014, 2015, 2020, 2021, 2022, 2026.

Na v1, AMOB3 em 29/05/2025 (R$ 0,24 para R$ 13,42) ficava no retorno como ganho. Na v2 esse salto é um grupamento 50:1 com data-ex no calendário do feed e não entra no retorno. O ano de 2025 ainda marca +114,7%. Parte disso pode vir de saltos que continuam `unadjusted`, listados na seção de ajuste; esta corrida não separa essa parcela.

## Benchmarks

CDI, amostra cheia (SGS 12): 9,9%. CDI is the opportunity cost. The book does not earn it on idle cash.

Ibovespa, retorno total oficial, sem custo de investidor: CAGR 5,6%, Sharpe 0,37, max DD -47,7%.

## DSR, PSR e MinTRL

Trials desta família: 55. Trials rejeitados do net-net, já no registro: 32. N da decisão: 142. N de transparência, somando os 24 trials de fatores de horizonte longo: 166. N efetivo da família, por correlação, fica em 1,68 e não é o N do DSR.

Fora da amostra, na manga escolhida: PSR 0,92, DSR 0,10, MinTRL — (infinito). Com os 24 trials de fatores no N: DSR 0,10, PSR 0,92, MinTRL — (infinito).

Amostra cheia da mesma manga: Sharpe 0,40, PSR 0,97, DSR 0,24, max DD -61,5% (líquido) e -54,4% (bruto). Max DD fora da amostra: -61,5%.

## Auditoria do 17,5% ao ano das small caps

Non-financial issuers with a point-in-time balance sheet, one ordinary listing, the most liquid line, bottom 30% by market capitalisation, phase-0 calendar (first session of every fourth month) from 2012-05-02, price return, R$ 1 million, resize rather than a round trip. This is the published path.

O simulador publicado, só preço, imprime CAGR bruto 21,8% e líquido 13,2%. Max DD bruto -32,7%, líquido -89,3%. O mesmo livro neste simulador, com resize, imprime líquido 13,2% e bruto 21,8%.

Vender e recomprar quem ficou no livro muda o líquido para 4,0% e o bruto para 12,8%. A correção de resize é o caminho base. O bug não é a origem do 13,2% líquido: esse número já é o caminho corrigido.

Sem o ajuste de desdobramento confirmado por protocolo de capital, o líquido vai a 20,0% e o bruto a 34,5%. Saltos confirmados como split: 47. Saltos de pelo menos 45% sem confirmação: 755, dos quais 736 têm razão redonda de grupamento ou desdobramento. Salto sem protocolo continua no retorno.

Com provento tributado na regra travada, o líquido vai a 14,6% e o caixa de provento somado é R$ 911 mil.

Marcar a saída sem negócio recente como perda total leva o líquido a 8,0%. O contador de saída do simulador publicado, que só incrementa no modo de carregar até o dobro, fica em 0. A saída de quem para de negociar, neste livro de substituição, acontece no rebalanceamento, no último negócio. Neste simulador isso aparece como 141 vendas com preço velho.

Liquidez do livro publicado: mediana de nomes small 55, ADV mediano R$ 152 mil, percentil 10 R$ 3 mil, fração de vagas com ADV abaixo de R$ 10 mil 24,1%, abaixo de R$ 100 mil 45,6%. Fills no teto de 5.000 bps: 282 de 2675. Slippage R$ 14,5 mi dentro de taxa R$ 28 mil e meio spread R$ 1,3 mi.

Negócios por dia, nos papéis que passaram pelo livro: mediana das medianas 213,0, fração de pregões com no máximo um negócio 3,9%.

Maiores saltos sem confirmação de capital, preço final sobre preço anterior:

- TOYB3 em 2015-08-27: razão 270,00
- GPCP3 em 2020-11-13: razão 210,00
- MNDL3 em 2013-05-06: razão 117,78
- PDGR3 em 2025-11-17: razão 112,00
- NUTR3 em 2016-02-26: razão 111,43
- SEQL3 em 2026-11-03: razão 102,25
- PDGR3 em 2025-02-28: razão 71,00
- OSXB3 em 2020-11-26: razão 59,51

Leitura: o 17,5% líquido e o 32,8% bruto publicados são o par preço-apenas depois da correção de não vender quem continua na carteira. Esta corrida mede 21,8% bruto e 13,2% líquido nesse desenho. A distância entre bruto e líquido é custo, e o slippage no teto é a maior peça quando o ADV do nome é pequeno diante da fatia igual do patrimônio. Desdobramento não confirmado e saída no último negócio empurram o bruto para cima se o salto ou o último negócio não são econômicos. Os números das variantes acima são o tamanho desse efeito, não um segundo estudo para escolher regra.

## Ajuste de grupamento e desdobramento (v2)

A janela de 250 dias foi retirada. Um documento protocolado depois do salto não justifica o salto. O fator aplicado é o da data-ex já conhecida naquele pregão. A regra está em `backend/app/models/corporate_actions.py` (`b3-corporate-actions-v2`) e foi escrita antes de reler o resultado. A v2 foi executada com o cache público completo (COTAHIST 2011–2026, CVM, CDI, Ibovespa e o feed de proventos com calendário de desdobramentos). A tabela abaixo põe a v1 publicada ao lado.

Fonte primária: evento oficial da B3 ou documento da CVM com fator e data-ex. O calendário de data-ex que já vem no mesmo arquivo dos proventos entra como fonte `b3`, tipo `chart_ex_date`, com conhecimento igual à data-ex. Arquivo ou CSV no mesmo ticker e na mesma data-ex prevalece sobre esse calendário. Um FRE de quantidade de ações não é data-ex.

Sem evento oficial utilizável, o fallback pré-registrado é heurístico, no mesmo pregão:

- Salto a partir da razão `1,45` (45% inclusive).
- Razão de preço perto de um inteiro `n` ou de `1/n`, com `n` de `2 a 100` e tolerância relativa de `3%`.
- Volume em ações no mesmo sentido e na mesma proporção, tolerância log-relativa `0,40`, mínimo de 100 ações nos dois pregões.
- Print que reverte em `5 pregões`, com o produto das duas razões a até `8%` de 1 e o fechamento de volta a até `8%` do fechamento anterior ao primeiro salto, é dado ruim. O preço é carregado do pregão anterior e a quantidade sai do ADV. Um evento oficial no mesmo pregão não é tratado como print ruim.
- Evento oficial só é aplicado se o conhecimento é anterior ou igual à data-ex e o fator explica o preço do pregão com resíduo de até `25%`. O fator cai no primeiro pregão na data-ex ou até `7 dias` depois.

O fator é ações novas / ações antigas. Grupamento de 80 para 1 aplica `1/80` na quantidade, no retorno e, quando a fonte é a heurística, no provento por ação. Provento com fator oficial permanece no valor por ação já cotado depois do evento. O preço do negócio continua o print, salvo o print ruim. O valor de mercado usa o preço cru vezes os fatores cuja data está depois do protocolo de capital já recebido e até a data do sinal. O ADV em reais não é reescalado. O ADV em ações volta à unidade da data do sinal.

Cada salto de pelo menos 45% gera uma linha de auditoria: ticker, data, razão, fonte (`b3`, `cvm`, `heuristic`, `unadjusted` ou `bad_print`) e fator aplicado. Protocolo tardio fica na razão como `late_filing_ignored` e não altera o fator.

O calendário do feed traz `numerator` e `denominator`. O fator é a divisão dos dois, ações novas por ações antigas. Se esses campos faltam, o texto `splitRatio` no formato `a:b` vale `a/b`: `1:8` é grupamento com fator 1/8, `2:1` é desdobramento com fator 2. Um texto que não fecha é contado e registrado; não derruba o arquivo. A leitura antiga passava esse texto para `float` e descartava o evento em silêncio, então os arquivos ficavam com `splits` vazio. `--refresh-splits` busca de novo o arquivo que não tem o registro `split_parse`.

Limitações conhecidas, sem mudar a regra. A tolerância de resíduo de 25%, a folga de 7 dias, as tolerâncias da heurística e a regra de print ruim continuam as da `b3-corporate-actions-v2`. Com o fator lido, estes saltos ficam `unadjusted` porque `|razão de preço × fator − 1|` passa de 25%:

- PDGR3 em 2025-02-28, razão de preço cerca de 71, feed `125:1` (fator 125).
- PDGR3 em 2025-11-17, razão de preço cerca de 112, feed `200:1` (fator 200).
- SEQL3, razão de preço cerca de 102. O fator do feed não entra na banda de 25%.

O parser dos IPE da CVM, de 2011 a 2026, extraiu 0 eventos. Ele só emite uma linha quando o assunto traz a razão e uma data-ex explícita. Essa extração não foi alterada.

A manga da decisão permanece a da v1: `small`, ADV de R$ 200 mil, trimestral, patrimônio de R$ 1 milhão. A v2 não reescolhe a manga pelo Sharpe de desenho. O critério continua DSR ≥ 0,95 e excesso líquido fora da amostra sobre o CDI > 0. `eligible_for_live_trading` permanece false. Nenhuma ordem é enviada.

N do DSR da decisão na v2: trials da família `b3_equal_weight_v2` mais os 55 trials da família v1 mais os 32 trials rejeitados do net-net. N de transparência: esse N mais os 24 trials de fatores de horizonte longo. A série de retornos da v1 não é reinserida.

| Medida, manga travada, OOS 2019–2026, R$ 1 milhão | v1 (janela antiga, publicada) | v2 (esta regra, commit 122a463) |
|---|---:|---:|
| CAGR líquido | 23,5% | 11,0% |
| CAGR bruto | 44,6% | 18,6% |
| Excesso sobre o CDI (9,6%) | 14,0% | 1,4% |
| Excesso sobre o Ibovespa TR (8,0%) | 15,6 p.p. | 3,0 p.p. |
| Sharpe fora da amostra | 0,56 | 0,40 |
| Sharpe de desenho | 0,66 | 0,41 |
| DSR fora da amostra, decisão | 0,30 (N = 87) | 0,10 (N = 142) |
| DSR fora da amostra, transparência | 0,28 (N = 111) | 0,10 (N = 166) |
| PSR fora da amostra | 0,98 | 0,92 |
| MinTRL fora da amostra | infinito | infinito |
| Max DD fora da amostra | −64,2% | −61,5% |
| Giro de mão única | 0,72 | 0,69 |
| Capacidade típica / tênue (10% do ADV) | R$ 5,8 mi / R$ 807 mil | R$ 5,3 mi / R$ 807 mil |
| CAGR líquido OOS a R$ 100 mil / R$ 1 mi / R$ 10 mi | 44,6% / 23,5% / 12,1% | 17,8% / 11,0% / 4,3% |
| Excesso OOS sobre o CDI a R$ 100 mil / R$ 1 mi / R$ 10 mi | 35,0% / 14,0% / 2,6% | 8,2% / 1,4% / −5,3% |
| N da família / decisão / transparência | 55 / 87 / 111 | 55 / 142 / 166 |
| Veredito | reprovado | **reprovado** |

N conservador: uma corrida anterior da v2, com o parser de `splitRatio` quebrado (todos os arquivos com `splits` vazio), foi descartada como bug, não como escolha de modelagem, e não entra no N principal. Contando também os 55 trials dela, o N fica em 197 na decisão e 221 na transparência; com esse N o DSR só cai, e o veredito não muda.

Saltos de pelo menos 45% na fita real, por fonte: `b3` 306, `cvm` 0, `heuristic` 67, `unadjusted` 2074, `bad_print` 338 (total 2785). A linha de cada salto está em `jump_audit` no JSON.

O registro v1 completo está em `docs/reports/equal-weight-b3-v1.json`. O provento agora volta ao valor nominal da data-ex com os desdobramentos posteriores lidos do mesmo feed; na v1, sem calendário, o valor por ação ficava na unidade de hoje.

Comando da corrida v2, com o cache já preenchido pelas fontes públicas que os scripts já usam:

```
python scripts/fetch_net_net_b3.py --cache data/net-net
python scripts/fetch_equal_weight_dividends.py --cache data/net-net --out data/equal-weight/yahoo --refresh-splits
python scripts/run_equal_weight_b3.py --cache data/net-net --events data/equal-weight/yahoo
```

A carteira paper B não tem o pré-registro nem o ledger reescritos. O efeito no mark-to-market está em `docs/B3-PAPER-FORWARD.md`.

## Limites

O N da decisão soma esta família e os 32 trials rejeitados do net-net. Os 24 trials de fatores entram só na coluna de transparência, porque esse bloco não está neste registro. N efetivo não substitui o N. `eligible_for_live_trading` é false.

Números completos, inclusive a série mensal de cada trial: `docs/reports/equal-weight-b3.json`.


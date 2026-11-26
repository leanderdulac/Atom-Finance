# Paper forward B3

Pesquisa em papel, a partir do fechamento de **2026-11-23**. Nenhuma ordem sai deste repositório. `eligible_for_live_trading` permanece `false` em todo estado, relatório e resposta da API. Um resultado em papel, um Sharpe realizado ou um z-score dentro da banda não autoriza capital.

O sinal de adesão é **2026-11-19**, último pregão presente no COTAHIST antes da entrada. **2026-11-20** é sexta-feira e feriado nacional da Consciência Negra, sem pregão. O preenchimento usa o fechamento registrado no dia da operação. O fechamento do sinal não é preço de fill. Não há backfill de fill nem uso de preço posterior à sessão que está sendo marcada.

O pré-registro congelado em 2026-11-21 está em `docs/reports/b3-paper-preregistration.json`. O SHA-256 desses bytes, `a7be87d1c1b11c7acd8882a3e8f62959ac363be37913d222f0880bedd66150c2`, entra no registro gênese do ledger. O arquivo não é reescrito.

## Carteira A — núcleo passivo

Patrimônio teórico de abertura: **R$ 1.000.000,00**. Alvo **70% CDI** (proxy de Tesouro Selic / fundo DI) e **30% BOVA11**.

A banda é de 5 pontos percentuais no peso do BOVA11. A checagem acontece em todo fechamento depois da abertura e também na primeira sessão em ou depois de cada aniversário de 2026-11-23. A regra exata é:

`negociar somente quando round(peso, 6) < 0,25 ou round(peso, 6) > 0,35`.

Os extremos 25% e 35% ficam dentro da banda. O peso usa o valor do CDI depois do come-cotas já pago, o BOVA11 no fechamento e o caixa parado. Se a banda estoura, o papel arma um rebalanceamento para o **próximo** fechamento, de volta a 70/30. Na data anual, se o peso está dentro da banda, o livro registra a observação e não opera. A carteira combinada 90/10 não rebalanceia entre as mangas.

A taxa de administração do BOVA11, cerca de 0,10% ao ano, **não é cobrada de novo**. O fechamento da bolsa já é líquido dessa taxa. O campo `bova_fee_charged` permanece 0. Uma estimativa informativa do que já está no preço fica em `bova_fee_embedded` e não entra no patrimônio. Nas operações de BOVA11 o livro cobra taxa B3, meio spread e slippage pelo `price_fill` do venue `b3`, com teto de 5.000 bps.

IR da parcela CDI, em dias corridos `(data do resgate − data de abertura do lote).days`, FIFO:

| Dias | Alíquota |
|---|---:|
| até 180 | 22,5% |
| até 360 | 20% |
| até 720 | 17,5% |
| acima de 720 | 15% |

Come-cotas de 15% na primeira sessão marcada de junho e de dezembro, sobre o ganho anterior ao CDI daquele dia, datado como a sessão anterior (último pregão marcado de maio ou de novembro). O IR complementar no resgate é `max(0, alíquota regressiva × ganho bruto − come-cotas já retido naquele lote)`. Venda de BOVA11 paga 15% sobre o ganho de capital realizado, com prejuízo realizado acumulado compensando o ganho antes do imposto. O relatório mostra o IR bruto, o IR recolhido, a provisão se A fosse liquidada naquele fechamento e o patrimônio de A depois dessa provisão. O patrimônio de desempenho, usado na banda e no retorno, é o de mercado depois dos impostos já pagos e antes da provisão ainda não recolhida.

O CDI da manga só começa a render no pregão **seguinte** ao fill de abertura, porque o dinheiro chega no fechamento. O benchmark de CDI é o SGS 12 do BCB, bruto, composto nas mesmas sessões em que a manga rende. O Ibovespa de comparação é o nível oficial, retorno total bruto; a base é o fechamento do dia de entrada (índice 1 nesse dia).

## Carteira B — small caps, peso igual

Patrimônio teórico de abertura: **R$ 100.000,00**. A regra é a função travada `build_signal_book` em `backend/app/models/equal_weight.py`, sem ajuste e sem reotimização.

- Universo `small`: 30% menor valor de mercado point-in-time, sem financeiros, um ticker por emissor pelo maior ADV.
- Piso de ADV de **R$ 200.000**. Menos de 15 nomes e a manga fica em caixa.
- Rebalanceamento trimestral. O sinal de trimestre é reconhecido quando a sessão anterior marcada cai em março, junho, setembro ou dezembro e a sessão corrente já está num mês posterior. O fill é no fechamento corrente, com o livro selecionado na sessão do sinal e com as fitas cortadas nesse sinal.
- Peso `1/N`. Nome que permanece é redimensionado. Não há venda e recompra do mesmo nome (`round_trip` falso).
- Custos, meio spread, slippage e teto de 5.000 bps pelo mesmo `price_fill`.
- Dividendo com rótulo é isento. JCP com rótulo e evento sem rótulo retêm 15%. Valor por ação acima do fechamento anterior é descartado.
- Saída por falta de liquidez: a mesma condição do `simulate_book`, idade em dias ordinais maior que 10, venda no último preço.

A abertura **não** é um sinal trimestral. Ela usa o livro congelado abaixo. Trimestres seguintes chamam `build_signal_book` de novo e gravam o resultado no ledger. O livro de abertura não é recalculado: um retrato posterior da CVM não reescreve a lista. Numa virada de trimestre o job baixa os arquivos públicos da CVM para `data/net-net` dentro do checkout (esse diretório não entra no git) e seleciona com as fitas cortadas no sinal. Os preços do fill continuam saindo do COTAHIST daquele pregão, no cache `data/b3-paper-cache`.

A partir da regra `b3-corporate-actions-v2`, cada mark novo aplica o fator de grupamento, desdobramento ou bonificação só na sessão que está sendo marcada. O arquivo de pré-registro e o ledger não são reescritos, e nenhuma linha antiga é reaberta. A lista de abertura permanece os 47 nomes congelados. Não houve reconstituição contrafactual dessa lista: o cache de preços não está neste checkout, então não se afirma se os 47 nomes mudariam se o sinal de 2026-11-19 fosse refeito. Um trimestre seguinte usa o valor de mercado point-in-time da regra nova, e a composição a partir daí pode diferir. `eligible_for_live_trading` continua false. Nenhuma ordem é enviada.

### Composição inicial, sinal 2026-11-19, entrada 2026-11-23

47 nomes, todos com ADV de pelo menos R$ 200.000, peso **1/47** cada. O fechamento da coluna é o do dia do sinal. Não é o preço do fill de 2026-11-23.

| # | Ticker | CNPJ | Classe | Peso | ADV (R$) | ADV (ações) | Valor de mercado (R$) | Fechamento do sinal |
|---:|---|---|---|---:|---:|---:|---:|---:|
| 1 | ALLD3 | 20.247.322/0001-47 | on | 1/47 | 5,597,961.00 | 965,800 | 645,821,137.28 | 6.73 |
| 2 | ALPK3 | 60.537.263/0001-66 | on | 1/47 | 652,639.50 | 140,750 | 763,183,950.84 | 3.48 |
| 3 | AMER3 | 00.776.574/0001-56 | on | 1/47 | 7,988,711.00 | 1,793,250 | 800,981,196.00 | 4.0 |
| 4 | AMOB3 | 35.654.688/0001-08 | on | 1/47 | 597,103.00 | 50,150 | 348,930,584.97 | 9.21 |
| 5 | ANIM3 | 09.288.252/0001-32 | on | 1/47 | 24,479,400.50 | 8,794,800 | 957,169,067.85 | 2.37 |
| 6 | ARML3 | 00.242.184/0001-04 | on | 1/47 | 5,100,599.00 | 1,223,350 | 1,382,511,447.03 | 3.99 |
| 7 | AZEV3 | 61.351.532/0001-68 | on | 1/47 | 7,349,161.50 | 966,150 | 443,785,511.52 | 10.51 |
| 8 | AZTE3 | 52.017.473/0001-03 | on | 1/47 | 998,436.00 | 822,600 | 24,007,486.80 | 0.6 |
| 9 | BIOM3 | 04.752.991/0001-10 | on | 1/47 | 277,620.50 | 46,550 | 729,423,739.72 | 5.33 |
| 10 | CAMB3 | 61.088.894/0001-08 | on | 1/47 | 228,470.50 | 28,500 | 289,584,298.00 | 6.85 |
| 11 | CASH3 | 14.110.585/0001-07 | on | 1/47 | 6,413,552.50 | 1,317,100 | 387,395,925.77 | 3.71 |
| 12 | CSED3 | 62.984.091/0001-02 | on | 1/47 | 2,425,930.00 | 424,250 | 1,221,217,549.20 | 3.35 |
| 13 | CSUD3 | 01.896.779/0001-38 | on | 1/47 | 706,525.50 | 49,300 | 597,740,000.00 | 14.3 |
| 14 | CVCB3 | 10.760.260/0001-19 | on | 1/47 | 19,485,574.00 | 14,911,600 | 378,425,589.84 | 0.72 |
| 15 | DMVF3 | 12.108.897/0001-50 | on | 1/47 | 237,685.00 | 39,450 | 224,170,590.06 | 4.43 |
| 16 | DOTZ3 | 18.174.270/0001-84 | on | 1/47 | 303,238.00 | 27,150 | 85,260,659.20 | 6.4 |
| 17 | ENJU3 | 16.922.038/0001-51 | on | 1/47 | 683,647.50 | 264,350 | 129,366,351.69 | 6.31 |
| 18 | ESPA3 | 26.659.061/0001-59 | on | 1/47 | 356,894.50 | 51,250 | 169,868,838.20 | 4.7 |
| 19 | ETER3 | 61.092.037/0001-81 | on | 1/47 | 301,535.00 | 89,950 | 185,329,725.00 | 3.0 |
| 20 | EVEN3 | 43.470.988/0001-65 | on | 1/47 | 5,722,804.00 | 1,287,250 | 730,000,000.00 | 3.65 |
| 21 | GFSA3 | 01.545.826/0001-07 | on | 1/47 | 983,449.50 | 4,139,800 | 33,047,483.91 | 0.21 |
| 22 | HBOR3 | 49.263.189/0001-02 | on | 1/47 | 1,648,065.00 | 842,900 | 124,481,496.96 | 0.93 |
| 23 | HBRE3 | 14.785.152/0001-51 | on | 1/47 | 2,215,171.50 | 937,800 | 125,890,556.82 | 1.22 |
| 24 | JALL3 | 02.635.522/0001-95 | on | 1/47 | 2,747,788.50 | 1,112,850 | 684,513,197.28 | 2.27 |
| 25 | KEPL3 | 91.983.056/0001-69 | on | 1/47 | 10,568,779.50 | 1,577,200 | 1,191,544,461.90 | 6.63 |
| 26 | LAND3 | 40.337.136/0001-06 | on | 1/47 | 329,551.00 | 34,950 | 905,495,712.42 | 9.41 |
| 27 | LJQQ3 | 96.418.264/0218-02 | on | 1/47 | 4,577,743.50 | 3,519,400 | 215,193,953.52 | 1.04 |
| 28 | LPSB3 | 08.078.847/0001-09 | on | 1/47 | 321,950.50 | 249,500 | 141,652,445.76 | 0.96 |
| 29 | MELK3 | 12.181.987/0001-77 | on | 1/47 | 1,620,007.50 | 562,600 | 422,852,149.05 | 2.05 |
| 30 | MTRE3 | 07.882.930/0001-65 | on | 1/47 | 2,384,138.00 | 726,600 | 324,728,697.40 | 3.07 |
| 31 | PFRM3 | 45.453.214/0001-51 | on | 1/47 | 1,193,914.50 | 156,750 | 919,928,903.39 | 7.43 |
| 32 | PLPL3 | 24.230.275/0001-80 | on | 1/47 | 21,540,708.50 | 3,336,750 | 870,657,270.00 | 4.27 |
| 33 | POSI3 | 81.243.735/0001-48 | on | 1/47 | 4,323,509.00 | 1,175,950 | 477,866,000.00 | 3.37 |
| 34 | PRNR3 | 18.593.815/0001-97 | on | 1/47 | 11,222,358.50 | 629,150 | 712,739,450.00 | 12.5 |
| 35 | PTBL3 | 83.475.913/0001-91 | on | 1/47 | 1,063,670.50 | 534,650 | 183,282,951.80 | 1.3 |
| 36 | ROMI3 | 56.720.428/0001-63 | on | 1/47 | 1,166,313.00 | 203,650 | 510,575,693.56 | 5.48 |
| 37 | SBFG3 | 13.217.485/0001-11 | on | 1/47 | 33,357,316.50 | 4,500,350 | 923,510,776.00 | 4.0 |
| 38 | SCAR3 | 29.780.061/0001-09 | on | 1/47 | 210,874.50 | 17,350 | 655,895,943.84 | 11.36 |
| 39 | SOJA3 | 10.807.374/0001-77 | on | 1/47 | 5,612,577.00 | 761,500 | 715,189,547.52 | 5.04 |
| 40 | SYNE3 | 08.801.621/0001-86 | on | 1/47 | 1,521,301.00 | 423,700 | 413,666,445.95 | 2.71 |
| 41 | TASA4 | 92.781.335/0001-02 | pn | 1/47 | 7,265,030.50 | 1,087,800 | 666,638,370.70 | 4.65 |
| 42 | TECN3 | 09.295.063/0001-97 | on | 1/47 | 344,791.00 | 39,950 | 506,683,730.30 | 8.42 |
| 43 | TPIS3 | 03.014.553/0001-91 | on | 1/47 | 360,493.00 | 32,350 | 528,000,000.00 | 12.0 |
| 44 | TRIS3 | 08.811.643/0001-27 | on | 1/47 | 1,501,767.50 | 324,600 | 1,089,352,745.62 | 4.49 |
| 45 | VITT3 | 45.365.558/0001-09 | on | 1/47 | 759,563.50 | 240,300 | 386,095,460.80 | 2.45 |
| 46 | VLID3 | 33.113.309/0001-47 | on | 1/47 | 4,224,874.50 | 232,750 | 1,179,981,622.50 | 14.78 |
| 47 | VVEO3 | 12.420.164/0001-57 | on | 1/47 | 744,746.00 | 1,116,750 | 643,162,064.50 | 0.5 |

A referência travada do mesmo livro a R$ 100 mil, usada só para o desvio, não é reestimada: CAGR líquido da amostra cheia 38,4%, CAGR líquido fora da amostra 44,6%, excesso fora da amostra sobre o CDI 35,0%, Sharpe 0,73, max DD −61,3%. O Sharpe é `sqrt(12) × média dos retornos mensais simples / desvio amostral (ddof=1)`. O z de tracking usa a média geométrica mensal do CAGR fora da amostra como centro e a volatilidade mensal invertida a partir da média geométrica da amostra cheia e do Sharpe 0,73. O intervalo de 95% é 1,96 erros-padrão. `|z| > 2` só vira bandeira com pelo menos 3 meses. A bandeira não muda a regra e não liga `eligible_for_live_trading`.

## Carteira combinada

`0,90 × (patrimônio de A / 1.000.000) + 0,10 × (patrimônio de B / 100.000)`. É a compra e manutenção dos dois multiplicadores. Não há rebalanceamento entre A e B.

## Ledger, marcação e relatório

Estado versionado:

| Arquivo | Papel |
|---|---|
| `docs/reports/b3-paper-preregistration.json` | Critérios e livro B congelados. Imutável. |
| `docs/reports/b3_paper/ledger.jsonl` | Log append-only. |
| `docs/reports/b3_paper/state.json` | Espelho do último lançamento. Se divergir e a cadeia validar, é reescrito a partir do ledger. |
| `docs/reports/b3_paper/monthly/AAAA-MM.md` | Relatório do mês. |
| `docs/reports/b3_paper/monthly/AAAA-MM.json` | O mesmo relatório em JSON. |

`data/b3-paper-cache/` é só cache de download e fica de fora do git. `docs/reports/b3_paper/ledger.lock` também: é o lock do append, não é estado.

Cada linha do ledger tem `seq`, `timestamp`, `prev_hash`, `entry_hash` (SHA-256 do JSON canônico sem o próprio hash). O gênese usa 64 zeros como hash anterior. Tipos: `genesis` (seq 0, hash do pré-registro), `target` (seq 1, sessão 2026-11-19, entrada planejada 2026-11-23) e `mark` (sessão ≥ 2026-11-23, estritamente crescente, `price_session` igual à sessão). A cadeia quebrada, um `eligible_for_live_trading` diferente de falso, uma sessão repetida, uma sessão anterior à última ou uma sessão posterior ao relógio levantam erro e não gravam.

A marcação diária usa o fechamento do COTAHIST (o BOVA11 precisa imprimir naquele pregão), o CDI SGS 12 e o Ibovespa. Proventos vêm do feed público de eventos; ausência de evento não é inventada. Um pregão sem CDI, sem Ibovespa ou sem BOVA11 depois da abertura falha a marcação inteira, para o job tentar de novo sem furar a cadeia. Sessões perdidas entram em ordem, cada uma com o fechamento daquele dia.

O relatório mensal traz o retorno do mês e o acumulado de A, de B e da combinada 90/10, contra o CDI bruto e o Ibovespa com dividendos; max drawdown, volatilidade/Sharpe, giro, custos e proventos; IR bruto, recolhido e provisionado; e o desvio de B contra a referência de R$ 100 mil, com intervalo e z-score.

## Critérios congelados de 6 e 12 meses

A leitura é o último pregão marcado em ou antes de **2027-05-23** (6 meses) e **2027-11-23** (12 meses).

| Id | Tipo | O que se lê |
|---|---|---|
| integrity | hard | Cadeia íntegra, nenhuma marca antes de 2026-11-23, nenhuma reescrita, `eligible_for_live_trading` falso. |
| membership | hard | Abertura em 1/N, ADV ≥ R$ 200.000, livro não vazio com pelo menos 15 nomes. Trimestre seguinte é uma chamada nova de `build_signal_book`. |
| execution | flag | Mais de 5% dos fills de B no teto de 5.000 bps, ou giro de alvo mão única depois da abertura, em um ano, acima de 1,5. |
| drawdown | flag | Max DD de B pior que −61,3%, ou de A pior que −25%. |
| excess_over_cdi | record | Excesso líquido de A, B e da combinada sobre o CDI bruto. |
| tracking | flag | Z fora da amostra fora de ±2, com pelo menos 3 meses. |
| live_trading | hard | Nenhuma leitura liga `eligible_for_live_trading`. |

## Como ler o estado

CLI, na raiz do repositório, com `PYTHONPATH=backend`:

```bash
python scripts/run_b3_paper_forward.py --status
python scripts/run_b3_paper_forward.py --mark-to-market
python scripts/run_b3_paper_forward.py --monthly-report
python scripts/run_b3_paper_forward.py --init
```

`--init` grava gênese e alvo e recusa um ledger que já existe. `--freeze-book` só existe para o congelamento único e recusa se o pré-registro já existe ou se a data é 2026-11-23 ou posterior. O livro desta entrega já está congelado; não rode `--freeze-book` de novo.

API somente leitura, no mesmo roteador autenticado das outras rotas da mesa:

- `GET /api/b3-paper/state`
- `GET /api/b3-paper/composition`
- `GET /api/b3-paper/ledger`
- `GET /api/b3-paper/preregistration`
- `GET /api/b3-paper/reports/monthly` e `GET /api/b3-paper/reports/monthly?month=AAAA-MM`

Os arquivos da tabela acima são a terceira leitura. `state.json` é um espelho. A cadeia em `ledger.jsonl` é o registro.

## Onde o job roda

Os dois agendamentos chamam o mesmo CLI. Não aponte os dois para o mesmo ledger ao mesmo tempo: o append segura `ledger.lock`, e um segundo processo espera.

**GitHub Actions.** `.github/workflows/b3-paper-forward.yml` dispara em dias úteis às 22:00 UTC, que é 19:00 em Brasília (o Brasil não adota horário de verão), e também por `workflow_dispatch`. O cron do GitHub só passa a valer quando o arquivo do workflow está no branch padrão. Até lá, a marcação é o `workflow_dispatch` ou o timer abaixo. O job marca, escreve o relatório do mês e, se o índice mudou, grava `docs/reports/b3_paper` no branch. O cache de download não entra no commit.

**Timer.** `ops/systemd/atom-b3-paper.service` e `ops/systemd/atom-b3-paper.timer`. O timer é `Mon..Fri 22:00:00 UTC`. O horário está em UTC porque o Brasil não adota horário de verão: 22:00 UTC é 19:00 em Brasília qualquer que seja o fuso do serviço. A unidade usa o checkout em `/var/lib/atom/Atom-Finance`, usuário `atom`, e o Python do virtualenv desse checkout. Instalação, nesse checkout:

```bash
sudo cp ops/systemd/atom-b3-paper.service ops/systemd/atom-b3-paper.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atom-b3-paper.timer
```

O serviço precisa de rede na hora da marcação, porque o fechamento, o CDI e o Ibovespa são lidos naquele dia. Sem sessão nova (feriado, fim de semana, ou antes de 2026-11-23) o comando termina sem acrescentar linha.

# Pares reais — barreiras triplas, meta-rótulo e portão DSR

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

Hedge do paper: Kalman, com δ e variância de observação escolhidos só no prefixo
anterior ao holdout e depois congelados. Rótulo de três barreiras líquido de
taxa+spread, meta-rótulo com PurgedKFold + embargo. O pré-filtro ADF+KPSS do
spread in-sample é diagnóstico; não entra no portão.
A diferença é a amostra: preços reais, pares escolhidos **antes** de olhar resultado,
e N = todas as variantes de todos os pares (não só os que "deram certo").

## Universo (tese econômica, a priori)

- `PETR3_PETR4` (B3): Mesmo emissor (Petrobras ON/PN): dual-class, mesmo fluxo de caixa.
- `CMIG3_CMIG4` (B3): Mesmo emissor (Cemig ON/PN): dual-class de utilidade elétrica.
- `ITUB4_BBDC4` (B3): Dois maiores bancos privados: mesmo ciclo de crédito e juros.
- `GGBR4_USIM5` (B3): Siderurgia: mesmo ciclo de minério, aço e câmbio.
- `VALE3_CSNA3` (B3): Cadeia de minério/aço (mineradora vs siderúrgica); tese mais fraca, incluída a priori.
- `ETHUSDT_SOLUSDT` (crypto_spot): ETH vs SOL à vista: betas de risco cripto; o paper ETH/SOL do ATOM já usa este par.

Nenhuma grade de `entry_z`, limiar ou horizonte. Dois ensaios por par: primário e meta-filtro.

## Período e fonte

- Intervalo: diário (`1d`). Holdout de cointegração: último 30% da amostra de cada par.
- B3: Yahoo Finance Chart v8, intervalo 1d, campo adjclose, range 5y. brapi tentado; só PETR4 responde sem token.
- Cripto: Binance.US GET /api/v3/klines ETHUSDT e SOLUSDT, 1d, close. Sem chave. USDM mark klines (fapi.binance.com) geo-bloqueado (HTTP 451).
- Snapshot gravado em: `2026-11-17T15:27:36Z`
- Custo B3 ida-e-volta (duas pernas): 0.0014. 2×(comissao 5 bps + slippage 2 bps) do nocional bruto das duas pernas (open+close).
- Custo ETH/SOL ida-e-volta: 0.0024. 2×(taker 10 bps + half-spread 2 bps) do nocional bruto. Funding não entra (spot).

## Tabela por par (fora da amostra, previsões OOF)

| Par | Período | Barras | Eventos | EG OOS | Prim. n | Prim. hit | Prim. liq/trade | Prim. total | Meta n | Meta hit | Meta liq/trade | Meta total | Nota |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `PETR3_PETR4` | 2021-11-17 → 2026-11-17 | 1249 | 52 | **não** | 52 | 67.3% | 0.062% | 3.209% | 21 | 66.7% | 0.043% | 0.909% |  |
| `CMIG3_CMIG4` | 2021-11-17 → 2026-11-17 | 1249 | 36 | **não** | 36 | 52.8% | -0.303% | -10.918% | 3 | 66.7% | 1.181% | 3.543% |  |
| `ITUB4_BBDC4` | 2021-11-17 → 2026-11-17 | 1249 | 27 | **não** | 27 | 59.3% | 0.141% | 3.803% | 0 | n/a | n/a | 0.000% |  |
| `GGBR4_USIM5` | 2021-11-17 → 2026-11-17 | 1249 | 49 | **não** | 49 | 36.7% | -0.703% | -34.459% | 15 | 40.0% | -0.759% | -11.388% |  |
| `VALE3_CSNA3` | 2021-11-17 → 2026-11-17 | 1249 | 39 | **não** | 39 | 43.6% | -0.306% | -11.929% | 8 | 25.0% | -1.104% | -8.835% |  |
| `ETHUSDT_SOLUSDT` | 2021-12-14 → 2026-11-17 | 1800 | 18 | sim | 18 | 38.9% | -2.654% | -47.769% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |

Não cointegraram fora da amostra (EG no último 30%): `PETR3_PETR4`, `CMIG3_CMIG4`, `ITUB4_BBDC4`, `GGBR4_USIM5`, `VALE3_CSNA3`.

Onde a nota diz que não houve previsão OOF, o primário conta **todos** os eventos rotulados (não é holdout); o meta ficou de fora. Pares sem cointegração OOS **entram no N** — não foram descartados.

Tentativas registradas: 12 (esperado 12 = 6 pares × 2 variantes).

## Portão de Sharpe deflacionado (livro combinado)

Livro pré-comprometido: média igual por calendário dos meta-filtros de **todos** os pares da lista
(incluindo os que não cointegraram). Não é o campeão da tabela.

DSR = 0.0004 — **não passou** no portão (limiar 0,95, N=12). A amostra real, com o N honesto, não autoriza promover o livro.

- Sharpe observado (série diária combinada, líquida de custo): -0.630439
- SR\* (esperado da busca): 0.53088
- PSR: 0.03356
- DSR: 0.000372
- MinTRL: inf
- T (barras): 1819
- N: 12.0
- N efetivo: 9.3740
- Assimetria: -4.498571
- Curtose excedente: 84.358464
- Custos declarados: True

Motivos do portão:

- DSR=0.0004 está abaixo do limiar 0.95 (SR̂=-0.630, SR*=0.531, N=9.37405).
- SR̂=-0.630 não supera o Sharpe esperado da busca (SR*=0.531); alongar a mesma amostra não resolve.

DSR do livro B3 (meta, equal-weight): 0.000374 (aprovado=False).
DSR ETH/SOL (meta, mesmo N da família): 0.061569 (aprovado=False).

Aprovação do portão **não** autoriza capital ao vivo.

## O que quebrou

- Lista de pares foi fixada por tese econômica; o N inclui os que não cointegraram OOS.
- B3: Yahoo Chart (adjclose) porque brapi exige token para tudo salvo PETR4; fapi.binance.com devolveu 451, então ETH/SOL veio de klines públicos Binance.US à vista.
- ELET3.SA/ELET6.SA retornam 404 no Yahoo (rebrand); o dual-class de utilidade na lista a priori passou a ser CMIG3/CMIG4, antes de qualquer Sharpe.
- Custo = 2×(taxa+spread) do nocional bruto das duas pernas; funding de perpétuo fica de fora (série é spot).
- EG OOS usa o último 30% da amostra com β reestimado nesse holdout — não é um teste rolante.
- O hedge do paper é Kalman: δ e a variância de observação são escolhidos só no prefixo anterior ao holdout.
- DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.

Reprodução: `python -m app.models.pairs_real --from-fixtures` a partir de `backend/`.
`--fetch` só para renovar o snapshot (respeita 429).

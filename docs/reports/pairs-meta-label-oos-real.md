# Pares reais — barreiras triplas, meta-rótulo e portão DSR

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

Receita idêntica ao relatório sintético: primário Gatev / Avellaneda–Lee (z expanding),
rótulo de três barreiras líquido de taxa+spread, meta-rótulo com PurgedKFold + embargo.
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
- Custo B3 ida-e-volta (duas pernas): 0.0028. Mesmo costing do desk de pares: 4×(comissao 5 bps + slippage 2 bps).
- Custo ETH/SOL ida-e-volta: 0.0048. Spot retail: taker 10 bps + half-spread 2 bps, quatro fills (duas pernas, ida e volta).

## Tabela por par (fora da amostra, previsões OOF)

| Par | Período | Barras | Eventos | EG OOS | Prim. n | Prim. hit | Prim. liq/trade | Prim. total | Meta n | Meta hit | Meta liq/trade | Meta total | Nota |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `PETR3_PETR4` | 2021-11-17 → 2026-11-17 | 1249 | 42 | **não** | 42 | 54.8% | -0.055% | -2.329% | 6 | 50.0% | -0.296% | -1.777% |  |
| `CMIG3_CMIG4` | 2021-11-17 → 2026-11-17 | 1249 | 38 | **não** | 38 | 42.1% | -2.292% | -87.108% | 0 | n/a | n/a | 0.000% |  |
| `ITUB4_BBDC4` | 2021-11-17 → 2026-11-17 | 1249 | 17 | **não** | 17 | 58.8% | -0.906% | -15.407% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `GGBR4_USIM5` | 2021-11-17 → 2026-11-17 | 1249 | 22 | **não** | 22 | 45.5% | -0.196% | -4.311% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `VALE3_CSNA3` | 2021-11-17 → 2026-11-17 | 1249 | 21 | **não** | 21 | 47.6% | -0.574% | -12.048% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `ETHUSDT_SOLUSDT` | 2021-12-14 → 2026-11-17 | 1800 | 35 | sim | 35 | 51.4% | 7.194% | 251.807% | 0 | n/a | n/a | 0.000% |  |

Não cointegraram fora da amostra (EG no último 30%): `PETR3_PETR4`, `CMIG3_CMIG4`, `ITUB4_BBDC4`, `GGBR4_USIM5`, `VALE3_CSNA3`.

Onde a nota diz que não houve previsão OOF, o primário conta **todos** os eventos rotulados (não é holdout); o meta ficou de fora. Pares sem cointegração OOS **entram no N** — não foram descartados.

Tentativas registradas: 12 (esperado 12 = 6 pares × 2 variantes).

## Portão de Sharpe deflacionado (livro combinado)

Livro pré-comprometido: média igual por calendário dos meta-filtros de **todos** os pares da lista
(incluindo os que não cointegraram). Não é o campeão da tabela.

DSR = 0.0067 — **não passou** no portão (limiar 0,95, N=12). A amostra real, com o N honesto, não autoriza promover o livro.

- Sharpe observado (série diária combinada, líquida de custo): -0.302279
- SR\* (esperado da busca): 0.600046
- PSR: 0.203633
- DSR: 0.006685
- MinTRL: inf
- T (barras): 1819
- N: 12.0
- N efetivo: 11.5233
- Assimetria: -2.80765
- Curtose excedente: 144.764345
- Custos declarados: True

Motivos do portão:

- DSR=0.0067 está abaixo do limiar 0.95 (SR̂=-0.302, SR*=0.600, N=11.5233).
- SR̂=-0.302 não supera o Sharpe esperado da busca (SR*=0.600); alongar a mesma amostra não resolve.

DSR do livro B3 (meta, equal-weight): 0.006691 (aprovado=False).
DSR ETH/SOL (meta, mesmo N da família): 0.049979 (aprovado=False).

Aprovação do portão **não** autoriza capital ao vivo.

## O que quebrou

- Lista de pares foi fixada por tese econômica; o N inclui os que não cointegraram OOS.
- B3: Yahoo Chart (adjclose) porque brapi exige token para tudo salvo PETR4; fapi.binance.com devolveu 451, então ETH/SOL veio de klines públicos Binance.US à vista.
- ELET3.SA/ELET6.SA retornam 404 no Yahoo (rebrand); o dual-class de utilidade na lista a priori passou a ser CMIG3/CMIG4, antes de qualquer Sharpe.
- Custo cripto = 4×(taker 10 bps + half-spread 2 bps); funding de perpétuo fica de fora (série é spot).
- EG OOS usa o último 30% da amostra com β reestimado nesse holdout — não é um teste rolante.
- DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.

Reprodução: `python -m app.models.pairs_real --from-fixtures` a partir de `backend/`.
`--fetch` só para renovar o snapshot (respeita 429).

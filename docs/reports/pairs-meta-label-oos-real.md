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
- Custo B3 ida-e-volta (duas pernas): 0.0014. 2×(comissao 5 bps + slippage 2 bps) do nocional bruto das duas pernas (open+close).
- Custo ETH/SOL ida-e-volta: 0.0024. 2×(taker 10 bps + half-spread 2 bps) do nocional bruto. Funding não entra (spot).

## Tabela por par (fora da amostra, previsões OOF)

| Par | Período | Barras | Eventos | EG OOS | Prim. n | Prim. hit | Prim. liq/trade | Prim. total | Meta n | Meta hit | Meta liq/trade | Meta total | Nota |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `PETR3_PETR4` | 2021-11-17 → 2026-11-17 | 1249 | 40 | **não** | 40 | 65.0% | 0.182% | 7.275% | 6 | 33.3% | -0.363% | -2.177% |  |
| `CMIG3_CMIG4` | 2021-11-17 → 2026-11-17 | 1249 | 37 | **não** | 37 | 45.9% | -0.618% | -22.868% | 1 | 0.0% | -2.098% | -2.098% |  |
| `ITUB4_BBDC4` | 2021-11-17 → 2026-11-17 | 1249 | 16 | **não** | 16 | 50.0% | -0.701% | -11.209% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `GGBR4_USIM5` | 2021-11-17 → 2026-11-17 | 1249 | 22 | **não** | 22 | 45.5% | -0.360% | -7.924% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `VALE3_CSNA3` | 2021-11-17 → 2026-11-17 | 1249 | 21 | **não** | 21 | 47.6% | -0.205% | -4.303% | 0 | n/a | n/a | 0.000% | poucas previsões OOF (0) |
| `ETHUSDT_SOLUSDT` | 2021-12-14 → 2026-11-17 | 1800 | 35 | sim | 35 | 45.7% | -1.366% | -47.807% | 9 | 33.3% | -3.130% | -28.168% |  |

Não cointegraram fora da amostra (EG no último 30%): `PETR3_PETR4`, `CMIG3_CMIG4`, `ITUB4_BBDC4`, `GGBR4_USIM5`, `VALE3_CSNA3`.

Onde a nota diz que não houve previsão OOF, o primário conta **todos** os eventos rotulados (não é holdout); o meta ficou de fora. Pares sem cointegração OOS **entram no N** — não foram descartados.

Tentativas registradas: 12 (esperado 12 = 6 pares × 2 variantes).

## Portão de Sharpe deflacionado (livro combinado)

Livro pré-comprometido: média igual por calendário dos meta-filtros de **todos** os pares da lista
(incluindo os que não cointegraram). Não é o campeão da tabela.

DSR = 0.0001 — **não passou** no portão (limiar 0,95, N=12). A amostra real, com o N honesto, não autoriza promover o livro.

- Sharpe observado (série diária combinada, líquida de custo): -0.589164
- SR\* (esperado da busca): 0.447092
- PSR: 0.019137
- DSR: 0.000134
- MinTRL: inf
- T (barras): 1819
- N: 12.0
- N efetivo: 9.9542
- Assimetria: -14.511928
- Curtose excedente: 352.105191
- Custos declarados: True

Motivos do portão:

- DSR=0.0001 está abaixo do limiar 0.95 (SR̂=-0.589, SR*=0.447, N=9.95424).
- SR̂=-0.589 não supera o Sharpe esperado da busca (SR*=0.447); alongar a mesma amostra não resolve.

DSR do livro B3 (meta, equal-weight): 0.004238 (aprovado=False).
DSR ETH/SOL (meta, mesmo N da família): 2.3e-05 (aprovado=False).

Aprovação do portão **não** autoriza capital ao vivo.

## O que quebrou

- Lista de pares foi fixada por tese econômica; o N inclui os que não cointegraram OOS.
- B3: Yahoo Chart (adjclose) porque brapi exige token para tudo salvo PETR4; fapi.binance.com devolveu 451, então ETH/SOL veio de klines públicos Binance.US à vista.
- ELET3.SA/ELET6.SA retornam 404 no Yahoo (rebrand); o dual-class de utilidade na lista a priori passou a ser CMIG3/CMIG4, antes de qualquer Sharpe.
- Custo = 2×(taxa+spread) do nocional bruto das duas pernas; funding de perpétuo fica de fora (série é spot).
- EG OOS usa o último 30% da amostra com β reestimado nesse holdout — não é um teste rolante.
- DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.

Reprodução: `python -m app.models.pairs_real --from-fixtures` a partir de `backend/`.
`--fetch` só para renovar o snapshot (respeita 429).

# Pares Gatev / Avellaneda–Lee — barreiras triplas, meta-rótulo e portão DSR

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

Sinal primário: resíduo de Engle–Granger com hedge expanding, entrada quando |z| > 2.0
(o backtest de pares já existente no ATOM). Rótulo: três barreiras (alvo, stop, prazo) no PnL
do book, **retorno sobre o nocional bruto** das duas pernas (|y|+|β||x|),
**líquido** de taxa e spread (ida e volta = 0.0014 do nocional bruto).
Meta-rótulo: um RF estima P(a operação dar certo) fora da amostra com PurgedKFold e embargo.
Abaixo do limiar 0.55 não entra; acima, o tamanho segue a probabilidade.

## Fora da amostra (previsões OOF)

| | Sem filtro (primário) | Com filtro (meta) |
|---|---|---|
| Operações | 49 | 49 |
| Taxa de acerto | 98.0% | 98.0% |
| Ganho líquido / operação | 0.426% | 0.426% |
| Ganho líquido total (soma das operações) | 20.864% | 20.864% |

O filtro de meta-rótulo **não** melhorou a taxa de acerto nem o ganho líquido por operação fora da amostra.

Eventos gerados: 49. Eventos com previsão OOF: 49.
Tentativas registradas na família `pairs_gatev_avellaneda`: 2.

## Portão de Sharpe deflacionado

DSR = 1.0000 — **passou** no portão (≥ 0,95) com N=2 tentativas realmente registradas. Isso só autoriza considerar paper, não capital ao vivo. N pequeno deixa o portão mais brando — não é evidência de alpha.

- Sharpe observado (série em barra, líquida de custo): 2.251756
- SR\* (esperado da busca): 0.020525
- PSR: 1.0
- MinTRL: 96.2916
- T (barras): 2140
- N: 2.0
- N efetivo: 1.011
- Assimetria: 3.319004
- Curtose excedente: 31.11986
- Custos declarados na série: True

Motivos do portão:

- (nenhum)

Aprovação do portão **não** autoriza capital ao vivo.

## Diagnóstico de cointegração (amostra cheia, hipótese)

- EG cointegrado: True (ADF=-13.1871, β=1.40345963)
- Meia-vida do resíduo (dias): 3.99
- Rank de Johansen: 2

## O que quebrou

- Sinal primário é o z expanding do resíduo EG (Gatev / Avellaneda–Lee), não um Kalman.
- PnL é retorno sobre o nocional bruto das duas pernas (|y|+|β||x|), hedge congelado na entrada.
- β expanding é OLS em nível, congelado na entrada; ainda não é Kalman.
- Lote, aluguel e funding de perpétuo ficam de fora do PnL à vista.
- Meta-rótulo é um RF raso com purga/embargo — não é um modelo de produção.
- DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.
- DGP sintético do relatório reproduz cointegração com saltos; não é um livro real.

Reprodução: `python -m app.models.pairs_meta --demo` a partir de `backend/`.

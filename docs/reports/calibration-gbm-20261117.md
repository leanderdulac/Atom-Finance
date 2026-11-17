# Calibração de intervalos GBM — primeira medição (2026-11-17)

Pesquisa apenas. `eligible_for_live_trading` é **false**.

Método: `interval_coverage` — vol EWMA (λ=0,94, warmup 60), drift 0,
intervalos normais de 90% sobre retornos log, blocos sem sobreposição
(passo = horizonte; nenhum retorno contado duas vezes). Vol e bandas
usam só informação disponível na abertura de cada bloco.

## Resultado (dados Yahoo, ajustados pelo provedor)

| Ativo | Barras | h (dias) | Blocos | Cobertura | Banda 95% | Largura média |
|---|---|---|---|---|---|---|
| PETR4.SA | 1249 | 5 | 237 | 85,65% | 81,2–90,1% | 0,140 |
| PETR4.SA | 1249 | 21 | 56 | 83,93% | 74,3–93,6% | 0,276 |
| BTC-USD | 1097 | 5 | 207 | 87,92% | 83,5–92,4% | 0,173 |
| BTC-USD | 1097 | 21 | 49 | 85,71% | 75,9–95,5% | 0,353 |

Leitura honesta: os quatro pontos ficam **abaixo dos 90% nominais**,
dentro da banda de 95% — o shortfall clássico de cauda gorda de
intervalos gaussianos sobre retornos reais. Os intervalos do simulador
são, na média histórica, um pouco estreitos demais.

## O que isso muda no produto

- O `what_broke` do simulador continua valendo — agora com número.
- Não alargamos bandas por multiplicador ad hoc: a correção honesta é
  trocar o motor (t-Student, mistura ou bootstrap de resíduos), o que é
  trabalho futuro e volta a ser medido aqui.
- Bruto em `calibration-gbm-20261117.json` (mesmo diretório).

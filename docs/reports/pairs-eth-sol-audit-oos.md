# ETH/SOL — auditoria de PnL, features informativas e veto de regime

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

## Parte A — auditoria do +7,2%

O líquido por operação de +7,2% (e picos de ±150% em um dia) **não era retorno de um book**.
O caminho de PnL fazia `r = r_ETH − β r_SOL` com β OLS **em nível** (mediana ≈ 13 ações de SOL
por ETH). Isso multiplica o retorno do SOL por ~13. Recriado no mesmo conjunto de eventos:
legado 21.621% líquido/trade
(máx 397.562%).

Número **auditado** (primário, retorno sobre nocional bruto, β congelado, custo 2×(taxa+spread)):
**-1.366%** por operação.

Fórmula: `(ΔETH − β0 ΔSOL) / (|ETH| + |β0| |SOL|)`.

β_t e z_t usam o print de t (OLS expanding); o fill é t+1, então o dia do sinal não entra no PnL.
Durante a operação o hedge **não** é reestimado.

Operações sobrepostas: **20 de 35**
eventos coincidem no calendário. Isso **não** explica o +7,2% — o bug era a unidade (β×retorno).
O DSR usa o livro ocupado (a primeira operação segura a barra até t1; as demais nesse intervalo
são ignoradas). O líquido/trade auditado é a média dos 35 caminhos,
incluindo os sobrepostos. Com ocupação exclusiva: n=18,
líq/trade=-1.057%.

Funding **não se aplica** ao PnL à vista (Binance.US spot). Entra só como feature do meta:
OKX SWAP cobre ~3 meses e o restante vem de Hyperliquid `fundingHistory` (desde 2023-05;
antes disso a feature fica ausente e o RF imputa 0). fapi.binance.com devolveu 451; Bybit 403.
OI: OKX rubik. Taker agressor: `kline[9]` Binance.US na amostra inteira.

Custo ida-e-volta: 0.0024 do nocional bruto
(2×(taker 10 bps + half-spread 2 bps), as duas pernas). Período: 2021-12-14 → 2026-11-17
(1800 barras diárias). Snapshot: `2026-11-17T16:24:34Z`.

β p10/p50/p90 = [10.2244, 13.315, 17.8796].

### Primário auditado por ano

| Ano | n | Hit | Líq/trade | Total | Máx |
|---|---:|---:|---:|---:|---:|
| 2022 | 7 | 28.6% | -4.525% | -31.677% | 5.372% |
| 2023 | 4 | 50.0% | -0.827% | -3.309% | 3.894% |
| 2024 | 13 | 46.2% | 0.002% | 0.032% | 6.263% |
| 2025 | 11 | 54.5% | -1.168% | -12.853% | 9.470% |

### Sensibilidade a subperíodos (mesmo primário auditado)

| Recorte | n | Hit | Líq/trade | Total | Máx |
|---|---:|---:|---:|---:|---:|
| primeira metade da amostra | 17 | 58.8% | -0.299% | -5.091% | 6.263% |
| segunda metade da amostra | 18 | 33.3% | -2.373% | -42.716% | 9.470% |
| 2022–2023 | 11 | 36.4% | -3.180% | -34.986% | 5.372% |
| fora de 2022–2023 | 24 | 50.0% | -0.534% | -12.822% | 9.470% |

### Cobertura das features informativas (barras com valor finito)

| Feature | Cobertura |
|---|---:|
| `taker_buy_ratio_y` | 100.0% |
| `taker_buy_ratio_x` | 100.0% |
| `taker_okx_y` | 4.0% |
| `taker_okx_x` | 4.0% |
| `funding_y` | 71.4% |
| `funding_x` | 71.4% |
| `funding_spread` | 71.4% |
| `oi_chg5_y` | 58.2% |
| `oi_chg5_x` | 58.2% |
| `btc_lead_1d` | 99.9% |
| `btc_lead_5d` | 99.8% |

## Parte B — candles vs features vs veto de regime

N = 4 tentativas registradas (primário + 3 metas). Nenhuma grade extra.

| Versão | Operações | Hit | Líq/trade | Total | DSR | Portão |
|---|---:|---:|---:|---:|---:|---|
| Primário (só candles, auditado) | 35 | 45.7% | -1.366% | -47.807% | 0.073453 | **não passou** |
| Meta só candles | 9 | 33.3% | -3.130% | -28.168% | 0.000555 | **não passou** |
| Meta + fluxo/funding/OI/BTC | 7 | 42.9% | -1.780% | -12.457% | 0.01965 | **não passou** |
| Meta candles + veto de regime | 1 | 0.0% | -6.789% | -6.789% | 0.000628 | **não passou** |

**Nenhuma variante passou no portão** (DSR ≥ 0,95, custos inclusos, N honesto).

EG OOS (último 30%): cointegrado=True
(ADF=-3.5987).

## O que quebrou

- O +7% líquido/trade anterior misturava β em ações com retorno percentual (β≈13× r_SOL).
- PnL auditado = (Δy − β0 Δx) / (|y|+|β0||x|), hedge congelado na entrada (fill em t+1).
- Funding não entra no PnL à vista; é feature (OKX ~3 meses + Hyperliquid desde 2023-05). OI/taker OKX são perpétuos alinhados por data UTC.
- Regime usa Hurst/RV/correlação de BTC-ETH-SOL (classificador ATOM) sem VIX/crédito — proxy.
- Veto de regime escolhido só no fold de treino. eligible_for_live_trading permanece false.

Reprodução: `python -m app.models.pairs_crypto --from-fixtures` a partir de `backend/`.

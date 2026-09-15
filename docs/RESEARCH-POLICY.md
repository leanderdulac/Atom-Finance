# Regras de negócio da pesquisa quantitativa

Versão: `ATOM-RESEARCH-1.0`

O Laboratório Quant (`/ml`, `POST /api/ml/evaluate`) avalia hipóteses com validação cronológica. Um resultado favorável **não autoriza execução** e **não comprova alpha**.

## O que o protocolo exige

1. Hipótese econômica escrita **antes** do teste, com condição que a refutaria.
2. Features disponíveis no fechamento da decisão; rótulo de `t+1` a `t+2` (atraso de execução de um pregão). O rótulo é um **retorno**, não um preço: o print não é estacionário e a escala em reais não viaja entre ativos (`/target-choice`).
3. Walk-forward por mês civil, com purga de rótulos sobrepostos e um mês de intervalo antes de cada janela de teste.
4. Normalização apenas no treino de cada janela.
5. Comparação fora da amostra com previsão zero, momentum simples e buy & hold, nos mesmos períodos.
6. Custos de comissão e slippage, turnover, alvo de volatilidade e trava de drawdown.
7. Dados sintéticos ou não ajustados identificados de forma explícita.

## O que o protocolo nunca faz

- Não promove um modelo a produção.
- Não envia ordens, não dimensiona conta real e não ignora custos.
- Não trata ajuste de preços ou qualidade da fonte como auditados: isso é declaração do solicitante.
- Não corrige seleção após olhar o fora da amostra (múltiplos testes).

## Avaliação

| Situação | `assessment` | `eligible_for_live_trading` |
|---|---|---|
| Qualquer execução da API | `insufficient_evidence` ou `candidate_for_independent_review` | sempre `false` |
| Dados sintéticos, custos zerados, Sharpe líquido < 0,5, instabilidade entre janelas, ou derrota para o baseline | `insufficient_evidence` | `false` |
| Critérios quantitativos atendidos | `candidate_for_independent_review` | `false` |

Promoção a qualquer uso real exige holdout independente, revisão humana e uma decisão operacional fora deste sistema.

## Backtest exploratório

`POST /api/backtesting/run` permanece como simulação histórica com atraso de execução, comissão e slippage. Não é validação fora da amostra. Use o Laboratório Quant quando a pergunta for evidência temporal.

O teste sequencial (`POST /api/desk/forward-test/evaluate`, `/forward-test`) deixa o princípio explícito: o sinal no fechamento `t` só pode usar preços até `t`, e o retorno que o avalia é o preço seguinte — ainda desconhecido na hora da decisão. Mineração de indicadores no mesmo histórico é a versão de análise técnica da maldição do vencedor. Uma spec travada, testável e executada todos os dias é o relógio; um backtest minerado não é. `eligible_for_live_trading` permanece `false`.

## Interpretação do comentário

A regra prioriza qualidade da hipótese, dos dados e da validação sobre complexidade. Não assume que toda rede neural falha nem usa opinião sobre recrutamento como fato mensurável. O ATOM exige evidência para sustentar qualquer método. As antigas simulações apresentadas como LSTM/RF/DQN foram retiradas das rotas de previsão; chamadas legadas autenticadas recebem HTTP 410.

## Implementação e critérios iniciais

- Ridge real (`StandardScaler` ajustado apenas no treino + `Ridge(alpha=10)`) é o padrão. O candidato Random Forest é treinado com 40 árvores, profundidade máxima 3, mínimo de 20 observações por folha e semente 42. Não há ajuste de hiperparâmetros sobre o OOS.
- Features: retorno de um dia, momentum de 5 e 20 dias, volatilidade e semidesvio negativo de 20 dias. São proxies causais de retorno/risco, acompanhados de justificativas; não substituem fatores fundamentais point-in-time ou dados de microestrutura.
- Entrada: 300–5.000 preços positivos e finitos, datas únicas crescentes, hipótese escrita e fonte declarada. A interface exige escolha explícita de demonstração quando o provedor falha.
- Treino expansivo com pelo menos seis grupos mensais, um a três grupos de intervalo antes do teste e três a seis janelas. Nenhum treino usa o futuro. Rótulos cujo término alcança o início informacional do teste são removidos. O intervalo anterior ao teste é uma opção conservadora de walk-forward, diferente do embargo posterior do PurgedKFold bidirecional.
- Decisão após o fechamento `t`, execução no fechamento `t+1`, retorno realizado entre `t+1` e `t+2`. A fronteira mensal agrupa decisões; as datas de término exibidas incluem a realização dos rótulos.
- Caixa ou posição comprada, peso entre 0 e 1. Peso limitado por volatilidade histórica; o alvo não garante volatilidade futura. Custos incidem sobre o rebalanceamento efetivo, considerando a mudança de peso causada pelo preço, e sobre a liquidação final.
- A trava de drawdown interrompe exposição na decisão seguinte. Saltos de preço e custos podem ultrapassar o limite; não há garantia de perda máxima. Caixa rende zero, Sharpe usa 252 pregões e taxa livre de risco zero.
- Parecer insuficiente se houver dados sintéticos, ajuste não confirmado, custo total zero, menos de 126 observações OOS, retorno líquido não positivo, Sharpe líquido inferior a 0,5, drawdown acima do limite, menos de 60% de janelas positivas ou última janela não positiva.
- O candidato precisa superar momentum em Sharpe líquido (Ridge) ou Ridge (Random Forest), além de reduzir MSE frente à previsão de retorno zero. Os valores são **limiares iniciais de pesquisa**, não testes de significância estatística ou evidência suficiente de capacidade de negociação.
- Mesmo quando todos os critérios são satisfeitos, o resultado é somente `candidate_for_independent_review`; `eligible_for_live_trading` é sempre `false`. Não há promoção operacional automática.

## Rastreabilidade e pesquisa de artigos

O relatório JSON inclui configuração, hipótese, fonte, versão da política, hash SHA-256 de dados/configuração, features, períodos de treino/teste, resultados líquidos, curva OOS e motivos do parecer. A exportação é manual; não existe registro imutável de todas as tentativas. Alterar a hipótese ou repetir testes após ver o resultado exige nova validação independente; o sistema não detecta experimentos externos ou corrige múltiplas tentativas.

O QuantMind recebe instruções para extrair hipótese econômica, disponibilidade temporal das features, validação, baselines, custos, turnover, volatilidade e drawdown. Deve marcar itens ausentes como “não reportados” e preservar citações. Também pede alvo em retorno/regime (não preço), relógio sequencial, Deflated Sharpe / maldição do vencedor, e rejeição de K-Fold embaralhado. Esta é orientação ao extrator, não comprovação automática da validade científica de um artigo.

A constituição da mesa (`ATOM-QUANT-1.0`, `GET /api/desk/doctrine`, UI `/quant-doctrine`) é injetada em todo `complete()` via `compose_system`. Não é fine-tune de pesos: é o mesmo currículo dos laboratórios carregado sempre que o modelo escreve.

## Verificação

Em 08/09/2026, no estado local integrado: 106 testes do backend e 4 do worker aprovados; TypeScript/Vite aprovados. Foram testados vazamento por alteração de preços futuros, normalização restrita ao treino, purga de intervalos, grupos inteiros, custos de entrada/saída, drift dos pesos, trava de risco, dados inválidos, modelos reais, autenticidade da rota e atraso de execução do backtest. O navegador executou a demonstração do início ao resultado e exibiu comparação, janelas e parecer insuficiente. Isso valida o protocolo de software, não rentabilidade em mercado real.

## Fontes metodológicas

A separação cronológica e o intervalo entre treino/teste seguem os princípios descritos em [TimeSeriesSplit — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html). O ajuste da normalização somente no treino segue a orientação de [prevenção de vazamento — scikit-learn](https://scikit-learn.org/stable/common_pitfalls.html). A purga dos intervalos de rótulos se baseia na descrição de [Purged and Embargo Cross Validation — MLFinLab](https://random-docs.readthedocs.io/en/latest/implementations/cross_validation.html). A implementação do ATOM é própria e usa somente treino anterior ao teste.

# Mesa de derivativos ATOM

## Objetivo e entrega
O produto deve explicar qual ativo considerar, qual estrutura montar, a duração, os gatilhos de entrada e saída e o capital comprometido. A primeira implementação monta **planos condicionais**, a partir de teses e snapshots fornecidos, sem fingir que já existe um sistema autônomo validado de descoberta de oportunidades.

| Pergunta | Implementado | Limite atual |
|---|---|---|
| Qual ação? | Compara ativos do snapshot e ordena estruturas elegíveis | Não varre a B3 automaticamente; ranking é cenário-alvo/risco, não retorno esperado |
| Long ou short? | Alta/baixa da tese separada de compra/venda das pernas | Direção vem da tese, não de previsão calibrada |
| Call ou put? | Compra de call/put, trava de alta com calls e baixa com puts | Sem venda descoberta, futuros, crédito, calendário, straddle ou gestão de cobertura |
| Quanto tempo? | Usa prazo da tese e filtra vencimentos pelo menos sete dias depois | Não otimiza horizonte; dias corridos com conferência de pregões |
| Quando entrar? | Gatilho no ativo, limite de débito e validade do snapshot | Não monitora gatilhos nem envia ordens |
| Quando sair? | Primeiro de invalidação, alvo, ganho/perda líquido ou prazo | Stop não assegura execução; não estima preço da opção antes do vencimento |
| Quanto investir? | Quantidade por lote, perda modelada, orçamento individual/agregado e livro | Não estima correlação, margem de exercício ou posições não informadas |

## Operação do produto
Abra Mesa de derivativos no menu principal. Carregue a demonstração fictícia ou importe o snapshot no formato do modelo disponível na tela. Informe capital e orçamento de risco; compare os planos. Resultados, inclusive não operar, ficam salvos por usuário e podem ser exportados com os dados originais.

Campos por contrato: símbolo, call/put, strike, vencimento, estilo de exercício, bid/ask, quantidade disponível em cada lado, multiplicador e lote. `multiplier` converte preço cotado em reais por contrato; `lot_size` é o incremento de quantidade contratual. `bid_size` e `ask_size` usam a mesma unidade da quantidade contratual. Esses valores precisam vir da especificação e do feed, nunca de uma suposição fixa de 100.

`as_of` com fuso deve representar o snapshot completo, inclusive cotações das opções e do ativo. O prazo de 15 minutos é uma regra inicial de rejeição; não torna uma cotação garantidamente executável. Importação não verifica autenticidade. `events_checked=true` significa que o responsável conferiu calendário de eventos; não é consulta automática.

## Cálculo
Compra ao ask, venda ao bid. Taxas reservadas para entrada e saída de todas as pernas. Quantidade arredondada para baixo ao lote, limitada pelo orçamento e pelas quantidades bid/ask informadas. Perda modelada de estruturas a débito: prêmio líquido + taxas reservadas, condicionada ao encerramento correto das pernas e sem exposição residual de exercício.

Travas exigem mesmo ativo, tipo, vencimento, multiplicador, lote e exercício europeu. Posições americanas vendidas são excluídas nesta fase. A B3 admite estilos europeu e americano, e especificações de cotação variáveis; por isso estes campos são explícitos. [Especificações B3](https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/opcoes-sobre-acoes.htm).

O risco de atribuição antecipada em opções americanas vendidas exige tratamento próprio; uma trava no gráfico de payoff não resolve, por si, a operação das pernas. [OIC: debit e credit spreads](https://www.optionseducation.org/news/august-webinar-key-takeaways-options-trading-strategies-debit-and-credit-spreads).

Os ganhos, equilíbrio e payoff informados são no vencimento; não estimam o valor realizável na data de saída anterior. O ranking usa o alvo fornecido como cenário no vencimento, sem probabilidades. Ele escolhe uma estrutura por ativo e aloca sequencialmente; não é um otimizador global de carteira.

## API
- POST `/api/derivatives/plan`: snapshot, teses e restrições; devolve plano ou razões para não operar.
- GET `/api/derivatives/plans`: até 50 registros recentes do usuário.
- GET `/api/derivatives/plans/{id}`: inputs e resultado do próprio usuário.
- Scanner legado `/api/ai/options-expert/scan`: 410 autenticado. Prêmios aproximados e probabilidades fixas foram retirados do caminho do produto.

Nenhum resultado tem `eligible_for_live_trading=true`. `simulation` identifica dados sintéticos, `conditional_review` exige revisão e `no_trade` comunica rejeição. Todos são históricos, não alertas de negociação vigentes.

## Para atingir o especialista pretendido
1. Conectar cadeia de opções B3 com licença, timestamp por contrato, calendário de pregões, eventos corporativos e especificações auditadas.
2. Produzir teses a partir de fatores econômicos e sinais validados OOS. Estimar incerteza e testar a escolha de horizonte, direção e estrutura; ranking de cenário não prova vantagem.
3. Precificar a estrutura ao longo do horizonte, com superfície de volatilidade, gregas, cenários e custos de execução. Comparar oportunidade com caixa/não operar.
4. Integrar posições e risco agregado, capacidade e margens; acompanhar o plano com dados atualizados e registrar alterações de tese.
5. Só depois de validação independente, considerar operacionalização com limites, controles e autorização separada. Esta entrega não conectou nem operou corretora.

## Verificação
Testes de call/put, payoff, taxas, lote/multiplicador, orçamento agregado, eventos, cotações antigas/futuras, liquidez, prazo, exclusão de pernas americanas vendidas, isolamento por usuário e retirada do scanner legado. Build de frontend e fluxo no navegador com dados fictícios. Sem teste econômico em cotações reais.

# Acompanhamento manual de operações simuladas

Há um segundo caminho paper, fechado e automático, só para o par ETH/SOL perpétuo: [ETH-SOL-PAPER-PIPELINE.md](ETH-SOL-PAPER-PIPELINE.md). Também não envia ordens. Este diário continua sendo o acompanhamento **manual** de planos da Mesa de derivativos.

Na Mesa de derivativos, gere um plano e escolha **Acompanhar como operação simulada**. A operação começa aguardando entrada. Informe fonte, horário original com fuso, preço do ativo, bid/ask e quantidades de todas as pernas, além do motivo da observação. Registre entrada, atualizações e encerramento; antes da entrada também é possível cancelar.

A estrutura e as quantidades são copiadas do plano salvo. Entradas exigem plano vigente, gatilho alcançado, tese ainda válida, débito dentro do limite e orçamento agregado suficiente. As simulações abertas do mesmo usuário consomem esse orçamento. Ele usa o capital e o risco externo declarados no plano; não representa uma conta de corretora conciliada.

Compras usam ask e vendas usam bid. Todas as pernas exigem quantidade suficiente no livro informado, sem preenchimento parcial. O resultado líquido considera multiplicador e taxas de entrada e saída. Atualizações mostram o resultado estimado de liquidação; encerramentos registram resultado realizado **simulado**. O histórico é acrescentado sem edição ou exclusão pela API; tentativas repetidas com a mesma chave são idempotentes. Cada usuário acessa apenas seus registros.

## Limites

- Não envia ordens, consulta automaticamente cotações, monitora em segundo plano ou encerra posições automaticamente.
- Dados fictícios são identificados e só podem ser preenchidos automaticamente em planos sintéticos.
- As cotações e a liquidez são declaradas pelo usuário. Não há garantia de execução simultânea, fila, latência, slippage adicional, exercício ou liquidação no vencimento.
- Registros após o vencimento recebem aviso de que exercício e liquidação não são modelados.
- Alertas de alvo, invalidação, ganho, perda e prazo são calculados ao registrar uma observação.
- Este diário não comprova rentabilidade, capacidade preditiva ou desempenho fora da amostra.

## Validação

Os testes em `backend/tests/test_paper_trades.py` cobrem ciclo completo, custos, multiplicador, idempotência, isolamento de usuários, transições, validade dos dados, gatilho, liquidez e orçamento agregado.

## Conferência de fontes

Na operação, escolha um dos últimos 20 snapshots salvos para a mesma ação e execute a conferência. O diagnóstico compara símbolo, tipo, strike, exercício, vencimento, multiplicador, lote, horário original, livro e quantidade do lado necessário (entrada ou liquidação). Contratos ausentes ou duplicados bloqueiam a correspondência. Dados de fechamento e fontes não homologadas continuam bloqueados, mesmo quando a estrutura passa nas verificações.

A conferência usa o relógio do servidor e não altera o snapshot, o formulário ou os eventos da operação. O relatório pode ser exportado com a referência ao snapshot e a hora da conferência; sua validade temporal deve ser reavaliada a cada consulta. Os snapshots permanecem privados por usuário. Não há cotação homologada do ativo-objeto nem promoção automática de um conector a fonte apta para observação.

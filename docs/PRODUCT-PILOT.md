# ATOM Research — produto e piloto

## Promessa
Ajudar pesquisadores e analistas de ações brasileiras a confrontar hipóteses com evidência e explicar suas decisões. Valor: tempo para investigar, comparabilidade e rastreabilidade. Rentabilidade não é uma promessa do produto.

## Entrega local
- Página inicial em português e navegação centrada em diário, experimento e biblioteca.
- Avaliações autenticadas registram hipótese, snapshot de dados, premissas e SHA-256 antes do cálculo. Resultados e falhas permanecem no diário. Repetições têm IDs distintos mesmo com inputs iguais.
- Histórico paginado e detalhes pertencem ao usuário autenticado. Decisões de investigar/descartar são acrescentadas, nunca editadas pela API.
- Exportação JSON com dados, resultado e decisões permite revisão externa. O hash identifica os inputs; não é assinatura digital nem prova contra adulteração por quem administra o banco.
- Preservados protocolo temporal, benchmarks, custos e métricas de risco. Fonte e ajustes continuam sendo declarações, não auditoria independente.
- Endpoints privados de conta e alteração de alavancagem Binance retornam 410; autenticação é exigida no router. Kelly exige capital informado e não consulta saldo real.
- Cenários de opções são identificados como teóricos; ITM neutro ao risco não é probabilidade de lucro. `validated` permanece falso.

## Jornada do piloto
1. Entrar e abrir Novo experimento.
2. Conhecer o fluxo com demonstração explicitamente sintética.
3. Formular hipótese e condição de refutação, carregar dados e conferir ajustes.
4. Definir custos e limites antes de avaliar.
5. Comparar OOS com baselines e registrar decisão fundamentada.
6. Exportar o registro para revisão; criar outra tentativa se houver nova hipótese.

## Validação comercial proposta (ainda não realizada)
Convidar 5 pesquisadores/analistas que já usem notebooks ou planilhas. Observar a primeira sessão, sem conduzir cada clique. Depois acompanhar uma segunda sessão voluntária. Não usar desempenho financeiro como métrica de sucesso do piloto.

Critérios de avanço propostos:
- Pelo menos 4 de 5 concluem experimento e decisão sem ajuda operacional.
- Pelo menos 3 retornam com uma hipótese própria e conseguem explicar custos, baseline e limitação OOS.
- Pelo menos 2 manifestam disposição concreta de contratar um piloto acompanhado, com escopo e preço a negociar.
- Nenhum vazamento entre usuários ou classificação de demonstração como evidência de mercado.
- Medir tempo até primeiro registro útil, dúvidas recorrentes, retorno voluntário e registros exportados; manter dados da entrevista separados de credenciais.

Se não atingidos: corrigir jornada e proposta de valor antes de adicionar modelos. Critérios são hipóteses do produto, não resultados observados. Nenhum convite ou cobrança foi enviado.

## Próximos marcos e condições
1. Dados: fonte licenciada, eventos corporativos, universo point-in-time, validação de calendário e provenance verificável.
2. Ciência: holdout intocado, protocolo de seleção/múltiplas tentativas, fatores econômicos e comparação independente. O diário torna repetição visível, não corrige viés estatístico.
3. Operação: workers com fila, recuperação de tarefas interrompidas, backups testados, revisão completa de segurança e isolamento dos módulos legados antes de SaaS público.
4. Produto pago: retenção demonstrada, onboarding repetível e demanda real por colaboração/revisão. Só então investir em equipes, cobrança e distribuição.

## Limites desta versão
Piloto local; não é SaaS institucional pronto. SQLite não tem trilha à prova de alteração. Queda do processo durante cálculo pode deixar tentativa em `running`; não interpretar como resultado. Não há fila, reprocessamento automático, RBAC de equipes ou correção por múltiplos testes. Biblioteca depende do worker e configuração de IA. Ferramentas exploratórias legadas não integram o protocolo validado do laboratório. APIs legadas e autenticação ainda demandam revisão abrangente antes de exposição pública.

## Verificação
109 testes backend passaram, incluindo isolamento entre usuários, preservação de falhas/repetições e bloqueio das chamadas privadas Binance. Build TypeScript/Vite passou. No navegador, dados sintéticos → avaliação → diário → decisão → recarregamento mantiveram resultado e decisão. Banco temporário separado do banco de uso normal. Não houve negociação, chamada de conta privada ou validação econômica com dados reais. O bundle principal ainda gera aviso de tamanho e dependências legadas emitem deprecações.

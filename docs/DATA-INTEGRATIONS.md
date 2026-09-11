# Integrações de fontes — ATOM

## Entregue
Tela **Fontes de mercado** (`/sources`), acessível também pela Mesa de Derivativos. Todos os endpoints `/api/sources/*` exigem autenticação ATOM.

| Fonte | Implementação | Situação |
|---|---|---|
| brapi | Vencimentos, cadeia por vencimento, dados normalizados e snapshot original por usuário | Consultas públicas PETR4 verificadas. Dados EOD, sem promoção a preço atual |
| Banco Central | Última Selic efetiva, SGS 11, data e unidade originais | Consulta pública verificada; anualização derivada explicitamente identificada |
| CVM | Catálogo ITR/DFP via CKAN, links HTTPS oficiais de arquivos | Consulta pública ITR verificada. Não inclui ingestão contábil dos ZIPs nem agenda futura |
| OpLab | Consulta de opções por ativo com Access-Token, campos de livro e timestamps | Adaptador testado com respostas controladas; falta credencial e homologação real |
| Cedro | Consulta optionsQuote usando cookie de sessão autorizado | Transporte preparado; falta sessão e homologação do esquema/latência/unidades. Resposta original preservada, sem mapper financeiro presumido |
| B3 UP2DATA | Não implementado | Depende de contratação, acesso e especificação dos arquivos contratados |

## Configuração
Em arquivo de ambiente local do backend, fora do Git:
- `BRAPI_TOKEN`: opcional para o sandbox PETR4; demais ativos dependem do plano.
- `OPLAB_ACCESS_TOKEN` e `OPLAB_OWNER`: token e nome exato do usuário ATOM autorizado.
- `CEDRO_SESSION_COOKIE` e `CEDRO_OWNER`: conteúdo do cabeçalho Cookie de uma sessão WebFeeder autorizada e usuário ATOM autorizado. Sessão expirada exige renovação externa; o ATOM não autentica por senha nem renova automaticamente.

Reiniciar o backend após configurar. O endpoint de status mostra apenas disponibilidade para a conta atual. Credenciais são enviadas somente no cabeçalho para a origem fixa do provedor; não são expostas ao navegador nem gravadas nos snapshots. Não enviar segredos no chat. Não houve assinatura, contratação ou operação de corretora nesta entrega.

A restrição por usuário permite testar uma assinatura individual sem compartilhá-la automaticamente com outras contas ATOM. Ela não substitui a autorização comercial do provedor para distribuição futura.

## Regras dos dados
- `fetched_at` é hora de recebimento. `observed_at` é timestamp do dado, mantido separadamente.
- brapi fica sempre `data_mode=eod`, mesmo que devolva bid/ask; volume diário não vira quantidade disponível no livro.
- OpLab/Cedro ficam `unverified` até homologação real. Campo recente sozinho não comprova plano real-time.
- Lote reportado não vira multiplicador financeiro automaticamente. Quantidade ou unidade ausente fica nula.
- A exportação de fonte não é um snapshot de entrada do planejador. `eligible_for_planning=false` impede uma indicação de prontidão indevida; não há ponte automática de fonte para plano nesta versão.
- Selic SGS 11 é percentual ao dia útil. A anualização usa composição de 252 dias e não é uma curva de desconto por vencimento.
- ITR/DFP listam documentos publicados. Não sinalizam que um calendário de eventos futuros foi conferido.
- URLs dos provedores são fixas, redirects desativados, timeout 20 s e resposta limitada a 8 MB. Erros externos não expõem corpo ou credenciais.
- Snapshots são gravados no Postgres existente e recuperados somente pelo próprio usuário. Não há sincronização agendada, stream contínuo, retenção automática ou garantia operacional de disponibilidade.

## Próximo passo necessário para planos com mercado real
Homologar OpLab ou Cedro com acesso autorizado: confirmar atraso contratado, timestamps, unidades de quantidades, lote, fator de cotação, origem do spot e estilo de exercício. Depois acrescentar a ponte server-side para o planejador e o calendário oficial de sessões/eventos. Não transformar EOD em cotação atual para contornar esse requisito.

## Fontes de implementação
- [brapi: opções e frequência](https://brapi.dev/docs/opcoes)
- [OpLab REST API](https://apidocs.oplab.com.br/)
- [Cedro: cadeia](https://docs.cedrotech.com/reference/market-data-services-quotes-optionsquote-codativo)
- [Cedro: sessão de autenticação](https://docs.cedrotech.com/reference/market-data-authentication)
- [BCB: SGS 11](https://dadosabertos.bcb.gov.br/dataset/11-taxa-de-juros---selic)
- [CVM: ITR](https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr)

## Verificação
136 testes de backend passaram, incluindo 10 específicos das fontes, com verificação de isolamento, unidades, EOD e erros sem vazamento. Build TypeScript/Vite aprovado. Consultas públicas reais executadas para PETR4, Selic e catálogo CVM. Serviços pagos não testados com credenciais reais. Permanecem avisos de dependências legadas e de tamanho do bundle.

# Fusão local: Atom-Finance + ATOM-QuantMind

## Decisão

Base: **Atom-Finance**, branch local `integration/quantmind`.

| Critério | Atom-Finance | ATOM-QuantMind |
|---|---|---|
| Último commit da origem | `1d060c7`, 07/09/2026 | `8e21888`, 08/05/2026 |
| Papel | Aplicação web de análise quantitativa | Biblioteca Python de pesquisa |
| Pontos fortes observados | React/MUI, FastAPI, JWT, persistência SQLite, precificação, risco, carteira, backtesting, integrações de mercado | Schemas tipados com proveniência e citações, extração de artigos, processamento PDF/HTML/arXiv, execução em lote, contratos de arquitetura e testes |
| Maturidade relativa | Melhor base como produto integrado; mais recente | Melhor disciplina de validação da biblioteca de conhecimento |
| Limitações observadas | Erros de compilação no Earnings Predictor; rotas ML/Neural SDE/autopilot comentadas no backend; dependências antigas | Migração incompleta: memória/arquivo de trajetórias são stubs; grafo e recuperação semântica não estão completos; DOI não tem resolução de PDF no fluxo |

A decisão não confunde quantidade de funcionalidades com prontidão para produção. Ambos ainda têm limitações. Os recursos quantitativos existentes permanecem na aplicação base; a biblioteca de pesquisa complementa essa aplicação.

## O que foi mesclado

- Histórico completo do QuantMind incorporado como segundo ancestral de um commit de integração, com seu conteúdo em `research/quantmind`. Licença, testes, exemplos e documentação preservados.
- Nova página **Pesquisa QuantMind**, rota `/research`, com login obrigatório, entrada de texto/arXiv, seções, resumos, citações e histórico.
- Gateway `/api/research` usa o JWT existente e define o proprietário a partir do token; o cliente não escolhe outro usuário.
- Worker `research/service.py` executa o fluxo QuantMind e persiste os resultados em SQLite por proprietário. Possui token privado de serviço, limite de entrada e timeout de três minutos.
- Ambientes separados: o backend usa NumPy 1.26/HTTPX 0.27; QuantMind requer NumPy >=2.2/HTTPX >=0.28. Não foram relaxadas as versões do motor quantitativo para encaixar a biblioteca.
- A interface antiga Paper Crawler (editor B3 Quant Architect) foi preservada.
- Corrigido o formato de saída do fluxo de artigos: o mapa de nós com UUID não é compatível com schema estrito do SDK. O adapter mantém validação Pydantic com schema não estrito; há teste de serialização/validação pelo SDK.
- Corrigidas propriedades legadas do Grid/MUI e duplicação de estilo que impediam o build do Earnings Predictor.
- Dependências do worker congeladas em `research/requirements.lock`, profile Docker `research` e workflow CI próprio.

## Execução local

Use três terminais na pasta `Atom-Finance`. Os ambientes `.venv` e `research/.venv` foram criados localmente com Python 3.12.

Defina o mesmo `QUANTMIND_SERVICE_TOKEN` nos terminais do backend e worker; gere-o com `python3 -c 'import secrets; print(secrets.token_hex(32))'`. Defina `OPENAI_API_KEY` apenas no worker. Não coloque chaves no frontend.

Worker:

```bash
cd research
# Instalação reproduzível em uma nova máquina:
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock
export QUANTMIND_SERVICE_TOKEN='seu-token-local'
export OPENAI_API_KEY='sua-chave'
export QUANTMIND_MODEL='gpt-4o-mini'
.venv/bin/uvicorn service:app --host 127.0.0.1 --port 8010
```

Backend, a partir da raiz:

```bash
export QUANTMIND_SERVICE_TOKEN='seu-token-local'
export QUANTMIND_URL='http://127.0.0.1:8010'
export SECRET_KEY='sua-chave-jwt-persistente'
.venv/bin/uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Frontend:

```bash
npm ci
npm run dev
```

Se a porta 8000 estiver ocupada, inicie o backend em outra porta e use `ATOM_API_URL=http://127.0.0.1:18000 npm run dev`. Acesse `/research`, entre ou crie uma conta local e envie o artigo. Consulte `research/examples/extract.py` para uso da API com JWT.

Docker, após configurar os valores em `.env`:

```bash
docker compose --profile research up --build
# Configuração de produção existente, com o novo serviço:
docker compose -f docker-compose.prod.yml --profile research up --build
```

O worker não publica porta externa no Compose; o volume `research_data` preserva artigos. Sem chave OpenAI, o histórico funciona e a extração informa a configuração pendente.

## Escopo e limites

A biblioteca completa está disponível para uso Python, incluindo lotes e preprocessamento. A interface expõe texto e identificadores arXiv; não expõe caminhos locais ou URLs arbitrárias. Os recursos planejados de memória, grafo e busca semântica não foram apresentados como implementados. Não houve execução de ordens financeiras, publicação, deploy ou push.

A validação do provedor pago foi substituída por mocks nos testes; uma extração real depende de credenciais e permanece não validada. Validação estrutural não comprova a exatidão científica das conclusões produzidas por um modelo.

## Validação em 08/09/2026

- Backend completo: **93 testes aprovados**, incluindo Neural SDE e gateway de pesquisa.
- QuantMind: **234 testes aprovados**, cobertura **89,48%**; formatação, lint, tipos e cinco contratos de arquitetura aprovados.
- Worker: **4 testes aprovados**, cobrindo persistência, separação por usuário, credenciais, validação de entradas e falhas/timeout do provedor.
- `npm run build`: TypeScript e Vite aprovados. Permanece aviso de bundle grande (~1,56 MB antes de gzip).
- Compose de desenvolvimento e produção: configuração validada; imagens Docker não foram construídas nem implantadas.
- Navegador: redirecionamento ao login, autenticação com conta temporária, histórico e abertura de artigo sintético, formulário e mensagem de chave ausente conferidos. Interface inspecionada visualmente.
- Servidores de teste usaram bases temporárias e foram encerrados após a validação. Nenhum artigo sintético entrou na base normal da aplicação.
- O teste visual usou o navegador integrado porque o CLI agent-browser não conseguiu criar seu diretório de socket na sandbox.

Os dois clones originais permanecem em `~/Projetos/Atom-Finance` e `~/Projetos/ATOM-QuantMind`. O segundo clone não foi alterado. A integração está no primeiro, em uma branch própria; `main` permanece no commit original.

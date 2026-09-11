# ATOM — operação do piloto em produção

Esta configuração suporta um piloto privado de pesquisa e planejamento condicional, em um único host. Não certifica recomendações, execução automática, disponibilidade contínua ou rentabilidade. Os módulos exploratórios continuam experimentais.

## Controles implementados

- Todas as APIs de negócio exigem JWT de uma conta ativa. Desativar a conta revoga o acesso de seus tokens na próxima requisição.
- Senha de cadastro com pelo menos 12 caracteres e até 72 bytes UTF-8; limite de tentativas de login e cadastro. Cadastro público desativado por padrão em produção.
- Relatórios, experimentos, planos e snapshots isolados por proprietário. Relatórios antigos sem proprietário permanecem no banco, mas não são expostos pela API. Atribuição histórica exige conferência administrativa; não atribuir todos ao primeiro usuário.
- JWT HS256 exige segredo de pelo menos 32 bytes em produção **e rejeita placeholders** (`your-secret-key-change-in-production`, `REPLACE_WITH_…`). Gerar aleatoriamente, armazenar fora do Git. Rotação invalida sessões existentes.
- `/api/live` verifica processo; `/api/health` verifica escrita no Postgres e retorna 503 em falha. Não consulta provedores nem revela chaves/configuração. Docs da API desativadas em produção.
- Banco é Postgres gerenciado (fora deste compose — ver `docs/POSTGRES-MIGRATION-SPIKE.md`). Após reinício, experimentos que ficaram em execução são marcados como falhos; os concluídos são preservados. Não há retomada automática do cálculo. **Atenção:** essa recuperação assume um único worker; rodar mais de um worker/réplica antes de revisar essa lógica pode marcar como falho um experimento que ainda está rodando em outro processo (ver comentário em `app/core/runtime.py`).
- Backend sem root; segredos, bancos e ambientes virtuais excluídos dos contextos Docker. Frontend publicado somente em loopback por padrão. Limite HTTP de 2 MB no nginx.
- Cada requisição recebe um `X-Request-ID` (aceita o do proxy/cliente se enviado, gera um se não) e toda linha de log da aplicação durante aquela requisição carrega o mesmo id — inclusive a de um erro de readiness do banco — o que permite isolar os logs de uma requisição específica num servidor com tráfego concorrente. Rastreamento de erro (Sentry) é opcional: fica completamente desligado até `SENTRY_DSN` ser definido, sem nenhuma outra dependência no restante do app.
- PyTorch para CPU evita instalar bibliotecas CUDA no servidor. Dependências Python resolvidas em `backend/requirements.lock`; npm em `package-lock.json`. CI executa todos os testes, build e auditorias de dependências. Publicação depende do sucesso do CI e usa o SHA exato validado.

## Instalação e configuração

1. Provisionar um Postgres gerenciado (DigitalOcean Managed Databases, RDS, Cloud SQL, ...) — este compose não sobe Postgres próprio; backups/HA/PITR ficam por conta do provedor. Anotar a connection string. No DigitalOcean, `scripts/provision-digitalocean.sh postgres` automatiza a criação do cluster, banco e usuário (idempotente — rodar de novo reaproveita o que já existe) e imprime a `ATOM_DATABASE_URL` pronta; exige `doctl` autenticado (`doctl auth init`) e `jq` na máquina de onde é executado. Um cluster novo não aceita conexão nenhuma até uma regra de firewall ser adicionada — o próprio script lembra o comando (`doctl databases firewalls append`) apontando para o host da aplicação.
2. Preparar um host com Docker Compose v2, Git, espaço para as imagens. A configuração de aplicação é single-host (um único worker; ver nota acima sobre recuperação de experimentos). `scripts/setup-server.sh` faz esse preparo (usuário sem privilégio, firewall, fail2ban, Docker, clone do repo, serviço systemd) numa droplet Ubuntu 22.04 nova — inclusive `scripts/provision-digitalocean.sh staging` para criar essa droplet.
3. Criar `.env.prod` fora dos releases, com modo 600. Definir `SECRET_KEY` aleatório, `ATOM_DATABASE_URL` (do passo 1, no formato `postgresql+asyncpg://usuario:senha@host:5432/banco`), `FRONTEND_URL` e `ALLOWED_ORIGINS` com a origem HTTPS real. Definir tokens licenciados e respectivos `OPLAB_OWNER`/`CEDRO_OWNER` apenas se contratados. Não copiar credenciais de negociação para o serviço.
4. Aplicar as migrations contra o banco do passo 1 antes do primeiro deploy: `cd backend && ATOM_DATABASE_URL=... alembic upgrade head` (rodar de uma máquina com acesso à rede do banco, ou via `docker compose exec backend alembic upgrade head` após o primeiro `up`). Se já existir um `atom_reports.db` (SQLite) de uma instalação anterior a este corte para Postgres, migrar os dados uma única vez logo em seguida: `python -m app.db.migrate_legacy_sqlite /caminho/atom_reports.db` (aceita `--dry-run` para conferir as contagens antes; recusa rodar se as tabelas de destino já tiverem linhas, a menos que `--force` seja passado).
5. Terminar TLS em um proxy do host apontando para `127.0.0.1:8080`. Configurar certificado, renovação e encaminhamento apropriado. O compose não instala TLS. Nunca abrir a porta HTTP diretamente à internet.
6. Executar `docker compose --project-name atom --env-file .env.prod -f docker-compose.prod.yml up -d --build --wait`. Em uma migração de schema, fazer backup antes (ver seção abaixo).
7. Criar operador: `docker compose --project-name atom --env-file .env.prod -f docker-compose.prod.yml exec backend python -m app.db.maintenance create-user operador operador@example.com --role admin`. A senha é solicitada interativamente, sem argumento de shell. Criar analistas pelo mesmo comando sem `--role admin`.
8. Manter `ATOM_ALLOW_REGISTRATION=false`. Rotas autenticadas limitam por JWT `sub`; login continua por IP. Atrás de nginx, o bucket de login ainda é compartilhado até `--proxy-headers` + hosts confiáveis.

O perfil opcional `research` exige token de serviço e tem banco próprio. Não foi incluído nesta homologação de containers; sua política de backup e dependências precisa de validação separada.

## Backup e restauração

O provedor do Postgres gerenciado normalmente já faz backup automático diário com retenção e PITR (point-in-time recovery) — confirmar isso está habilitado é o primeiro passo, e é preferível a qualquer coisa manual abaixo para restauração de rotina.

Para um snapshot ad hoc (ex.: imediatamente antes de uma migration arriscada), `app/db/maintenance.py` oferece um `pg_dump`/`pg_restore` fino:

```sh
docker compose --project-name atom --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python -m app.db.maintenance backup /data/backup-20260909.dump
```

(o arquivo fica dentro do container; copiar para fora com `docker compose cp` antes de remover o container). Copiar backups para armazenamento cifrado fora do host, restringir acesso e testar restauração periodicamente.

Restauração é destrutiva — `pg_restore --clean` derruba e recria os objetos existentes no banco de destino a partir do dump:

```sh
python -m app.db.maintenance restore backup-20260909.dump
```

Parar o serviço antes de restaurar sobre o banco ativo, ou restaurar num banco novo e trocar `ATOM_DATABASE_URL` depois de validar. Não há confirmação interativa — o comando assume que `ATOM_DATABASE_URL` já aponta para o alvo correto.

## Publicação e recuperação

Instalar a versão revisada de `scripts/deploy.sh` no host antes de habilitar o workflow. O script exige `TARGET_SHA`, rejeita releases atrasados em relação a `origin/main`, cria worktree separado, recusa alterações no checkout do release e nunca executa `git reset --hard`. Preserva imagens e releases anteriores. Antes de substituir um backend existente, roda `pg_dump` de dentro do container atual e copia o arquivo para `$APP_DIR/backups/` no host (modo 600) — o Postgres em si nunca fica no volume deste compose, então é isso, e não uma cópia de arquivo local, que garante ter algo pra restaurar se o deploy for adiante com um schema quebrado.

A implantação só registra `deployed-sha` depois que `compose up --wait` confirma os serviços saudáveis. Falha interrompe a publicação; não há rollback automático de esquema. Para recuperar: bloquear tráfego, examinar logs, usar o compose do release anterior e, se necessário, restaurar backup em volume novo. Manter o mesmo nome de projeto `atom` e o mesmo arquivo de ambiente. Não apagar imagens antigas até encerrar a janela de recuperação.

Configurar no GitHub o environment `production` e os secrets `DO_HOST`, `DO_USER`, `DO_SSH_KEY`. Nenhum servidor foi publicado por esta entrega local.

## Staging

Mesmo compose (`docker-compose.prod.yml`), mesmo `scripts/setup-server.sh`, um droplet e um cluster Postgres à parte — nunca aponte staging para o banco ou o `.env.prod` de produção. `scripts/provision-digitalocean.sh staging` cria o droplet; `scripts/provision-digitalocean.sh postgres` com `ATOM_DO_PG_NAME=atom-postgres-staging` cria o banco. Fora isso, é o mesmo passo a passo da seção "Instalação e configuração" acima, começando do zero num host novo.

## Segredos

Este piloto guarda segredos num `.env.prod` fora dos releases, modo 600, nunca versionado — não num cofre dedicado (Vault, AWS Secrets Manager, ...). Para uma implantação single-host, sem múltiplos serviços consumindo o mesmo segredo nem rotação automática, um cofre adicionaria uma dependência operacional nova sem resolver um problema que essa configuração já não resolva; `scripts/setup-server.sh` já gera `SECRET_KEY` aleatoriamente e cuida da permissão do arquivo. Reconsiderar isso quando houver mais de um serviço ou operador precisando do mesmo segredo, ou um requisito de rotação que o arquivo sozinho não cubra.

## Validação e limites

- Testes cobrem fronteira de autenticação de todas as rotas documentadas, revogação de conta, privacidade dos relatórios, cadastro fechado, rate limit, falha de readiness, backup/restauração e recuperação de experimentos interrompidos.
- `scripts/smoke-production.py` exercita login, leitura autenticada, restrição de conta de negociação, experimento e persistência. Executar somente em ambiente de teste: cria um experimento sintético.
- Health HTTP não substitui monitoramento: configurar alerta externo de 503, reinícios, disco, idade do backup e erros dos provedores. Redis é cache descartável; a persistência principal é o Postgres gerenciado. Definir `SENTRY_DSN` cobre a parte de captura de exceção não tratada; ainda não há métricas nem tracing de performance (`SENTRY_TRACES_SAMPLE_RATE` fica em 0.0 por padrão — piloto não precisa do custo/volume de eventos de tracing ainda).
- Sem teste de carga prolongado ou SLA. Sem HA, fila durável ou confirmação de dados licenciados OpLab/Cedro. Planos continuam condicionais e bloqueados para negociação real.
- Auditoria de dependências cobre vulnerabilidades publicadas no momento da consulta, não prova ausência de falhas. Reexecutar CI e auditorias antes de cada release.

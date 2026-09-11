# Piloto privado — preparação e ativação

## Infraestrutura identificada (10/09/2026)

DigitalOcean: droplet `atom-finance-production`, ID 566342099, IP 198.199.74.179, região nyc1, 1 vCPU, 2 GB RAM e 50 GB de disco. Estava desligado na consulta. Não foram encontradas regras de firewall de nuvem nem secrets/environments de implantação no GitHub do ATOM. Há outros recursos na conta; eles não foram alterados.

O domínio e o destino externo dos backups precisam ser escolhidos pelo proprietário. A preparação local não cria bucket, não contrata serviços e não inicia o servidor.

## Ordem de ativação

1. Confirmar hostname, destino S3/Spaces ou SFTP, acesso SSH e endereço/CIDR administrativo. Preservar os dados existentes do servidor. Aplicar firewall com SSH somente do endereço administrativo antes de iniciar o host; liberar 80/443 quando o piloto estiver configurado. Não expor 8000, 8080 ou 6379.
2. Inspecionar serviços, volumes, disco e memória do host antes de qualquer substituição. Fazer backup do banco atual. A configuração com 2 GB exige medir consumo sob carga; não é capacidade homologada. Construir imagens fora do servidor ou confirmar espaço/memória antes do build, sem ampliar recursos automaticamente.
3. Criar release versionado e executar os testes/CI. Preparar `.env.prod` (600) com segredo forte, cadastro fechado e origem HTTPS real. Para volumes antigos, seguir a migração de permissões descrita em PRODUCTION.md.
4. Apontar DNS para o servidor escolhido e definir `ATOM_DOMAIN` em `.env.prod`, sem esquema/caminho. Usar o compose adicional:

```sh
docker compose -p atom --env-file /opt/atom/.env.prod \
  -f docker-compose.prod.yml -f docker-compose.edge.yml up -d --build --wait
```

O Caddy cuida da emissão e renovação de certificados, persistidos em `caddy_data`. O nginx interno continua em loopback no host. O script antigo `setup-ssl.sh` foi desativado: sobrescrevia arquivo versionado sem montar corretamente os certificados. Não combinar os dois métodos.

Para atualizar com `scripts/deploy.sh`, passar `ATOM_ENABLE_EDGE=true` e `TARGET_SHA` do commit aprovado pelo CI. A ativação HTTPS não é presumida no workflow existente: configurar o hostname e verificar primeiro o host. O sucesso de `compose --wait` não certifica TLS público: conferir HTTPS externamente.

5. Criar contas pelo comando administrativo; não abrir registro público. Testar login, limites, privacidade, persistência e fluxo de pesquisa com dados sintéticos. Manter estratégias bloqueadas para execução real.

## Backup cifrado externo

Instalar restic no host. Copiar `ops/operations.env.example` para `/etc/atom/operations.env` (600), preencher o repositório e credenciais. Guardar a senha de criptografia em `/etc/atom/restic-password` (600) e uma cópia de recuperação fora do host, separada dos backups. Perder essa senha impede restauração. Nunca commitar esses arquivos.

Inicializar o repositório explicitamente com `restic init`, usando as variáveis configuradas. `scripts/backup-offsite.py` não cria repositório automaticamente: gera snapshot SQLite consistente, copia para staging privado, envia pelo restic e só registra sucesso após a conclusão. Remove o snapshot temporário do volume em seguida. Não executa prune/forget; retenção deve ser definida após o primeiro teste de recuperação.

Executar o primeiro backup e conferir `restic snapshots --tag atom-core`; restaurar um snapshot para diretório novo e rodar `PRAGMA integrity_check`. O upload e a restauração no destino real ainda não foram testados. O serviço QuantMind tem banco separado e não está incluído nessa rotina.

Copiar os arquivos de `ops/systemd/` para `/etc/systemd/system/` depois de instalar os scripts em `/opt/atom/scripts`. Configurar `ATOM_RELEASE_DIR` para o release ativo e então habilitar `atom-backup.timer` e `atom-monitor.timer` com systemctl. O backup é diário às 03:00 UTC, com até 15 minutos de atraso aleatório.

## Monitoramento

O check local roda a cada 5 minutos e falha se a API não estiver saudável, se o disco livre for menor que 5 GiB ou 10%, ou se o backup externo não tiver sucesso registrado nas últimas 26 horas. Uma instalação ainda sem backup aparece como falha, nunca como saudável.

As falhas ficam no journal/systemd; **não há canal de alerta externo configurado**. Definir destinatário e serviço de notificação com o proprietário, e configurar um monitor de HTTPS fora do servidor para detectar também queda total do host. Nenhuma mensagem de alerta foi enviada por esta preparação.

## Verificação desta entrega

Caddyfile validado com a imagem caddy:2.11.2-alpine; compose combinado validado; scripts Python compilados e shell conferido. Cinco testes cobrem upload com falha, sucesso, rejeição de destino local e monitoramento saudável/degradado. São verificações locais, sem emissão de certificado real, upload externo ou acesso SSH ao droplet.

Referências de configuração: [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [preparação de repositório restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html) e [backup restic](https://restic.readthedocs.io/en/stable/040_backup.html).

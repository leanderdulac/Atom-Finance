# Hyperliquid broker link

ATOM continua plataforma de análise quant. O modo pesquisa (labs, paper,
Laboratório Quant) não envia ordem. Este conector é opt-in: a ponte para
operar na Hyperliquid (perp DEX), com leitura pública e envio de ordens
assinadas por uma API wallet. Testnet por padrão.

## Rotas (`/api/broker/hyperliquid`)

GETs exigem usuário autenticado. `POST /order` e `POST /cancel` exigem
papel **admin ou operador** (o mesmo critério de `is_operator_role`).

- `GET /status` — rede, travas, slippage e teto de nocional. Sem chave, sem rede.
- `GET /markets` — mids + decimais de lote/alavancagem (`/info` público).
- `GET /account` — estado da conta + ordens abertas (precisa `HYPERLIQUID_ACCOUNT_ADDRESS`).
- `POST /order` — `{coin, side, size, price?, reduce_only?, live?}`. Sem `price` vira ordem a mercado.
- `POST /cancel` — `{coin, oid, live?}`.

As chamadas do SDK são síncronas e rodam em thread (`run_in_threadpool`),
para não travar o event loop.

## Travas (escrita só sai se todas passarem)

1. Testnet por padrão (`HYPERLIQUID_TESTNET=true`).
2. Mainnet, na ordem **e** no cancelamento, exige `HYPERLIQUID_LIVE_TRADING=true` **e** `live=true` no corpo.
3. Papel admin ou operador.
4. Teto por ordem: `HYPERLIQUID_MAX_NOTIONAL_USD` (padrão 100).
5. Chave de API wallet + endereço da conta master configurados.
6. Ativo existente no `meta`, nome `upper()` casando `[A-Z0-9]{1,12}`, tamanho arredondado no lote (`szDecimals`).

Ordem a mercado: o teto usa o pior preço que o SDK vai mandar, não o mid cru.
Compra: `mid × (1 + slippage)`. Venda: `mid × (1 − slippage)`. O slippage é
`HYPERLIQUID_MARKET_SLIPPAGE` (padrão `0.01`, intervalo `[0, 1)`) e é
passado explícito para `market_open` — o padrão de 5% do SDK não entra.
Valor inválido cai para 0,01 e bloqueia a escrita até a env ser corrigida.
Ordem limitada usa o preço informado, sem inflar pelo slippage.

Se a exchange devolver `statuses` com `error`, a rota responde **422**.
Status de transporte diferente de `ok` responde **502**. Nenhum dos dois
caso responde 200. A chave da API wallet não volta na mensagem.

## Chaves

Não existe API key clássica: cria-se uma **API wallet** na conta Hyperliquid
(opera, mas **não saca**) e aprova-se o endereço dela na conta master.
Não coloque a chave master, nem um endereço real, em código, teste, doc ou log.

- `HYPERLIQUID_API_WALLET_KEY` — privada da API wallet. Nunca a chave master.
- `HYPERLIQUID_ACCOUNT_ADDRESS` — endereço da conta master.

Testnet usa os mesmos contratos com `https://api.hyperliquid-testnet.xyz`.

## Arquivos

- `backend/app/services/hyperliquid_trading.py` — config, travas, clientes SDK.
- `backend/app/api/hyperliquid.py` — rotas.
- `backend/tests/test_hyperliquid_trading.py` — sem rede.

# Hyperliquid broker link

ATOM continua plataforma de análise quant. Este conector é só a ponte para
operar na Hyperliquid (perp DEX): leitura pública + envio de ordens com
assinatura de API wallet.

## Rotas (`/api/broker/hyperliquid`, autenticadas)

- `GET /status` — rede, travas, teto de nocional. Sem chave, sem rede.
- `GET /markets` — mids + decimais de lote/alavancagem (`/info` público).
- `GET /account` — estado da conta + ordens abertas (precisa `HYPERLIQUID_ACCOUNT_ADDRESS`).
- `POST /order` — `{coin, side, size, price?, reduce_only?, live?}`. Sem `price` vira ordem a mercado.
- `POST /cancel` — `{coin, oid}`.

## Travas (ordem só sai se todas passarem)

1. Testnet por padrão (`HYPERLIQUID_TESTNET=true`).
2. Mainnet exige `HYPERLIQUID_LIVE_TRADING=true` **e** `live=true` no corpo.
3. Teto por ordem: `HYPERLIQUID_MAX_NOTIONAL_USD` (padrão 100).
4. Chave de API wallet + endereço da conta master configurados.
5. Tamanho arredondado no lote (`szDecimals`) e ativo existente no `meta`.

## Chaves

Não existe API key clássica: cria-se uma **API wallet** na conta Hyperliquid
(opera, mas **não saca**) e aprova-se o endereço dela na conta master.

- `HYPERLIQUID_API_WALLET_KEY` — privada da API wallet. Nunca a chave master.
- `HYPERLIQUID_ACCOUNT_ADDRESS` — endereço da conta master.

Testnet usa os mesmos contratos com `https://api.hyperliquid-testnet.xyz`.

## Arquivos

- `backend/app/services/hyperliquid_trading.py` — config, travas, clientes SDK.
- `backend/app/api/hyperliquid.py` — rotas.
- `backend/tests/test_hyperliquid_trading.py` — 15 testes, sem rede.

"""Public crypto positioning: funding + open interest (Binance/OKX) and optional on-chain."""
from __future__ import annotations

from typing import Any

from app.services.context.http import cached_get_json

BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_OI = "https://fapi.binance.com/fapi/v1/openInterest"
OKX_FUNDING = "https://www.okx.com/api/v5/public/funding-rate"
MEMPOOL_FEES = "https://mempool.space/api/v1/fees/recommended"
MEMPOOL_HASH = "https://mempool.space/api/v1/mining/hashrate/3d"

_PAIR = {
    "BTC": ("BTCUSDT", "BTC-USDT-SWAP"),
    "ETH": ("ETHUSDT", "ETH-USDT-SWAP"),
    "SOL": ("SOLUSDT", "SOL-USDT-SWAP"),
}


def positioning(ticker: str) -> dict[str, Any] | None:
    key = ticker.upper().replace("-USD", "").replace("USDT", "")
    pair = _PAIR.get(key)
    if not pair:
        return None
    binance_sym, okx_inst = pair
    funding = cached_get_json(
        BINANCE_FUNDING,
        params={"symbol": binance_sym},
        prefix="bn-funding",
        timeout=3.0,
        ttl=60,
    )
    oi = cached_get_json(
        BINANCE_OI,
        params={"symbol": binance_sym},
        prefix="bn-oi",
        timeout=3.0,
        ttl=60,
    )
    okx = cached_get_json(
        OKX_FUNDING,
        params={"instId": okx_inst},
        prefix="okx-funding",
        timeout=3.0,
        ttl=60,
    )
    if funding is None and oi is None and okx is None:
        return None
    last_funding = None
    if isinstance(funding, dict):
        try:
            last_funding = float(funding.get("lastFundingRate") or 0)
        except (TypeError, ValueError):
            last_funding = None
    open_interest = None
    if isinstance(oi, dict):
        try:
            open_interest = float(oi.get("openInterest") or 0)
        except (TypeError, ValueError):
            open_interest = None
    okx_rate = None
    if isinstance(okx, dict):
        data = okx.get("data") or []
        if data and isinstance(data[0], dict):
            try:
                okx_rate = float(data[0].get("fundingRate") or 0)
            except (TypeError, ValueError):
                okx_rate = None
    onchain = _onchain(key)
    return {
        "ticker": key,
        "binance_funding": last_funding,
        "binance_open_interest": open_interest,
        "okx_funding": okx_rate,
        "onchain": onchain,
        "fontes": [
            {"titulo": f"Binance funding {binance_sym}", "url": BINANCE_FUNDING, "data": ""},
            {"titulo": f"OKX funding {okx_inst}", "url": OKX_FUNDING, "data": ""},
        ],
    }


def _onchain(ticker: str) -> dict[str, Any] | None:
    if ticker != "BTC":
        return None
    fees = cached_get_json(MEMPOOL_FEES, prefix="mempool-fees", timeout=3.0, ttl=60)
    hashrate = cached_get_json(MEMPOOL_HASH, prefix="mempool-hash", timeout=3.0, ttl=300)
    if fees is None and hashrate is None:
        return None
    return {
        "fees": fees if isinstance(fees, dict) else None,
        "hashrate": hashrate if isinstance(hashrate, dict) else None,
        "fonte": "https://mempool.space",
    }

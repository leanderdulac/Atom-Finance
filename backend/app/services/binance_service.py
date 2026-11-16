import hashlib
import hmac
import logging
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.cache import Cache

logger = logging.getLogger(__name__)

class BinanceService:
    BASE_URL = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    FUTURES_URL = os.getenv("BINANCE_FUTURES_URL", "https://fapi.binance.com")
    CACHE_TTL = 30  # seconds for price data

    @staticmethod
    def _get_api_key() -> str:
        return os.getenv("BINANCE_API_KEY", "")

    @staticmethod
    def _get_api_secret() -> str:
        return os.getenv("BINANCE_API_SECRET", "")

    @staticmethod
    def _live_trading_enabled() -> bool:
        """Signed (account/money) endpoints require an explicit operator flag.

        Paper-only is the default: even with API keys configured, no code path
        may touch a real account unless the operator sets ATOM_ENABLE_LIVE_TRADING=1.
        """
        return os.getenv("ATOM_ENABLE_LIVE_TRADING", "").strip().lower() in ("1", "true", "yes")

    @classmethod
    def _live_guard(cls) -> dict[str, Any] | None:
        if cls._live_trading_enabled():
            return None
        return {"error": "Live trading disabled (ATOM_ENABLE_LIVE_TRADING is not set)"}

    @classmethod
    def _get_signature(cls, query_string: str) -> str:
        secret = cls._get_api_secret()
        if not secret:
            return ""
        return hmac.new(
            secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    @classmethod
    async def get_ticker_price(cls, symbol: str) -> dict[str, Any] | None:
        """Fetch current price for a symbol (e.g. BTCUSDT)."""
        symbol = symbol.upper()
        cache_key = f"binance:price:{symbol}"
        cached = Cache.get(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.BASE_URL}/api/v3/ticker/price"
                response = await client.get(url, params={"symbol": symbol}, timeout=5)
                response.raise_for_status()
                data = response.json()
                result = {
                    "symbol": data["symbol"],
                    "price": float(data["price"]),
                    "provider": "binance"
                }
                Cache.set(cache_key, result, ex=cls.CACHE_TTL)
                return result
        except Exception as e:
            logger.error("Error fetching Binance ticker %s: %s", symbol, e)
            return None

    @classmethod
    async def get_all_tickers(cls) -> list | None:
        """Fetch current prices for all symbols."""
        cache_key = "binance:all_tickers"
        cached = Cache.get(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.BASE_URL}/api/v3/ticker/price"
                response = await client.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                Cache.set(cache_key, data, ex=cls.CACHE_TTL)
                return data
        except Exception as e:
            logger.error("Error fetching Binance all tickers: %s", e)
            return None

    @classmethod
    async def get_order_book(cls, symbol: str, limit: int = 100) -> dict[str, Any] | None:
        """Fetch market depth (Order Book)."""
        symbol = symbol.upper()
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.BASE_URL}/api/v3/depth"
                response = await client.get(url, params={"symbol": symbol, "limit": limit}, timeout=5)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Error fetching Binance depth for %s: %s", symbol, e)
            return None

    @classmethod
    async def get_futures_ticker(cls, symbol: str) -> dict[str, Any] | None:
        """Fetch current price for a futures contract."""
        symbol = symbol.upper()
        cache_key = f"binance:futures:price:{symbol}"
        cached = Cache.get(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.FUTURES_URL}/fapi/v1/ticker/price"
                response = await client.get(url, params={"symbol": symbol}, timeout=5)
                response.raise_for_status()
                data = response.json()
                result = {
                    "symbol": data["symbol"],
                    "price": float(data["price"]),
                    "provider": "binance_futures"
                }
                Cache.set(cache_key, result, ex=cls.CACHE_TTL)
                return result
        except Exception as e:
            logger.error("Error fetching Binance futures ticker %s: %s", symbol, e)
            return None

    @classmethod
    async def get_klines(cls, symbol: str, interval: str = "1d", limit: int = 100) -> list | None:
        """Fetch historical candle data."""
        symbol = symbol.upper()
        cache_key = f"binance:klines:{symbol}:{interval}:{limit}"
        cached = Cache.get(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.BASE_URL}/api/v3/klines"
                params = {"symbol": symbol,"interval": interval,"limit": limit}
                response = await client.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                Cache.set(cache_key, data, ex=300)
                return data
        except Exception as e:
            logger.error("Error fetching Binance klines for %s: %s", symbol, e)
            return None

    @classmethod
    async def get_account_info(cls) -> dict[str, Any] | None:
        """Fetch account balance and info (Spot - Signed)."""
        if (blocked := cls._live_guard()) is not None:
            return blocked
        api_key = cls._get_api_key()
        api_secret = cls._get_api_secret()
        if not api_key or not api_secret or api_secret == "INSERT_SECRET_HERE":
            return {"error": "API Secret missing"}
        try:
            params = {"timestamp": int(time.time() * 1000)}
            query_string = urlencode(params)
            signature = cls._get_signature(query_string)
            headers = {"X-MBX-APIKEY": api_key}
            url = f"{cls.BASE_URL}/api/v3/account?{query_string}&signature={signature}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Error fetching Binance account info: %s", e)
            return {"error": str(e)}

    @classmethod
    async def get_futures_account(cls) -> dict[str, Any] | None:
        """Fetch futures account balance and positions (Signed)."""
        if (blocked := cls._live_guard()) is not None:
            return blocked
        api_key = cls._get_api_key()
        api_secret = cls._get_api_secret()
        if not api_key or not api_secret or api_secret == "INSERT_SECRET_HERE":
            return {"error": "API Secret missing"}
        try:
            params = {"timestamp": int(time.time() * 1000)}
            query_string = urlencode(params)
            signature = cls._get_signature(query_string)
            headers = {"X-MBX-APIKEY": api_key}
            url = f"{cls.FUTURES_URL}/fapi/v2/account?{query_string}&signature={signature}"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Error fetching Binance futures account: %s", e)
            return {"error": str(e)}

    @classmethod
    async def change_leverage(cls, symbol: str, leverage: int) -> dict[str, Any] | None:
        """Change leverage for a futures symbol (Signed)."""
        if (blocked := cls._live_guard()) is not None:
            return blocked
        api_key = cls._get_api_key()
        api_secret = cls._get_api_secret()
        if not api_key or not api_secret or api_secret == "INSERT_SECRET_HERE":
            return {"error": "API Secret missing"}
        try:
            params = {"symbol": symbol.upper(), "leverage": leverage, "timestamp": int(time.time() * 1000)}
            query_string = urlencode(params)
            signature = cls._get_signature(query_string)
            headers = {
                "X-MBX-APIKEY": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            url = f"{cls.FUTURES_URL}/fapi/v1/leverage"
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, content=f"{query_string}&signature={signature}", timeout=10)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Error changing leverage for %s: %s", symbol, e)
            return {"error": str(e)}

    @classmethod
    async def calculate_kelly_sizing(cls, symbol: str, win_prob: float, payout_ratio: float, bankroll_override: float | None = None, fraction: float = 0.25):
        """Integrates current Binance price with Kelly Sizing."""
        ticker = await cls.get_ticker_price(symbol)
        if not ticker:
            return {"error": f"Could not fetch price for {symbol}"}
        price = ticker["price"]
        bankroll = bankroll_override
        if bankroll is None:
            # No account fallback: research sizing must use explicit capital,
            # never touch the exchange account (the API layer already requires
            # bankroll_override > 0; this is defense in depth).
            return {"error": "bankroll_override is required; account lookup is disabled"}
        from app.models.kelly_derivatives import kelly_derivatives
        sizing = kelly_derivatives(win_prob, payout_ratio, bankroll, fraction)
        if "erro" in sizing:
            return sizing
        sizing["current_price"] = price
        sizing["symbol"] = symbol
        sizing["asset_units"] = round(sizing["alocacao_dolares"] / price, 6) if price > 0 else 0
        return sizing

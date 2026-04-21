import hmac
import hashlib
import time
import logging
import os
from typing import Optional, Union, Dict, Any
from urllib.parse import urlencode

import httpx
from app.core.cache import Cache

logger = logging.getLogger(__name__)

class BinanceService:
    BASE_URL = "https://api.binance.com"
    FUTURES_URL = "https://fapi.binance.com"
    CACHE_TTL = 30  # seconds for price data

    @staticmethod
    def _get_api_key() -> str:
        return os.getenv("BINANCE_API_KEY", "")

    @staticmethod
    def _get_api_secret() -> str:
        return os.getenv("BINANCE_API_SECRET", "")

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
    async def get_ticker_price(cls, symbol: str) -> Optional[Dict[str, Any]]:
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
            logger.error(f"Error fetching Binance ticker {symbol}: {e}")
            return None

    @classmethod
    async def get_all_tickers(cls) -> Optional[list]:
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
            logger.error(f"Error fetching Binance all tickers: {e}")
            return None

    @classmethod
    async def get_order_book(cls, symbol: str, limit: int = 100) -> Optional[Dict[str, Any]]:
        """Fetch market depth (Order Book)."""
        symbol = symbol.upper()
        try:
            async with httpx.AsyncClient() as client:
                url = f"{cls.BASE_URL}/api/v3/depth"
                response = await client.get(url, params={"symbol": symbol, "limit": limit}, timeout=5)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching Binance depth for {symbol}: {e}")
            return None

    @classmethod
    async def get_futures_ticker(cls, symbol: str) -> Optional[Dict[str, Any]]:
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
            logger.error(f"Error fetching Binance futures ticker {symbol}: {e}")
            return None

    @classmethod
    async def get_klines(cls, symbol: str, interval: str = "1d", limit: int = 100) -> Optional[list]:
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
            logger.error(f"Error fetching Binance klines for {symbol}: {e}")
            return None

    @classmethod
    async def get_account_info(cls) -> Optional[Dict[str, Any]]:
        """Fetch account balance and info (Spot - Signed)."""
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
            logger.error(f"Error fetching Binance account info: {e}")
            return {"error": str(e)}

    @classmethod
    async def get_futures_account(cls) -> Optional[Dict[str, Any]]:
        """Fetch futures account balance and positions (Signed)."""
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
            logger.error(f"Error fetching Binance futures account: {e}")
            return {"error": str(e)}

    @classmethod
    async def change_leverage(cls, symbol: str, leverage: int) -> Optional[Dict[str, Any]]:
        """Change leverage for a futures symbol (Signed)."""
        api_key = cls._get_api_key()
        api_secret = cls._get_api_secret()
        if not api_key or not api_secret or api_secret == "INSERT_SECRET_HERE":
            return {"error": "API Secret missing"}
        try:
            params = {"symbol": symbol.upper(), "leverage": leverage, "timestamp": int(time.time() * 1000)}
            query_string = urlencode(params)
            signature = cls._get_signature(query_string)
            headers = {"X-MBX-APIKEY": api_key}
            url = f"{cls.FUTURES_URL}/fapi/v1/leverage"
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, data=f"{query_string}&signature={signature}", timeout=10)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error changing leverage for {symbol}: {e}")
            return {"error": str(e)}

    @classmethod
    async def calculate_kelly_sizing(cls, symbol: str, win_prob: float, payout_ratio: float, bankroll_override: Optional[float] = None, fraction: float = 0.25):
        """Integrates current Binance price with Kelly Sizing."""
        ticker = await cls.get_ticker_price(symbol)
        if not ticker:
            return {"error": f"Could not fetch price for {symbol}"}
        price = ticker["price"]
        bankroll = bankroll_override
        if bankroll is None:
            acc = await cls.get_account_info()
            if "balances" in acc:
                usdt_balance = next((b for b in acc["balances"] if b["asset"] == "USDT"), None)
                if usdt_balance:
                    bankroll = float(usdt_balance["free"])
                else:
                    bankroll = 0.0
            else:
                bankroll = 10000.0
        from app.models.kelly_derivatives import kelly_derivatives
        sizing = kelly_derivatives(win_prob, payout_ratio, bankroll, fraction)
        if "erro" in sizing:
            return sizing
        sizing["current_price"] = price
        sizing["symbol"] = symbol
        sizing["asset_units"] = round(sizing["alocacao_dolares"] / price, 6) if price > 0 else 0
        return sizing

"""Tests for BinanceService — mocks the httpx boundary, exercises our own
caching, signing, and error-handling logic around Binance's REST API."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.binance_service import BinanceService


def _mock_async_client(response=None, raise_exc=None):
    """Build a mock for `async with httpx.AsyncClient() as client: ...`."""
    client = AsyncMock()
    if raise_exc is not None:
        client.get.side_effect = raise_exc
        client.post.side_effect = raise_exc
    else:
        client.get.return_value = response
        client.post.return_value = response
    cm = AsyncMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = False
    return cm, client


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


@pytest.mark.asyncio
class TestGetTickerPrice:
    async def test_returns_cached_value_without_hitting_the_network(self):
        cached = {"symbol": "BTCUSDT", "price": 50000.0, "provider": "binance"}
        with patch("app.services.binance_service.Cache.get", return_value=cached), \
             patch("app.services.binance_service.httpx.AsyncClient") as ac:
            result = await BinanceService.get_ticker_price("btcusdt")
            ac.assert_not_called()
        assert result == cached

    async def test_fetches_and_caches_on_cache_miss(self):
        resp = _mock_response({"symbol": "BTCUSDT", "price": "51000.50"})
        cm, client = _mock_async_client(response=resp)
        with patch("app.services.binance_service.Cache.get", return_value=None), \
             patch("app.services.binance_service.Cache.set") as cache_set, \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_ticker_price("btcusdt")

        assert result == {"symbol": "BTCUSDT", "price": 51000.50, "provider": "binance"}
        cache_set.assert_called_once()

    async def test_returns_none_on_http_error(self):
        resp = _mock_response({}, status_ok=False)
        cm, _ = _mock_async_client(response=resp)
        with patch("app.services.binance_service.Cache.get", return_value=None), \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_ticker_price("BADSYM")
        assert result is None

    async def test_returns_none_on_network_error(self):
        cm, _ = _mock_async_client(raise_exc=httpx.ConnectError("no network"))
        with patch("app.services.binance_service.Cache.get", return_value=None), \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_ticker_price("ETHUSDT")
        assert result is None


@pytest.mark.asyncio
class TestGetAllTickers:
    async def test_returns_list_from_api(self):
        resp = _mock_response([{"symbol": "BTCUSDT", "price": "1"}])
        cm, _ = _mock_async_client(response=resp)
        with patch("app.services.binance_service.Cache.get", return_value=None), \
             patch("app.services.binance_service.Cache.set"), \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_all_tickers()
        assert result == [{"symbol": "BTCUSDT", "price": "1"}]


@pytest.mark.asyncio
class TestGetOrderBook:
    async def test_passes_symbol_and_limit_through(self):
        resp = _mock_response({"bids": [], "asks": []})
        cm, client = _mock_async_client(response=resp)
        with patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_order_book("btcusdt", limit=50)
        client.get.assert_called_once()
        _, kwargs = client.get.call_args
        assert kwargs["params"] == {"symbol": "BTCUSDT", "limit": 50}
        assert result == {"bids": [], "asks": []}

    async def test_returns_none_on_exception(self):
        cm, _ = _mock_async_client(raise_exc=RuntimeError("boom"))
        with patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            assert await BinanceService.get_order_book("X") is None


@pytest.mark.asyncio
class TestGetKlines:
    async def test_fetches_and_caches(self):
        candles = [[1, "100", "110", "90", "105", "1000"]]
        resp = _mock_response(candles)
        cm, _ = _mock_async_client(response=resp)
        with patch("app.services.binance_service.Cache.get", return_value=None), \
             patch("app.services.binance_service.Cache.set") as cache_set, \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_klines("btcusdt", interval="1h", limit=10)
        assert result == candles
        cache_set.assert_called_once_with("binance:klines:BTCUSDT:1h:10", candles, ex=300)


class TestSignature:
    def test_empty_secret_yields_empty_signature(self):
        with patch.object(BinanceService, "_get_api_secret", return_value=""):
            assert BinanceService._get_signature("a=1&b=2") == ""

    def test_signature_is_deterministic_hmac_sha256(self):
        with patch.object(BinanceService, "_get_api_secret", return_value="mysecret"):
            sig1 = BinanceService._get_signature("a=1&b=2")
            sig2 = BinanceService._get_signature("a=1&b=2")
            sig3 = BinanceService._get_signature("a=1&b=3")
        assert sig1 == sig2
        assert sig1 != sig3
        assert len(sig1) == 64  # hex-encoded sha256


@pytest.mark.asyncio
class TestGetAccountInfo:
    async def test_returns_error_dict_when_credentials_missing(self):
        with patch.object(BinanceService, "_get_api_key", return_value=""), \
             patch.object(BinanceService, "_get_api_secret", return_value=""):
            result = await BinanceService.get_account_info()
        assert result == {"error": "API Secret missing"}

    async def test_returns_error_dict_on_exception(self):
        cm, _ = _mock_async_client(raise_exc=RuntimeError("timeout"))
        with patch.object(BinanceService, "_get_api_key", return_value="key"), \
             patch.object(BinanceService, "_get_api_secret", return_value="secret"), \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.get_account_info()
        assert "error" in result


@pytest.mark.asyncio
class TestChangeLeverage:
    async def test_sends_form_encoded_body_with_content_type(self):
        """Regression test: change_leverage must send the signed query string
        as `content=` with an explicit form-urlencoded Content-Type — passing
        it as a raw string via `data=` (the original code) sends the same
        bytes but drops the Content-Type header Binance's signed endpoints
        expect."""
        resp = _mock_response({"leverage": 10, "symbol": "BTCUSDT"})
        cm, client = _mock_async_client(response=resp)
        with patch.object(BinanceService, "_get_api_key", return_value="key"), \
             patch.object(BinanceService, "_get_api_secret", return_value="secret"), \
             patch("app.services.binance_service.httpx.AsyncClient", return_value=cm):
            result = await BinanceService.change_leverage("btcusdt", 10)

        assert result == {"leverage": 10, "symbol": "BTCUSDT"}
        _, kwargs = client.post.call_args
        assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert "content" in kwargs
        assert "signature=" in kwargs["content"]

    async def test_returns_error_dict_when_credentials_missing(self):
        with patch.object(BinanceService, "_get_api_key", return_value=""), \
             patch.object(BinanceService, "_get_api_secret", return_value=""):
            result = await BinanceService.change_leverage("BTCUSDT", 5)
        assert result == {"error": "API Secret missing"}


@pytest.mark.asyncio
class TestCalculateKellySizing:
    async def test_uses_bankroll_override_when_given(self):
        with patch.object(BinanceService, "get_ticker_price", return_value={"price": 100.0}):
            result = await BinanceService.calculate_kelly_sizing(
                "BTCUSDT", win_prob=0.6, payout_ratio=2.0, bankroll_override=5000.0
            )
        assert result["current_price"] == 100.0
        assert result["symbol"] == "BTCUSDT"
        assert result["asset_units"] == pytest.approx(result["alocacao_dolares"] / 100.0, rel=1e-6)

    async def test_returns_error_when_price_unavailable(self):
        with patch.object(BinanceService, "get_ticker_price", return_value=None):
            result = await BinanceService.calculate_kelly_sizing("BADSYM", win_prob=0.5, payout_ratio=1.0)
        assert "error" in result

    async def test_falls_back_to_default_bankroll_when_account_has_no_balances(self):
        with patch.object(BinanceService, "get_ticker_price", return_value={"price": 100.0}), \
             patch.object(BinanceService, "get_account_info", return_value={"error": "no creds"}):
            result = await BinanceService.calculate_kelly_sizing("BTCUSDT", win_prob=0.6, payout_ratio=2.0)
        # default bankroll is 10_000.0 when account info has no "balances" key
        assert result["current_price"] == 100.0

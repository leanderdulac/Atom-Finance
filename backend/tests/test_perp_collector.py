"""Public perp collector — mocked Binance + Hyperliquid, no live orders."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.perp_collector import collect_quotes


def _resp(json_data):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = json_data
    return r


@pytest.mark.asyncio
async def test_collects_two_books_and_flags_positive_edge():
    async def _get(url, params=None, timeout=None):
        if "bookTicker" in url:
            return _resp({"bidPrice": "100.0", "askPrice": "100.05"})
        if "premiumIndex" in url:
            return _resp({"lastFundingRate": "0.0001"})
        raise AssertionError(url)

    async def _post(url, json=None, timeout=None):
        if json and json.get("type") == "l2Book":
            return _resp({
                "levels": [
                    [{"px": "100.8", "sz": "2", "n": 1}],
                    [{"px": "100.9", "sz": "2", "n": 1}],
                ]
            })
        if json and json.get("type") == "metaAndAssetCtxs":
            return _resp([{"universe": [{"name": "BTC"}]}, [{"funding": -0.00005}]])
        raise AssertionError(json)

    client = MagicMock()
    client.get = _get
    client.post = _post
    out = await collect_quotes("BTCUSDT", client=client, notional=10_000)
    assert out["live_books"] is True
    assert {v["venue"] for v in out["venues"]} == {"binance_usdm", "hyperliquid"}
    assert out["best_route"]["buy_venue"] == "binance_usdm"
    assert out["eligible_for_live_trading"] is False


@pytest.mark.asyncio
async def test_raises_when_only_one_venue_responds():
    async def _get(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    client = MagicMock()
    client.get = _get
    client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ValueError, match="Need two live books"):
        await collect_quotes("ETHUSDT", client=client)

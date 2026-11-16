"""Crypto snapshot for the client arsenal: Binance first, timeout on Yahoo."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.ready_operation import MIN_HISTORY
from app.services.client_arsenal import (
    FX_CACHE_KEY,
    FX_LAST_KEY,
    fetch_binance_crypto,
    load_market,
    resolve_usd_brl,
)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, price: float, n: int = 80):
        self.price = price
        self.n = n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        if "ticker/price" in url:
            return _Resp({"price": str(self.price)})
        start = datetime(2025, 1, 1, tzinfo=UTC)
        rows = []
        px = self.price * 0.7
        for i in range(self.n):
            px *= 1.003
            ts = int((start + timedelta(days=i)).timestamp() * 1000)
            rows.append([ts, px, px, px, px, 1, 0, 0, 0, 0, 0, 0])
        return _Resp(rows)


def test_fetch_binance_crypto_parses_klines(monkeypatch):
    monkeypatch.setattr("app.services.client_arsenal.httpx.Client", lambda timeout=8.0: _Client(1956.31, n=120))
    asset = {"id": "ETH", "binance": "ETHUSDT"}
    quote, history = fetch_binance_crypto(asset)
    assert quote is not None and history is not None
    assert quote["provider"] == "binance"
    assert quote["price"] == 1956.31
    assert len(history["close"]) >= MIN_HISTORY
    assert history["close"][-1] > 0


def test_fetch_binance_crypto_short_history_is_none(monkeypatch):
    monkeypatch.setattr("app.services.client_arsenal.httpx.Client", lambda timeout=8.0: _Client(100.0, n=10))
    quote, history = fetch_binance_crypto({"id": "SOL", "binance": "SOLUSDT"})
    assert quote is None and history is None


def test_load_market_uses_binance_for_btc(monkeypatch):
    quote = {"ticker": "BTC", "price": 95000.0, "provider": "binance", "source": "binance"}
    history = {
        "ticker": "BTC",
        "close": [90000.0 + i * 10 for i in range(80)],
        "dates": ["2025-01-01"] * 80,
        "provider": "binance",
        "source": "binance",
    }
    monkeypatch.setattr("app.services.client_arsenal.Cache.get", lambda *a, **k: None)
    monkeypatch.setattr("app.services.client_arsenal.fetch_binance_crypto", lambda asset: (quote, history))
    view = load_market("BTC")
    assert view is not None
    assert view.quote["provider"] == "binance"
    assert len(view.history["close"]) >= MIN_HISTORY


def test_resolve_usd_brl_live_then_stale_cache(monkeypatch):
    from app.core.cache import Cache

    Cache.delete(FX_CACHE_KEY)
    Cache.delete(FX_LAST_KEY)

    class _Fx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None):
            return _Resp({"price": "5.42"})

    monkeypatch.setattr("app.services.client_arsenal.httpx.Client", lambda timeout=8.0: _Fx())
    live = resolve_usd_brl(allow_network=True)
    assert live is not None
    assert live["rate"] == 5.42
    assert live["source"] == "binance:USDTBRL"
    assert live["stale"] is False

    monkeypatch.setattr("app.services.client_arsenal._fetch_usd_brl_binance", lambda: None)
    monkeypatch.setattr("app.services.client_arsenal._fetch_usd_brl_yahoo", lambda: None)
    Cache.delete(FX_CACHE_KEY)
    stale = resolve_usd_brl(allow_network=True)
    assert stale is not None
    assert stale["rate"] == 5.42
    assert stale["stale"] is True


def test_resolve_usd_brl_rejects_nonsensical_rate(monkeypatch):
    from app.core.cache import Cache

    Cache.delete(FX_CACHE_KEY)
    Cache.delete(FX_LAST_KEY)

    class _Fx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None):
            return _Resp({"price": "1956.0"})

    monkeypatch.setattr("app.services.client_arsenal.httpx.Client", lambda timeout=8.0: _Fx())
    monkeypatch.setattr("app.services.client_arsenal._fetch_usd_brl_yahoo", lambda: None)
    assert resolve_usd_brl(allow_network=True) is None

"""Oracle: routing, arbitration, staleness, disagreement, heartbeat, US chains.

All provider seams are monkeypatched — no network. Cache diary uses the
in-memory store and is cleared per test.
"""
from datetime import UTC, datetime, timedelta

import pytest

from app.core.cache import Cache
from app.services import oracle
from app.services.market_sources import SourceError


@pytest.fixture(autouse=True)
def _clean_diary():
    Cache.delete(oracle.DIARY_KEY)
    yield
    Cache.delete(oracle.DIARY_KEY)


def _ts(seconds_ago=5):
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _patch(monkeypatch, **overrides):
    async def _boom(*a, **k):
        raise SourceError(502, "down")
    defaults = {"_fetch_yfinance": _boom, "_fetch_tradier": _boom,
                "_fetch_brapi": _boom, "_fetch_binance": _boom,
                "_fetch_hyperliquid": _boom}
    defaults.update(overrides)
    for name, fn in defaults.items():
        monkeypatch.setattr(oracle, name, fn)


def test_classify_routes_each_class():
    assert oracle.classify("PETR4") == "equity_br"
    assert oracle.classify("petr4.sa") == "equity_br"
    assert oracle.classify("BTC") == "crypto"
    assert oracle.classify("ETHUSDT") == "crypto"
    assert oracle.classify("SOL-USD") == "crypto"
    assert oracle.classify("DOGEUSDT") == "crypto"
    assert oracle.classify("AAPL") == "equity_us"
    with pytest.raises(SourceError):
        oracle.classify("")
    with pytest.raises(SourceError):
        oracle.classify("x" * 26)


@pytest.mark.asyncio
async def test_spot_median_of_fresh_sources(monkeypatch):
    async def yf(symbol, owner):
        assert symbol == "PETR4.SA"
        return {"price": 40.0, "bid": 39.9, "ask": 40.1, "ts": _ts(10),
                "data_mode": "delayed", "currency": "BRL"}

    async def brapi(ticker):
        assert ticker == "PETR4"
        return {"price": 40.2, "bid": None, "ask": None, "ts": None,
                "data_mode": "unverified", "currency": "BRL"}

    _patch(monkeypatch, _fetch_yfinance=yf, _fetch_brapi=brapi)
    out = await oracle.spot("PETR4")
    # brapi has unknown age: excluded from arbitration, kept for display.
    assert out["usable"] is True
    assert out["price"] == 40.0
    assert out["method"] == "median_fresh"
    assert out["disagreement_bps"] == 0.0
    assert {s["provider"] for s in out["sources"]} == {"brapi", "yfinance"}


@pytest.mark.asyncio
async def test_spot_disagreement_is_flagged(monkeypatch):
    async def yf(symbol, owner):
        return {"price": 100.0, "bid": None, "ask": None, "ts": _ts(5),
                "data_mode": "delayed", "currency": "USD"}

    async def tradier(symbol, owner):
        return {"price": 101.0, "bid": None, "ask": None, "ts": _ts(5),
                "data_mode": "realtime", "currency": "USD"}

    _patch(monkeypatch, _fetch_yfinance=yf, _fetch_tradier=tradier)
    monkeypatch.setenv("TRADIER_ACCESS_TOKEN", "test")
    out = await oracle.spot("AAPL")
    assert out["usable"] is True
    assert out["price"] == 100.5
    assert out["disagreement_bps"] == pytest.approx(99.5, abs=0.1)
    assert any("divergem" in b for b in out["blockers"])


@pytest.mark.asyncio
async def test_spot_stale_source_excluded_and_reported(monkeypatch):
    async def yf(symbol, owner):
        return {"price": 50.0, "bid": None, "ask": None, "ts": _ts(2000),
                "data_mode": "delayed", "currency": "USD"}

    async def tradier(symbol, owner):
        return {"price": 55.0, "bid": None, "ask": None, "ts": _ts(5),
                "data_mode": "realtime", "currency": "USD"}

    _patch(monkeypatch, _fetch_yfinance=yf, _fetch_tradier=tradier)
    monkeypatch.setenv("TRADIER_ACCESS_TOKEN", "test")
    out = await oracle.spot("AAPL")
    assert out["price"] == 55.0
    assert out["stale"] == ["yfinance"]
    assert any("2000" in b and "1500" in b for b in out["blockers"])


def test_stale_after_is_mode_aware_with_strict_fallback():
    assert oracle.stale_after("crypto", "realtime") == 30.0
    assert oracle.stale_after("crypto", "delayed") == 300.0
    assert oracle.stale_after("equity_br", "realtime") == 300.0
    assert oracle.stale_after("equity_br", "delayed") == 1500.0
    assert oracle.stale_after("equity_us", "delayed") == 1500.0
    assert oracle.stale_after("equity_us", "unverified") == 300.0
    assert oracle.stale_after("equity_us", None) == 300.0
    assert oracle.stale_after("crypto", "weird") == 30.0


@pytest.mark.asyncio
async def test_spot_delayed_quote_within_25min_is_fresh(monkeypatch):
    async def yf(symbol, owner):
        return {"price": 100.0, "bid": None, "ask": None, "ts": _ts(900),
                "data_mode": "delayed", "currency": "USD"}

    _patch(monkeypatch, _fetch_yfinance=yf)
    out = await oracle.spot("AAPL")
    assert out["usable"] is True
    assert out["price"] == 100.0
    assert out["stale"] == []
    assert out["method"] == "median_fresh"


@pytest.mark.asyncio
async def test_spot_sole_unknown_age_is_display_only(monkeypatch):
    async def bn(symbol):
        assert symbol == "BTCUSDT"
        return {"price": 90000.0, "bid": None, "ask": None, "ts": None,
                "data_mode": "unverified", "currency": "USDT"}

    _patch(monkeypatch, _fetch_binance=bn)
    out = await oracle.spot("BTC")
    assert out["usable"] is True
    assert out["method"] == "sole_unknown_age"
    assert any("Idade desconhecida" in b for b in out["blockers"])


@pytest.mark.asyncio
async def test_spot_hyperliquid_joins_crypto_arbitration(monkeypatch):
    async def bn(symbol):
        return {"price": 90000.0, "bid": None, "ask": None, "ts": None,
                "data_mode": "unverified", "currency": "USDT"}

    async def hl(base):
        assert base == "BTC"
        return {"price": 90100.0, "bid": 90090.0, "ask": 90110.0, "ts": _ts(3),
                "data_mode": "realtime", "currency": "USD"}

    async def yf(symbol, owner):
        return {"price": 90200.0, "bid": None, "ask": None, "ts": _ts(10),
                "data_mode": "delayed", "currency": "USD"}

    _patch(monkeypatch, _fetch_binance=bn, _fetch_hyperliquid=hl, _fetch_yfinance=yf)
    out = await oracle.spot("BTC")
    assert out["usable"] is True
    assert out["price"] == 90150.0  # median of the two fresh lasts
    assert {s["provider"] for s in out["sources"]} == {"binance", "hyperliquid", "yfinance"}
    hl_row = next(s for s in out["sources"] if s["provider"] == "hyperliquid")
    assert hl_row["stale"] is False and hl_row["age_unknown"] is False


@pytest.mark.asyncio
async def test_spot_all_failed_is_unusable_not_synthetic(monkeypatch):
    _patch(monkeypatch)
    out = await oracle.spot("PETR4")
    assert out["usable"] is False
    assert out["price"] is None
    assert len(out["blockers"]) == 2


@pytest.mark.asyncio
async def test_spot_records_diary_and_heartbeat_reads_it(monkeypatch):
    async def yf(symbol, owner):
        return {"price": 10.0, "bid": None, "ask": None, "ts": _ts(5),
                "data_mode": "delayed", "currency": "USD"}

    _patch(monkeypatch, _fetch_yfinance=yf)
    await oracle.spot("AAPL")
    beat = oracle.heartbeat()
    assert beat["providers"]["yfinance"]["last_ok"] is True
    assert "brapi" not in beat["providers"]  # US routing never touches brapi
    assert beat["configured"]["yfinance"] is True
    assert isinstance(beat["diary"], list) and beat["diary"]


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def to_dict(self, _mode):
        return self._rows


class _FakeChain:
    def __init__(self, calls, puts):
        self.calls = _FakeFrame(calls)
        self.puts = _FakeFrame(puts)


class _FakeTicker:
    options = ["2026-07-17", "2026-09-18"]

    def __init__(self, symbol):
        self.symbol = symbol
        self.fast_info = {"last_price": 100.0}

    def option_chain(self, exp):
        row = {"strike": 100, "lastPrice": 4.0, "bid": 3.9, "ask": 4.1,
               "volume": 10, "openInterest": 50, "impliedVolatility": 0.3}
        return _FakeChain([dict(row)], [dict(row, lastPrice=5.0)])


@pytest.mark.asyncio
async def test_chain_us_multi_expiry_shape(monkeypatch):
    monkeypatch.setattr(oracle, "_yf_ticker", _FakeTicker)
    out = await oracle.chain_us("AAPL")
    assert out["S0"] == 100.0
    assert out["expirations"] == ["2026-07-17", "2026-09-18"]
    assert len(out["chains"]) == 2
    assert out["chains"][0]["calls"][0]["strike"] == 100
    # The Heston adapter must accept this shape directly.
    from app.models.volatility import HestonModel
    quotes = HestonModel.quotes_from_option_chain(out["chains"], S0=100.0, as_of="2026-01-02")
    assert len(quotes) == 4
    assert {q["option_type"] for q in quotes} == {"call", "put"}


@pytest.mark.asyncio
async def test_chain_us_rejects_bad_input(monkeypatch):
    monkeypatch.setattr(oracle, "_yf_ticker", _FakeTicker)
    with pytest.raises(SourceError):
        await oracle.chain_us("PETR4.SA")
    with pytest.raises(SourceError):
        await oracle.chain_us("AAPL", expiries=["2030-01-01"])
    with pytest.raises(SourceError):
        await oracle.chain_us("AAPL", expiries=["a", "b", "c", "d", "e"])

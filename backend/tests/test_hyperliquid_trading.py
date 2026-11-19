"""Hyperliquid broker link — guards, config and endpoints. No network."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import hyperliquid as hl_api
from app.api.hyperliquid import router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.services import hyperliquid_trading as hl


def _env(monkeypatch, **pairs):
    for key in (
        "HYPERLIQUID_TESTNET",
        "HYPERLIQUID_API_WALLET_KEY",
        "HYPERLIQUID_ACCOUNT_ADDRESS",
        "HYPERLIQUID_LIVE_TRADING",
        "HYPERLIQUID_MAX_NOTIONAL_USD",
        "HYPERLIQUID_MARKET_SLIPPAGE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in pairs.items():
        monkeypatch.setenv(key, value)


def _client(monkeypatch, role="admin"):
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "alice"

    async def _lookup(username: str):
        if role is None:
            return None
        return {"username": username, "role": role}

    monkeypatch.setattr(hl_api, "get_user_by_username", _lookup)
    return TestClient(app, raise_server_exceptions=False)


def _offline(*_args, **_kwargs):
    raise AssertionError("SDK must not be called")


class _FakeInfo:
    def __init__(self, mids=None):
        self._mids = mids or {"BTC": "67000.5", "ETH": "3500.0"}

    def all_mids(self):
        return self._mids

    def meta(self):
        return {
            "universe": [
                {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
            ]
        }

    def user_state(self, address):
        return {"address": address, "marginSummary": {"accountValue": "1000.0"}}

    def open_orders(self, address):
        return []


class _FakeExchange:
    def __init__(self, response=None):
        self.calls = []
        self._response = response if response is not None else {"status": "ok"}

    def market_open(self, name, is_buy, sz, px=None, slippage=None, **kwargs):
        self.calls.append(("market_open", name, is_buy, sz, px, slippage))
        return self._response

    def order(self, name, is_buy, sz, px, order_type, reduce_only=False, **kwargs):
        self.calls.append(("order", name, is_buy, sz, px, order_type, reduce_only))
        return self._response

    def cancel(self, name, oid):
        self.calls.append(("cancel", name, oid))
        return self._response


def _keys(**extra):
    base = {
        "HYPERLIQUID_API_WALLET_KEY": "0xabc",
        "HYPERLIQUID_ACCOUNT_ADDRESS": "0xmaster",
    }
    base.update(extra)
    return base


# --- config & guards ---


def test_defaults_are_testnet_blocked(monkeypatch):
    _env(monkeypatch)
    cfg = hl.load_config()
    assert cfg.testnet is True
    assert cfg.live_trading is False
    assert cfg.base_url == "https://api.hyperliquid-testnet.xyz"
    assert cfg.max_notional_usd == 100.0
    assert cfg.market_slippage == 0.01
    assert cfg.what_broke == []


def test_write_needs_keys(monkeypatch):
    _env(monkeypatch)
    cfg = hl.load_config()
    blockers = hl.guard_write(cfg, live=False, notional_usd=10)
    assert any("HYPERLIQUID_API_WALLET_KEY" in b for b in blockers)
    assert any("HYPERLIQUID_ACCOUNT_ADDRESS" in b for b in blockers)


def test_testnet_write_allowed_with_keys_under_cap(monkeypatch):
    _env(monkeypatch, **_keys())
    cfg = hl.load_config()
    assert hl.guard_write(cfg, live=False, notional_usd=10) == []
    assert hl.guard_cancel(cfg, live=False) == []


def test_notional_cap_blocks(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_MAX_NOTIONAL_USD="50"))
    cfg = hl.load_config()
    blockers = hl.guard_write(cfg, live=False, notional_usd=51)
    assert any("teto" in b for b in blockers)


def test_mainnet_blocked_by_default(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_TESTNET="false"))
    cfg = hl.load_config()
    assert cfg.network == "mainnet"
    blockers = hl.guard_write(cfg, live=True, notional_usd=10)
    assert any("LIVE_TRADING" in b for b in blockers)
    assert any("LIVE_TRADING" in b for b in hl.guard_cancel(cfg, live=True))


def test_mainnet_needs_flag_and_explicit_live(monkeypatch):
    _env(
        monkeypatch,
        **_keys(HYPERLIQUID_TESTNET="false", HYPERLIQUID_LIVE_TRADING="true"),
    )
    cfg = hl.load_config()
    assert any("live=True" in b for b in hl.guard_write(cfg, live=False, notional_usd=10))
    assert any("live=True" in b for b in hl.guard_cancel(cfg, live=False))
    assert hl.guard_write(cfg, live=True, notional_usd=10) == []
    assert hl.guard_cancel(cfg, live=True) == []


def test_market_notional_uses_worst_price():
    assert hl.market_notional(1, 100, "buy", 0.01) == pytest.approx(101)
    assert hl.market_notional(1, 100, "sell", 0.01) == pytest.approx(99)
    assert hl.market_notional(2, 10, "buy", 0) == pytest.approx(20)


def test_default_slippage_is_one_percent(monkeypatch):
    _env(monkeypatch)
    cfg = hl.load_config()
    assert cfg.market_slippage == 0.01
    assert hl.status_payload(cfg)["market_slippage"] == 0.01


def test_custom_slippage(monkeypatch):
    _env(monkeypatch, HYPERLIQUID_MARKET_SLIPPAGE="0.02")
    cfg = hl.load_config()
    assert cfg.market_slippage == 0.02
    assert cfg.what_broke == []


@pytest.mark.parametrize("raw", ["nope", "-0.1", "1", "1.5", "nan"])
def test_invalid_slippage_falls_back_and_blocks_writes(monkeypatch, raw):
    _env(monkeypatch, **_keys(HYPERLIQUID_MARKET_SLIPPAGE=raw))
    cfg = hl.load_config()
    assert cfg.market_slippage == 0.01
    blockers = hl.guard_write(cfg, live=False, notional_usd=10)
    assert any("MARKET_SLIPPAGE" in b for b in blockers)


def test_round_to_lot():
    assert hl.round_to_lot(0.123456, 3) == 0.123
    assert hl.round_to_lot(-1, 3) == 0.0


def test_normalize_coin():
    assert hl.normalize_coin(" btc ") == "BTC"
    assert hl.normalize_coin("eth2") == "ETH2"
    for bad in ("", "BTC-USD", "btc/usdt", "ABCDEFGHIJKLM", "btc usd", "!!!", "a.b"):
        with pytest.raises(ValueError):
            hl.normalize_coin(bad)


def test_status_never_leaks_key(monkeypatch):
    _env(monkeypatch, HYPERLIQUID_API_WALLET_KEY="super-secret-key")
    payload = hl.status_payload(hl.load_config())
    assert "super-secret-key" not in str(payload)
    assert payload["wallet_configured"] is True


def test_sdk_rejection_maps_statuses_and_transport():
    code, message = hl.sdk_rejection(
        {"status": "ok", "response": {"data": {"statuses": [{"error": "min notional"}]}}}
    )
    assert code == 422
    assert "min notional" in message
    code, _message = hl.sdk_rejection({"status": "err", "response": "Invalid nonce"})
    assert code == 502
    assert hl.sdk_rejection({"status": "ok"}) is None
    assert hl.sdk_rejection({"status": "ok", "response": {"data": {"statuses": [{"filled": {"oid": 1}}]}}}) is None
    assert hl.sdk_rejection({"status": "ok", "response": {"data": {"statuses": ["success"]}}}) is None
    assert hl.sdk_rejection("nope")[0] == 502


# --- endpoints (mocked SDK, no network) ---


def test_status_endpoint(monkeypatch):
    _env(monkeypatch)
    resp = _client(monkeypatch).get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["network"] == "testnet"
    assert body["market_slippage"] == 0.01


def test_markets_endpoint(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).get("/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mids"]["BTC"] == "67000.5"
    assert body["meta"]["BTC"]["sz_decimals"] == 5


def test_reads_stay_available_to_non_operators(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "info_client", _offline)
    monkeypatch.setattr(hl, "exchange_client", _offline)
    client = _client(monkeypatch, role="analyst")
    assert client.get("/status").status_code == 200
    resp = client.post("/order", json={"coin": "BTC", "side": "buy", "size": 0.001})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin or operator access required."
    resp = client.post("/cancel", json={"coin": "BTC", "oid": 1})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin or operator access required."


def test_unknown_user_cannot_write(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "exchange_client", _offline)
    resp = _client(monkeypatch, role=None).post("/cancel", json={"coin": "BTC", "oid": 1})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin or operator access required."


def test_order_blocked_without_keys(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 0.001})
    assert resp.status_code == 403
    assert "blockers" in resp.json()["detail"] or "blockers" in str(resp.json())


def test_order_unknown_coin(monkeypatch):
    _env(monkeypatch, **_keys())
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).post("/order", json={"coin": "NOPE", "side": "buy", "size": 1})
    assert resp.status_code == 422


def test_order_rejects_coin_outside_charset(monkeypatch):
    _env(monkeypatch, **_keys())
    monkeypatch.setattr(hl, "info_client", _offline)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC-USD", "side": "buy", "size": 0.001})
    assert resp.status_code == 422
    assert "desconhecido" not in resp.text


def test_order_testnet_market_sends(monkeypatch):
    _env(monkeypatch, **_keys())
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/order", json={"coin": "btc", "side": "buy", "size": 0.001})
    assert resp.status_code == 200
    assert fake.calls and fake.calls[0][0] == "market_open"
    assert fake.calls[0][5] == 0.01
    assert fake.calls[0][4] == pytest.approx(67000.5)
    body = resp.json()
    assert body["network"] == "testnet"
    assert body["coin"] == "BTC"
    assert body["slippage"] == 0.01
    assert body["notional_usd"] == pytest.approx(0.001 * 67000.5 * 1.01)


def test_order_over_cap_blocked(monkeypatch):
    _env(monkeypatch, **_keys())
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", _offline)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 1.0})
    assert resp.status_code == 403


def test_market_buy_notional_includes_slippage(monkeypatch):
    """Mid notional sits on the cap; the aggressive buy price steps over it."""
    _env(monkeypatch, **_keys(HYPERLIQUID_MAX_NOTIONAL_USD="100"))
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo(mids={"BTC": "100"}))
    monkeypatch.setattr(hl, "exchange_client", _offline)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 1})
    assert resp.status_code == 403
    assert "101.00" in str(resp.json())


def test_market_sell_notional_uses_slippage_discount(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_MAX_NOTIONAL_USD="100"))
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo(mids={"BTC": "100"}))
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "sell", "size": 1})
    assert resp.status_code == 200
    assert resp.json()["notional_usd"] == pytest.approx(99)
    assert fake.calls[0] == ("market_open", "BTC", False, 1.0, 100.0, 0.01)


def test_custom_slippage_is_passed_to_market_open(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_MARKET_SLIPPAGE="0.02", HYPERLIQUID_MAX_NOTIONAL_USD="1000"))
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo(mids={"BTC": "100"}))
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 1})
    assert resp.status_code == 200
    assert resp.json()["notional_usd"] == pytest.approx(102)
    assert fake.calls[0][5] == 0.02


def test_limit_notional_ignores_market_slippage(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_MAX_NOTIONAL_USD="100"))
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo(mids={"BTC": "100"}))
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post(
        "/order",
        json={"coin": "BTC", "side": "buy", "size": 1, "price": 100, "reduce_only": True},
    )
    assert resp.status_code == 200
    assert resp.json()["notional_usd"] == pytest.approx(100)
    assert resp.json()["slippage"] is None
    assert fake.calls[0] == (
        "order",
        "BTC",
        True,
        1.0,
        100.0,
        {"limit": {"tif": "Gtc"}},
        True,
    )


def test_order_status_error_is_422(monkeypatch):
    _env(monkeypatch, **_keys())
    fake = _FakeExchange(
        response={"status": "ok", "response": {"data": {"statuses": [{"error": "Order must have minimum value of $10."}]}}}
    )
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 0.001})
    assert resp.status_code == 422
    assert "minimum value" in resp.text


def test_order_transport_error_is_502(monkeypatch):
    _env(monkeypatch, **_keys())
    secret = "0xabc"
    fake = _FakeExchange(response={"status": "err", "response": f"boom {secret}"})
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/order", json={"coin": "BTC", "side": "buy", "size": 0.001})
    assert resp.status_code == 502
    assert secret not in resp.text
    assert "[redacted]" in resp.text


def test_cancel_testnet_operator(monkeypatch):
    _env(monkeypatch, **_keys())
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch, role="operator").post("/cancel", json={"coin": "btc", "oid": 123})
    assert resp.status_code == 200
    assert fake.calls == [("cancel", "BTC", 123)]


def test_cancel_mainnet_requires_live_true(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_TESTNET="false", HYPERLIQUID_LIVE_TRADING="true"))
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    client = _client(monkeypatch)
    blocked = client.post("/cancel", json={"coin": "BTC", "oid": 7})
    assert blocked.status_code == 403
    assert fake.calls == []
    assert "live=True" in str(blocked.json())
    allowed = client.post("/cancel", json={"coin": "BTC", "oid": 7, "live": True})
    assert allowed.status_code == 200
    assert fake.calls == [("cancel", "BTC", 7)]


def test_cancel_mainnet_requires_env_flag(monkeypatch):
    _env(monkeypatch, **_keys(HYPERLIQUID_TESTNET="false"))
    monkeypatch.setattr(hl, "exchange_client", _offline)
    resp = _client(monkeypatch).post("/cancel", json={"coin": "BTC", "oid": 7, "live": True})
    assert resp.status_code == 403
    assert "LIVE_TRADING" in str(resp.json())


def test_cancel_status_error_is_422(monkeypatch):
    _env(monkeypatch, **_keys())
    fake = _FakeExchange(
        response={"status": "ok", "response": {"data": {"statuses": [{"error": "already canceled"}]}}}
    )
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/cancel", json={"coin": "BTC", "oid": 1})
    assert resp.status_code == 422
    assert "already canceled" in resp.text


def test_sdk_calls_run_in_threadpool(monkeypatch):
    seen: list[str] = []

    async def _inline(func, *args, **kwargs):
        target = getattr(func, "func", func)
        seen.append(getattr(target, "__name__", type(target).__name__))
        return func(*args, **kwargs)

    _env(monkeypatch, **_keys())
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    monkeypatch.setattr(hl_api, "run_in_threadpool", _inline)
    client = _client(monkeypatch)
    assert client.get("/markets").status_code == 200
    assert client.get("/account").status_code == 200
    assert client.post("/order", json={"coin": "BTC", "side": "buy", "size": 0.001}).status_code == 200
    assert client.post("/cancel", json={"coin": "BTC", "oid": 1}).status_code == 200
    assert "fetch_markets" in seen
    assert "fetch_account" in seen
    assert "submit_order" in seen
    assert "submit_cancel" in seen

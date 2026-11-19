"""Hyperliquid broker link — guards, config and endpoints. No network."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hyperliquid import router
from app.core.security import get_current_user
from app.services import hyperliquid_trading as hl


def _env(monkeypatch, **pairs):
    for key in (
        "HYPERLIQUID_TESTNET",
        "HYPERLIQUID_API_WALLET_KEY",
        "HYPERLIQUID_ACCOUNT_ADDRESS",
        "HYPERLIQUID_LIVE_TRADING",
        "HYPERLIQUID_MAX_NOTIONAL_USD",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in pairs.items():
        monkeypatch.setenv(key, value)


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    return TestClient(app, raise_server_exceptions=False)


class _FakeInfo:
    def __init__(self, *args, **kwargs):
        pass

    def all_mids(self):
        return {"BTC": "67000.5", "ETH": "3500.0"}

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
    def __init__(self):
        self.calls = []

    def market_open(self, name, is_buy, sz, **kwargs):
        self.calls.append(("market_open", name, is_buy, sz))
        return {"status": "ok"}

    def order(self, name, is_buy, sz, px, order_type, **kwargs):
        self.calls.append(("order", name, is_buy, sz, px))
        return {"status": "ok"}

    def cancel(self, name, oid):
        self.calls.append(("cancel", name, oid))
        return {"status": "ok"}


# --- config & guards ---


def test_defaults_are_testnet_blocked(monkeypatch):
    _env(monkeypatch)
    cfg = hl.load_config()
    assert cfg.testnet is True
    assert cfg.live_trading is False
    assert cfg.base_url == "https://api.hyperliquid-testnet.xyz"
    assert cfg.max_notional_usd == 100.0


def test_write_needs_keys(monkeypatch):
    _env(monkeypatch)
    cfg = hl.load_config()
    blockers = hl.guard_write(cfg, live=False, notional_usd=10)
    assert any("HYPERLIQUID_API_WALLET_KEY" in b for b in blockers)
    assert any("HYPERLIQUID_ACCOUNT_ADDRESS" in b for b in blockers)


def test_testnet_write_allowed_with_keys_under_cap(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    cfg = hl.load_config()
    assert hl.guard_write(cfg, live=False, notional_usd=10) == []


def test_notional_cap_blocks(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
        HYPERLIQUID_MAX_NOTIONAL_USD="50",
    )
    cfg = hl.load_config()
    blockers = hl.guard_write(cfg, live=False, notional_usd=51)
    assert any("teto" in b for b in blockers)


def test_mainnet_blocked_by_default(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_TESTNET="false",
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    cfg = hl.load_config()
    assert cfg.network == "mainnet"
    blockers = hl.guard_write(cfg, live=True, notional_usd=10)
    assert any("LIVE_TRADING" in b for b in blockers)


def test_mainnet_needs_flag_and_explicit_live(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_TESTNET="false",
        HYPERLIQUID_LIVE_TRADING="true",
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    cfg = hl.load_config()
    assert any("live=True" in b for b in hl.guard_write(cfg, live=False, notional_usd=10))
    assert hl.guard_write(cfg, live=True, notional_usd=10) == []


def test_round_to_lot():
    assert hl.round_to_lot(0.123456, 3) == 0.123
    assert hl.round_to_lot(-1, 3) == 0.0


def test_status_never_leaks_key(monkeypatch):
    _env(monkeypatch, HYPERLIQUID_API_WALLET_KEY="super-secret-key")
    payload = hl.status_payload(hl.load_config())
    assert "super-secret-key" not in str(payload)
    assert payload["wallet_configured"] is True


# --- endpoints (mocked SDK, no network) ---


def test_status_endpoint(monkeypatch):
    _env(monkeypatch)
    resp = _client(monkeypatch).get("/status")
    assert resp.status_code == 200
    assert resp.json()["network"] == "testnet"


def test_markets_endpoint(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).get("/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mids"]["BTC"] == "67000.5"
    assert body["meta"]["BTC"]["sz_decimals"] == 5


def test_order_blocked_without_keys(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).post(
        "/order", json={"coin": "BTC", "side": "buy", "size": 0.001}
    )
    assert resp.status_code == 403
    assert "blockers" in resp.json()["detail"] or "blockers" in str(resp.json())


def test_order_unknown_coin(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).post(
        "/order", json={"coin": "NOPE", "side": "buy", "size": 1}
    )
    assert resp.status_code == 422


def test_order_testnet_market_sends(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post(
        "/order", json={"coin": "BTC", "side": "buy", "size": 0.001}
    )
    assert resp.status_code == 200
    assert fake.calls and fake.calls[0][0] == "market_open"
    assert resp.json()["network"] == "testnet"


def test_order_over_cap_blocked(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    monkeypatch.setattr(hl, "info_client", lambda cfg: _FakeInfo())
    resp = _client(monkeypatch).post(
        "/order", json={"coin": "BTC", "side": "buy", "size": 1.0}
    )
    assert resp.status_code == 403


def test_cancel_testnet(monkeypatch):
    _env(
        monkeypatch,
        HYPERLIQUID_API_WALLET_KEY="0xabc",
        HYPERLIQUID_ACCOUNT_ADDRESS="0xmaster",
    )
    fake = _FakeExchange()
    monkeypatch.setattr(hl, "exchange_client", lambda cfg: fake)
    resp = _client(monkeypatch).post("/cancel", json={"coin": "BTC", "oid": 123})
    assert resp.status_code == 200
    assert fake.calls == [("cancel", "BTC", 123)]

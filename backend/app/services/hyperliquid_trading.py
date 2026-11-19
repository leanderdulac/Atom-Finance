"""Hyperliquid trading connector. Testnet-first, mainnet blocked by default.

Reads go through the public unsigned ``/info`` endpoint (no key needed).
Writes go through ``/exchange`` signed by an API wallet key. An API wallet
can trade but cannot withdraw; the master account address must be supplied
separately and every live order or cancel needs BOTH the
``HYPERLIQUID_LIVE_TRADING=true`` env flag AND an explicit ``live=True``
call-site argument, plus a per-order USD notional cap.

Market orders are capped at the price ``market_open`` will actually submit:
mid × (1 + slippage) on a buy and mid × (1 − slippage) on a sell. Slippage
is ``HYPERLIQUID_MARKET_SLIPPAGE`` (default 0.01) and is passed explicitly
so the SDK's own 5% default never applies.

Env:
  HYPERLIQUID_TESTNET=true|false (default true)
  HYPERLIQUID_API_WALLET_KEY=<hex> (API wallet only, never the master key)
  HYPERLIQUID_ACCOUNT_ADDRESS=0x... (master account that approved the wallet)
  HYPERLIQUID_LIVE_TRADING=true to arm mainnet writes (default false)
  HYPERLIQUID_MAX_NOTIONAL_USD per-order cap (default 100)
  HYPERLIQUID_MARKET_SLIPPAGE aggressive limit vs mid (default 0.01)
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants

    _SDK_MISSING: str | None = None
except ImportError as exc:  # pragma: no cover - exercised when SDK absent
    Exchange = Info = constants = None  # type: ignore[assignment]
    _SDK_MISSING = str(exc)

DEFAULT_MAX_NOTIONAL_USD = 100.0
DEFAULT_MARKET_SLIPPAGE = 0.01
COIN_RE = re.compile(r"[A-Z0-9]{1,12}")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sdk_missing() -> str | None:
    return _SDK_MISSING


def _require_sdk() -> None:
    if _SDK_MISSING is not None or constants is None or Info is None or Exchange is None:
        raise RuntimeError(f"hyperliquid-python-sdk ausente: {_SDK_MISSING}")


@dataclass(frozen=True)
class HLConfig:
    testnet: bool = True
    api_wallet_key: str = ""
    account_address: str = ""
    live_trading: bool = False
    max_notional_usd: float = DEFAULT_MAX_NOTIONAL_USD
    market_slippage: float = DEFAULT_MARKET_SLIPPAGE
    what_broke: list[str] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        urls = constants
        if urls is None:
            raise RuntimeError(f"hyperliquid-python-sdk ausente: {_SDK_MISSING}")
        if self.testnet:
            return urls.TESTNET_API_URL
        return urls.MAINNET_API_URL

    @property
    def network(self) -> str:
        return "testnet" if self.testnet else "mainnet"


def _market_slippage() -> tuple[float, str | None]:
    raw = os.getenv("HYPERLIQUID_MARKET_SLIPPAGE")
    if raw is None or not raw.strip():
        return DEFAULT_MARKET_SLIPPAGE, None
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MARKET_SLIPPAGE, "config: HYPERLIQUID_MARKET_SLIPPAGE inválido, usando 0.01"
    if not math.isfinite(value) or not 0 <= value < 1:
        return DEFAULT_MARKET_SLIPPAGE, "config: HYPERLIQUID_MARKET_SLIPPAGE fora de [0, 1), usando 0.01"
    return value, None


def load_config() -> HLConfig:
    """Read connector config from env. Never logs secret values."""
    what_broke: list[str] = []
    if _SDK_MISSING is not None:
        what_broke.append(f"sdk-missing: hyperliquid-python-sdk not installed ({_SDK_MISSING})")
    try:
        max_notional = float(os.getenv("HYPERLIQUID_MAX_NOTIONAL_USD", DEFAULT_MAX_NOTIONAL_USD))
    except ValueError:
        max_notional = DEFAULT_MAX_NOTIONAL_USD
        what_broke.append("config: HYPERLIQUID_MAX_NOTIONAL_USD inválido, usando 100")
    if max_notional <= 0:
        max_notional = DEFAULT_MAX_NOTIONAL_USD
        what_broke.append("config: HYPERLIQUID_MAX_NOTIONAL_USD<=0, usando 100")
    slippage, slip_note = _market_slippage()
    if slip_note:
        what_broke.append(slip_note)
    cfg = HLConfig(
        testnet=_env_bool("HYPERLIQUID_TESTNET", True),
        api_wallet_key=os.getenv("HYPERLIQUID_API_WALLET_KEY", "").strip(),
        account_address=os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "").strip(),
        live_trading=_env_bool("HYPERLIQUID_LIVE_TRADING", False),
        max_notional_usd=max_notional,
        market_slippage=slippage,
        what_broke=what_broke,
    )
    if not cfg.testnet and not cfg.live_trading:
        cfg.what_broke.append("guard: mainnet sem HYPERLIQUID_LIVE_TRADING=true — escrita bloqueada")
    return cfg


def _auth_blockers(cfg: HLConfig) -> list[str]:
    blockers: list[str] = []
    if not cfg.api_wallet_key:
        blockers.append("auth: HYPERLIQUID_API_WALLET_KEY ausente")
    if not cfg.account_address:
        blockers.append("auth: HYPERLIQUID_ACCOUNT_ADDRESS ausente")
    return blockers


def _mainnet_blockers(cfg: HLConfig, *, live: bool) -> list[str]:
    """Same double lock for orders and cancels. Empty on testnet."""
    if cfg.testnet:
        return []
    blockers: list[str] = []
    if not cfg.live_trading:
        blockers.append("guard: mainnet bloqueada sem HYPERLIQUID_LIVE_TRADING=true")
    if not live:
        blockers.append("guard: mainnet exige live=True explícito na chamada")
    return blockers


def guard_write(cfg: HLConfig, *, live: bool, notional_usd: float) -> list[str]:
    """Return blockers for an order. Empty list means allowed to proceed."""
    blockers = list(cfg.what_broke)
    if _SDK_MISSING is not None:
        return blockers
    blockers.extend(_auth_blockers(cfg))
    if notional_usd <= 0:
        blockers.append("order: nocional precisa ser > 0")
    elif notional_usd > cfg.max_notional_usd:
        blockers.append(
            f"guard: nocional ${notional_usd:.2f} acima do teto ${cfg.max_notional_usd:.2f}"
        )
    blockers.extend(_mainnet_blockers(cfg, live=live))
    return blockers


def guard_cancel(cfg: HLConfig, *, live: bool) -> list[str]:
    """Return blockers for a cancel. Mainnet uses the same double lock as orders."""
    blockers = list(cfg.what_broke)
    if _SDK_MISSING is not None:
        return blockers
    blockers.extend(_auth_blockers(cfg))
    blockers.extend(_mainnet_blockers(cfg, live=live))
    return blockers


def normalize_coin(coin: str) -> str:
    """Uppercase then require ``[A-Z0-9]{1,12}``."""
    cleaned = coin.strip().upper()
    if COIN_RE.fullmatch(cleaned) is None:
        raise ValueError("Ativo inválido: use 1–12 caracteres A–Z e 0–9.")
    return cleaned


def market_notional(size: float, mid: float, side: str, slippage: float) -> float:
    """Notional at the aggressive price ``market_open`` submits.

    Buy pays up to mid × (1 + slippage). Sell's equivalent is
    mid × (1 − slippage).
    """
    factor = (1.0 + slippage) if side == "buy" else (1.0 - slippage)
    return size * mid * factor


def info_client(cfg: HLConfig) -> Any:
    _require_sdk()
    from hyperliquid.info import Info as InfoClient

    return InfoClient(cfg.base_url, skip_ws=True)


def exchange_client(cfg: HLConfig) -> Any:
    _require_sdk()
    from eth_account import Account
    from hyperliquid.exchange import Exchange as ExchangeClient

    wallet = Account.from_key(cfg.api_wallet_key)
    return ExchangeClient(wallet, cfg.base_url, account_address=cfg.account_address or None)


def round_to_lot(size: float, sz_decimals: int) -> float:
    return round(max(size, 0.0), sz_decimals)


def meta_map(info: Any) -> dict[str, dict[str, int]]:
    """coin -> {sz_decimals, max_leverage} from universe meta."""
    universe = info.meta().get("universe", [])
    out: dict[str, dict[str, int]] = {}
    for asset in universe:
        out[asset["name"]] = {
            "sz_decimals": int(asset.get("szDecimals", 3)),
            "max_leverage": int(asset.get("maxLeverage", 1)),
        }
    return out


def fetch_markets(cfg: HLConfig) -> tuple[Any, dict[str, dict[str, int]]]:
    """Synchronous SDK read. Callers must leave the event loop first."""
    client = info_client(cfg)
    return client.all_mids(), meta_map(client)


def fetch_account(cfg: HLConfig) -> tuple[Any, Any]:
    client = info_client(cfg)
    return client.user_state(cfg.account_address), client.open_orders(cfg.account_address)


def submit_order(
    cfg: HLConfig,
    *,
    coin: str,
    is_buy: bool,
    size: float,
    limit_px: float | None,
    mid: float,
    reduce_only: bool,
) -> Any:
    """Sign and send one order. ``limit_px is None`` is a market order.

    The reference ``mid`` is passed through so ``market_open`` applies
    ``cfg.market_slippage`` once, on the same price the notional cap used.
    """
    ex = exchange_client(cfg)
    if limit_px is None:
        return ex.market_open(coin, is_buy, size, mid, slippage=cfg.market_slippage)
    return ex.order(
        coin,
        is_buy,
        size,
        limit_px,
        {"limit": {"tif": "Gtc"}},
        reduce_only=reduce_only,
    )


def submit_cancel(cfg: HLConfig, coin: str, oid: int) -> Any:
    ex = exchange_client(cfg)
    return ex.cancel(coin, oid)


def sdk_rejection(payload: object) -> tuple[int, str] | None:
    """Map an SDK write payload to ``(status_code, message)``.

    ``None`` means the call succeeded. A venue rejection inside
    ``statuses`` (an ``error`` field, or a non-``success`` string) is 422.
    A missing object or a top-level status other than ``ok`` is 502.
    """
    if not isinstance(payload, dict):
        return 502, "Resposta do SDK ilegível."
    status = payload.get("status")
    if status != "ok":
        response = payload.get("response")
        detail = response if isinstance(response, str) and response else f"status {status!r}"
        return 502, f"Falha na exchange: {detail}"[:400]
    errors = _status_errors(payload)
    if errors:
        return 422, f"Ordem rejeitada pela exchange: {'; '.join(errors)}"[:400]
    return None


def _status_errors(payload: dict[str, Any]) -> list[str]:
    response = payload.get("response")
    if not isinstance(response, dict):
        return []
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    statuses = data.get("statuses")
    if not isinstance(statuses, list):
        return []
    errors: list[str] = []
    for item in statuses:
        if isinstance(item, dict) and item.get("error"):
            errors.append(str(item["error"]))
        elif isinstance(item, str) and item != "success":
            errors.append(item)
    return errors


def status_payload(cfg: HLConfig) -> dict[str, Any]:
    return {
        "network": cfg.network,
        "base_url": cfg.base_url,
        "live_trading_armed": cfg.live_trading,
        "wallet_configured": bool(cfg.api_wallet_key),
        "account_configured": bool(cfg.account_address),
        "max_notional_usd": cfg.max_notional_usd,
        "market_slippage": cfg.market_slippage,
        "sdk_installed": _SDK_MISSING is None,
        "what_broke": list(cfg.what_broke),
    }

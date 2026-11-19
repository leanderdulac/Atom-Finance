"""Hyperliquid trading connector. Testnet-first, mainnet blocked by default.

Reads go through the public unsigned ``/info`` endpoint (no key needed).
Writes go through ``/exchange`` signed by an API wallet key. An API wallet
can trade but cannot withdraw; the master account address must be supplied
separately and every live order needs BOTH the
``HYPERLIQUID_LIVE_TRADING=true`` env flag AND an explicit ``live=True``
call-site argument, plus a per-order USD notional cap.

Env:
  HYPERLIQUID_TESTNET=true|false (default true)
  HYPERLIQUID_API_WALLET_KEY=<hex> (API wallet only, never the master key)
  HYPERLIQUID_ACCOUNT_ADDRESS=0x... (master account that approved the wallet)
  HYPERLIQUID_LIVE_TRADING=true to arm mainnet writes (default false)
  HYPERLIQUID_MAX_NOTIONAL_USD per-order cap (default 100)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants

    _SDK_MISSING: str | None = None
except ImportError as exc:  # pragma: no cover - exercised when SDK absent
    Exchange = Info = constants = None  # type: ignore[assignment]
    _SDK_MISSING = str(exc)

DEFAULT_MAX_NOTIONAL_USD = 100.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HLConfig:
    testnet: bool = True
    api_wallet_key: str = ""
    account_address: str = ""
    live_trading: bool = False
    max_notional_usd: float = DEFAULT_MAX_NOTIONAL_USD
    what_broke: list = field(default_factory=list)

    @property
    def base_url(self) -> str:
        if self.testnet:
            return constants.TESTNET_API_URL
        return constants.MAINNET_API_URL

    @property
    def network(self) -> str:
        return "testnet" if self.testnet else "mainnet"


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
    cfg = HLConfig(
        testnet=_env_bool("HYPERLIQUID_TESTNET", True),
        api_wallet_key=os.getenv("HYPERLIQUID_API_WALLET_KEY", "").strip(),
        account_address=os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", "").strip(),
        live_trading=_env_bool("HYPERLIQUID_LIVE_TRADING", False),
        max_notional_usd=max_notional,
        what_broke=what_broke,
    )
    if not cfg.testnet and not cfg.live_trading:
        cfg.what_broke.append("guard: mainnet sem HYPERLIQUID_LIVE_TRADING=true — escrita bloqueada")
    return cfg


def guard_write(cfg: HLConfig, *, live: bool, notional_usd: float) -> list[str]:
    """Return blockers for a write. Empty list means allowed to proceed."""
    blockers = list(cfg.what_broke)
    if _SDK_MISSING is not None:
        return blockers
    if not cfg.api_wallet_key:
        blockers.append("auth: HYPERLIQUID_API_WALLET_KEY ausente")
    if not cfg.account_address:
        blockers.append("auth: HYPERLIQUID_ACCOUNT_ADDRESS ausente")
    if notional_usd <= 0:
        blockers.append("order: nocional precisa ser > 0")
    elif notional_usd > cfg.max_notional_usd:
        blockers.append(
            f"guard: nocional ${notional_usd:.2f} acima do teto ${cfg.max_notional_usd:.2f}"
        )
    if not cfg.testnet:
        if not cfg.live_trading:
            blockers.append("guard: mainnet bloqueada sem HYPERLIQUID_LIVE_TRADING=true")
        if not live:
            blockers.append("guard: mainnet exige live=True explícito na chamada")
    return blockers


def info_client(cfg: HLConfig) -> Info:
    if _SDK_MISSING is not None:
        raise RuntimeError(f"hyperliquid-python-sdk ausente: {_SDK_MISSING}")
    return Info(cfg.base_url, skip_ws=True)


def exchange_client(cfg: HLConfig) -> Exchange:
    if _SDK_MISSING is not None:
        raise RuntimeError(f"hyperliquid-python-sdk ausente: {_SDK_MISSING}")
    from eth_account import Account

    wallet = Account.from_key(cfg.api_wallet_key)
    return Exchange(wallet, cfg.base_url, account_address=cfg.account_address or None)


def round_to_lot(size: float, sz_decimals: int) -> float:
    return round(max(size, 0.0), sz_decimals)


def meta_map(info: Info) -> dict:
    """coin -> {szDecimals, maxLeverage} from universe meta."""
    universe = info.meta().get("universe", [])
    out = {}
    for asset in universe:
        out[asset["name"]] = {
            "sz_decimals": int(asset.get("szDecimals", 3)),
            "max_leverage": int(asset.get("maxLeverage", 1)),
        }
    return out


def status_payload(cfg: HLConfig) -> dict:
    return {
        "network": cfg.network,
        "base_url": cfg.base_url,
        "live_trading_armed": cfg.live_trading,
        "wallet_configured": bool(cfg.api_wallet_key),
        "account_configured": bool(cfg.account_address),
        "max_notional_usd": cfg.max_notional_usd,
        "sdk_installed": _SDK_MISSING is None,
        "what_broke": list(cfg.what_broke),
    }

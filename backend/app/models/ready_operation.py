"""Assemble a paper operation from three client choices — no invented book.

The client picks ticker, instrument (spot / option / future) and horizon.
Numbers come from the existing arsenal (quote, EWMA/GARCH, Hurst, desk regime,
Black–Scholes greeks, derivatives planner, Heston CF when a chain exists).
The LLM never picks direction. Missing data → status=insufficient, not a guess.

«Ativo de operação» is the vehicle, not a second ticker: ação/cripto à vista,
opção sobre o mesmo ativo, ou futuro/perpétuo (cripto via Binance público).
B3 futures are not in the arsenal — we say so instead of faking a contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from math import floor, isfinite
from typing import Any, Literal

import numpy as np

from app.models.mean_reversion import _expanding_z, _hurst
from app.models.pricing import BlackScholes
from app.models.volatility import EWMAVolatility, GARCHModel, HestonModel
from app.services.regime_job import last_snapshot

Instrument = Literal["spot", "option", "future"]
Horizon = Literal["days", "weeks", "months"]

HORIZONS: dict[Horizon, dict[str, Any]] = {
    "days": {"holding_days": 5, "label": "Alguns dias"},
    "weeks": {"holding_days": 21, "label": "Algumas semanas"},
    "months": {"holding_days": 63, "label": "Alguns meses"},
}

# What the public Mac can attempt with feeds the app already has (no paid key).
UNIVERSE: list[dict[str, Any]] = [
    {"id": "PETR4", "label": "Petrobras (PETR4)", "asset_class": "equity_br",
     "quote_symbol": "PETR4", "yahoo": "PETR4.SA", "instruments": ["spot", "option"]},
    {"id": "VALE3", "label": "Vale (VALE3)", "asset_class": "equity_br",
     "quote_symbol": "VALE3", "yahoo": "VALE3.SA", "instruments": ["spot", "option"]},
    {"id": "ITUB4", "label": "Itaú Unibanco (ITUB4)", "asset_class": "equity_br",
     "quote_symbol": "ITUB4", "yahoo": "ITUB4.SA", "instruments": ["spot", "option"]},
    {"id": "BBDC4", "label": "Bradesco (BBDC4)", "asset_class": "equity_br",
     "quote_symbol": "BBDC4", "yahoo": "BBDC4.SA", "instruments": ["spot", "option"]},
    {"id": "WEGE3", "label": "WEG (WEGE3)", "asset_class": "equity_br",
     "quote_symbol": "WEGE3", "yahoo": "WEGE3.SA", "instruments": ["spot", "option"]},
    {"id": "BTC", "label": "Bitcoin", "asset_class": "crypto",
     "quote_symbol": "BTC-USD", "yahoo": "BTC-USD", "binance": "BTCUSDT",
     "instruments": ["spot", "future"], "lot_size": 0.0001},
    {"id": "ETH", "label": "Ethereum", "asset_class": "crypto",
     "quote_symbol": "ETH-USD", "yahoo": "ETH-USD", "binance": "ETHUSDT",
     "instruments": ["spot", "future"], "lot_size": 0.001},
    {"id": "SOL", "label": "Solana", "asset_class": "crypto",
     "quote_symbol": "SOL-USD", "yahoo": "SOL-USD", "binance": "SOLUSDT",
     "instruments": ["spot", "future"], "lot_size": 0.01},
]
UNIVERSE_BY_ID = {row["id"]: row for row in UNIVERSE}

MIN_HISTORY = 60
_CLIENT_JARGON = (
    "z_score", "z-score", "eligible_for_live_trading", "ewma", "garch",
    "hurst", "kill_switch", "horizon_vol", "trade", "pontos",
)
_SCI_RE = re.compile(r"(?<![A-Za-z])\d+\.?\d*[eE][+-]?\d+")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FX_MIN, _FX_MAX = 3.0, 10.0
_REGIME_PT = {
    "trending": "em tendência",
    "mean_reverting": "em oscilação",
    "high_vol": "com volatilidade alta",
}


@dataclass
class MarketView:
    """Injected in tests; production fills this from cache or live fetchers."""
    quote: dict[str, Any]
    history: dict[str, Any]
    chain: list[dict[str, Any]] | None = None
    chain_source: str | None = None
    regime: dict[str, Any] | None = None
    fx_usd_brl: dict[str, Any] | None = None
    contributions: list[dict[str, Any]] = field(default_factory=list)


def universe_public() -> list[dict[str, Any]]:
    return [
        {k: row[k] for k in ("id", "label", "asset_class", "instruments")}
        for row in UNIVERSE
    ]


def resolve_asset(ticker: str) -> dict[str, Any] | None:
    key = ticker.strip().upper()
    aliases = {
        "BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL",
        "BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL",
    }
    return UNIVERSE_BY_ID.get(aliases.get(key, key))


def format_price_ptbr(value: float, decimals: int = 2) -> str:
    """Client money: 77.640,12 — never scientific notation, never extra cents."""
    n = float(value)
    if not isfinite(n):
        return "—"
    sign = "-" if n < 0 else ""
    grouped = f"{abs(n):,.{decimals}f}"
    return sign + grouped.replace(",", "_").replace(".", ",").replace("_", ".")


def format_money_ptbr(value: float, currency: str = "BRL") -> str:
    prefix = "US$ " if currency == "USD" else "R$ "
    return prefix + format_price_ptbr(value)


def format_date_ptbr(value: date | datetime | str | None) -> str:
    """Client dates: 04/12/2026 — never ISO, so the line cannot wrap on the hyphen."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        raw = str(value).strip()
        try:
            d = date.fromisoformat(raw[:10])
        except ValueError:
            return raw
    return d.strftime("%d/%m/%Y")


def _fx_rate(row: dict[str, Any] | None) -> float | None:
    if not isinstance(row, dict):
        return None
    try:
        rate = float(row.get("rate") or 0)
    except (TypeError, ValueError):
        return None
    if not isfinite(rate) or rate < _FX_MIN or rate > _FX_MAX:
        return None
    return rate


def _mark(contributions: list[dict[str, Any]], part: str, used: bool, note: str) -> None:
    contributions.append({"part": part, "used": used, "note": note})


def _insufficient(reason: str, contributions: list[dict[str, Any]], *, extra: dict | None = None) -> dict[str, Any]:
    body = {
        "status": "insufficient",
        "reason": reason,
        "eligible_for_live_trading": False,
        "mode": "paper_only",
        "arsenal": contributions,
        "disclaimer": (
            "Isto não é recomendação nem ordem. Sem dados suficientes o ATOM "
            "não inventa operação."
        ),
    }
    if extra:
        body.update(extra)
    return body


def _closes(history: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    raw = history.get("close") or history.get("closes") or []
    dates = list(history.get("dates") or [])
    closes = np.asarray([float(x) for x in raw], dtype=np.float64)
    n = min(len(closes), len(dates)) if dates else len(closes)
    return closes[-n:], dates[-n:] if dates else []


def _is_synthetic(payload: dict[str, Any]) -> bool:
    return str(payload.get("provider") or payload.get("source") or "").lower() == "synthetic"


def _local_regime(vol: float, hurst: float | None, mom: float) -> str:
    if vol >= 0.85:
        return "high_vol"
    if hurst is not None and np.isfinite(hurst):
        if hurst >= 0.55:
            return "trending"
        if hurst <= 0.45:
            return "mean_reverting"
    return "trending" if mom > 0 else "mean_reverting"


def _confidence(strength: float, desk_regime: str | None) -> str:
    # Doctrine: never claim high confidence from one nowcast.
    if desk_regime in {"crisis", "high_vol"}:
        return "baixa"
    if strength < 0.5:
        return "baixa"
    if strength < 1.2:
        return "média"
    return "moderada"


def _garch_vol(returns: np.ndarray) -> tuple[float | None, dict | None]:
    if len(returns) < 40:
        return None, None
    try:
        fitted = GARCHModel().fit(returns)
        vol = fitted.get("long_run_volatility")
        if vol is None or not np.isfinite(vol) or vol <= 0:
            return None, fitted
        return float(vol), fitted
    except Exception:
        return None, None


def _levels(spot: float, direction: str, horizon_vol: float) -> tuple[float, float, float]:
    """Stop/target as 1× / 1.6× of horizon vol, clipped so crypto months stay sane."""
    width_stop = float(np.clip(horizon_vol, 0.02, 0.12))
    width_tgt = width_stop * 1.6
    if direction == "bullish":
        entry = round(spot * 1.002, 6)
        invalidation = max(spot * (1 - width_stop), spot * 0.05)
        target = spot * (1 + width_tgt)
    else:
        entry = round(spot * 0.998, 6)
        invalidation = spot * (1 + width_stop)
        target = max(spot * (1 - width_tgt), spot * 0.05)
    return entry, float(invalidation), float(target)


def _size(
    capital: float,
    risk_pct: float,
    entry: float,
    invalidation: float,
    lot: float = 1.0,
    *,
    quote_currency: str = "BRL",
    fx_usd_brl: float | None = None,
) -> tuple[float, float, bool, str | None]:
    budget = capital * risk_pct / 100.0
    per_unit_quote = abs(entry - invalidation)
    if per_unit_quote <= 1e-12:
        return 0.0, budget, False, "Distância até a invalidação nula."
    if quote_currency == "USD":
        if fx_usd_brl is None or fx_usd_brl <= 0:
            return 0.0, budget, False, (
                "O arsenal não tem câmbio USD/BRL agora. "
                "Sem converter o dólar, não dimensionamos o risco em reais sobre um preço em dólar."
            )
        per_unit = per_unit_quote * fx_usd_brl
    else:
        per_unit = per_unit_quote
    lot = lot if lot > 0 else 1.0
    raw = budget / per_unit
    qty = floor(raw / lot + 1e-12) * lot
    if qty < lot:
        return round(raw, 8), budget, False, (
            "O risco máximo deste cenário não cabe o lote mínimo deste ativo. "
            "A tela mostra o tamanho fracionário; o diário só registra a partir do lote."
        )
    return float(round(qty, 8)), budget, True, None


def _notional_brl(
    instrument: str,
    qty: float,
    entry: float,
    paper_plan: dict | None,
    *,
    quote_currency: str = "BRL",
    fx_usd_brl: float | None = None,
) -> float | None:
    """Gross position value in BRL. Crypto needs USD/BRL; without it we do not pretend USD is R$."""
    if instrument == "option" and isinstance(paper_plan, dict):
        prem = paper_plan.get("premium_outlay_brl")
        if prem is not None:
            try:
                return round(abs(float(prem)), 2)
            except (TypeError, ValueError):
                pass
    try:
        raw = abs(float(qty or 0) * float(entry or 0))
    except (TypeError, ValueError):
        return 0.0
    if quote_currency == "USD":
        if fx_usd_brl is None or fx_usd_brl <= 0:
            return None
        return round(raw * fx_usd_brl, 2)
    return round(raw, 2)


def client_facing_why(text: str | None, fallback: str) -> str:
    """Drop model-variable names if the LLM (or a template) leaked them."""
    lowered = (text or "").lower()
    if (
        not text
        or any(token in lowered for token in _CLIENT_JARGON)
        or _SCI_RE.search(text)
        or _ISO_DATE_RE.search(text)
    ):
        return fallback
    return text


MAX_BASKET = 8


def unique_tickers(tickers: list[str] | None) -> list[str]:
    """Dedupe, resolve aliases, cap at MAX_BASKET. Unknown names are kept for a honest refusal."""
    seen: list[str] = []
    for raw in tickers or []:
        token = (raw or "").strip()
        if not token:
            continue
        asset = resolve_asset(token)
        key = asset["id"] if asset else token.upper()
        if key not in seen:
            seen.append(key)
        if len(seen) >= MAX_BASKET:
            break
    return seen


def basket_weights(n: int, weights: list[float] | None) -> list[float]:
    if n <= 0:
        return []
    if weights and len(weights) == n:
        cleaned = [max(0.0, float(w)) for w in weights]
        total = sum(cleaned)
        if total > 0:
            return [w / total for w in cleaned]
    return [1.0 / n] * n


def _instrument_for(asset: dict[str, Any], requested: Instrument) -> Instrument:
    raw = asset.get("instruments") or ["spot"]
    if requested in raw:
        return requested
    first = raw[0] if raw else "spot"
    if first == "option":
        return "option"
    if first == "future":
        return "future"
    return "spot"


def _why_fallback(payload: dict[str, Any]) -> str:
    if payload.get("status") == "insufficient":
        return (
            f"{payload.get('reason')} Isto é um recado do arsenal, não uma recomendação. "
            "Nenhuma ordem foi enviada."
        )
    if payload.get("basket") or (payload.get("structure") or {}).get("strategy") == "mixed_book":
        ready = [row for row in (payload.get("basket") or []) if row.get("status") == "ready"]
        names = ", ".join((row.get("label") or row.get("ticker") or "") for row in ready)
        refused = [row for row in (payload.get("basket") or []) if row.get("status") != "ready"]
        extra = ""
        if refused:
            extra = " Recusas: " + "; ".join(
                f"{row.get('ticker')}: {row.get('reason')}" for row in refused
            ) + "."
        size = payload.get("suggested_size") or {}
        return (
            f"Carteira mista no horizonte {payload.get('horizon_label')} com {len(ready)} perna(s) "
            f"({names}). Risco total limitado a "
            f"{format_money_ptbr(float(size.get('risk_budget_brl') or 0))}, "
            f"dividido pelos pesos marcados. Cada ativo tem o próprio gatilho e stop.{extra} "
            "Simulação paper, não recomendação. Nenhuma ordem vai à corretora."
        )
    direction = "alta" if payload["direction"] == "bullish" else "baixa"
    label = payload.get("label") or payload.get("ticker")
    local = _REGIME_PT.get((payload.get("regime") or {}).get("local", ""), "no mercado recente")
    conf = payload.get("confidence", "baixa")
    invalid = payload.get("invalidation_reason") or ""
    ccy = payload.get("quote_currency") or "BRL"
    spot = payload.get("spot")
    entry = payload.get("entry")
    levels = ""
    if spot is not None and entry is not None:
        levels = (
            f"A cotação agora é {format_money_ptbr(float(spot), ccy)}; "
            f"o gatilho de entrada é {format_money_ptbr(float(entry), ccy)} — não é o preço atual. "
        )
    expiry = (payload.get("structure") or {}).get("expiry")
    prazo = f"Prazo até {format_date_ptbr(expiry)}. " if expiry else ""
    return (
        f"O movimento recente de {label} ({local}) levou o arsenal a montar um cenário de {direction} "
        f"no horizonte {payload['horizon_label']}, com confiança {conf}. "
        f"{levels}{prazo}{invalid} Isto é simulação paper, não uma recomendação, e nenhuma ordem vai à corretora."
    )


def _spot_plan(
    *,
    ticker: str,
    direction: str,
    instrument: str,
    strategy: str,
    spot: float,
    entry: float,
    invalidation: float,
    target: float,
    holding_days: int,
    quantity: float,
    rationale: str,
    capital: float,
    risk_pct: float,
    now: datetime,
    lot: float = 1.0,
    quote_currency: str = "BRL",
    fx_usd_brl: float | None = None,
) -> dict[str, Any]:
    qty = float(quantity) if quantity and quantity > 0 else 0.0
    close_by = (now.date() + timedelta(days=holding_days)).isoformat()
    side = "buy" if direction == "bullish" else "sell"
    debit = abs(entry)  # per unit; shorts are handled as credit on open
    sized = qty if qty > 0 else lot
    brl_per_quote = 1.0
    if quote_currency == "USD":
        brl_per_quote = float(fx_usd_brl) if fx_usd_brl and fx_usd_brl > 0 else 0.0
    risk = abs(entry - invalidation) * sized * brl_per_quote
    return {
        "ticker": ticker,
        "direction": "long_bias" if direction == "bullish" else "short_bias",
        "strategy": strategy,
        "instrument": instrument,
        "rationale": rationale,
        "legs": [{
            "symbol": ticker,
            "side": side,
            "kind": "spot" if instrument == "spot" else "future",
            "strike": round(spot, 4),
            "limit_reference": round(entry, 6),
            "quantity": sized,
            "exercise": "european",
        }],
        "expiry": close_by,
        "holding_days": holding_days,
        "close_by": close_by,
        "calendar_basis": "dias corridos; antecipar ao pregão anterior se não houver sessão",
        "entry": {
            "underlying_trigger": entry,
            "comparison": ">=" if direction == "bullish" else "<=",
            "max_net_debit_per_unit": round(debit, 6),
            "quote_valid_until": (now + timedelta(minutes=15)).isoformat(),
            "instruction": (
                "Aguardar gatilho e revalidar cotação. Paper only — o diário "
                "registra a simulação; nenhuma ordem vai à corretora."
            ),
        },
        "exit": {
            "underlying_invalidation": round(invalidation, 6),
            "underlying_target": round(target, 6),
            "take_profit_net_brl": round(qty * abs(target - entry) * brl_per_quote, 2) if qty else None,
            "stop_loss_net_brl": round(qty * abs(entry - invalidation) * brl_per_quote, 2) if qty else round(risk, 2),
            "instruction": (
                "Encerrar no primeiro evento: invalidação, alvo ou data-limite. "
                "Limiares não garantem preço de saída."
            ),
        },
        "quantity_per_leg": sized if qty > 0 else 0,
        "multiplier": 1,
        "lot_size": lot,
        "premium_outlay_brl": round(qty * entry * brl_per_quote, 2) if side == "buy" and qty else 0,
        "fees_reserved_brl": 0,
        "modeled_max_loss_brl": round(qty * abs(entry - invalidation) * brl_per_quote, 2) if qty else round(risk, 2),
        "modeled_max_profit_brl": round(qty * abs(target - entry) * brl_per_quote, 2) if qty else None,
        "target_scenario_reward_risk": round(abs(target - entry) / abs(entry - invalidation), 3),
        "breakeven_at_expiry": round(entry, 6),
        "eligible_for_live_trading": False,
        "capital": capital,
        "risk_per_trade_pct": risk_pct,
    }


def _usable_quotes(chain: list[dict[str, Any]], kind: str, close_date, max_spread_pct: float = 15) -> list[dict[str, Any]]:
    from datetime import date as date_cls
    usable = []
    for raw in chain:
        if str(raw.get("kind") or raw.get("option_type") or "").lower() != kind:
            continue
        try:
            bid = float(raw["bid"])
            ask = float(raw["ask"])
            strike = float(raw["strike"])
            bid_size = int(raw.get("bid_size") or 0)
            ask_size = int(raw.get("ask_size") or 0)
            expiry = raw["expiry"]
            if isinstance(expiry, str):
                expiry_d = date_cls.fromisoformat(expiry[:10])
            else:
                expiry_d = expiry
            symbol = str(raw.get("symbol") or raw.get("contractSymbol") or "")
        except (KeyError, TypeError, ValueError):
            continue
        if bid <= 0 or ask <= 0 or bid > ask or strike <= 0 or not symbol:
            continue
        if bid_size <= 0 or ask_size <= 0:
            continue
        mid = (ask + bid) / 2
        if (ask - bid) / mid * 100 > max_spread_pct:
            continue
        if (expiry_d - close_date).days < 7:
            continue
        usable.append({
            "symbol": symbol[:30],
            "kind": kind,
            "strike": strike,
            "expiry": expiry_d,
            "exercise": str(raw.get("exercise") or "european"),
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "multiplier": float(raw.get("multiplier") or 100),
            "lot_size": int(raw.get("lot_size") or 1),
            "iv": raw.get("iv"),
        })
    return usable


def _greeks_for_leg(spot: float, leg: dict, sigma: float, r: float = 0.1) -> dict[str, Any] | None:
    try:
        from datetime import date as date_cls
        expiry = date_cls.fromisoformat(str(leg.get("expiry") or leg.get("exp") or "")[:10])
        t_years = max((expiry - datetime.now(UTC).date()).days, 1) / 365.0
        kind = "call" if "call" in str(leg.get("kind") or leg.get("strategy") or "") else "put"
        if str(leg.get("kind")) in {"call", "put"}:
            kind = str(leg["kind"])
        strike = float(leg.get("strike") or 0)
        if strike <= 0 or sigma <= 0:
            return None
        g = BlackScholes.greeks(spot, strike, t_years, r, sigma, kind)  # type: ignore[arg-type]
        return {
            "price": g.price, "delta": g.delta, "gamma": g.gamma,
            "theta": g.theta, "vega": g.vega, "rho": g.rho,
            "sigma_used": round(sigma, 4),
        }
    except Exception:
        return None


def assemble(
    ticker: str,
    instrument: Instrument,
    horizon: Horizon,
    *,
    market: MarketView | None = None,
    now: datetime | None = None,
    capital: float | None = None,
    risk_pct: float | None = None,
) -> dict[str, Any]:
    """Pure orchestrator. Pass `market` in tests; production loads it separately."""
    import os
    contributions: list[dict[str, Any]] = list(market.contributions if market else [])
    now = now or datetime.now(UTC)
    capital = float(capital if capital is not None else os.getenv("ATOM_CLIENT_PAPER_CAPITAL", "10000"))
    risk_pct = float(risk_pct if risk_pct is not None else os.getenv("ATOM_CLIENT_RISK_PCT", "1"))

    asset = resolve_asset(ticker)
    if asset is None:
        return _insufficient(
            "Este ativo não está no universo que o arsenal serve ao cliente "
            "(PETR4, VALE3, ITUB4, BBDC4, WEGE3, BTC, ETH, SOL).",
            contributions,
        )
    if instrument not in asset["instruments"]:
        if instrument == "future" and asset["asset_class"] == "equity_br":
            return _insufficient(
                "O arsenal não tem livro de futuro B3 para este ativo. "
                "Futuro/perpétuo automático existe só para BTC, ETH e SOL (Binance público).",
                contributions,
                extra={"ticker": asset["id"], "available_instruments": asset["instruments"]},
            )
        if instrument == "option" and asset["asset_class"] == "crypto":
            return _insufficient(
                "O arsenal não monta opção automática em cripto neste modo. "
                "Escolha à vista ou futuro/perpétuo.",
                contributions,
                extra={"ticker": asset["id"], "available_instruments": asset["instruments"]},
            )
        return _insufficient(
            f"Instrumento «{instrument}» não é suportado para {asset['id']}.",
            contributions,
            extra={"ticker": asset["id"], "available_instruments": asset["instruments"]},
        )

    if market is None:
        return _insufficient(
            f"Sem cotação ou histórico de mercado para {asset['id']} agora. "
            "O ATOM não inventa preço. Tente de novo em instantes ou escolha outro ativo.",
            contributions,
        )

    if _is_synthetic(market.quote) or _is_synthetic(market.history):
        return _insufficient(
            "A cotação disponível é sintética. O ATOM não monta operação com preço inventado.",
            contributions,
        )
    spot = float(market.quote.get("price") or market.quote.get("current_price") or 0)
    if spot <= 0:
        return _insufficient("Sem cotação de mercado para este ativo agora.", contributions)
    _mark(contributions, "cotação", True, f"{market.quote.get('provider') or market.quote.get('source') or 'feed'} {spot}")

    closes, dates = _closes(market.history)
    if len(closes) < MIN_HISTORY:
        return _insufficient(
            f"Histórico curto demais ({len(closes)} pregões; mínimo {MIN_HISTORY}) para um cenário honesto.",
            contributions,
        )
    _mark(contributions, "histórico", True, f"{len(closes)} pregões ({market.history.get('provider') or market.history.get('source') or 'feed'})")

    log_p = np.log(closes)
    rets = np.diff(log_p)
    ewma = EWMAVolatility.compute(rets)
    ewma_vol = float(ewma["current_vol"])
    if not np.isfinite(ewma_vol) or ewma_vol < 0.01:
        return _insufficient("Volatilidade EWMA não estimável neste histórico.", contributions)
    garch_vol, garch_fit = _garch_vol(rets)
    vol = garch_vol if garch_vol else ewma_vol
    _mark(contributions, "EWMA", True, f"vol anualizada {ewma_vol:.1%}")
    _mark(contributions, "GARCH", bool(garch_vol),
          f"vol de longo prazo {garch_vol:.1%}" if garch_vol else "ajuste instável ou série curta — usando EWMA")

    holding_days = int(HORIZONS[horizon]["holding_days"])
    horizon_vol = vol * float(np.sqrt(holding_days / 252.0))
    look = min(holding_days, len(closes) - 1)
    mom = float(closes[-1] / closes[-1 - look] - 1.0)
    z_score = float(_expanding_z(log_p)) if len(log_p) >= 20 else 0.0
    hurst = None
    try:
        if len(log_p) >= 50:
            raw_h = float(_hurst(log_p))
            hurst = raw_h if np.isfinite(raw_h) else None
    except Exception:
        hurst = None
    local = _local_regime(vol, hurst, mom)
    hurst_ok = hurst is not None and bool(np.isfinite(hurst))
    _mark(contributions, "Hurst / regime local", hurst_ok,
          f"H={hurst:.2f} → {local}" if hurst_ok else f"Hurst indisponível; regime local {local}")

    desk = market.regime if market.regime is not None else last_snapshot()
    desk_regime = (desk or {}).get("regime")
    kill = (desk or {}).get("kill_switch") or {}
    _mark(contributions, "regime da mesa", bool(desk),
          f"{desk_regime}" if desk else "job de regime ainda sem snapshot — só o regime local do ativo")
    if kill.get("armed") or desk_regime == "crisis":
        return _insufficient(
            "Regime de crise (ou kill switch armado) no agora: a mesa não monta operação automática. "
            "O flatten paper continua valendo; nada vai ao broker.",
            contributions,
        )

    if local == "mean_reverting":
        if z_score > 0.5:
            direction: str | None = "bearish"
        elif z_score < -0.5:
            direction = "bullish"
        else:
            direction = None
        if direction is None:
            return _insufficient(
                "Regime de reversão sem desvio claro do preço: o arsenal não inventa direção.",
                contributions,
            )
    else:
        if abs(mom) < 0.15 * max(horizon_vol, 1e-9):
            return _insufficient(
                "Variação do horizonte está dentro do ruído da volatilidade: sem evidência para uma direção.",
                contributions,
            )
        direction = "bullish" if mom > 0 else "bearish"

    if local == "high_vol" and abs(mom) < 0.5 * max(horizon_vol, 1e-9):
        return _insufficient(
            "Volatilidade alta e sinal fraco: o arsenal não monta operação neste estado.",
            contributions,
        )

    entry, invalidation, target = _levels(spot, direction, horizon_vol)
    strength = abs(mom) / max(horizon_vol, 1e-9)
    confidence = _confidence(strength, desk_regime)
    lot = float(asset.get("lot_size") or 1.0)
    quote_ccy = "USD" if asset.get("asset_class") == "crypto" else "BRL"
    fx_rate = _fx_rate(market.fx_usd_brl if market else None)
    if quote_ccy == "USD":
        _mark(
            contributions, "câmbio USD/BRL", bool(fx_rate),
            (
                f"{(market.fx_usd_brl or {}).get('source', 'feed')} {fx_rate:.4f}"
                + (" (cache)" if (market.fx_usd_brl or {}).get("stale") else "")
            ) if fx_rate else "sem cotação — não dimensionamos R$ sobre preço em dólar",
        )
    qty, budget, can_lot, size_note = _size(
        capital, risk_pct, entry, invalidation, lot=lot,
        quote_currency=quote_ccy, fx_usd_brl=fx_rate,
    )
    invalidation_reason = (
        f"A tese cai se o preço cruzar {format_money_ptbr(invalidation, quote_ccy)} "
        f"({('abaixo' if direction == 'bullish' else 'acima')} do gatilho) "
        f"ou se o regime da mesa virar crise."
    )
    rationale = (
        f"Cenário automático {direction} em {asset['id']} no horizonte {HORIZONS[horizon]['label']}. "
        f"Regime local {local}, momentum {mom:.2%}, vol {vol:.1%}. "
        f"Não é recomendação; paper only."
    )
    if len(rationale) < 30:
        rationale = rationale + " Simulação da mesa ATOM."

    heston = None
    greeks = None
    paper_plan = None
    structure = None
    can_paper = can_lot
    paper_block = size_note

    if instrument == "option":
        close_date = now.date() + timedelta(days=holding_days)
        kind = "call" if direction == "bullish" else "put"
        quotes = _usable_quotes(market.chain or [], kind, close_date)
        if not quotes:
            why_chain = "sem livro" if not market.chain else "livro sem bid/ask/quantidade utilizáveis"
            return _insufficient(
                f"O arsenal não tem livro de opções utilizável para {asset['id']} ({why_chain}). "
                "Não inventamos liquidez nem contratos.",
                contributions,
            )
        _mark(contributions, "livro de opções", True, f"{len(quotes)} contratos {kind} com bid/ask e tamanho ({market.chain_source or 'feed'})")
        from app.models.derivatives_planner import PlanRequest, make_plans
        plan_quotes = [{k: v for k, v in q.items() if k != "iv"} for q in quotes]
        try:
            req = PlanRequest.model_validate({
                "source": "ATOM cliente · livro do arsenal, tese montada automaticamente",
                "provenance": "user_supplied",
                "as_of": now,
                "capital": capital,
                "risk_per_trade_pct": min(risk_pct, 5),
                "theses": [{
                    "ticker": asset["quote_symbol"],
                    "spot": spot,
                    "direction": direction,
                    "rationale": rationale,
                    "entry": entry,
                    "invalidation": invalidation,
                    "target": target,
                    "holding_days": holding_days,
                    "events_checked": True,
                    "options": plan_quotes,
                }],
            })
        except Exception as exc:
            return _insufficient(f"Livro rejeitado pelo planner: {exc}", contributions)
        report = make_plans(req, now=now)
        _mark(contributions, "planner de derivativos", bool(report.get("plans")),
              report["status"] if report.get("plans") else (report.get("rejected") or [{"reason": "no_trade"}])[0].get("reason", "no_trade"))
        if not report.get("plans"):
            rejected = report.get("rejected") or []
            detail = rejected[0]["reason"] if rejected else "nenhuma estrutura passou nos filtros"
            return _insufficient(
                f"O planner não achou estrutura condicional honesta: {detail}",
                contributions,
            )
        paper_plan = report["plans"][0]
        paper_plan["instrument"] = "option"
        structure = {
            "strategy": paper_plan["strategy"],
            "legs": paper_plan["legs"],
            "expiry": paper_plan["expiry"],
        }
        long_leg = next((leg for leg in paper_plan["legs"] if leg["side"] == "buy"), paper_plan["legs"][0])
        long_leg = {**long_leg, "expiry": paper_plan["expiry"], "kind": long_leg.get("kind", kind)}
        greeks = _greeks_for_leg(spot, long_leg, vol)
        _mark(contributions, "Black–Scholes (gregas)", greeks is not None,
              "gregas da perna comprada com σ EWMA/GARCH" if greeks else "gregas indisponíveis")
        iv_quotes = [
            {"K": q["strike"], "T": max((q["expiry"] - now.date()).days, 1) / 365.0,
             "iv": float(q["iv"]), "option_type": q["kind"]}
            for q in quotes if q.get("iv") not in (None, "", 0)
        ]
        if len(iv_quotes) >= 4 and os.getenv("ATOM_ENV") != "test":
            try:
                heston = HestonModel.calibrate(spot, 0.1, iv_quotes[:12], max_nfev=40)
                _mark(contributions, "Heston", True, f"RMSE {heston.get('rmse')} — calibração ilustrativa, não decide a estrutura")
            except Exception as exc:
                _mark(contributions, "Heston", False, f"calibração recusada ({type(exc).__name__})")
                heston = None
        else:
            _mark(contributions, "Heston", False, "menos de 4 IVs no livro — sem calibração")
        can_paper = True
        paper_block = None
        qty = paper_plan.get("quantity_per_leg") or qty
    else:
        strategy = {
            ("spot", "bullish"): "long_stock",
            ("spot", "bearish"): "short_stock",
            ("future", "bullish"): "long_perp",
            ("future", "bearish"): "short_perp",
        }[(instrument, direction)]
        _mark(contributions, "planner de derivativos", False, "instrumento à vista/futuro — plano paper direto, sem livro de opções")
        _mark(contributions, "Black–Scholes (gregas)", False, "não se aplica à vista/futuro")
        _mark(contributions, "Heston", False, "sem superfície de opções neste instrumento")
        if instrument == "future":
            _mark(contributions, "Binance público", True, "mark/perpétuo via feed já usado no app; sem chaves de execução")
        paper_plan = _spot_plan(
            ticker=asset["id"], direction=direction, instrument=instrument, strategy=strategy,
            spot=spot, entry=entry, invalidation=invalidation, target=target,
            holding_days=holding_days, quantity=qty, rationale=rationale,
            capital=capital, risk_pct=risk_pct, now=now, lot=lot,
            quote_currency=quote_ccy, fx_usd_brl=fx_rate,
        )
        structure = {"strategy": strategy, "legs": paper_plan["legs"], "expiry": paper_plan["expiry"]}
        if not can_paper:
            paper_plan = {**paper_plan, "quantity_per_leg": 0}

    payload = {
        "status": "ready",
        "ticker": asset["id"],
        "label": asset["label"],
        "instrument": instrument,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon]["label"],
        "holding_days": holding_days,
        "direction": direction,
        "structure": structure,
        "spot": round(spot, 6),
        "entry": round(entry, 6),
        "invalidation": round(invalidation, 6),
        "target": round(target, 6),
        "quantity": qty,
        "quote_currency": quote_ccy,
        "fx_usd_brl": None if not fx_rate else {
            "rate": fx_rate,
            "source": (market.fx_usd_brl or {}).get("source"),
            "stale": bool((market.fx_usd_brl or {}).get("stale")),
        },
        "suggested_size": {
            "quantity": qty,
            "capital_brl": capital,
            "risk_budget_brl": round(budget, 2),
            "notional_brl": _notional_brl(
                instrument, qty, entry, paper_plan if isinstance(paper_plan, dict) else None,
                quote_currency=quote_ccy, fx_usd_brl=fx_rate,
            ),
            "notional_usd": round(abs(float(qty or 0) * float(entry or 0)), 2) if quote_ccy == "USD" else None,
            "risk_per_trade_pct": risk_pct,
            "can_register_paper": bool(can_paper),
            "paper_block": paper_block,
        },
        "greeks": greeks,
        "heston": None if not heston else {
            "rmse": heston.get("rmse"),
            "params": heston.get("params"),
            "success": heston.get("success"),
            "eligible_for_live_trading": False,
        },
        "confidence": confidence,
        "invalidation_reason": invalidation_reason,
        "regime": {"local": local, "desk": desk_regime, "hurst": hurst, "z_score": round(z_score, 3), "momentum": round(mom, 4)},
        "volatility": {"ewma": ewma_vol, "garch": garch_vol, "horizon": horizon_vol, "used": vol},
        "paper_plan": paper_plan,
        "plan_inputs": {
            "source": "ATOM cliente · operação pronta",
            "provenance": "user_supplied",
            "capital": capital,
            "total_risk_pct": 3,
            "existing_risk_brl": 0,
            "fee_per_contract_side": 0.05,
            "risk_per_trade_pct": risk_pct,
        },
        "eligible_for_live_trading": False,
        "mode": "paper_only",
        "as_of": now.isoformat(),
        "arsenal": contributions,
        "disclaimer": (
            "Cenário/simulação montado pelo arsenal. Não é recomendação, não é ordem, "
            "não promete retorno. Nenhuma ordem vai à corretora."
        ),
    }
    payload["why_fallback"] = _why_fallback(payload)
    payload["why"] = client_facing_why(payload["why_fallback"], payload["why_fallback"])
    if garch_fit:
        payload["volatility"]["garch_persistence"] = garch_fit.get("persistence")
    return payload


def assemble_basket(
    tickers: list[str],
    instrument: Instrument,
    horizon: Horizon,
    *,
    markets: dict[str, MarketView | None] | None = None,
    weights: list[float] | None = None,
    now: datetime | None = None,
    capital: float | None = None,
    risk_pct: float | None = None,
) -> dict[str, Any]:
    """One paper leg per marked asset. Total risk stays inside `risk_pct` of capital.

    Single-ticker lists fall through to `assemble` so the client path stays unchanged.
    Instrument is requested once; each asset falls back to what the arsenal actually has.
    """
    import os

    ids = unique_tickers(tickers)
    if not ids:
        return _insufficient(
            "Marque ao menos um ativo do universo (B3 ou cripto) para montar a carteira mista.",
            [],
        )
    now = now or datetime.now(UTC)
    capital = float(capital if capital is not None else os.getenv("ATOM_CLIENT_PAPER_CAPITAL", "10000"))
    risk_pct = float(risk_pct if risk_pct is not None else os.getenv("ATOM_CLIENT_RISK_PCT", "1"))
    market_map = markets or {}
    if len(ids) == 1:
        return assemble(
            ids[0], instrument, horizon,
            market=market_map.get(ids[0]), now=now, capital=capital, risk_pct=risk_pct,
        )

    wts = basket_weights(len(ids), weights)
    rows: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    for ticker, weight in zip(ids, wts, strict=True):
        asset = resolve_asset(ticker)
        if asset is None:
            row = _insufficient(
                "Este ativo não está no universo que o arsenal serve ao cliente "
                "(PETR4, VALE3, ITUB4, BBDC4, WEGE3, BTC, ETH, SOL).",
                [],
                extra={"ticker": ticker},
            )
            row["weight"] = weight
            rows.append(row)
            continue
        inst = _instrument_for(asset, instrument)
        row = assemble(
            asset["id"], inst, horizon,
            market=market_map.get(asset["id"]),
            now=now, capital=capital, risk_pct=risk_pct * weight,
        )
        row["weight"] = weight
        row["requested_instrument"] = instrument
        rows.append(row)
        contributions.extend(row.get("arsenal") or [])

    ready = [row for row in rows if row.get("status") == "ready"]
    refused = [row for row in rows if row.get("status") != "ready"]
    if not ready:
        detail = "; ".join(f"{row.get('ticker')}: {row.get('reason')}" for row in refused)
        return _insufficient(
            "Nenhuma perna da carteira mista teve sinal ou dado suficiente. " + detail,
            contributions,
            extra={"basket": [_basket_row(row) for row in rows], "tickers": ids},
        )

    legs: list[dict[str, Any]] = []
    notionals: list[float] = []
    for row in ready:
        legs.extend((row.get("structure") or {}).get("legs") or [])
        notional = (row.get("suggested_size") or {}).get("notional_brl")
        if notional is not None:
            notionals.append(float(notional))

    registerable = [
        row for row in ready
        if (row.get("suggested_size") or {}).get("can_register_paper") and row.get("paper_plan")
    ]
    directions = {row.get("direction") for row in ready}
    direction = next(iter(directions)) if len(directions) == 1 else None
    close_bys = [
        (row.get("structure") or {}).get("expiry") or (row.get("paper_plan") or {}).get("close_by")
        for row in ready
    ]
    close_bys = [item for item in close_bys if item]
    close_by = min(close_bys) if close_bys else None
    risk_budget = round(sum(
        float((row.get("suggested_size") or {}).get("risk_budget_brl") or 0) for row in ready
    ), 2)
    refuse_note = None
    if refused:
        refuse_note = "Pernas recusadas: " + "; ".join(
            f"{row.get('ticker')}: {row.get('reason')}" for row in refused
        )
    paper_blocks = [
        (row.get("suggested_size") or {}).get("paper_block")
        for row in ready
        if not (row.get("suggested_size") or {}).get("can_register_paper")
    ]
    paper_block = next((item for item in paper_blocks if item), refuse_note)
    first_plan = (registerable[0].get("paper_plan") if registerable else None) or {}
    combined_plan = None
    if registerable:
        plan_legs = []
        for row in registerable:
            plan_legs.extend((row.get("paper_plan") or {}).get("legs") or [])
        if direction == "bullish":
            plan_direction = "long_bias"
        elif direction == "bearish":
            plan_direction = "short_bias"
        else:
            plan_direction = first_plan.get("direction") or "long_bias"
        combined_plan = {
            **first_plan,
            "ticker": "MIX",
            "strategy": "mixed_book",
            "instrument": instrument,
            "direction": plan_direction,
            "rationale": (
                f"Carteira mista paper com {len(registerable)} perna(s). "
                "Cada perna tem o próprio gatilho. Simulação, não recomendação."
            ),
            "legs": plan_legs,
            "expiry": close_by,
            "close_by": close_by,
            "modeled_max_loss_brl": risk_budget,
            "quantity_per_leg": 1,
            "eligible_for_live_trading": False,
            "entry": {
                **(first_plan.get("entry") or {}),
                "instruction": (
                    "Carteira mista: cada perna espera o próprio gatilho. "
                    "Paper only — o diário registra a simulação; nenhuma ordem vai à corretora."
                ),
            },
        }

    first = ready[0]
    payload = {
        "status": "ready",
        "ticker": "MIX",
        "label": "Carteira mista",
        "tickers": ids,
        "instrument": instrument,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon]["label"],
        "holding_days": int(HORIZONS[horizon]["holding_days"]),
        "direction": direction,
        "structure": {"strategy": "mixed_book", "legs": legs, "expiry": close_by},
        "spot": None,
        "entry": None,
        "invalidation": None,
        "target": None,
        "quantity": len(ready),
        "quote_currency": "BRL",
        "fx_usd_brl": next((row.get("fx_usd_brl") for row in ready if row.get("fx_usd_brl")), None),
        "suggested_size": {
            "quantity": len(ready),
            "capital_brl": capital,
            "risk_budget_brl": risk_budget,
            "notional_brl": round(sum(notionals), 2) if notionals else None,
            "notional_usd": None,
            "risk_per_trade_pct": risk_pct,
            "can_register_paper": bool(combined_plan),
            "paper_block": paper_block,
        },
        "basket": [_basket_row(row) for row in rows],
        "greeks": None,
        "heston": None,
        "confidence": "média" if len(ready) == len(rows) else "baixa",
        "invalidation_reason": (
            "Cada perna cai no próprio stop ou se o regime da mesa virar crise."
            + (f" {refuse_note}" if refuse_note else "")
        ),
        "regime": {"local": "mixed_book", "desk": (first.get("regime") or {}).get("desk")},
        "paper_plan": combined_plan,
        "plan_inputs": first.get("plan_inputs") or {
            "source": "ATOM cliente · operação pronta",
            "provenance": "user_supplied",
            "capital": capital,
            "total_risk_pct": 3,
            "existing_risk_brl": 0,
            "fee_per_contract_side": 0.05,
            "risk_per_trade_pct": risk_pct,
        },
        "eligible_for_live_trading": False,
        "mode": "paper_only",
        "as_of": now.isoformat(),
        "arsenal": contributions,
        "disclaimer": (
            "Cenário/simulação montado pelo arsenal. Não é recomendação, não é ordem, "
            "não promete retorno. Nenhuma ordem vai à corretora."
        ),
    }
    payload["why_fallback"] = _why_fallback(payload)
    payload["why"] = client_facing_why(payload["why_fallback"], payload["why_fallback"])
    return payload


def _basket_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker"),
        "label": row.get("label") or row.get("ticker"),
        "status": row.get("status"),
        "weight": row.get("weight"),
        "instrument": row.get("instrument"),
        "direction": row.get("direction"),
        "spot": row.get("spot"),
        "entry": row.get("entry"),
        "invalidation": row.get("invalidation"),
        "target": row.get("target"),
        "quote_currency": row.get("quote_currency"),
        "structure": row.get("structure"),
        "suggested_size": row.get("suggested_size"),
        "reason": row.get("reason"),
        "confidence": row.get("confidence"),
        "invalidation_reason": row.get("invalidation_reason"),
    }


def facts_for_llm(payload: dict[str, Any]) -> str:
    if payload.get("status") == "insufficient":
        return (
            f"O arsenal recusou montar a operação. Motivo em português: {payload.get('reason')}. "
            "Explique a recusa sem inventar tese e sem nomes de variáveis."
        )
    if payload.get("basket"):
        size = payload.get("suggested_size") or {}
        lines = [
            "Carteira mista (B3 e/ou cripto).",
            f"Horizonte: {payload.get('horizon_label')}",
            f"Risco total: {format_money_ptbr(float(size.get('risk_budget_brl') or 0), 'BRL')}",
        ]
        notional = size.get("notional_brl")
        if notional is not None:
            lines.append(f"Nocional: {format_money_ptbr(float(notional), 'BRL')}")
        for row in payload["basket"]:
            if row.get("status") == "ready":
                ccy = row.get("quote_currency") or "BRL"
                weight = round(float(row.get("weight") or 0) * 100, 1)
                direction = "alta" if row.get("direction") == "bullish" else "baixa"
                lines.append(
                    f"- {row.get('label') or row.get('ticker')} peso {weight}% {direction} "
                    f"preço agora {format_money_ptbr(float(row.get('spot') or 0), ccy)} "
                    f"gatilho {format_money_ptbr(float(row.get('entry') or 0), ccy)} "
                    f"stop {format_money_ptbr(float(row.get('invalidation') or 0), ccy)} "
                    f"risco {format_money_ptbr(float((row.get('suggested_size') or {}).get('risk_budget_brl') or 0), 'BRL')}"
                )
            else:
                lines.append(f"- {row.get('ticker')} recusado: {row.get('reason')}")
        lines.append(
            "Redija em português simples. Copie os preços exatamente como estão "
            "(pt-BR, sem ISO aaaa-mm-dd, sem notação científica). "
            "Não trate o preço agora como o gatilho de entrada. "
            "Proibido citar nomes técnicos (z_score, EWMA, GARCH, Hurst, eligible_for_live_trading) "
            "e as palavras trade e pontos. Preços de cripto em dólares (US$); risco e nocional em reais (R$)."
        )
        return "\n".join(lines)
    direction = "alta" if payload.get("direction") == "bullish" else "baixa"
    local = _REGIME_PT.get((payload.get("regime") or {}).get("local", ""), "no mercado recente")
    ccy = payload.get("quote_currency") or "BRL"
    expiry = (payload.get("structure") or {}).get("expiry")
    fx = payload.get("fx_usd_brl") or {}
    fx_line = ""
    if ccy == "USD" and fx.get("rate"):
        fx_line = f"Câmbio USD/BRL: {format_price_ptbr(float(fx['rate']), 4)} ({fx.get('source') or 'feed'})\n"
    size = payload.get("suggested_size") or {}
    notional = size.get("notional_brl")
    notional_line = (
        f"Nocional: {format_money_ptbr(float(notional), 'BRL')}\n" if notional is not None
        else ""
    )
    return (
        f"Ativo: {payload.get('label') or payload.get('ticker')}\n"
        f"Direção: {direction}\n"
        f"Instrumento: {payload.get('instrument')}\n"
        f"Horizonte: {payload.get('horizon_label')}\n"
        f"Preço agora (cotação atual, NÃO é o gatilho): {format_money_ptbr(float(payload.get('spot') or 0), ccy)}\n"
        f"Gatilho de entrada (só entra se o preço chegar neste nível): {format_money_ptbr(float(payload.get('entry') or 0), ccy)}\n"
        f"Invalidação (stop): {format_money_ptbr(float(payload.get('invalidation') or 0), ccy)}\n"
        f"Alvo: {format_money_ptbr(float(payload.get('target') or 0), ccy)}\n"
        f"Risco máximo: {format_money_ptbr(float(size.get('risk_budget_brl') or 0), 'BRL')}\n"
        f"{notional_line}"
        f"{fx_line}"
        f"Prazo até: {format_date_ptbr(expiry)}\n"
        f"Confiança: {payload.get('confidence')}\n"
        f"Leitura de mercado: {local}\n"
        f"Por que a tese cai: {payload.get('invalidation_reason')}\n"
        "Redija em português simples. Copie os preços e a data exatamente como estão "
        "(pt-BR, dd/mm/aaaa, sem ISO aaaa-mm-dd, sem notação científica). "
        "Não trate o preço agora como o gatilho de entrada — são dois números. "
        "Proibido citar nomes técnicos "
        "(z_score, EWMA, GARCH, Hurst, eligible_for_live_trading) e as palavras "
        "trade e pontos. Preços de cripto em dólares (US$); risco e nocional em reais (R$)."
    )

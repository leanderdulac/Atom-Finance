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

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import floor
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
     "instruments": ["spot", "future"]},
    {"id": "ETH", "label": "Ethereum", "asset_class": "crypto",
     "quote_symbol": "ETH-USD", "yahoo": "ETH-USD", "binance": "ETHUSDT",
     "instruments": ["spot", "future"]},
]
UNIVERSE_BY_ID = {row["id"]: row for row in UNIVERSE}

MIN_HISTORY = 60


@dataclass
class MarketView:
    """Injected in tests; production fills this from cache or live fetchers."""
    quote: dict[str, Any]
    history: dict[str, Any]
    chain: list[dict[str, Any]] | None = None
    chain_source: str | None = None
    regime: dict[str, Any] | None = None
    contributions: list[dict[str, Any]] = field(default_factory=list)


def universe_public() -> list[dict[str, Any]]:
    return [
        {k: row[k] for k in ("id", "label", "asset_class", "instruments")}
        for row in UNIVERSE
    ]


def resolve_asset(ticker: str) -> dict[str, Any] | None:
    key = ticker.strip().upper()
    aliases = {"BTC-USD": "BTC", "ETH-USD": "ETH", "BTCUSDT": "BTC", "ETHUSDT": "ETH"}
    return UNIVERSE_BY_ID.get(aliases.get(key, key))


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
    width_stop = 1.5 * horizon_vol
    width_tgt = 2.0 * horizon_vol
    if direction == "bullish":
        entry = round(spot * 1.002, 6)
        invalidation = max(spot * (1 - width_stop), spot * 0.05)
        target = spot * (1 + width_tgt)
    else:
        entry = round(spot * 0.998, 6)
        invalidation = spot * (1 + width_stop)
        target = max(spot * (1 - width_tgt), spot * 0.05)
    return entry, float(invalidation), float(target)


def _size(capital: float, risk_pct: float, entry: float, invalidation: float, lot: float = 1.0) -> tuple[float, float, bool, str | None]:
    budget = capital * risk_pct / 100.0
    per_unit = abs(entry - invalidation)
    if per_unit <= 1e-12:
        return 0.0, budget, False, "Distância até a invalidação nula."
    raw = budget / per_unit
    qty = floor(raw / lot) * lot
    if qty < lot:
        return round(raw, 6), budget, False, (
            "O capital paper padrão não cabe um lote inteiro com este stop. "
            "A operação aparece como cenário; o diário não registra fração abaixo do lote."
        )
    return float(qty), budget, True, None


def _why_fallback(payload: dict[str, Any]) -> str:
    if payload.get("status") == "insufficient":
        return (
            f"{payload.get('reason')} Isto é um recado do arsenal, não uma recomendação. "
            "Nenhuma ordem foi enviada."
        )
    direction = "alta" if payload["direction"] == "bullish" else "baixa"
    conf = payload.get("confidence", "baixa")
    invalid = payload.get("invalidation_reason")
    return (
        f"Cenário {direction} em {payload['ticker']} no horizonte {payload['horizon_label']}, "
        f"com confiança {conf}. O arsenal usou cotação, volatilidade e regime — "
        f"não uma previsão de lucro. {invalid} Simulação paper; eligible_for_live_trading é sempre falso."
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
) -> dict[str, Any]:
    qty = int(quantity) if quantity >= 1 else 0
    close_by = (now.date() + timedelta(days=holding_days)).isoformat()
    side = "buy" if direction == "bullish" else "sell"
    debit = abs(entry)  # per unit; shorts are handled as credit on open
    risk = abs(entry - invalidation) * max(qty, 1)
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
            "quantity": max(qty, 1),
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
            "take_profit_net_brl": round(qty * abs(target - entry), 2) if qty else None,
            "stop_loss_net_brl": round(qty * abs(entry - invalidation), 2) if qty else round(risk, 2),
            "instruction": (
                "Encerrar no primeiro evento: invalidação, alvo ou data-limite. "
                "Limiares não garantem preço de saída."
            ),
        },
        "quantity_per_leg": max(qty, 1),
        "multiplier": 1,
        "lot_size": 1,
        "premium_outlay_brl": round(qty * entry, 2) if side == "buy" and qty else 0,
        "fees_reserved_brl": 0,
        "modeled_max_loss_brl": round(qty * abs(entry - invalidation), 2) if qty else round(risk, 2),
        "modeled_max_profit_brl": round(qty * abs(target - entry), 2) if qty else None,
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
            "(PETR4, VALE3, ITUB4, BBDC4, WEGE3, BTC, ETH).",
            contributions,
        )
    if instrument not in asset["instruments"]:
        if instrument == "future" and asset["asset_class"] == "equity_br":
            return _insufficient(
                "O arsenal não tem livro de futuro B3 para este ativo. "
                "Futuro/perpétuo automático existe só para BTC e ETH (Binance público).",
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
            "Sem cotação ou histórico de mercado para este ativo agora. O ATOM não inventa preço.",
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
            hurst = float(_hurst(log_p))
    except Exception:
        hurst = None
    local = _local_regime(vol, hurst, mom)
    _mark(contributions, "Hurst / regime local", hurst is not None,
          f"H={hurst:.2f} → {local}" if hurst is not None else f"Hurst indisponível; regime local {local}")

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
    qty, budget, can_lot, size_note = _size(capital, risk_pct, entry, invalidation)
    invalidation_reason = (
        f"A tese cai se o preço cruzar {invalidation:.4g} "
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
            req = PlanRequest(
                source="ATOM cliente · livro do arsenal, tese montada automaticamente",
                provenance="user_supplied",
                as_of=now,
                capital=capital,
                risk_per_trade_pct=min(risk_pct, 5),
                theses=[{
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
            )
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
            capital=capital, risk_pct=risk_pct, now=now,
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
        "suggested_size": {
            "quantity": qty,
            "capital_brl": capital,
            "risk_budget_brl": round(budget, 2),
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
            "não promete retorno. eligible_for_live_trading é sempre falso."
        ),
    }
    payload["why_fallback"] = _why_fallback(payload)
    payload["why"] = payload["why_fallback"]
    if garch_fit:
        payload["volatility"]["garch_persistence"] = garch_fit.get("persistence")
    return payload


def facts_for_llm(payload: dict[str, Any]) -> str:
    keys = (
        "status", "ticker", "instrument", "horizon_label", "direction", "spot",
        "entry", "invalidation", "target", "confidence", "invalidation_reason",
        "regime", "volatility", "structure", "reason", "disclaimer",
    )
    lines = [f"{k}: {payload.get(k)}" for k in keys if k in payload]
    return "\n".join(lines)

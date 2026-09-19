"""Desk-paper APIs: Heston CF, Engle–Granger, Avellaneda–Stoikov, FF5, scanners."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.quant_doctrine import payload as doctrine_payload
from app.core.security import get_current_user
from app.models.cointegration import engle_granger, johansen, pairs_backtest
from app.models.fama_french import decompose as ff_decompose
from app.models.forward_test import evaluate as forward_evaluate
from app.models.insider_clusters import detect as detect_insiders
from app.models.market_making import avellaneda_stoikov_quotes, simulate_inventory
from app.models.mean_reversion import scan as mr_scan
from app.models.perp_arb import scan as perp_scan
from app.models.regime import demo_payload
from app.models.regime import evaluate as regime_evaluate
from app.models.target_choice import evaluate as target_choice_evaluate
from app.models.vectorize import evaluate as vectorize_evaluate
from app.models.volatility import HestonModel
from app.models.winners_curse import deflated_sharpe
from app.models.winners_curse import simulate as winners_curse_simulate

router = APIRouter()


@router.get("/doctrine")
async def desk_doctrine():
    return doctrine_payload()


async def _run(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


class HestonPriceRequest(BaseModel):
    S0: float = Field(100, gt=0)
    K: float = Field(100, gt=0)
    v0: float = Field(0.04, gt=0)
    r: float = 0.05
    kappa: float = Field(2.0, gt=0)
    theta: float = Field(0.04, gt=0)
    xi: float = Field(0.3, gt=0)
    rho: float = Field(-0.7, ge=-1, le=1)
    T: float = Field(1.0, gt=0)
    q: float = Field(0.0, ge=0)
    option_type: Literal["call", "put"] = "call"
    method: Literal["cf", "mc"] = "cf"
    n_paths: int = Field(20_000, ge=1_000, le=50_000)


class PairRequest(BaseModel):
    y: list[float] = Field(..., min_length=60)
    x: list[float] = Field(..., min_length=60)
    entry_z: float = Field(2.0, gt=0, le=5)
    exit_z: float = Field(0.5, gt=0, le=2)
    commission: float = Field(0.0005, ge=0, le=0.01)
    slippage: float = Field(0.0002, ge=0, le=0.01)


class QuotesRequest(BaseModel):
    mid: float = Field(..., gt=0)
    inventory: float = 0.0
    sigma: float = Field(0.2, ge=0)
    gamma: float = Field(0.1, gt=0)
    k: float = Field(1.5, gt=0)
    A: float = Field(140, gt=0)
    time_remaining: float = Field(1.0, ge=0)


class MMSimRequest(QuotesRequest):
    n_steps: int = Field(390, ge=50, le=2000)
    q_max: float = Field(10, gt=0)
    seed: int = 42


class FFRequest(BaseModel):
    excess_returns: list[float] = Field(..., min_length=36)
    mkt_rf: list[float] = Field(..., min_length=36)
    smb: list[float] = Field(..., min_length=36)
    hml: list[float] = Field(..., min_length=36)
    rmw: list[float] = Field(..., min_length=36)
    cma: list[float] = Field(..., min_length=36)


class MRScanRequest(BaseModel):
    universe: dict[str, list[float]]


class VenueQuoteIn(BaseModel):
    venue: str
    bid: float = Field(..., gt=0)
    ask: float = Field(..., gt=0)
    taker_fee_bps: float = Field(..., ge=0)
    funding_8h: float = 0.0


class PerpArbRequest(BaseModel):
    quotes: list[VenueQuoteIn] = Field(..., min_length=2)
    notional: float = Field(10_000, gt=0)


class InsiderEvent(BaseModel):
    ticker: str
    insider_id: str
    side: Literal["buy", "sell"]
    shares: float = Field(..., gt=0)
    date: str
    notional: float | None = None


class InsiderRequest(BaseModel):
    events: list[InsiderEvent] = Field(..., min_length=3)
    window_days: int = Field(7, ge=1, le=60)
    min_insiders: int = Field(3, ge=2, le=20)


class HestonCalibrateRequest(BaseModel):
    S0: float = Field(..., gt=0)
    r: float = 0.05
    q: float = Field(0.0, ge=0)
    quotes: list[dict] = Field(..., min_length=4, max_length=40)


class JohansenRequest(BaseModel):
    series: dict[str, list[float]]
    k_ar: int = Field(2, ge=1, le=8)


class EdgarRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=5)
    limit: int = Field(6, ge=1, le=15)
    window_days: int = Field(7, ge=1, le=60)
    min_insiders: int = Field(3, ge=2, le=20)


class RegimePositionIn(BaseModel):
    id: str
    strategy_id: str | None = None
    weight: float = Field(..., ge=0, le=1)
    book_corr: float | None = Field(None, ge=-1, le=1)


class RegimeStrategyIn(BaseModel):
    id: str
    name: str | None = None
    live_in: list[str]
    standby_in: list[str] = Field(default_factory=list)
    kill_in: list[str] = Field(default_factory=list)
    half_kelly: float = Field(0.5, gt=0, le=1)
    kelly_by_regime: dict[str, float] = Field(default_factory=dict)


class RegimeEvaluateRequest(BaseModel):
    demo: Literal["calm", "trending", "crisis"] | None = None
    equity_prices: dict[str, list[float]] | None = None
    vix_front: list[float] | None = None
    vix_back: list[float] | None = None
    implied_vol: list[float] | None = None
    credit_spread: list[float] | None = None
    yield_2y: list[float] | None = None
    yield_10y: list[float] | None = None
    window: int = Field(90, ge=30, le=252)
    strategies: list[RegimeStrategyIn] | None = None
    positions: list[RegimePositionIn] | None = None
    persist: bool = False


@router.post("/heston/price")
async def heston_price(req: HestonPriceRequest):
    if req.method == "cf":
        return await _run(
            HestonModel.price_option_cf,
            req.S0, req.K, req.v0, req.r, req.kappa, req.theta, req.xi, req.rho, req.T,
            req.option_type, req.q,
        )
    return await _run(
        HestonModel.price_option,
        req.S0, req.K, req.v0, req.r, req.kappa, req.theta, req.xi, req.rho, req.T,
        req.option_type, req.n_paths,
    )


@router.post("/heston/calibrate")
@limiter.limit("20/minute")
async def heston_calibrate(request: Request, req: HestonCalibrateRequest):
    try:
        return await _run(HestonModel.calibrate, req.S0, req.r, req.quotes, req.q)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pairs/johansen")
async def pairs_johansen(req: JohansenRequest):
    names = list(req.series.keys())
    if len(names) < 2:
        raise HTTPException(400, "Need at least two series")
    cols = [req.series[n] for n in names]
    n = len(cols[0])
    if any(len(c) != n for c in cols):
        raise HTTPException(400, "Series must be aligned")
    try:
        panel = np.column_stack([np.array(c, dtype=float) for c in cols])
        result = await _run(johansen, panel, req.k_ar)
        result["names"] = names
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pairs/engle-granger")
async def pairs_eg(req: PairRequest):
    if len(req.y) != len(req.x):
        raise HTTPException(400, "y and x must have the same length")
    try:
        return await _run(engle_granger, np.array(req.y), np.array(req.x))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pairs/backtest")
async def pairs_bt(req: PairRequest):
    if len(req.y) != len(req.x):
        raise HTTPException(400, "y and x must have the same length")
    try:
        return await _run(
            pairs_backtest,
            np.array(req.y), np.array(req.x),
            req.entry_z, req.exit_z, 60, req.commission, req.slippage,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/market-making/quotes")
async def mm_quotes(req: QuotesRequest):
    try:
        return avellaneda_stoikov_quotes(
            req.mid, req.inventory, req.sigma, req.gamma, req.k, req.A, req.time_remaining,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/market-making/simulate")
async def mm_sim(req: MMSimRequest):
    return await _run(
        simulate_inventory,
        req.mid, req.sigma, req.gamma, req.k, req.A, req.time_remaining,
        req.n_steps, req.q_max, req.seed,
    )


@router.post("/fama-french/decompose")
async def ff_dec(req: FFRequest):
    try:
        return await _run(
            ff_decompose,
            np.array(req.excess_returns),
            {
                "mkt_rf": np.array(req.mkt_rf),
                "smb": np.array(req.smb),
                "hml": np.array(req.hml),
                "rmw": np.array(req.rmw),
                "cma": np.array(req.cma),
            },
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/mean-reversion/scan")
async def mr(req: MRScanRequest):
    if len(req.universe) > 50:
        raise HTTPException(400, "Universe capped at 50 series")
    try:
        return await _run(mr_scan, req.universe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/perp-arb/scan")
async def perp(req: PerpArbRequest):
    try:
        return perp_scan([q.model_dump() for q in req.quotes], req.notional)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/perp-arb/live")
@limiter.limit("30/minute")
async def perp_live(
    request: Request,
    symbol: str = Query("BTCUSDT", min_length=3, max_length=20),
    notional: float = Query(10_000, gt=0),
):
    import httpx

    from app.services.perp_collector import collect_quotes
    try:
        async with httpx.AsyncClient() as client:
            return await collect_quotes(symbol, client=client, notional=notional)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/insider-clusters/detect")
async def insiders(req: InsiderRequest):
    payload = []
    for e in req.events:
        row = e.model_dump()
        if row.get("notional") is None:
            row.pop("notional")
        payload.append(row)
    try:
        return detect_insiders(payload, req.window_days, req.min_insiders)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/insider-clusters/edgar")
@limiter.limit("10/hour")
async def insiders_edgar(request: Request, req: EdgarRequest):
    import httpx

    from app.services.edgar import fetch_form4_events
    try:
        async with httpx.AsyncClient() as client:
            pulled = await fetch_form4_events(req.ticker, client=client, limit=req.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "SEC EDGAR request failed") from exc
    events = pulled.get("events") or []
    if len(events) < req.min_insiders:
        return {**pulled, "clusters": [], "n_clusters": 0, "note": "Not enough open-market events to cluster."}
    clustered = detect_insiders(events, req.window_days, req.min_insiders)
    return {**pulled, **clustered}


@router.post("/regime/evaluate")
@limiter.limit("20/minute")
async def regime_eval(request: Request, req: RegimeEvaluateRequest):
    payload = demo_payload(req.demo) if req.demo else None
    if payload is None:
        needed = (
            req.equity_prices, req.vix_front, req.vix_back, req.implied_vol,
            req.credit_spread, req.yield_2y, req.yield_10y,
        )
        if any(x is None for x in needed):
            raise HTTPException(400, "Supply demo=calm|trending|crisis or all six signal series")
        payload = {
            "equity_prices": req.equity_prices,
            "vix_front": req.vix_front,
            "vix_back": req.vix_back,
            "implied_vol": req.implied_vol,
            "credit_spread": req.credit_spread,
            "yield_2y": req.yield_2y,
            "yield_10y": req.yield_10y,
        }
    try:
        result = await _run(
            regime_evaluate,
            equity_prices=payload["equity_prices"],
            vix_front=payload["vix_front"],
            vix_back=payload["vix_back"],
            implied_vol=payload["implied_vol"],
            credit_spread=payload["credit_spread"],
            yield_2y=payload["yield_2y"],
            yield_10y=payload["yield_10y"],
            window=req.window,
            strategies=[s.model_dump() for s in req.strategies] if req.strategies else None,
            positions=[p.model_dump() for p in req.positions] if req.positions else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    from app.services.regime_context import (
        render_adjustments,
        render_current_regime,
        render_history,
        write_context,
    )
    result["context"] = {
        "current-regime.md": render_current_regime(result),
        "position-adjustments.md": render_adjustments(result),
        "regime-history.md": render_history(result),
    }
    if req.persist:
        import os
        from pathlib import Path

        dest = Path(os.getenv("ATOM_STRATEGY_CONTEXT_DIR") or "").expanduser()
        if not dest.is_absolute() or not str(dest):
            raise HTTPException(400, "persist requires ATOM_STRATEGY_CONTEXT_DIR as an absolute path")
        write_context(dest, result)
        result["context_dir"] = str(dest)
    return result


@router.post("/regime/live")
@limiter.limit("6/hour")
async def regime_live(
    request: Request,
    flatten: bool = Query(False),
    owner: str = Depends(get_current_user),
):
    import asyncio

    from app.services.regime_feeds import fetch_live_payload
    from app.services.regime_job import run_snapshot

    try:
        result = await asyncio.to_thread(run_snapshot, fetch=fetch_live_payload)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Live regime books failed") from exc

    from app.services.regime_context import render_adjustments, render_current_regime, render_history
    result["context"] = {
        "current-regime.md": render_current_regime(result),
        "position-adjustments.md": render_adjustments(result),
        "regime-history.md": render_history(result),
    }
    if flatten and result.get("kill_switch", {}).get("armed"):
        from app.api.paper_trades import flatten_open_trades
        result["paper_flatten"] = await flatten_open_trades(
            owner, reason="regime_live_crisis",
        )
        result["kill_switch"]["paper_flatten"] = "applied"
    elif flatten:
        result["paper_flatten"] = {
            "closed": [],
            "skipped": [],
            "note": "Kill switch not armed; paper book untouched.",
            "broker_orders_sent": 0,
        }
    return result


@router.get("/regime/last")
async def regime_last():
    from app.services.regime_job import last_snapshot
    snap = last_snapshot()
    if snap is None:
        raise HTTPException(404, "No regime job snapshot yet")
    return snap


@router.post("/regime/execute")
async def regime_execute():
    raise HTTPException(
        410,
        "Broker execution is retired. Use POST /api/desk/regime/live?flatten=true "
        "to close simulated paper trades at last mark when the kill switch is armed.",
    )


class WinnersCurseSimRequest(BaseModel):
    n_strategies: int = Field(400, ge=10, le=2000)
    t_is: int = Field(504, ge=60, le=2500)
    t_oos: int = Field(252, ge=60, le=2500)
    daily_vol: float = Field(0.01, gt=1e-4, le=0.1)
    seed: int = Field(7, ge=0)


class WinnersCurseDeflateRequest(BaseModel):
    observed_sharpe: float = Field(..., ge=-20, le=20)
    n_trials: int = Field(..., ge=2, le=100_000)
    n_obs: int = Field(..., ge=30, le=10_000)
    skew: float = Field(0.0, ge=-5, le=5)
    excess_kurtosis: float = Field(0.0, ge=-2, le=20)


@router.post("/winners-curse/simulate")
@limiter.limit("20/minute")
async def winners_curse_sim(request: Request, req: WinnersCurseSimRequest):
    try:
        return await _run(
            winners_curse_simulate,
            req.n_strategies, req.t_is, req.t_oos, req.daily_vol, req.seed,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/winners-curse/deflate")
async def winners_curse_deflate(req: WinnersCurseDeflateRequest):
    try:
        out = deflated_sharpe(
            req.observed_sharpe, req.n_trials, req.n_obs, req.skew, req.excess_kurtosis,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out["eligible_for_live_trading"] = False
    out["math"] = (
        "DSR = Φ((SR̂ − SR*)/σ̂). SR* is the expected maximum Sharpe among n_trials "
        "independent zero-edge tests. Ask how many candidates this Sharpe beat."
    )
    return out


class ForwardTestRequest(BaseModel):
    prices: list[float] | None = Field(None, min_length=250, max_length=3000)
    locked_fast: int = Field(10, ge=2, le=100)
    locked_slow: int = Field(40, ge=3, le=200)
    commission: float = Field(0.001, ge=0, le=0.01)
    slippage: float = Field(0.0005, ge=0, le=0.01)
    seed: int = Field(11, ge=0)
    n: int = Field(756, ge=250, le=3000)


@router.post("/forward-test/evaluate")
@limiter.limit("20/minute")
async def forward_test_evaluate(request: Request, req: ForwardTestRequest):
    try:
        return await _run(
            forward_evaluate,
            req.prices,
            req.locked_fast,
            req.locked_slow,
            req.commission,
            req.slippage,
            req.seed,
            req.n,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TargetChoiceRequest(BaseModel):
    n: int = Field(504, ge=250, le=2000)
    seed: int = Field(5, ge=0)


@router.post("/target-choice/evaluate")
@limiter.limit("20/minute")
async def target_choice_eval(request: Request, req: TargetChoiceRequest):
    try:
        return await _run(target_choice_evaluate, req.n, req.seed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class VectorizeRequest(BaseModel):
    n_names: int = Field(80, ge=10, le=400)
    n_days: int = Field(504, ge=80, le=2000)
    seed: int = Field(7, ge=0)
    pe_max: float = Field(10.0, gt=1.0, le=40.0)


@router.post("/vectorize/evaluate")
@limiter.limit("20/minute")
async def vectorize_eval(request: Request, req: VectorizeRequest):
    try:
        return await _run(vectorize_evaluate, req.n_names, req.n_days, req.seed, req.pe_max)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

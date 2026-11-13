"""
Unified Quant Playbook Scanner — 3-Pillar Institutional Strategy Engine.

Combines:
1. Statistical Arbitrage & Commodity Spreads (Engle–Granger + Johansen + OU half-life)
2. Crypto Cash-and-Carry / Cross-Venue Perp Funding Arbitrage (BTC, ETH, SOL)
3. Regime Nowcast + Half-Kelly Capital Allocation with Multiple-Testing DSR Haircut
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np

from app.models.cointegration import engle_granger, johansen, pairs_backtest
from app.models.perp_arb import scan as perp_scan
from app.models.regime import demo_payload as regime_demo_payload
from app.models.regime import evaluate as regime_evaluate
from app.models.winners_curse import deflated_sharpe

logger = logging.getLogger(__name__)

DEFAULT_PAIR_CANDIDATES: list[dict[str, str]] = [
    {"y": "PETR4.SA", "x": "PETR3.SA", "bucket": "b3_equities", "label": "Petrobras PN vs ON"},
    {"y": "ITUB4.SA", "x": "BBDC4.SA", "bucket": "b3_equities", "label": "Itaú vs Bradesco"},
    {"y": "GGBR4.SA", "x": "GOAU4.SA", "bucket": "b3_equities", "label": "Gerdau vs Metalúrgica Gerdau"},
    {"y": "GLD", "x": "SLV", "bucket": "commodities", "label": "Ouro (GLD) vs Prata (SLV)"},
    {"y": "USO", "x": "XLE", "bucket": "commodities", "label": "Petróleo WTI (USO) vs Energia (XLE)"},
    {"y": "VALE3.SA", "x": "GGBR4.SA", "bucket": "commodities", "label": "Minério/Vale vs Siderurgia"},
]

DEFAULT_PLAYBOOK_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "b3_stat_arb_pairs",
        "name": "Arbitragem Estatística B3 (Pares ON/PN & Bancos)",
        "live_in": ["calm_mean_rev", "high_vol"],
        "standby_in": ["trending"],
        "kill_in": ["crisis"],
        "half_kelly": 0.5,
        "kelly_by_regime": {"calm_mean_rev": 0.50, "high_vol": 0.35, "trending": 0.20, "crisis": 0.0},
    },
    {
        "id": "commodities_coint_spreads",
        "name": "Spreads Cointegrados de Commodities (Ouro/Prata & Petróleo/Energia)",
        "live_in": ["calm_mean_rev", "trending", "high_vol"],
        "standby_in": [],
        "kill_in": ["crisis"],
        "half_kelly": 0.5,
        "kelly_by_regime": {"calm_mean_rev": 0.45, "trending": 0.40, "high_vol": 0.30, "crisis": 0.0},
    },
    {
        "id": "crypto_funding_carry",
        "name": "Cash-and-Carry Funding Arbitrage (BTC / ETH / SOL Delta-Neutro)",
        "live_in": ["calm_mean_rev", "trending", "high_vol"],
        "standby_in": ["crisis"],
        "kill_in": [],
        "half_kelly": 0.5,
        "kelly_by_regime": {"calm_mean_rev": 0.40, "trending": 0.50, "high_vol": 0.30, "crisis": 0.15},
    },
    {
        "id": "options_tail_protection",
        "name": "Opções Estruturadas & Proteção de Cauda (EVT / Long Gamma em Crise)",
        "live_in": ["crisis", "high_vol", "calm_mean_rev"],
        "standby_in": ["trending"],
        "kill_in": [],
        "half_kelly": 0.5,
        "kelly_by_regime": {"calm_mean_rev": 0.25, "trending": 0.15, "high_vol": 0.45, "crisis": 0.60},
    },
]


def _synthetic_pair_series(idx: int, n: int = 240, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate realistic cointegrated or near-cointegrated price series for deterministic scanning."""
    rng = np.random.default_rng(seed + idx * 17)
    base_scales = [36.0, 32.0, 18.0, 215.0, 74.0, 61.0]
    scale = base_scales[idx % len(base_scales)]
    common_factor = scale * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    beta_true = 1.15 - 0.12 * (idx % 3)
    alpha_true = 2.0 + 0.5 * idx
    # Mean-reverting Ornstein-Uhlenbeck spread with a recent dislocation on the first pairs
    theta = 0.14 if idx < 4 else 0.03
    spread = np.zeros(n, dtype=np.float64)
    for t in range(1, n):
        spread[t] = (1.0 - theta) * spread[t - 1] + rng.normal(0.0, 0.45)
    # Inject an actionable dislocation at the end of the sample for top candidates
    if idx == 0:
        spread[-1] = 2.45 * float(np.std(spread[:-1]))
    elif idx == 1:
        spread[-1] = -2.20 * float(np.std(spread[:-1]))
    elif idx == 3:
        spread[-1] = 2.10 * float(np.std(spread[:-1]))

    x = np.maximum(common_factor, 1.0)
    y = np.maximum(alpha_true + beta_true * x + spread, 1.0)
    return y, x


def _fetch_or_synthetic_pair(
    y_ticker: str,
    x_ticker: str,
    idx: int,
    mode: Literal["synthetic", "live"],
    n: int = 240,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, str]:
    if mode == "live":
        try:
            import pandas as pd

            from app.services.data_fetcher import DataFetcher
            df_y = DataFetcher.get_historical_data(y_ticker, period="1y", interval="1d")
            df_x = DataFetcher.get_historical_data(x_ticker, period="1y", interval="1d")
            if df_y is not None and df_x is not None and not df_y.empty and not df_x.empty:
                joined = pd.DataFrame({"y": df_y["Close"], "x": df_x["Close"]}).dropna()
                if len(joined) >= 80:
                    return (
                        joined["y"].to_numpy(dtype=np.float64),
                        joined["x"].to_numpy(dtype=np.float64),
                        "live_market",
                    )
        except Exception as exc:
            logger.debug("Live pair fetch fallback for %s/%s: %s", y_ticker, x_ticker, exc)

    y_syn, x_syn = _synthetic_pair_series(idx, n=n, seed=seed)
    return y_syn, x_syn, "synthetic_benchmark"


def _build_pair_order_ticket(
    *,
    y_ticker: str,
    x_ticker: str,
    last_y: float,
    last_x: float,
    beta: float,
    z_now: float,
    entry_z: float,
    exit_z: float,
    half_life_days: float | None,
    cointegrated: bool,
    allocated_notional: float,
) -> dict[str, Any]:
    """Compute exact dollar-neutral share quantities and stop/target rules for a pair."""
    dollar_hedge = abs(beta) * (last_x / max(last_y, 1e-8))
    gross_unit = 1.0 + max(dollar_hedge, 1e-8)
    notional_y = allocated_notional / gross_unit
    notional_x = allocated_notional - notional_y

    shares_y = max(int(round(notional_y / max(last_y, 1e-8))), 0)
    shares_x = max(int(round(notional_x / max(last_x, 1e-8))), 0)
    lot_100_y = (shares_y // 100) * 100
    lot_100_x = (shares_x // 100) * 100

    if not cointegrated or allocated_notional <= 0 or abs(z_now) < entry_z:
        side_y = "WAIT"
        side_x = "WAIT"
        signed_notional = 0.0
    elif z_now <= -entry_z:
        # Spread is cheap: Buy Y, Sell X
        side_y = "BUY"
        side_x = "SELL_SHORT"
        signed_notional = round(shares_y * last_y - shares_x * last_x, 2)
    else:
        # Spread is rich: Sell Y, Buy X
        side_y = "SELL_SHORT"
        side_x = "BUY"
        signed_notional = round(-shares_y * last_y + shares_x * last_x, 2)

    time_stop_days = (
        int(math.ceil(2.5 * half_life_days))
        if half_life_days is not None and math.isfinite(half_life_days) and half_life_days > 0
        else 20
    )

    return {
        "allocated_gross_notional": round(allocated_notional, 2),
        "dollar_hedge_ratio": round(dollar_hedge, 4),
        "leg_y": {
            "ticker": y_ticker,
            "side": side_y,
            "last_price": round(last_y, 2),
            "shares_exact": shares_y,
            "b3_standard_lot": lot_100_y,
            "fractional_shares": shares_y - lot_100_y,
            "notional": round(shares_y * last_y, 2),
        },
        "leg_x": {
            "ticker": x_ticker,
            "side": side_x,
            "last_price": round(last_x, 2),
            "shares_exact": shares_x,
            "b3_standard_lot": lot_100_x,
            "fractional_shares": shares_x - lot_100_x,
            "notional": round(shares_x * last_x, 2),
        },
        "net_dollar_exposure": signed_notional,
        "rules": {
            "entry_trigger_z": f"|z| >= {entry_z:.2f} (atual: {z_now:+.2f})",
            "take_profit_z": f"|z| <= {exit_z:.2f}",
            "stop_loss_z": "|z| >= 3.50 ou perda de cointegração ADF",
            "time_stop_trading_days": time_stop_days,
        },
    }


def _fetch_live_binance_carry(symbol: str) -> dict[str, float] | None:
    """Fetch live Binance Spot bookTicker + USDT-M Futures bookTicker & 8h funding rate."""
    try:
        import httpx
        with httpx.Client(timeout=4.0) as client:
            spot_r = client.get("https://api.binance.com/api/v3/ticker/bookTicker", params={"symbol": symbol})
            spot_r.raise_for_status()
            spot = spot_r.json()

            fut_r = client.get("https://fapi.binance.com/fapi/v1/ticker/bookTicker", params={"symbol": symbol})
            fut_r.raise_for_status()
            fut = fut_r.json()

            prem_r = client.get("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": symbol})
            prem_r.raise_for_status()
            prem = prem_r.json()

            spot_bid = float(spot["bidPrice"])
            spot_ask = float(spot["askPrice"])
            return {
                "spot_mid": round(0.5 * (spot_bid + spot_ask), 4),
                "spot_bid": spot_bid,
                "spot_ask": spot_ask,
                "perp_bid": float(fut["bidPrice"]),
                "perp_ask": float(fut["askPrice"]),
                "funding_8h_binance": float(prem.get("lastFundingRate") or 0.0),
            }
    except Exception as exc:
        logger.debug("Live Binance carry fetch fallback for %s: %s", symbol, exc)
        return None


def _scan_crypto_carry(
    allocated_bucket_capital: float,
    seed: int = 42,
    mode: Literal["synthetic", "live"] = "synthetic",
) -> list[dict[str, Any]]:
    """Evaluate delta-neutral perp funding & cross-venue basis on liquid crypto majors."""
    rng = np.random.default_rng(seed)
    majors = [
        {
            "symbol": "BTCUSDT",
            "spot_mid": 68_500.0,
            "funding_8h_binance": 0.00018 + float(rng.normal(0, 0.00002)),
            "funding_8h_hyperliquid": 0.00026 + float(rng.normal(0, 0.00002)),
        },
        {
            "symbol": "ETHUSDT",
            "spot_mid": 2_620.0,
            "funding_8h_binance": 0.00014 + float(rng.normal(0, 0.00002)),
            "funding_8h_hyperliquid": 0.00021 + float(rng.normal(0, 0.00002)),
        },
        {
            "symbol": "SOLUSDT",
            "spot_mid": 172.0,
            "funding_8h_binance": 0.00024 + float(rng.normal(0, 0.00003)),
            "funding_8h_hyperliquid": 0.00035 + float(rng.normal(0, 0.00003)),
        },
    ]

    per_asset_capital = round(allocated_bucket_capital / max(len(majors), 1), 2)
    results: list[dict[str, Any]] = []
    for item in majors:
        live_snap = _fetch_live_binance_carry(item["symbol"]) if mode == "live" else None
        if live_snap is not None:
            mid = live_snap["spot_mid"]
            f_bin = live_snap["funding_8h_binance"]
            quotes = [
                {
                    "venue": "binance_spot_hedge",
                    "bid": live_snap["spot_bid"],
                    "ask": live_snap["spot_ask"],
                    "taker_fee_bps": 4.0,
                    "funding_8h": 0.0,
                },
                {
                    "venue": "binance_usdm_perp",
                    "bid": live_snap["perp_bid"],
                    "ask": live_snap["perp_ask"],
                    "taker_fee_bps": 4.0,
                    "funding_8h": f_bin,
                },
            ]
            best_funding_8h = f_bin
            provenance = "live_binance"
        else:
            mid = item["spot_mid"]
            quotes = [
                {
                    "venue": "binance_spot_hedge",
                    "bid": round(mid * 0.9998, 4),
                    "ask": round(mid * 1.0002, 4),
                    "taker_fee_bps": 4.0,
                    "funding_8h": 0.0,
                },
                {
                    "venue": "binance_usdm_perp",
                    "bid": round(mid * 1.0006, 4),
                    "ask": round(mid * 1.0010, 4),
                    "taker_fee_bps": 4.0,
                    "funding_8h": item["funding_8h_binance"],
                },
                {
                    "venue": "hyperliquid_perp",
                    "bid": round(mid * 1.0009, 4),
                    "ask": round(mid * 1.0014, 4),
                    "taker_fee_bps": 3.5,
                    "funding_8h": item["funding_8h_hyperliquid"],
                },
            ]
            best_funding_8h = max(item["funding_8h_binance"], item["funding_8h_hyperliquid"])
            provenance = "synthetic_benchmark"

        spot_notional = round(per_asset_capital * 0.5, 2)
        perp_margin = round(per_asset_capital - spot_notional, 2)
        arb = perp_scan(quotes, notional=max(spot_notional, 1_000.0))
        ann_funding_pct = best_funding_8h * 3.0 * 365.0 * 100.0
        best_route = arb["best_route"] or {}
        qty = round(spot_notional / mid, 6) if mid > 0 else 0.0
        daily_carry = round(spot_notional * (ann_funding_pct / 100.0) / 365.0, 2)

        results.append({
            "symbol": item["symbol"],
            "provenance": provenance,
            "strategy": "cash_and_carry_delta_neutral",
            "annualized_funding_pct": round(float(ann_funding_pct), 2),
            "best_8h_funding_bps": round(float(best_funding_8h * 1e4), 3),
            "best_route": best_route,
            "positive_after_fees": arb["positive_after_fees"],
            "action": "long_spot_short_perp" if ann_funding_pct > 10.0 else "standby",
            "order_ticket": {
                "allocated_capital": per_asset_capital,
                "spot_leg": {
                    "venue": best_route.get("buy_venue", "binance_spot_hedge"),
                    "side": "BUY_SPOT",
                    "reference_price": mid,
                    "quantity": qty,
                    "notional": spot_notional,
                },
                "perp_leg": {
                    "venue": best_route.get("sell_venue", "hyperliquid_perp"),
                    "side": "SHORT_PERP_1X",
                    "reference_price": mid,
                    "quantity": qty,
                    "margin_posted_1x": perp_margin,
                },
                "net_delta": 0.0,
                "expected_daily_carry": daily_carry,
                "exit_rule": "Encerrar ambas as pontas se funding anualizado cair < 10% a.a. por 3 janelas de 8h",
            },
        })

    results.sort(key=lambda r: r["annualized_funding_pct"], reverse=True)
    return results


def run_playbook_scan(
    *,
    mode: Literal["synthetic", "live"] = "synthetic",
    regime_demo: Literal["calm", "trending", "crisis"] = "calm",
    capital: float = 100_000.0,
    entry_z: float = 1.8,
    exit_z: float = 0.5,
    seed: int = 42,
) -> dict[str, Any]:
    """Run the 3-pillar quantitative playbook scan and compute regime-adjusted allocations + order tickets."""
    # Step 1: Market Regime Nowcast & Half-Kelly Sizing first so we know exact bucket budgets
    reg_inputs = regime_demo_payload(kind=regime_demo, n=260, seed=7)
    positions_in = [
        {"id": s["id"], "strategy_id": s["id"], "weight": 0.20}
        for s in DEFAULT_PLAYBOOK_STRATEGIES
    ]
    reg_eval = regime_evaluate(
        **reg_inputs,
        strategies=DEFAULT_PLAYBOOK_STRATEGIES,
        positions=positions_in,
    )

    raw_allocs = reg_eval["adjustments"]
    total_target_w = sum(float(a["target_weight"]) for a in raw_allocs)
    norm_scale = 1.0 / max(total_target_w, 1.0)

    capital_plan: list[dict[str, Any]] = []
    bucket_budgets: dict[str, float] = {}
    allocated_sum = 0.0
    for a in raw_allocs:
        sid = str(a["strategy_id"])
        strat_meta = next((s for s in DEFAULT_PLAYBOOK_STRATEGIES if s["id"] == sid), {})
        eff_weight = round(float(a["target_weight"]) * norm_scale, 4)
        notional_alloc = round(capital * eff_weight, 2)
        allocated_sum += notional_alloc
        bucket_budgets[sid] = notional_alloc
        capital_plan.append({
            "strategy_id": sid,
            "strategy_name": strat_meta.get("name", sid),
            "action": a["action"],
            "target_weight_pct": round(eff_weight * 100.0, 2),
            "allocated_capital": notional_alloc,
            "reason": a["reason"],
        })

    cash_reserve = round(max(0.0, capital - allocated_sum), 2)

    # Step 2: Pillar 1 — Pairs & Commodities Cointegration Scan + Order Tickets
    pair_rows: list[dict[str, Any]] = []
    best_sharpe = -999.0
    best_n_obs = 240

    b3_budget = bucket_budgets.get("b3_stat_arb_pairs", 0.0)
    comm_budget = bucket_budgets.get("commodities_coint_spreads", 0.0)

    for idx, cand in enumerate(DEFAULT_PAIR_CANDIDATES):
        y, x, provenance = _fetch_or_synthetic_pair(
            cand["y"], cand["x"], idx=idx, mode=mode, n=240, seed=seed
        )
        eg = engle_granger(y, x)
        bt = pairs_backtest(y, x, entry_z=entry_z, exit_z=exit_z, warmup=50)
        try:
            joh = johansen(np.column_stack([y, x]), k_ar=2)
            joh_rank = joh["rank"]
        except ValueError:
            joh_rank = 0

        res_last = float(y[-1] - (float(eg["alpha"]) + float(eg["beta"]) * x[-1]))
        z_now = round(res_last / max(float(eg["residual_std"]), 1e-8), 4)
        coint = bool(eg["cointegrated"])
        if coint and z_now <= -entry_z:
            signal = f"LONG SPREAD (Comprar {cand['y']} / Vender {cand['x']})"
            actionable = True
        elif coint and z_now >= entry_z:
            signal = f"SHORT SPREAD (Vender {cand['y']} / Comprar {cand['x']})"
            actionable = True
        else:
            signal = "AGUARDAR GATILHO (|z| < entry_z ou sem cointegração)"
            actionable = False

        sr = float(bt["sharpe"])
        if sr > best_sharpe:
            best_sharpe = sr
            best_n_obs = len(y)

        pair_notional = (b3_budget / 2.0) if cand["bucket"] == "b3_equities" else (comm_budget / 2.0)
        ticket = _build_pair_order_ticket(
            y_ticker=cand["y"],
            x_ticker=cand["x"],
            last_y=float(y[-1]),
            last_x=float(x[-1]),
            beta=float(eg["beta"]),
            z_now=z_now,
            entry_z=entry_z,
            exit_z=exit_z,
            half_life_days=eg["half_life_days"],
            cointegrated=coint,
            allocated_notional=pair_notional,
        )

        pair_rows.append({
            "pair": f"{cand['y']} / {cand['x']}",
            "label": cand["label"],
            "bucket": cand["bucket"],
            "provenance": provenance,
            "hedge_ratio_beta": eg["beta"],
            "adf_t_stat": eg["adf_tstat"],
            "cointegrated_5pct": coint,
            "johansen_rank": joh_rank,
            "half_life_days": eg["half_life_days"],
            "current_z": z_now,
            "backtest_sharpe": bt["sharpe"],
            "backtest_return_pct": bt["total_return_pct"],
            "max_drawdown_pct": bt["max_drawdown_pct"],
            "actionable": actionable,
            "signal": signal,
            "order_ticket": ticket,
        })

    pair_rows.sort(
        key=lambda r: (bool(r["actionable"]), bool(r["cointegrated_5pct"]), abs(float(r["current_z"]))),
        reverse=True,
    )

    # Step 3: Pillar 2 — Crypto Cash-and-Carry Funding + Order Tickets
    crypto_budget = bucket_budgets.get("crypto_funding_carry", 0.0)
    crypto_carry = _scan_crypto_carry(allocated_bucket_capital=crypto_budget, seed=seed, mode=mode)

    # Step 4: Multiple-testing audit via Deflated Sharpe Ratio across all scanned candidates
    n_trials = len(DEFAULT_PAIR_CANDIDATES) + len(crypto_carry)
    dsr_audit = deflated_sharpe(
        observed_sharpe=max(best_sharpe, 0.1),
        n_trials=max(n_trials, 2),
        n_obs=max(best_n_obs, 60),
    )

    return {
        "as_of": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "mode": mode,
        "capital": capital,
        "regime_summary": {
            "regime": reg_eval["regime"],
            "probabilities": reg_eval["probs"],
            "kill_switch": reg_eval["kill_switch"],
        },
        "capital_allocation": {
            "strategies": capital_plan,
            "cash_reserve": cash_reserve,
            "cash_reserve_pct": round((cash_reserve / capital) * 100.0, 2) if capital > 0 else 0.0,
        },
        "pillar_1_pairs_and_commodities": pair_rows,
        "pillar_2_crypto_funding_carry": crypto_carry,
        "multiple_testing_audit": dsr_audit,
        "eligible_for_live_trading": False,
        "methodology": (
            "Tripé Quantitativo: (1) Pares B3 & Commodities filtrados por Engle–Granger (ADF p<5%), "
            "Johansen e meia-vida OU com boleta Dollar-Neutral; (2) Cash-and-Carry Delta-Neutro em Cripto Majors "
            "(BTC/ETH/SOL); (3) Dimensionamento Half-Kelly ajustado pelo Regime de Mercado e auditado por Deflated Sharpe Ratio."
        ),
    }

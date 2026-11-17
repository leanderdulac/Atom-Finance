"""ETH/SOL audit + informative features + regime veto. Paper only.

Prices: Binance.US spot klines (public, no key). Funding: OKX SWAP (~3 months)
filled with Hyperliquid fundingHistory (from 2023-05). Open interest: OKX rubik.
Taker flow from Binance.US kline[9] plus OKX contract taker volume.
fapi.binance.com returns 451; Bybit 403.

Spot PnL has no funding. Funding/OI enter only as meta features.
``eligible_for_live_trading`` is always false.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from app.models.afml.gate import gate
from app.models.afml.trials import TrialRegistry
from app.models.mean_reversion import _hurst
from app.models.pairs_meta import FEATURE_COLS, build_event_table, evaluate_pairs_meta
from app.models.pairs_real import (
    CRYPTO_COMMISSION,
    CRYPTO_SLIPPAGE,
    _get_json,
    align_pair,
    default_report_dir,
)
from app.models.regime import classify
from app.models.winners_curse import DEFAULT_PERIODS

FAMILY_ID = "pairs_eth_sol_audit"
INFO_FEATURES = [
    "taker_buy_ratio_y",
    "taker_buy_ratio_x",
    "taker_okx_y",
    "taker_okx_x",
    "funding_y",
    "funding_x",
    "funding_spread",
    "oi_chg5_y",
    "oi_chg5_x",
    "btc_lead_1d",
    "btc_lead_5d",
]
CANDLE_PLUS_INFO = FEATURE_COLS + INFO_FEATURES

_WHAT_BROKE = [
    "O +7% líquido/trade anterior misturava β em ações com retorno percentual (β≈13× r_SOL).",
    "PnL auditado = (Δy − β0 Δx) / (|y|+|β0||x|), hedge congelado na entrada (fill em t+1).",
    "Funding não entra no PnL à vista; é feature (OKX ~3 meses + Hyperliquid desde 2023-05). OI/taker OKX são perpétuos alinhados por data UTC.",
    "Regime usa Hurst/RV/correlação de BTC-ETH-SOL (classificador ATOM) sem VIX/crédito — proxy.",
    "Veto de regime escolhido só no fold de treino. eligible_for_live_trading permanece false.",
]


def default_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pairs_crypto"


def _ms_to_day(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def fetch_binance_us_klines(symbol: str, lookback_days: int = 1800) -> dict[str, Any]:
    """Spot klines with taker-buy volume (aggressor). No key."""
    end_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_ms = end_ms - lookback_days * 86_400_000
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        batch = _get_json(
            "https://api.binance.us/api/v3/klines",
            {"symbol": symbol, "interval": "1d", "startTime": cursor, "limit": 1000},
        )
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1][0]) + 86_400_000
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    dates, close, volume, taker_buy = [], [], [], []
    seen: set[str] = set()
    for row in rows:
        day = _ms_to_day(int(row[0]))
        if day in seen:
            continue
        seen.add(day)
        px = float(row[4])
        vol = float(row[5] or 0)
        tb = float(row[9] or 0) if len(row) > 9 else 0.0
        if px <= 0:
            continue
        dates.append(day)
        close.append(round(px, 6))
        volume.append(vol)
        taker_buy.append(tb)
    return {
        "ticker": symbol.upper(),
        "source": "binance_us_spot_klines",
        "interval": "1d",
        "dates": dates,
        "close": close,
        "volume": volume,
        "taker_buy": taker_buy,
    }


def _okx_pages(
    url: str,
    params: dict[str, Any],
    *,
    page_key: str = "end",
    limit: int = 100,
) -> list[Any]:
    out: list[Any] = []
    cursor = None
    for _ in range(40):
        q = dict(params)
        q["limit"] = str(limit)
        if cursor is not None:
            q[page_key] = str(cursor)
        payload = _get_json(url, q)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            break
        out.extend(rows)
        last = rows[-1]
        ts = last[0] if isinstance(last, list) else (last.get("fundingTime") or last.get("ts"))
        nxt = int(ts) - 1
        if cursor is not None and nxt >= int(cursor):
            break
        cursor = nxt
        if len(rows) < limit:
            break
        time.sleep(0.25)
    return out


def fetch_okx_funding(inst_id: str) -> dict[str, float]:
    rows = _okx_pages(
        "https://www.okx.com/api/v5/public/funding-rate-history",
        {"instId": inst_id},
        page_key="after",
        limit=100,
    )
    by_day: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = row.get("fundingTime")
        rate = row.get("fundingRate") or row.get("realizedRate")
        if ts is None or rate in (None, ""):
            continue
        day = _ms_to_day(int(ts))
        by_day.setdefault(day, []).append(float(rate))
    return {d: float(np.mean(v)) for d, v in by_day.items()}


def fetch_okx_oi(inst_id: str) -> dict[str, float]:
    rows = _okx_pages(
        "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history",
        {"instId": inst_id, "period": "1D"},
        limit=100,
    )
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        out[_ms_to_day(int(row[0]))] = float(row[1])
    return out


def fetch_hl_funding(coin: str) -> dict[str, float]:
    """Hyperliquid fundingHistory (hourly, public POST, no key). Paginated by startTime."""
    start = int(datetime(2021, 12, 1, tzinfo=UTC).timestamp() * 1000)
    now = int(datetime.now(UTC).timestamp() * 1000)
    by_day: dict[str, list[float]] = {}
    cursor = start
    headers = {
        "Accept": "application/json",
        "User-Agent": "ATOM-Finance paper-research/0.1 (unsigned public market data)",
    }
    for _ in range(90):
        payload = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "fundingHistory", "coin": coin, "startTime": int(cursor)},
            headers=headers,
            timeout=25,
        )
        payload.raise_for_status()
        rows = payload.json()
        if not isinstance(rows, list) or not rows:
            break
        last_ts = cursor
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = row.get("time")
            rate = row.get("fundingRate")
            if ts is None or rate in (None, ""):
                continue
            last_ts = max(last_ts, int(ts))
            by_day.setdefault(_ms_to_day(int(ts)), []).append(float(rate))
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        if last_ts >= now - 3_600_000:
            break
        time.sleep(0.15)
    return {d: float(np.mean(v)) for d, v in by_day.items()}


def fetch_okx_taker(ccy: str) -> dict[str, float]:
    payload = _get_json(
        "https://www.okx.com/api/v5/rubik/stat/taker-volume",
        {"ccy": ccy, "instType": "CONTRACTS", "period": "1D"},
    )
    rows = payload.get("data") if isinstance(payload, dict) else None
    out: dict[str, float] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, list) or len(row) < 3:
            continue
        sell, buy = float(row[1]), float(row[2])
        tot = sell + buy
        if tot <= 0:
            continue
        out[_ms_to_day(int(row[0]))] = buy / tot
    return out


def fetch_crypto_panel(fixture_dir: Path) -> dict[str, Any]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    eth = fetch_binance_us_klines("ETHUSDT")
    time.sleep(0.4)
    sol = fetch_binance_us_klines("SOLUSDT")
    time.sleep(0.4)
    btc = fetch_binance_us_klines("BTCUSDT")
    fund_eth = fetch_okx_funding("ETH-USDT-SWAP")
    fund_sol = fetch_okx_funding("SOL-USDT-SWAP")
    hl_eth = fetch_hl_funding("ETH")
    hl_sol = fetch_hl_funding("SOL")
    fund_eth = {**hl_eth, **fund_eth}
    fund_sol = {**hl_sol, **fund_sol}
    oi_eth = fetch_okx_oi("ETH-USDT-SWAP")
    oi_sol = fetch_okx_oi("SOL-USDT-SWAP")
    taker_eth = fetch_okx_taker("ETH")
    taker_sol = fetch_okx_taker("SOL")
    panel = {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "eth": eth,
        "sol": sol,
        "btc": btc,
        "funding_eth": fund_eth,
        "funding_sol": fund_sol,
        "oi_eth": oi_eth,
        "oi_sol": oi_sol,
        "taker_okx_eth": taker_eth,
        "taker_okx_sol": taker_sol,
        "sources": {
            "prices_flow": "Binance.US GET /api/v3/klines (spot, taker buy = kline[9])",
            "funding_oi": (
                "Funding: OKX SWAP history (~3 meses) preenchido com Hyperliquid fundingHistory "
                "(desde 2023-05). OI/taker: OKX rubik CONTRACTS."
            ),
            "blocked": "fapi.binance.com 451; api.bybit.com 403",
        },
        "eligible_for_live_trading": False,
    }
    (fixture_dir / "panel.json").write_text(json.dumps(panel), encoding="utf-8")
    return {"fetched_at": panel["fetched_at"], "n_eth": len(eth["dates"]), "n_sol": len(sol["dates"])}


def load_panel(fixture_dir: Path) -> dict[str, Any]:
    path = fixture_dir / "panel.json"
    if not path.exists():
        raise FileNotFoundError(f"Fixture ausente: {path}. Rode python -m app.models.pairs_crypto --fetch")
    return json.loads(path.read_text(encoding="utf-8"))


def _series(dates: list[str], values: list[float], index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float)
    aligned = s.reindex(index)
    return aligned.to_numpy(dtype=float)


def _map_day(mapping: dict[str, float], index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(mapping, dtype=float)
    s.index = pd.DatetimeIndex(s.index)
    return s.reindex(index).to_numpy(dtype=float)


def aligned_book(panel: dict[str, Any]) -> dict[str, Any]:
    eth, sol, btc = panel["eth"], panel["sol"], panel["btc"]
    y, x, dates = align_pair(
        {"ticker": "ETHUSDT", "dates": eth["dates"], "close": eth["close"]},
        {"ticker": "SOLUSDT", "dates": sol["dates"], "close": sol["close"]},
    )
    idx = pd.DatetimeIndex(dates)
    btc_px = _series(btc["dates"], btc["close"], idx)
    eth_tb = _series(eth["dates"], eth.get("taker_buy") or [0.0] * len(eth["dates"]), idx)
    eth_vol = _series(eth["dates"], eth.get("volume") or [0.0] * len(eth["dates"]), idx)
    sol_tb = _series(sol["dates"], sol.get("taker_buy") or [0.0] * len(sol["dates"]), idx)
    sol_vol = _series(sol["dates"], sol.get("volume") or [0.0] * len(sol["dates"]), idx)
    taker_y = np.divide(eth_tb, np.maximum(eth_vol, 1e-12), out=np.full_like(eth_tb, np.nan), where=eth_vol > 0)
    taker_x = np.divide(sol_tb, np.maximum(sol_vol, 1e-12), out=np.full_like(sol_tb, np.nan), where=sol_vol > 0)
    btc_ret = np.zeros(len(y))
    ok = np.isfinite(btc_px)
    r = np.diff(btc_px) / btc_px[:-1]
    btc_ret[1:] = np.where(ok[1:] & ok[:-1], r, 0.0)
    btc_lead_1d = np.roll(btc_ret, 1)
    btc_lead_1d[:2] = np.nan
    btc_sum5 = np.asarray(pd.Series(btc_ret, dtype=float).rolling(5, min_periods=3).sum(), dtype=float)
    btc_lead_5d = np.concatenate([[np.nan], btc_sum5[:-1]])
    fund_y = _map_day(panel.get("funding_eth") or {}, idx)
    fund_x = _map_day(panel.get("funding_sol") or {}, idx)
    oi_y = _map_day(panel.get("oi_eth") or {}, idx)
    oi_x = _map_day(panel.get("oi_sol") or {}, idx)
    oi_chg_y = pd.Series(oi_y).pct_change(5, fill_method=None).to_numpy()
    oi_chg_x = pd.Series(oi_x).pct_change(5, fill_method=None).to_numpy()
    extras = {
        "taker_buy_ratio_y": taker_y,
        "taker_buy_ratio_x": taker_x,
        "taker_okx_y": _map_day(panel.get("taker_okx_eth") or {}, idx),
        "taker_okx_x": _map_day(panel.get("taker_okx_sol") or {}, idx),
        "funding_y": fund_y,
        "funding_x": fund_x,
        "funding_spread": fund_y - fund_x,
        "oi_chg5_y": oi_chg_y,
        "oi_chg5_x": oi_chg_x,
        "btc_lead_1d": btc_lead_1d,
        "btc_lead_5d": btc_lead_5d,
    }
    return {"y": y, "x": x, "dates": dates, "btc": btc_px, "extras": extras}


def crypto_regime_labels(btc: np.ndarray, eth: np.ndarray, sol: np.ndarray, window: int = 90) -> np.ndarray:
    """ATOM ``classify`` on BTC Hurst, BTC RV percentile, ETH/SOL/BTC corr. No future bars."""
    n = len(btc)
    out = np.array(["mean_reverting"] * n, dtype=object)
    r_b = np.zeros(n)
    r_e = np.zeros(n)
    r_s = np.zeros(n)
    r_b[1:] = np.diff(btc) / np.maximum(btc[:-1], 1e-12)
    r_e[1:] = np.diff(eth) / np.maximum(eth[:-1], 1e-12)
    r_s[1:] = np.diff(sol) / np.maximum(sol[:-1], 1e-12)
    hurst = np.full(n, np.nan)
    rv = np.full(n, np.nan)
    corr = np.full(n, np.nan)
    for t in range(126, n):
        window_p = btc[t - 125 : t + 1]
        if np.any(window_p <= 0) or not np.all(np.isfinite(window_p)):
            continue
        hurst[t] = _hurst(np.log(window_p))
    for t in range(20, n):
        sl = r_b[t - 19 : t + 1]
        sl = sl[np.isfinite(sl)]
        if len(sl) >= 10:
            rv[t] = float(np.std(sl, ddof=1) * np.sqrt(365.0))
    for t in range(20, n):
        panel = np.column_stack([r_b[t - 19 : t + 1], r_e[t - 19 : t + 1], r_s[t - 19 : t + 1]])
        if not np.all(np.isfinite(panel)) or panel.shape[0] < 10:
            continue
        c = np.corrcoef(panel, rowvar=False)
        vals = c[np.triu_indices(3, 1)]
        vals = vals[np.isfinite(vals)]
        if len(vals):
            corr[t] = float(np.mean(vals))

    def _flag(series: np.ndarray, t: int) -> str | None:
        sl = series[max(0, t - window + 1) : t + 1]
        sl = sl[np.isfinite(sl)]
        if len(sl) < 20:
            return None
        last = float(sl[-1])
        pct = 100.0 * float(np.mean(sl <= last))
        if pct >= 90.0:
            return "high"
        if pct <= 10.0:
            return "low"
        return None

    for t in range(window, n):
        flags = {
            "hurst": _flag(hurst, t),
            "rv_iv_spread": _flag(rv, t),
            "cross_asset_corr": _flag(corr, t),
        }
        out[t] = classify(flags, hurst_value=float(hurst[t]) if np.isfinite(hurst[t]) else None)
    return out


def _bucket_stats(mask: np.ndarray, events: pd.DataFrame) -> dict[str, Any]:
    net = events["ret_net"].to_numpy()[mask]
    bins = events["bin"].to_numpy()[mask]
    return {
        "n": int(mask.sum()),
        "hit_rate": None if len(net) == 0 else round(float(np.mean(bins)), 4),
        "net_per_trade": None if len(net) == 0 else round(float(np.mean(net)), 6),
        "total_net": round(float(np.sum(net)), 6) if len(net) else 0.0,
        "max_net": None if len(net) == 0 else round(float(np.max(net)), 6),
    }


def _year_buckets(dates: list[str], events: pd.DataFrame) -> list[dict[str, Any]]:
    if events.empty:
        return []
    years = [dates[int(t)][:4] for t in events["t0"].to_numpy(dtype=int)]
    out = []
    for year in sorted(set(years)):
        m = np.array(years) == year
        row = _bucket_stats(m, events)
        row["year"] = year
        out.append(row)
    return out


def _subperiod_buckets(dates: list[str], events: pd.DataFrame) -> list[dict[str, Any]]:
    """Chronological halves and 2022–2023 vs the rest — sensitivity, not a new grid."""
    if events.empty:
        return []
    t0 = events["t0"].to_numpy(dtype=int)
    mid = len(dates) // 2
    years = np.array([dates[int(t)][:4] for t in t0])
    crisis = np.isin(years, ["2022", "2023"])
    return [
        {"label": "primeira metade da amostra", **_bucket_stats(t0 < mid, events)},
        {"label": "segunda metade da amostra", **_bucket_stats(t0 >= mid, events)},
        {"label": "2022–2023", **_bucket_stats(crisis, events)},
        {"label": "fora de 2022–2023", **_bucket_stats(~crisis, events)},
    ]


def _occupied_event_stats(events: pd.DataFrame) -> dict[str, Any]:
    """First event occupies until t1 — the book that the DSR series actually trades."""
    if events.empty:
        return {"n": 0, "hit_rate": None, "net_per_trade": None, "total_net": 0.0, "max_net": None}
    busy = -1
    keep = np.zeros(len(events), dtype=bool)
    order = np.argsort(events["t0"].to_numpy())
    for i in order:
        t0 = int(events["t0"].iloc[i])
        t1 = int(events["t1"].iloc[i])
        if t0 <= busy:
            continue
        keep[i] = True
        busy = t1
    stats = _bucket_stats(keep, events)
    stats["n_dropped_overlap"] = int((~keep).sum())
    return stats


def _feature_coverage(extras: dict[str, np.ndarray]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, arr in extras.items():
        vec = np.asarray(arr, dtype=float)
        out[name] = round(float(np.mean(np.isfinite(vec))), 4) if len(vec) else 0.0
    return out


def _legacy_beta_times_return(y: np.ndarray, x: np.ndarray, events: pd.DataFrame) -> dict[str, Any]:
    """Reproduce the unit bug: r = r_y − β_shares · r_x, cost as 4×(c+s) of the y-leg."""
    if events.empty:
        return {"n": 0, "net_per_trade": None, "max_net": None}
    old_cost = 4.0 * (0.0010 + 0.0002)
    nets = []
    for i in range(len(events)):
        t0 = int(events["t0"].iloc[i])
        t1 = int(events["t1"].iloc[i])
        side = float(events["side"].iloc[i])
        b0 = float(events["beta"].iloc[i])
        if t1 <= t0 or y[t0] <= 0 or x[t0] <= 0:
            continue
        r_y = y[t1] / y[t0] - 1.0
        r_x = x[t1] / x[t0] - 1.0
        nets.append(side * (r_y - b0 * r_x) - old_cost)
    arr = np.asarray(nets, dtype=float)
    if len(arr) == 0:
        return {"n": 0, "net_per_trade": None, "max_net": None}
    return {
        "n": int(len(arr)),
        "net_per_trade": round(float(np.mean(arr)), 6),
        "total_net": round(float(np.sum(arr)), 6),
        "max_net": round(float(np.max(arr)), 6),
        "note": "r = r_ETH − β_shares · r_SOL; custo 4×(10+2) bps da perna y. Não é retorno de book.",
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.floating | float):
        v = float(obj)
        return None if not np.isfinite(v) else v
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def run_crypto_audit(
    fixture_dir: Path | None = None,
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    fixture_dir = fixture_dir or default_fixture_dir()
    panel = load_panel(fixture_dir)
    book = aligned_book(panel)
    y, x, dates = book["y"], book["x"], book["dates"]
    extras = book["extras"]
    regimes = crypto_regime_labels(book["btc"], y, x)
    registry = TrialRegistry(registry_path) if registry_path else TrialRegistry(":memory:")
    close_reg = registry_path is None
    common: dict[str, Any] = {
        "entry_z": 2.0,
        "commission": CRYPTO_COMMISSION,
        "slippage": CRYPTO_SLIPPAGE,
        "registry": registry,
        "family_id": FAMILY_ID,
        "pair_id": "ETHUSDT_SOLUSDT",
        "periods_per_year": DEFAULT_PERIODS,
        "min_events": 0,
        "min_oos_scored": 0,
        "apply_gate": False,
        "include_bar_returns": True,
    }
    try:
        candles = evaluate_pairs_meta(
            y, x, extra_features=extras, feature_cols=list(FEATURE_COLS),
            register_primary=True, meta_variant="meta_candles", **common,
        )
        info = evaluate_pairs_meta(
            y, x, extra_features=extras, feature_cols=list(CANDLE_PLUS_INFO),
            register_primary=False, meta_variant="meta_info_features", **common,
        )
        veto = evaluate_pairs_meta(
            y, x, extra_features=extras, feature_cols=list(FEATURE_COLS),
            regimes=regimes, regime_veto=True,
            register_primary=False, meta_variant="meta_regime_veto", **common,
        )
        n_trials = registry.count(FAMILY_ID)
        trial_rows = registry.trials(FAMILY_ID)
        trial_sharpes = [t.sharpe for t in trial_rows if t.sharpe is not None]
        try:
            n_eff = registry.effective_n_trials(FAMILY_ID)["n_eff"]
        except ValueError:
            n_eff = None
        use_neff = n_eff is not None and n_eff >= 2

        def _gate(result: dict[str, Any], *, primary: bool = False) -> dict[str, Any]:
            key = "bar_primary" if primary else "bar_filtered"
            rets = result.get(key) or [0.0, 0.0, 0.0]
            return gate(
                costs_included=True,
                returns=rets,
                n_trials=float(n_trials),
                trial_sharpes=None if use_neff else (trial_sharpes if len(trial_sharpes) >= 2 else None),
                n_eff=n_eff if use_neff else None,
                periods_per_year=DEFAULT_PERIODS,
            ).to_dict()

        events, state = build_event_table(
            y, x, commission=CRYPTO_COMMISSION, slippage=CRYPTO_SLIPPAGE, min_events=0,
        )
        audited_primary = candles["primary"]
        audit = {
            "beta_p10_p50_p90": [round(float(v), 4) for v in np.nanpercentile(state["beta"][np.isfinite(state["beta"])], [10, 50, 90])],
            "n_events": int(len(events)),
            "n_overlapping": candles.get("n_overlapping"),
            "pnl_unit": "gross_two_leg_notional",
            "hedge": "expanding_ols_frozen_at_entry",
            "look_ahead": (
                "β_t e z_t usam o print de t (OLS expanding em data[:t+1], residual Gatev). "
                "O fill é t+1, então o retorno de t não entra no PnL. Durante a operação β fica congelado."
            ),
            "funding_in_spot_pnl": False,
            "by_year": _year_buckets(dates, events),
            "by_subperiod": _subperiod_buckets(dates, events),
            "legacy_beta_times_return": _legacy_beta_times_return(y, x, events),
            "audited_net_per_trade": audited_primary.get("net_per_trade"),
            "occupied": _occupied_event_stats(events),
            "feature_coverage": _feature_coverage(extras),
            "old_bug": (
                "ret = r_ETH − β_shares · r_SOL com β≈13–18 (OLS em nível) inflava o PnL "
                "até ±150% em um dia. O número auditado usa (Δy−β0 Δx)/(|y|+|β0||x|)."
            ),
        }
        variants = {
            "primary": candles["primary"],
            "meta_candles": candles["filtered"],
            "meta_info_features": info["filtered"],
            "meta_regime_veto": veto["filtered"],
        }
        gates = {
            "primary": _gate(candles, primary=True),
            "meta_candles": _gate(candles),
            "meta_info_features": _gate(info),
            "meta_regime_veto": _gate(veto),
        }
    finally:
        if close_reg:
            registry.close()

    return {
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": False,
        "start": dates[0],
        "end": dates[-1],
        "n_bars": len(dates),
        "n_trials_registered": int(n_trials),
        "fetched_at": panel.get("fetched_at"),
        "sources": panel.get("sources"),
        "costs": {
            "round_trip_gross": 2.0 * (CRYPTO_COMMISSION + CRYPTO_SLIPPAGE),
            "note": "2×(taker 10 bps + half-spread 2 bps) do nocional bruto. Funding não entra no PnL à vista.",
        },
        "audit": audit,
        "engle_granger_oos": candles["engle_granger_oos"],
        "variants": variants,
        "gates": gates,
        "gate": gates["meta_info_features"],
        "what_broke": list(_WHAT_BROKE),
    }


def _pct(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.1f}%"


def _bps(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.3f}%"


def render_crypto_report_md(result: dict[str, Any]) -> str:
    v = result["variants"]
    g = result["gates"]
    years = result["audit"].get("by_year") or []
    year_rows = "\n".join(
        f"| {r['year']} | {r['n']} | {_pct(r['hit_rate'])} | {_bps(r['net_per_trade'])} | {_bps(r['total_net'])} | {_bps(r['max_net'])} |"
        for r in years
    )
    subs = result["audit"].get("by_subperiod") or []
    sub_rows = "\n".join(
        f"| {r['label']} | {r['n']} | {_pct(r['hit_rate'])} | {_bps(r['net_per_trade'])} | {_bps(r['total_net'])} | {_bps(r['max_net'])} |"
        for r in subs
    )
    cov = result["audit"].get("feature_coverage") or {}
    cov_rows = "\n".join(
        f"| `{name}` | {100 * frac:.1f}% |"
        for name, frac in cov.items()
    ) if cov else "| (sem extras) | n/a |"
    def row(name: str, stats: dict[str, Any], gate: dict[str, Any]) -> str:
        dsr = gate.get("dsr")
        verdict = "passou" if gate.get("approved") else "**não passou**"
        return (
            f"| {name} | {stats.get('n_trades')} | {_pct(stats.get('hit_rate'))} | "
            f"{_bps(stats.get('net_per_trade'))} | {_bps(stats.get('total_net'))} | "
            f"{dsr} | {verdict} |"
        )
    table = "\n".join([
        row("Primário (só candles, auditado)", v["primary"], g["primary"]),
        row("Meta só candles", v["meta_candles"], g["meta_candles"]),
        row("Meta + fluxo/funding/OI/BTC", v["meta_info_features"], g["meta_info_features"]),
        row("Meta candles + veto de regime", v["meta_regime_veto"], g["meta_regime_veto"]),
    ])
    any_pass = any(bool(g[k].get("approved")) for k in g)
    verdict = (
        "Pelo menos uma variante passou no DSR ≥ 0,95 — ainda assim só paper."
        if any_pass
        else "**Nenhuma variante passou no portão** (DSR ≥ 0,95, custos inclusos, N honesto)."
    )
    return f"""# ETH/SOL — auditoria de PnL, features informativas e veto de regime

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

## Parte A — auditoria do +7,2%

O líquido por operação de +7,2% (e picos de ±150% em um dia) **não era retorno de um book**.
O caminho de PnL fazia `r = r_ETH − β r_SOL` com β OLS **em nível** (mediana ≈ 13 ações de SOL
por ETH). Isso multiplica o retorno do SOL por ~13. Recriado no mesmo conjunto de eventos:
legado {_bps(result["audit"].get("legacy_beta_times_return", {}).get("net_per_trade"))} líquido/trade
(máx {_bps(result["audit"].get("legacy_beta_times_return", {}).get("max_net"))}).

Número **auditado** (primário, retorno sobre nocional bruto, β congelado, custo 2×(taxa+spread)):
**{_bps(result["audit"].get("audited_net_per_trade"))}** por operação.

Fórmula: `(ΔETH − β0 ΔSOL) / (|ETH| + |β0| |SOL|)`.

β_t e z_t usam o print de t (OLS expanding); o fill é t+1, então o dia do sinal não entra no PnL.
Durante a operação o hedge **não** é reestimado.

Operações sobrepostas: **{result["audit"].get("n_overlapping")} de {result["audit"].get("n_events")}**
eventos coincidem no calendário. Isso **não** explica o +7,2% — o bug era a unidade (β×retorno).
O DSR usa o livro ocupado (a primeira operação segura a barra até t1; as demais nesse intervalo
são ignoradas). O líquido/trade auditado é a média dos {result["audit"].get("n_events")} caminhos,
incluindo os sobrepostos. Com ocupação exclusiva: n={result["audit"].get("occupied", {}).get("n")},
líq/trade={_bps(result["audit"].get("occupied", {}).get("net_per_trade"))}.

Funding **não se aplica** ao PnL à vista (Binance.US spot). Entra só como feature do meta:
OKX SWAP cobre ~3 meses e o restante vem de Hyperliquid `fundingHistory` (desde 2023-05;
antes disso a feature fica ausente e o RF imputa 0). fapi.binance.com devolveu 451; Bybit 403.
OI: OKX rubik. Taker agressor: `kline[9]` Binance.US na amostra inteira.

Custo ida-e-volta: {result["costs"]["round_trip_gross"]:.4f} do nocional bruto
(2×(taker 10 bps + half-spread 2 bps), as duas pernas). Período: {result["start"]} → {result["end"]}
({result["n_bars"]} barras diárias). Snapshot: `{result.get("fetched_at")}`.

β p10/p50/p90 = {result["audit"].get("beta_p10_p50_p90")}.

### Primário auditado por ano

| Ano | n | Hit | Líq/trade | Total | Máx |
|---|---:|---:|---:|---:|---:|
{year_rows}

### Sensibilidade a subperíodos (mesmo primário auditado)

| Recorte | n | Hit | Líq/trade | Total | Máx |
|---|---:|---:|---:|---:|---:|
{sub_rows}

### Cobertura das features informativas (barras com valor finito)

| Feature | Cobertura |
|---|---:|
{cov_rows}

## Parte B — candles vs features vs veto de regime

N = {result["n_trials_registered"]} tentativas registradas (primário + 3 metas). Nenhuma grade extra.

| Versão | Operações | Hit | Líq/trade | Total | DSR | Portão |
|---|---:|---:|---:|---:|---:|---|
{table}

{verdict}

EG OOS (último 30%): cointegrado={result["engle_granger_oos"].get("cointegrated")}
(ADF={result["engle_granger_oos"].get("adf_tstat")}).

## O que quebrou

{chr(10).join(f"- {w}" for w in result["what_broke"])}

Reprodução: `python -m app.models.pairs_crypto --from-fixtures` a partir de `backend/`.
"""


def write_crypto_report(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "pairs-eth-sol-audit-oos.md"
    json_path = out_dir / "pairs-eth-sol-audit-oos.json"
    md_path.write_text(render_crypto_report_md(result), encoding="utf-8")
    json_path.write_text(json.dumps(_json_safe(result), indent=2, default=str), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ETH/SOL audit + info features + regime veto (paper).")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--from-fixtures", action="store_true")
    p.add_argument("--fixture-dir", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args(argv)
    fixture_dir = args.fixture_dir or default_fixture_dir()
    if args.fetch:
        print(json.dumps(fetch_crypto_panel(fixture_dir), indent=2))
    result = run_crypto_audit(fixture_dir=fixture_dir)
    md, js = write_crypto_report(result, args.out_dir or default_report_dir())
    print(md)
    print(js)
    print(json.dumps(_json_safe({
        "n_trials": result["n_trials_registered"],
        "variants": result["variants"],
        "dsr": {k: v.get("dsr") for k, v in result["gates"].items()},
        "approved": {k: v.get("approved") for k, v in result["gates"].items()},
        "eligible_for_live_trading": False,
    }), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

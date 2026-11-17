"""Real-data pairs: Gatev/Avellaneda primary vs meta-filter, DSR gate.

Pair list is fixed by economic thesis *before* looking at results. Every pair
and both variants (primary, meta) are registered so N is the search that was
actually run — including pairs that fail cointegration out of sample.

Paper / simulation only. ``eligible_for_live_trading`` is always false.
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
from app.models.pairs_meta import evaluate_pairs_meta
from app.models.winners_curse import DEFAULT_PERIODS

FAMILY_ID = "pairs_real_gatev_avellaneda"
OOS_FRAC = 0.3
B3_COMMISSION = 0.0005
B3_SLIPPAGE = 0.0002
# Binance.US spot retail taker ~10 bps; half-spread 2 bps. Two legs, open+close.
CRYPTO_COMMISSION = 0.0010
CRYPTO_SLIPPAGE = 0.0002
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
BINANCE_US_KLINES = "https://api.binance.us/api/v3/klines"
BRAPI_QUOTE = "https://brapi.dev/api/quote/{ticker}"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ATOM-Finance paper-research/0.1 (unsigned public market data)",
}

# Chosen a priori. Do not add/drop names after seeing Sharpe / DSR.
UNIVERSE: tuple[dict[str, Any], ...] = (
    {
        "pair_id": "PETR3_PETR4",
        "y": "PETR3",
        "x": "PETR4",
        "venue": "B3",
        "thesis": "Mesmo emissor (Petrobras ON/PN): dual-class, mesmo fluxo de caixa.",
        "yahoo_y": "PETR3.SA",
        "yahoo_x": "PETR4.SA",
        "commission": B3_COMMISSION,
        "slippage": B3_SLIPPAGE,
    },
    {
        "pair_id": "CMIG3_CMIG4",
        "y": "CMIG3",
        "x": "CMIG4",
        "venue": "B3",
        "thesis": "Mesmo emissor (Cemig ON/PN): dual-class de utilidade elétrica.",
        "yahoo_y": "CMIG3.SA",
        "yahoo_x": "CMIG4.SA",
        "commission": B3_COMMISSION,
        "slippage": B3_SLIPPAGE,
    },
    {
        "pair_id": "ITUB4_BBDC4",
        "y": "ITUB4",
        "x": "BBDC4",
        "venue": "B3",
        "thesis": "Dois maiores bancos privados: mesmo ciclo de crédito e juros.",
        "yahoo_y": "ITUB4.SA",
        "yahoo_x": "BBDC4.SA",
        "commission": B3_COMMISSION,
        "slippage": B3_SLIPPAGE,
    },
    {
        "pair_id": "GGBR4_USIM5",
        "y": "GGBR4",
        "x": "USIM5",
        "venue": "B3",
        "thesis": "Siderurgia: mesmo ciclo de minério, aço e câmbio.",
        "yahoo_y": "GGBR4.SA",
        "yahoo_x": "USIM5.SA",
        "commission": B3_COMMISSION,
        "slippage": B3_SLIPPAGE,
    },
    {
        "pair_id": "VALE3_CSNA3",
        "y": "VALE3",
        "x": "CSNA3",
        "venue": "B3",
        "thesis": "Cadeia de minério/aço (mineradora vs siderúrgica); tese mais fraca, incluída a priori.",
        "yahoo_y": "VALE3.SA",
        "yahoo_x": "CSNA3.SA",
        "commission": B3_COMMISSION,
        "slippage": B3_SLIPPAGE,
    },
    {
        "pair_id": "ETHUSDT_SOLUSDT",
        "y": "ETHUSDT",
        "x": "SOLUSDT",
        "venue": "crypto_spot",
        "thesis": "ETH vs SOL à vista: betas de risco cripto; o paper ETH/SOL do ATOM já usa este par.",
        "commission": CRYPTO_COMMISSION,
        "slippage": CRYPTO_SLIPPAGE,
    },
)

_WHAT_BROKE = [
    "Lista de pares foi fixada por tese econômica; o N inclui os que não cointegraram OOS.",
    "B3: Yahoo Chart (adjclose) porque brapi exige token para tudo salvo PETR4; fapi.binance.com devolveu 451, então ETH/SOL veio de klines públicos Binance.US à vista.",
    "ELET3.SA/ELET6.SA retornam 404 no Yahoo (rebrand); o dual-class de utilidade na lista a priori passou a ser CMIG3/CMIG4, antes de qualquer Sharpe.",
    "Custo = 2×(taxa+spread) do nocional bruto das duas pernas; funding de perpétuo fica de fora (série é spot).",
    "EG OOS usa o último 30% da amostra com β reestimado nesse holdout — não é um teste rolante.",
    "DSR ≥ 0,95 autoriza só considerar paper. eligible_for_live_trading permanece false.",
]


def default_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pairs_real"


def default_report_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "reports"


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _get_json(url: str, params: dict[str, Any] | None = None, retries: int = 4) -> Any:
    last: Exception | None = None
    delay = 1.5
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, headers=_HEADERS, timeout=25)
            if r.status_code in {429, 503, 502}:
                time.sleep(delay)
                delay *= 2
                last = RuntimeError(f"{url} HTTP {r.status_code}")
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"GET {url} failed: {last}")


def fetch_yahoo_daily(symbol: str, range_spec: str = "5y") -> dict[str, Any]:
    payload = _get_json(YAHOO_CHART.format(symbol=symbol), {"range": range_spec, "interval": "1d"})
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"Yahoo chart vazio para {symbol}")
    block = result[0]
    ts = block.get("timestamp") or []
    quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((block.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    raw_close = quote.get("close") or []
    closes = adj if adj else raw_close
    dates: list[str] = []
    values: list[float] = []
    for t, px in zip(ts, closes, strict=False):
        if t is None or px is None:
            continue
        try:
            v = float(px)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(v) or v <= 0:
            continue
        dates.append(datetime.fromtimestamp(int(t), tz=UTC).strftime("%Y-%m-%d"))
        values.append(round(v, 6))
    if len(dates) < 120:
        raise ValueError(f"Yahoo {symbol}: só {len(dates)} barras")
    meta = block.get("meta") or {}
    return {
        "ticker": symbol.replace(".SA", ""),
        "yahoo_symbol": symbol,
        "source": "yahoo_chart",
        "source_url": YAHOO_CHART.format(symbol=symbol),
        "interval": "1d",
        "field": "adjclose" if adj else "close",
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName"),
        "dates": dates,
        "close": values,
    }


def fetch_brapi_daily(ticker: str, range_spec: str = "5y") -> dict[str, Any] | None:
    """Public brapi history. PETR4 works without token; others typically 401."""
    try:
        payload = _get_json(
            BRAPI_QUOTE.format(ticker=ticker),
            {"range": range_spec, "interval": "1d"},
        )
    except RuntimeError:
        return None
    results = payload.get("results") or []
    if not results:
        return None
    hist = results[0].get("historicalDataPrice") or []
    dates: list[str] = []
    closes: list[float] = []
    for bar in sorted(hist, key=lambda b: b.get("date") or 0):
        epoch = bar.get("date")
        close = bar.get("close")
        if not epoch or close is None:
            continue
        try:
            px = float(close)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        dates.append(datetime.fromtimestamp(int(epoch), tz=UTC).strftime("%Y-%m-%d"))
        closes.append(round(px, 6))
    if len(dates) < 120:
        return None
    return {
        "ticker": ticker.upper(),
        "source": "brapi",
        "source_url": "https://brapi.dev/api/quote/" + ticker,
        "interval": "1d",
        "field": "close",
        "currency": results[0].get("currency", "BRL"),
        "dates": dates,
        "close": closes,
    }


def fetch_binance_us_daily(symbol: str, lookback_days: int = 1800) -> dict[str, Any]:
    """Public Binance.US spot klines (no key). fapi.binance.com is geo-blocked here."""
    end_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_ms = end_ms - lookback_days * 86_400_000
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        batch = _get_json(
            BINANCE_US_KLINES,
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
        time.sleep(0.35)
    dates: list[str] = []
    closes: list[float] = []
    seen: set[str] = set()
    for row in rows:
        ts_ms = int(row[0])
        px = float(row[4])
        if px <= 0:
            continue
        day = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")
        if day in seen:
            continue
        seen.add(day)
        dates.append(day)
        closes.append(round(px, 6))
    if len(dates) < 120:
        raise ValueError(f"Binance.US {symbol}: só {len(dates)} barras")
    return {
        "ticker": symbol.upper(),
        "source": "binance_us_spot_klines",
        "source_url": BINANCE_US_KLINES,
        "interval": "1d",
        "field": "close",
        "currency": "USDT",
        "dates": dates,
        "close": closes,
        "note": (
            "Klines públicos à vista em api.binance.us. "
            "GET fapi.binance.com/fapi/v1/markPriceKlines devolveu HTTP 451 (geo-block)."
        ),
    }


def series_to_frame(blob: dict[str, Any]) -> pd.Series:
    return pd.Series(blob["close"], index=pd.DatetimeIndex(blob["dates"]), dtype=float, name=blob["ticker"])


def align_pair(y_blob: dict[str, Any], x_blob: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    y = series_to_frame(y_blob)
    x = series_to_frame(x_blob)
    joined = pd.concat([y, x], axis=1, join="inner").dropna()
    joined = joined[(joined.iloc[:, 0] > 0) & (joined.iloc[:, 1] > 0)]
    if len(joined) < 120:
        raise ValueError(f"Alinhamento {y.name}/{x.name}: só {len(joined)} barras comuns")
    dates = [str(pd.Timestamp(d).date()) for d in joined.index]
    return joined.iloc[:, 0].to_numpy(dtype=float), joined.iloc[:, 1].to_numpy(dtype=float), dates


def fetch_universe(fixture_dir: Path, pause_s: float = 1.1) -> dict[str, Any]:
    """Download every ticker in UNIVERSE and write versioned fixtures. No scoring."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = _utcnow()
    tickers: dict[str, dict[str, Any]] = {}

    b3_names: list[str] = []
    for spec in UNIVERSE:
        if spec["venue"] == "B3":
            b3_names.extend([spec["y"], spec["x"]])
    for raw in dict.fromkeys(b3_names):
        yahoo = f"{raw}.SA"
        blob = fetch_yahoo_daily(yahoo)
        blob["fetched_at"] = fetched_at
        brapi = fetch_brapi_daily(raw) if raw == "PETR4" else None
        if brapi:
            blob["brapi_available"] = True
            blob["brapi_n"] = len(brapi["close"])
        else:
            blob["brapi_available"] = False
        tickers[raw] = blob
        (fixture_dir / f"{raw}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")
        time.sleep(pause_s)

    for coin in ("ETHUSDT", "SOLUSDT"):
        blob = fetch_binance_us_daily(coin)
        blob["fetched_at"] = fetched_at
        tickers[coin] = blob
        (fixture_dir / f"{coin}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")
        time.sleep(pause_s)

    manifest = {
        "fetched_at": fetched_at,
        "family_id": FAMILY_ID,
        "interval": "1d",
        "universe": [
            {
                "pair_id": s["pair_id"],
                "y": s["y"],
                "x": s["x"],
                "venue": s["venue"],
                "thesis": s["thesis"],
            }
            for s in UNIVERSE
        ],
        "tickers": {k: {"n": len(v["close"]), "start": v["dates"][0], "end": v["dates"][-1], "source": v["source"]} for k, v in tickers.items()},
        "license_note": (
            "Snapshots EOD para reproduzir o relatório. Yahoo Chart e Binance.US klines são "
            "endpoints públicos sem chave. brapi PETR4 público; demais tickers B3 sem token 401."
        ),
        "eligible_for_live_trading": False,
    }
    (fixture_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_ticker(fixture_dir: Path, ticker: str) -> dict[str, Any]:
    path = fixture_dir / f"{ticker}.json"
    if not path.exists():
        raise FileNotFoundError(f"Fixture ausente: {path}. Rode python -m app.models.pairs_real --fetch")
    return json.loads(path.read_text(encoding="utf-8"))


def _calendar_mean(series: list[tuple[list[str], np.ndarray]]) -> tuple[list[str], np.ndarray]:
    frames = []
    for dates, rets in series:
        frames.append(pd.Series(rets, index=pd.DatetimeIndex(dates), dtype=float))
    if not frames:
        return [], np.array([])
    panel = pd.concat(frames, axis=1)
    mean_s = pd.Series(panel.mean(axis=1, skipna=True), dtype=float).fillna(0.0)
    return [str(pd.Timestamp(d).date()) for d in mean_s.index], mean_s.to_numpy(dtype=float)


def run_real_universe(
    fixture_dir: Path | None = None,
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    fixture_dir = fixture_dir or default_fixture_dir()
    manifest_path = fixture_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    close_reg = False
    registry = TrialRegistry(registry_path) if registry_path else TrialRegistry(":memory:")
    if registry_path is None:
        close_reg = True

    pair_rows: list[dict[str, Any]] = []
    b3_meta_series: list[tuple[list[str], np.ndarray]] = []
    b3_primary_series: list[tuple[list[str], np.ndarray]] = []
    crypto_meta: np.ndarray | None = None
    crypto_dates: list[str] = []

    try:
        for spec in UNIVERSE:
            y_blob = load_ticker(fixture_dir, spec["y"])
            x_blob = load_ticker(fixture_dir, spec["x"])
            y, x, dates = align_pair(y_blob, x_blob)
            result = evaluate_pairs_meta(
                y,
                x,
                entry_z=2.0,
                commission=float(spec["commission"]),
                slippage=float(spec["slippage"]),
                registry=registry,
                family_id=FAMILY_ID,
                pair_id=spec["pair_id"],
                periods_per_year=DEFAULT_PERIODS,
                min_events=0,
                min_oos_scored=0,
                apply_gate=False,
                oos_frac=OOS_FRAC,
                include_bar_returns=True,
            )
            bar_p = np.asarray(result.get("bar_primary") or np.zeros(len(dates)), dtype=float)
            bar_f = np.asarray(result.get("bar_filtered") or np.zeros(len(dates)), dtype=float)
            if spec["venue"] == "B3":
                b3_primary_series.append((dates, bar_p))
                b3_meta_series.append((dates, bar_f))
            else:
                crypto_dates = dates
                crypto_meta = bar_f
            pair_rows.append({
                "pair_id": spec["pair_id"],
                "y": spec["y"],
                "x": spec["x"],
                "venue": spec["venue"],
                "thesis": spec["thesis"],
                "source_y": y_blob.get("source"),
                "source_x": x_blob.get("source"),
                "field_y": y_blob.get("field"),
                "field_x": x_blob.get("field"),
                "start": dates[0],
                "end": dates[-1],
                "n_bars": len(dates),
                "round_trip_cost": result["round_trip_cost"],
                "engle_granger": result["engle_granger"],
                "engle_granger_oos": result["engle_granger_oos"],
                "johansen_rank": result["johansen_rank"],
                "cointegrated_oos": bool(result["engle_granger_oos"].get("cointegrated")),
                "n_events": result["n_events"],
                "n_oos_scored": result["n_oos_scored"],
                "skipped_meta": result["skipped_meta"],
                "skip_reason": result["skip_reason"],
                "primary": result["primary"],
                "filtered": result["filtered"],
                "filter_improves_hit_or_net": result["filter_improves_hit_or_net"],
                "hit_rate_delta": result["hit_rate_delta"],
                "net_per_trade_delta": result["net_per_trade_delta"],
            })

        n_trials = registry.count(FAMILY_ID)
        trial_rows = registry.trials(FAMILY_ID)
        trial_sharpes = [t.sharpe for t in trial_rows if t.sharpe is not None]
        try:
            n_eff = registry.effective_n_trials(FAMILY_ID)["n_eff"]
        except ValueError:
            n_eff = None
        use_neff = n_eff is not None and n_eff >= 2

        b3_dates, b3_meta = _calendar_mean(b3_meta_series)
        _, b3_primary = _calendar_mean(b3_primary_series)

        def _gate_series(returns: np.ndarray | None) -> dict[str, Any]:
            if returns is None or len(returns) < 3:
                return gate(costs_included=True, returns=[0.0, 0.0, 0.0], n_trials=float(n_trials)).to_dict()
            return gate(
                costs_included=True,
                returns=returns.tolist(),
                n_trials=float(n_trials),
                trial_sharpes=None if use_neff else (trial_sharpes if len(trial_sharpes) >= 2 else None),
                n_eff=n_eff if use_neff else None,
                periods_per_year=DEFAULT_PERIODS,
            ).to_dict()

        gate_b3 = _gate_series(b3_meta)
        gate_crypto = _gate_series(crypto_meta)
        # Pre-committed book: equal-weight B3 meta + ETH/SOL meta, aligned by calendar day.
        combined_series: list[tuple[list[str], np.ndarray]] = list(b3_meta_series)
        if crypto_meta is not None and crypto_dates:
            combined_series.append((crypto_dates, crypto_meta))
        comb_dates, comb_meta = _calendar_mean(combined_series)
        gate_combined = _gate_series(comb_meta)

        registered = [
            {
                "id": t.id,
                "pair_id": (t.params or {}).get("pair_id") if isinstance(t.params, dict) else None,
                "variant": (t.params or {}).get("variant") if isinstance(t.params, dict) else None,
                "sharpe": t.sharpe,
                "n_obs": t.n_obs,
                "costs_included": t.costs_included,
            }
            for t in trial_rows
        ]
    finally:
        if close_reg:
            registry.close()

    n_pairs = len(UNIVERSE)
    expected_n = n_pairs * 2
    return {
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": False,
        "out_of_sample": True,
        "fetched_at": manifest.get("fetched_at"),
        "interval": "1d",
        "oos_frac": OOS_FRAC,
        "n_pairs_tested": n_pairs,
        "n_trials_registered": int(n_trials),
        "n_trials_expected": expected_n,
        "selection": (
            "Pares escolhidos por tese econômica antes de olhar resultado. "
            "Nenhuma variante extra (z, limiar, horizonte) foi gradeada."
        ),
        "sources": {
            "B3": "Yahoo Finance Chart v8, intervalo 1d, campo adjclose, range 5y. brapi tentado; só PETR4 responde sem token.",
            "crypto": "Binance.US GET /api/v3/klines ETHUSDT e SOLUSDT, 1d, close. Sem chave. USDM mark klines (fapi.binance.com) geo-bloqueado (HTTP 451).",
        },
        "costs": {
            "B3_round_trip": 2.0 * (B3_COMMISSION + B3_SLIPPAGE),
            "crypto_round_trip": round(2.0 * (CRYPTO_COMMISSION + CRYPTO_SLIPPAGE), 6),
            "B3_note": "2×(comissao 5 bps + slippage 2 bps) do nocional bruto das duas pernas (open+close).",
            "crypto_note": "2×(taker 10 bps + half-spread 2 bps) do nocional bruto. Funding não entra (spot).",
        },
        "pairs": pair_rows,
        "registered_trials": registered,
        "books": {
            "b3_equal_weight_meta": {
                "start": b3_dates[0] if b3_dates else None,
                "end": b3_dates[-1] if b3_dates else None,
                "n_bars": len(b3_dates),
                "total_net": None if b3_meta is None else round(float(np.sum(b3_meta)), 8),
            },
            "eth_sol_meta": {
                "start": crypto_dates[0] if crypto_dates else None,
                "end": crypto_dates[-1] if crypto_dates else None,
                "n_bars": len(crypto_dates),
                "total_net": None if crypto_meta is None else round(float(np.sum(crypto_meta)), 8),
            },
            "combined_equal_weight_meta": {
                "start": comb_dates[0] if comb_dates else None,
                "end": comb_dates[-1] if comb_dates else None,
                "n_bars": len(comb_dates),
                "total_net": round(float(np.sum(comb_meta)), 8) if len(comb_meta) else 0.0,
            },
        },
        "gate_b3_meta": gate_b3,
        "gate_eth_sol_meta": gate_crypto,
        "gate": gate_combined,
        "primary_b3_total_net": round(float(np.sum(b3_primary)), 8) if len(b3_primary) else 0.0,
        "what_broke": list(_WHAT_BROKE),
        "math": (
            "Mesma receita do relatório sintético: z expanding Gatev/EG, barreiras triplas "
            "líquidas de custo, RF OOF com PurgedKFold+embargo, DSR Bailey & López de Prado "
            "com N = todas as (par × variante) registradas. O livro combinado é a média "
            "calendário dos pares pré-escolhidos — não um campeão cherry-picked."
        ),
    }


def _pct(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.1f}%"


def _bps(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"{100 * x:.3f}%"


def _fmt(x: Any) -> str:
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not np.isfinite(v):
        return "n/a"
    return f"{v:.4f}"


def render_real_report_md(result: dict[str, Any]) -> str:
    g = result["gate"]
    approved = bool(g.get("approved"))
    dsr = g.get("dsr")
    n = result["n_trials_registered"]
    if approved and dsr is not None:
        gate_line = (
            f"DSR = {dsr:.4f} — **passou** no portão (≥ 0,95) com N={n} tentativas "
            "realmente registradas (todo par × primário e meta). Isso só autoriza considerar "
            "paper. N ainda é a busca desta receita, não um universo de mil grades."
        )
    elif dsr is not None:
        gate_line = (
            f"DSR = {dsr:.4f} — **não passou** no portão (limiar 0,95, N={n}). "
            "A amostra real, com o N honesto, não autoriza promover o livro."
        )
    else:
        gate_line = "DSR indisponível — o portão recusou."
    reasons = g.get("reasons") or []
    reasons_md = "\n".join(f"- {r}" for r in reasons) or "- (nenhum)"

    rows = []
    for p in result["pairs"]:
        prim, fil = p["primary"], p["filtered"]
        coint = "sim" if p["cointegrated_oos"] else "**não**"
        note = p.get("skip_reason") or ""
        rows.append(
            f"| `{p['pair_id']}` | {p['start']} → {p['end']} | {p['n_bars']} | {p['n_events']} | {coint} | "
            f"{prim['n_trades']} | {_pct(prim['hit_rate'])} | {_bps(prim['net_per_trade'])} | {_bps(prim['total_net'])} | "
            f"{fil['n_trades']} | {_pct(fil['hit_rate'])} | {_bps(fil['net_per_trade'])} | {_bps(fil['total_net'])} | {note} |"
        )
    thesis_md = "\n".join(f"- `{p['pair_id']}` ({p['venue']}): {p['thesis']}" for p in result["pairs"])
    fail_coint = [p["pair_id"] for p in result["pairs"] if not p["cointegrated_oos"]]
    coint_line = (
        "Todos os pares cointegraram no holdout de 30%."
        if not fail_coint
        else "Não cointegraram fora da amostra (EG no último 30%): " + ", ".join(f"`{x}`" for x in fail_coint) + "."
    )
    sources = result["sources"]
    gb, gc = result["gate_b3_meta"], result["gate_eth_sol_meta"]
    return f"""# Pares reais — barreiras triplas, meta-rótulo e portão DSR

Pesquisa apenas. `eligible_for_live_trading` é **false**. Nada envia ordem a corretora.

Receita idêntica ao relatório sintético: primário Gatev / Avellaneda–Lee (z expanding),
rótulo de três barreiras líquido de taxa+spread, meta-rótulo com PurgedKFold + embargo.
A diferença é a amostra: preços reais, pares escolhidos **antes** de olhar resultado,
e N = todas as variantes de todos os pares (não só os que "deram certo").

## Universo (tese econômica, a priori)

{thesis_md}

Nenhuma grade de `entry_z`, limiar ou horizonte. Dois ensaios por par: primário e meta-filtro.

## Período e fonte

- Intervalo: diário (`1d`). Holdout de cointegração: último {int(100 * result["oos_frac"])}% da amostra de cada par.
- B3: {sources["B3"]}
- Cripto: {sources["crypto"]}
- Snapshot gravado em: `{result.get("fetched_at") or "fixtures/pairs_real"}`
- Custo B3 ida-e-volta (duas pernas): {result["costs"]["B3_round_trip"]:.4f}. {result["costs"]["B3_note"]}
- Custo ETH/SOL ida-e-volta: {result["costs"]["crypto_round_trip"]:.4f}. {result["costs"]["crypto_note"]}

## Tabela por par (fora da amostra, previsões OOF)

| Par | Período | Barras | Eventos | EG OOS | Prim. n | Prim. hit | Prim. liq/trade | Prim. total | Meta n | Meta hit | Meta liq/trade | Meta total | Nota |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

{coint_line}

Onde a nota diz que não houve previsão OOF, o primário conta **todos** os eventos rotulados (não é holdout); o meta ficou de fora. Pares sem cointegração OOS **entram no N** — não foram descartados.

Tentativas registradas: {result["n_trials_registered"]} (esperado {result["n_trials_expected"]} = {result["n_pairs_tested"]} pares × 2 variantes).

## Portão de Sharpe deflacionado (livro combinado)

Livro pré-comprometido: média igual por calendário dos meta-filtros de **todos** os pares da lista
(incluindo os que não cointegraram). Não é o campeão da tabela.

{gate_line}

- Sharpe observado (série diária combinada, líquida de custo): {g.get("observed_sharpe")}
- SR\\* (esperado da busca): {g.get("sr_star")}
- PSR: {g.get("psr")}
- DSR: {g.get("dsr")}
- MinTRL: {g.get("min_trl")}
- T (barras): {g.get("n_obs")}
- N: {g.get("n_trials")}
- N efetivo: {_fmt(g.get("n_eff"))}
- Assimetria: {g.get("skew")}
- Curtose excedente: {g.get("excess_kurtosis")}
- Custos declarados: {g.get("costs_included")}

Motivos do portão:

{reasons_md}

DSR do livro B3 (meta, equal-weight): {gb.get("dsr")} (aprovado={gb.get("approved")}).
DSR ETH/SOL (meta, mesmo N da família): {gc.get("dsr")} (aprovado={gc.get("approved")}).

Aprovação do portão **não** autoriza capital ao vivo.

## O que quebrou

{chr(10).join(f"- {w}" for w in result["what_broke"])}

Reprodução: `python -m app.models.pairs_real --from-fixtures` a partir de `backend/`.
`--fetch` só para renovar o snapshot (respeita 429).
"""


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


def write_real_report(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slim = dict(result)
    md_path = out_dir / "pairs-meta-label-oos-real.md"
    json_path = out_dir / "pairs-meta-label-oos-real.json"
    md_path.write_text(render_real_report_md(slim), encoding="utf-8")
    json_path.write_text(json.dumps(_json_safe(slim), indent=2, default=str), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pares reais + meta-rótulo + portão DSR (paper only).")
    p.add_argument("--fetch", action="store_true", help="Baixa Yahoo/brapi/Binance.US e grava fixtures.")
    p.add_argument("--from-fixtures", action="store_true", help="Avalia o snapshot versionado (padrão).")
    p.add_argument("--fixture-dir", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args(argv)
    fixture_dir = args.fixture_dir or default_fixture_dir()
    if args.fetch:
        print(json.dumps(fetch_universe(fixture_dir), indent=2))
    result = run_real_universe(fixture_dir=fixture_dir)
    out_dir = args.out_dir or default_report_dir()
    md_path, json_path = write_real_report(result, out_dir)
    print(md_path)
    print(json_path)
    print(json.dumps({
        "n_trials_registered": result["n_trials_registered"],
        "pairs": [
            {
                "pair_id": p["pair_id"],
                "cointegrated_oos": p["cointegrated_oos"],
                "primary": p["primary"],
                "filtered": p["filtered"],
            }
            for p in result["pairs"]
        ],
        "gate_approved": result["gate"]["approved"],
        "dsr": result["gate"]["dsr"],
        "n": result["gate"]["n_trials"],
        "eligible_for_live_trading": result["eligible_for_live_trading"],
    }, indent=2))
    return 0 if result.get("eligible_for_live_trading") is False else 2


if __name__ == "__main__":
    raise SystemExit(main())

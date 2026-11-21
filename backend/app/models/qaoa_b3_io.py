"""Parquet and JSON exchange for the QAOA B3 phase-1 contract.

The selection panel is one file per rebalance date. The holdout panel is a
separate file and is not an input to a solver. ``eligible_for_live_trading``
stays false.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.models.equal_weight_io import (
    Listing,
    listings_from_tapes,
    load_cash_events,
    load_listings,
    load_strategy_tapes,
    share_events_from_companies,
)
from app.models.net_net_io import load_bundle, session_calendar
from app.models.qaoa_b3 import (
    AUM_LOOSE,
    ELIGIBLE_FOR_LIVE_TRADING,
    EMBARGO_SESSIONS,
    FAMILY_ID,
    HOLDING_SESSIONS,
    HOLDOUT_SCHEMA_VERSION,
    K_MAX,
    K_MIN,
    LAMBDA_GRID,
    MU_MIN_OBS,
    MU_WINDOW,
    SCHEMA_VERSION,
    SELECTION_AUM,
    SELECTION_SCHEMA_VERSION,
    UNIVERSE_RULE,
    NameView,
    Selection,
    Snapshot,
    canonical_payload,
    definitions,
    payload_hash,
    selection_from_mapping,
)

SNAPSHOT_SCHEMA = pa.schema(
    [
        ("schema_version", pa.string()),
        ("family_id", pa.string()),
        ("rebalance_date", pa.string()),
        ("as_of", pa.string()),
        ("estimation_end", pa.string()),
        ("session_date", pa.string()),
        ("ticker", pa.string()),
        ("cnpj", pa.string()),
        ("adv_brl", pa.float64()),
        ("adv_shares", pa.float64()),
        ("mcap", pa.float64()),
        ("close", pa.float64()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("adj_return", pa.float64()),
        ("in_estimation", pa.bool_()),
        ("in_mu_window", pa.bool_()),
        ("n_history", pa.int32()),
        ("n_estimation", pa.int32()),
        ("estimable", pa.bool_()),
        ("mu", pa.float64()),
        ("sigma_index", pa.int32()),
        ("spread_source", pa.string()),
        ("cost_entry_bps_aum_100k", pa.float64()),
        ("cost_exit_bps_aum_100k", pa.float64()),
        ("cost_roundtrip_bps_aum_100k", pa.float64()),
        ("cost_notional_aum_100k", pa.float64()),
        ("cost_capped_aum_100k", pa.bool_()),
        ("cost_entry_bps_aum_1m", pa.float64()),
        ("cost_exit_bps_aum_1m", pa.float64()),
        ("cost_roundtrip_bps_aum_1m", pa.float64()),
        ("cost_notional_aum_1m", pa.float64()),
        ("cost_capped_aum_1m", pa.bool_()),
        ("k_min", pa.int32()),
        ("k_max", pa.int32()),
        ("lambda_grid", pa.string()),
        ("embargo_sessions", pa.int32()),
        ("mu_window_sessions", pa.int32()),
        ("mu_min_obs", pa.int32()),
        ("holding_sessions", pa.int32()),
        ("universe_rule", pa.string()),
        ("snapshot_hash", pa.string()),
        ("eligible_for_live_trading", pa.bool_()),
    ]
)

HOLDOUT_SCHEMA = pa.schema(
    [
        ("schema_version", pa.string()),
        ("family_id", pa.string()),
        ("rebalance_date", pa.string()),
        ("next_rebalance_date", pa.string()),
        ("session_date", pa.string()),
        ("ticker", pa.string()),
        ("adj_return", pa.float64()),
        ("selection_snapshot_hash", pa.string()),
        ("holdout_hash", pa.string()),
        ("purpose", pa.string()),
        ("eligible_for_live_trading", pa.bool_()),
    ]
)

SELECTION_SCHEMA = pa.schema(
    [
        ("schema_version", pa.string()),
        ("rebalance_date", pa.string()),
        ("solver", pa.string()),
        ("K", pa.int32()),
        ("lambda", pa.float64()),
        ("p", pa.int32()),
        ("tickers", pa.list_(pa.string())),
        ("seed", pa.int32()),
        ("n_trials_total", pa.int32()),
        ("eligible_for_live_trading", pa.bool_()),
    ]
)

PURPOSE_HOLDOUT = "not_for_selection"


def _lambda_text() -> str:
    parts = []
    for value in LAMBDA_GRID:
        number = float(value)
        parts.append(str(int(number)) if number.is_integer() else str(number))
    return ",".join(parts)


def _name_rows(snap: Snapshot, name: NameView) -> list[dict[str, Any]]:
    shared = _shared(snap, name)
    if not name.returns:
        shared["session_date"] = snap.rebalance.isoformat()
        shared["adj_return"] = None
        shared["in_estimation"] = False
        shared["in_mu_window"] = False
        return [shared]
    rows = []
    for point in name.returns:
        row = dict(shared)
        row["session_date"] = date.fromordinal(point.ordinal).isoformat()
        row["adj_return"] = point.value
        row["in_estimation"] = point.in_estimation
        row["in_mu_window"] = point.in_mu_window
        rows.append(row)
    return rows


def _shared(snap: Snapshot, name: NameView | None) -> dict[str, Any]:
    cost_100 = None if name is None else name.costs["aum_100k"]
    cost_1m = None if name is None else name.costs["aum_1m"]
    return {
        "schema_version": SCHEMA_VERSION,
        "family_id": FAMILY_ID,
        "rebalance_date": snap.rebalance.isoformat(),
        "as_of": snap.rebalance.isoformat(),
        "estimation_end": snap.estimation_end.isoformat(),
        "session_date": snap.rebalance.isoformat(),
        "ticker": "" if name is None else name.ticker,
        "cnpj": "" if name is None else name.cnpj,
        "adv_brl": None if name is None else name.adv_brl,
        "adv_shares": None if name is None else name.adv_shares,
        "mcap": None if name is None else name.mcap,
        "close": None if name is None else name.close,
        "bid": None if name is None else name.bid,
        "ask": None if name is None else name.ask,
        "adj_return": None,
        "in_estimation": False,
        "in_mu_window": False,
        "n_history": 0 if name is None else name.n_history,
        "n_estimation": 0 if name is None else name.n_estimation,
        "estimable": False if name is None else name.estimable,
        "mu": None if name is None else name.mu,
        "sigma_index": -1 if name is None else name.sigma_index,
        "spread_source": "" if name is None else name.spread_source,
        "cost_entry_bps_aum_100k": None if cost_100 is None else cost_100["entry_bps"],
        "cost_exit_bps_aum_100k": None if cost_100 is None else cost_100["exit_bps"],
        "cost_roundtrip_bps_aum_100k": None if cost_100 is None else cost_100["roundtrip_bps"],
        "cost_notional_aum_100k": None if cost_100 is None else cost_100["notional"],
        "cost_capped_aum_100k": False if cost_100 is None else bool(cost_100["capped"]),
        "cost_entry_bps_aum_1m": None if cost_1m is None else cost_1m["entry_bps"],
        "cost_exit_bps_aum_1m": None if cost_1m is None else cost_1m["exit_bps"],
        "cost_roundtrip_bps_aum_1m": None if cost_1m is None else cost_1m["roundtrip_bps"],
        "cost_notional_aum_1m": None if cost_1m is None else cost_1m["notional"],
        "cost_capped_aum_1m": False if cost_1m is None else bool(cost_1m["capped"]),
        "k_min": K_MIN,
        "k_max": K_MAX,
        "lambda_grid": _lambda_text(),
        "embargo_sessions": EMBARGO_SESSIONS,
        "mu_window_sessions": MU_WINDOW,
        "mu_min_obs": MU_MIN_OBS,
        "holding_sessions": HOLDING_SESSIONS,
        "universe_rule": UNIVERSE_RULE,
        "snapshot_hash": snap.snapshot_hash,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
    }


def snapshot_rows(snap: Snapshot) -> list[dict[str, Any]]:
    if not snap.names:
        return [_shared(snap, None)]
    rows: list[dict[str, Any]] = []
    for name in snap.names:
        rows.extend(_name_rows(snap, name))
    return rows


def write_snapshot(directory: Path, snap: Snapshot) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = snap.rebalance.isoformat()
    frame = pa.Table.from_pylist(snapshot_rows(snap), schema=SNAPSHOT_SCHEMA)
    path = directory / f"{stem}.parquet"
    pq.write_table(frame, path, compression="snappy")
    body = {
        "snapshot_hash": snap.snapshot_hash,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "definitions": definitions(),
        "payload": canonical_payload(snap),
    }
    if payload_hash(body["payload"]) != snap.snapshot_hash:
        raise ValueError("snapshot hash does not match the payload")
    (directory / f"{stem}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def holdout_hash(rebalance: date, nxt: date | None, rows: list[tuple[str, str, float]], selection_hash: str) -> str:
    payload = {
        "family_id": FAMILY_ID,
        "next_rebalance_date": None if nxt is None else nxt.isoformat(),
        "purpose": PURPOSE_HOLDOUT,
        "rebalance_date": rebalance.isoformat(),
        "rows": [{"r": value, "session_date": day, "ticker": ticker} for ticker, day, value in rows],
        "schema_version": HOLDOUT_SCHEMA_VERSION,
        "selection_snapshot_hash": selection_hash,
    }
    return payload_hash(payload)


def write_holdout(
    directory: Path,
    snap: Snapshot,
    nxt: date | None,
    points: tuple[tuple[str, int, float], ...],
) -> Path:
    """``points`` are ``(ticker, ordinal, return)`` strictly after the signal."""
    directory.mkdir(parents=True, exist_ok=True)
    packed = [(ticker, date.fromordinal(ordinal).isoformat(), value) for ticker, ordinal, value in points]
    digest = holdout_hash(snap.rebalance, nxt, packed, snap.snapshot_hash)
    rows = [
        {
            "schema_version": HOLDOUT_SCHEMA_VERSION,
            "family_id": FAMILY_ID,
            "rebalance_date": snap.rebalance.isoformat(),
            "next_rebalance_date": "" if nxt is None else nxt.isoformat(),
            "session_date": day,
            "ticker": ticker,
            "adj_return": value,
            "selection_snapshot_hash": snap.snapshot_hash,
            "holdout_hash": digest,
            "purpose": PURPOSE_HOLDOUT,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        for ticker, day, value in packed
    ]
    path = directory / f"{snap.rebalance.isoformat()}_fwd.parquet"
    frame = pa.Table.from_pylist(rows, schema=HOLDOUT_SCHEMA)
    pq.write_table(frame, path, compression="snappy")
    (directory / f"{snap.rebalance.isoformat()}_fwd.json").write_text(
        json.dumps(
            {
                "holdout_hash": digest,
                "selection_snapshot_hash": snap.snapshot_hash,
                "purpose": PURPOSE_HOLDOUT,
                "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
                "rebalance_date": snap.rebalance.isoformat(),
                "next_rebalance_date": None if nxt is None else nxt.isoformat(),
                "n_rows": len(packed),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def read_table(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)
    return table.to_pylist()


def universe_from_rows(rows: list[dict[str, Any]]) -> tuple[date, set[str], str]:
    if not rows:
        raise ValueError("snapshot parquet has no rows")
    day = date.fromisoformat(str(rows[0]["rebalance_date"]))
    digest = str(rows[0]["snapshot_hash"])
    tickers = {str(row["ticker"]) for row in rows if str(row.get("ticker") or "")}
    for row in rows:
        if date.fromisoformat(str(row["rebalance_date"])) != day:
            raise ValueError("snapshot mixes rebalance dates")
        session = date.fromisoformat(str(row["session_date"]))
        if session > day:
            raise ValueError(f"snapshot row {session.isoformat()} is after {day.isoformat()}")
        if str(row["snapshot_hash"]) != digest:
            raise ValueError("snapshot hash is not constant inside the file")
    return day, tickers, digest


def write_selections(path: Path, selections: list[Selection]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "rebalance_date": sel.rebalance.isoformat(),
            "solver": sel.solver,
            "K": sel.k,
            "lambda": sel.lam,
            "p": sel.p,
            "tickers": list(sel.tickers),
            "seed": sel.seed,
            "n_trials_total": sel.n_trials_total,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        for sel in selections
    ]
    frame = pa.Table.from_pylist(rows, schema=SELECTION_SCHEMA)
    pq.write_table(frame, path, compression="snappy")


def read_selections(path: Path) -> list[Selection]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("selections", [])
        if not isinstance(payload, list):
            raise ValueError("selection JSON must be a list")
        return [selection_from_mapping(row) for row in payload]
    rows = read_table(path)
    return [selection_from_mapping(row) for row in rows]


def aum_note() -> dict[str, float]:
    return {"loose_capacity_brl": AUM_LOOSE, "selection_brl": SELECTION_AUM}


def _listings_with_on_fallback(listings: list[Listing], companies: list) -> list[Listing]:
    known = {(item.cnpj, item.ticker) for item in listings}
    extra: list[Listing] = []
    for company in companies:
        for ticker, start, end in company.tickers:
            key = (company.cnpj, ticker)
            if key in known:
                continue
            known.add(key)
            extra.append(Listing(company.cnpj, ticker, int(start), None if end is None else int(end), "on"))
    return listings + extra


def load_research_inputs(cache: Path, events_dir: Path) -> dict[str, Any]:
    """Same cache read as the equal-weight study. Does not open a socket."""
    bundle = load_bundle(cache)
    filed = _listings_with_on_fallback(load_listings(cache), bundle["companies"])
    share_events = share_events_from_companies(bundle["companies"], filed)
    tapes, trades, n_splits = load_strategy_tapes(cache, None, share_events)
    sessions = session_calendar(tapes)
    listings = listings_from_tapes(tapes, filed, int(sessions[-1]) if sessions else 0)
    events = load_cash_events(events_dir)
    return {
        "companies": bundle["companies"],
        "tapes": tapes,
        "sessions": sessions,
        "events": events,
        "listings": listings,
        "cdi_ords": bundle["cdi_ords"],
        "cdi_rates": bundle["cdi_rates"],
        "trades": trades,
        "n_splits": n_splits,
    }

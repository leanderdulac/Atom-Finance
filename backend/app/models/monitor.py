"""Thesis monitor: point-in-time evaluation of a declared paper operation.

A monitor watches one ticker against declared entry/stop/target levels and a
horizon. Checks are snapshots — the evaluator only sees the previous check's
spot and the current one, so intra-check excursions are MISSED (stated in
every response). When a gap crosses both stop and target in one interval,
the stop wins: conservative for the holder, documented, never silent.

States: watching -> active -> {stopped | target_hit | expired}.
Terminal states never change. All math is pure; persistence lives in the API.

A return history, when the caller supplies one, is scored by the causal
Isolation Forest in ``app.models.anomaly``. That flag is a data-quality
pause, not an entry signal, and it never sends an order.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

TERMINAL = ("stopped", "target_hit", "expired")
NEAR_FRAC = 0.25
TIME_WARN_FRAC = 0.75
FIRST_SIGHT_TOL = 0.005


def validate_geometry(direction: str, entry: float, stop: float, target: float) -> None:
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    for name, value in (("entry", entry), ("stop", stop), ("target", target)):
        if not isinstance(value, int | float) or value != value or value <= 0:
            raise ValueError(f"{name} must be a positive number")
    if direction == "long" and not (stop < entry < target):
        raise ValueError("long needs stop < entry < target")
    if direction == "short" and not (target < entry < stop):
        raise ValueError("short needs target < entry < stop")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _crossed(a: float | None, b: float, level: float) -> bool:
    """Did the path cross `level` between the previous sighting and now?"""
    if a is None:
        return abs(b - level) / level <= FIRST_SIGHT_TOL
    if a == level or b == level:
        return True
    return (a - level) * (b - level) < 0


def _beyond(a: float | None, b: float, level: float, side: str) -> bool:
    """Is `b` past `level` on `side`, having arrived from the other side?"""
    if side == "above":
        return b >= level and (a is None or a < level)
    return b <= level and (a is None or a > level)


def evaluate(monitor: dict[str, Any], spot: float, now_iso: str,
             oracle: dict[str, Any] | None = None,
             return_history: list[float] | None = None) -> dict[str, Any]:
    """Evaluate one check. Returns state, metrics, alerts and caveats."""
    direction = monitor["direction"]
    entry = float(monitor["entry"])
    stop = float(monitor["stop"])
    target = float(monitor["target"])
    validate_geometry(direction, entry, stop, target)
    if not isinstance(spot, int | float) or spot != spot or spot <= 0:
        raise ValueError("spot must be a positive number")
    now = _parse(now_iso)
    declared = _parse(monitor["declared_at"])
    horizon_days = int(monitor["horizon_days"])
    horizon_end = declared.timestamp() + horizon_days * 86400.0
    now_ts = now.timestamp()
    elapsed_pct = min(1.0, max(0.0, (now_ts - declared.timestamp()) / (horizon_days * 86400.0)))
    expired = now_ts > horizon_end

    oracle = oracle or {}
    quote_stale = bool(oracle.get("stale")) or oracle.get("usable") is False
    disagreement = oracle.get("disagreement_bps")

    prev_state = monitor.get("state", "watching")
    last_spot = monitor.get("last_spot")
    last_spot_f = float(last_spot) if last_spot is not None else None
    entered_at = monitor.get("entered_at")
    entry_px = monitor.get("entry_px")

    alerts: list[dict[str, str]] = []
    state = prev_state
    exit_px: float | None = None
    exit_reason = ""

    if prev_state in TERMINAL:
        pass
    elif prev_state == "watching":
        if _crossed(last_spot_f, spot, entry):
            state = "active"
            entered_at = now_iso
            entry_px = entry
            alerts.append({"kind": "entered", "text": f"Entrada tocada em {entry}."})
        elif expired:
            state = "expired"
            exit_reason = "Horizonte vencido sem tocar a entrada."
    elif prev_state == "active":
        assert entry_px is not None
        if direction == "long":
            stop_hit = _beyond(last_spot_f, spot, stop, "below") or _crossed(last_spot_f, spot, stop)
            tgt_hit = _beyond(last_spot_f, spot, target, "above") or _crossed(last_spot_f, spot, target)
        else:
            stop_hit = _beyond(last_spot_f, spot, stop, "above") or _crossed(last_spot_f, spot, stop)
            tgt_hit = _beyond(last_spot_f, spot, target, "below") or _crossed(last_spot_f, spot, target)
        if stop_hit:
            state = "stopped"
            exit_px = stop
            exit_reason = "Stop tocado (preenchimento assumido no nível)."
        elif tgt_hit:
            state = "target_hit"
            exit_px = target
            exit_reason = "Alvo tocado (preenchimento assumido no nível)."
        elif expired:
            state = "expired"
            exit_px = spot
            exit_reason = "Horizonte vencido com posição aberta; marcado a mercado."
    else:
        raise ValueError(f"unknown monitor state {prev_state!r}")

    if state != prev_state and state in TERMINAL:
        alerts.append({"kind": "state_changed",
                       "text": f"{prev_state} → {state}. {exit_reason}".strip()})

    # Distances: fraction of the initial entry→level range still open.
    if direction == "long":
        stop_frac = (spot - stop) / (entry - stop)
        tgt_frac = (target - spot) / (target - entry)
    else:
        stop_frac = (stop - spot) / (stop - entry)
        tgt_frac = (spot - target) / (entry - target)
    if state == "active":
        if stop_frac <= NEAR_FRAC:
            alerts.append({"kind": "near_stop",
                           "text": f"Stop a {max(stop_frac, 0.0):.0%} da distância inicial."})
        if tgt_frac <= NEAR_FRAC:
            alerts.append({"kind": "near_target",
                           "text": f"Alvo a {max(tgt_frac, 0.0):.0%} da distância inicial."})
        if elapsed_pct >= TIME_WARN_FRAC:
            alerts.append({"kind": "time_running_out",
                           "text": f"{elapsed_pct:.0%} do horizonte decorrido."})
    if quote_stale:
        alerts.append({"kind": "quote_stale",
                       "text": "Cotação velha ou inutilizável nesta leitura."})
    if isinstance(disagreement, int | float) and disagreement > 50:
        alerts.append({"kind": "quotes_disagree",
                       "text": f"Fontes divergem {disagreement} bps nesta leitura."})

    pnl_pct = None
    if state in ("stopped", "target_hit", "expired") and entry_px:
        ref = exit_px if exit_px is not None else spot
        signed = (ref - entry_px) / entry_px
        pnl_pct = round((signed if direction == "long" else -signed) * 100, 4)

    out = {
        "state": state, "prev_state": prev_state,
        "spot": spot, "checked_at": now_iso,
        "entered_at": entered_at, "entry_px": entry_px,
        "exit_px": exit_px, "exit_reason": exit_reason,
        "pnl_pct": pnl_pct,
        "metrics": {
            "stop_distance_frac": round(stop_frac, 4),
            "target_distance_frac": round(tgt_frac, 4),
            "elapsed_frac": round(elapsed_pct, 4),
            "horizon_end": datetime.fromtimestamp(horizon_end).isoformat(),
        },
        "alerts": alerts,
        "eligible_for_live_trading": False,
        "what_broke": [
            "Leituras pontuais: toques entre verificações passam despercebidos.",
            "Preenchimento assumido no nível, sem gap nem slippage modelados.",
            "Gap que cruza stop e alvo no mesmo intervalo resolve sempre no stop.",
        ],
    }
    if return_history is not None:
        from app.models.anomaly import latest_quality_flag

        out["data_quality"] = latest_quality_flag(return_history)
    return out

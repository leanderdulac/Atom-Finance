"""Render regime context files. Research artifacts, not an OMS blotter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CONTEXT_FILES = (
    "current-regime.md",
    "regime-history.md",
    "position-adjustments.md",
    "signals.md",
)


def render_current_regime(result: dict[str, Any]) -> str:
    ks = result["kill_switch"]
    flag_lines = "\n".join(
        f"- `{name}`: {meta['value']:.4g} (p{meta['percentile']:.0f}{' · ' + meta['flag'] if meta['flag'] else ''})"
        for name, meta in (result.get("signals") or {}).items()
    )
    strat_lines = "\n".join(
        f"- **{s['id']}**: `{s['status']}` (live in {s.get('live_in')})"
        for s in result.get("strategies") or []
    )
    return (
        f"# Current regime\n\n"
        f"> Research snapshot. Not a live market feed.\n\n"
        f"- As of: `{result['as_of']}`\n"
        f"- Regime: **{result['regime']}**\n"
        f"- Kill switch: `{'ARMED — research_risk_off' if ks['armed'] else 'watch'}`\n"
        f"- Broker orders sent: `{ks['broker_orders_sent']}`\n"
        f"- `eligible_for_live_trading`: `{result['eligible_for_live_trading']}`\n\n"
        f"## Flags\n\n{flag_lines}\n\n"
        f"## Strategy book\n\n{strat_lines}\n\n"
        f"## Math\n\n{result.get('math', '')}\n\n"
        f"## What broke\n\n"
        + "\n".join(f"- {w}" for w in result.get("what_broke") or [])
        + "\n"
    )


def render_history_line(result: dict[str, Any]) -> str:
    return (
        f"| {result['as_of']} | {result['regime']} | "
        f"{'armed' if result['kill_switch']['armed'] else 'watch'} |\n"
    )


def render_history(result: dict[str, Any], previous: str = "") -> str:
    header = (
        "# Regime history\n\n"
        "| as_of | regime | kill_switch |\n"
        "|---|---|---|\n"
    )
    if previous.strip() and "| as_of |" in previous:
        body = previous.split("|---|---|---|\n", 1)[-1]
        if not body.endswith("\n"):
            body += "\n"
        return header + body + render_history_line(result)
    return header + render_history_line(result)


def render_adjustments(result: dict[str, Any]) -> str:
    rows = result.get("adjustments") or []
    lines = [
        "# Position adjustments\n",
        f"Regime: **{result['regime']}**. These are research sizes, not tickets.\n",
        "| id | strategy | current | target | delta | action | reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in rows:
        lines.append(
            f"| {a['id']} | {a['strategy_id']} | {a['current_weight']} | "
            f"{a['target_weight']} | {a['delta']} | `{a['action']}` | {a['reason']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_context(directory: Path, result: dict[str, Any], signals_catalog: str | None = None) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    history_path = directory / "regime-history.md"
    previous = history_path.read_text() if history_path.exists() else ""
    files = {
        "current-regime.md": render_current_regime(result),
        "regime-history.md": render_history(result, previous),
        "position-adjustments.md": render_adjustments(result),
    }
    if signals_catalog is not None:
        files["signals.md"] = signals_catalog
    for name, text in files.items():
        (directory / name).write_text(text)
    return files

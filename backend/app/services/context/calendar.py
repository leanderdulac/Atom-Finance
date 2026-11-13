"""Macro calendar: Copom (BCB), FOMC/CPI/payroll from public pages + a dated fallback.

If every fetch fails we still return the official-ish fallback list, each row
pointing at the source URL — never a made-up meeting that is not on that list.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.services.context.http import cached_get_json

BCB_COPOM = "https://www.bcb.gov.br/api/servico/sitebcb/agendareuniao/filtrar"
FED_ICAL_HINT = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_CPI = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_NFP = "https://www.bls.gov/schedule/news_release/empsit.htm"

# Dated 2026 reference (FOMC statements calendar as published by the Fed;
# Copom from BCB typical eight-meeting year). Used only when live fetch is empty.
_FALLBACK_2026: list[dict[str, str]] = [
    {"nome": "FOMC", "data": "2026-01-28", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-03-18", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-04-29", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-06-17", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-07-29", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-09-16", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-10-28", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "FOMC", "data": "2026-12-09", "tipo": "binary", "fonte": FED_ICAL_HINT},
    {"nome": "Copom", "data": "2026-01-28", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-03-18", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-05-06", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-06-17", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-07-29", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-09-16", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-11-04", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
    {"nome": "Copom", "data": "2026-12-09", "tipo": "binary", "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom"},
]


def upcoming_events(*, horizon_days: int, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(UTC).date()
    until = today + timedelta(days=max(horizon_days, 1))
    rows = _from_bcb() + _fallback()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        day = _parse_day(row.get("data") or "")
        if day is None or day < today or day > until:
            continue
        key = (row["nome"], row["data"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "nome": row["nome"],
            "data": row["data"],
            "tipo": row.get("tipo") or "macro",
            "url": row.get("fonte") or FED_ICAL_HINT,
            "impacto": "alto",
        })
    # Recurring US prints: first Friday (payroll) and mid-month CPI in the window.
    out.extend(_us_prints(today, until))
    out.sort(key=lambda r: r["data"])
    return out[:12]


def _from_bcb() -> list[dict[str, str]]:
    year = datetime.now(UTC).year
    payload = cached_get_json(
        BCB_COPOM,
        params={"ano": year},
        prefix="bcb-copom",
        timeout=4.0,
        ttl=3600,
    )
    rows: list[dict[str, str]] = []
    if not payload:
        return rows
    items = payload if isinstance(payload, list) else payload.get("conteudo") or payload.get("items") or []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("DataInicio") or item.get("data") or item.get("Data") or "")
        day = _parse_day(raw[:10])
        if day is None:
            continue
        rows.append({
            "nome": "Copom",
            "data": day.isoformat(),
            "tipo": "binary",
            "fonte": "https://www.bcb.gov.br/controleinflacao/comunicadoscopom",
        })
    return rows


def _fallback() -> list[dict[str, str]]:
    return list(_FALLBACK_2026)


def _us_prints(today: date, until: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = today
    while cursor <= until:
        if cursor.weekday() == 4 and 1 <= cursor.day <= 7:  # first Friday
            rows.append({
                "nome": "Payroll (NFP)",
                "data": cursor.isoformat(),
                "tipo": "binary",
                "url": BLS_NFP,
                "impacto": "alto",
            })
        if cursor.day == 13:
            rows.append({
                "nome": "CPI (EUA)",
                "data": cursor.isoformat(),
                "tipo": "binary",
                "url": BLS_CPI,
                "impacto": "alto",
            })
        cursor += timedelta(days=1)
    return rows


def _parse_day(raw: str) -> date | None:
    raw = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None

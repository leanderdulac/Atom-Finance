"""Run the equal-weight B3 study and write the report.

Reads the cache from ``scripts/fetch_net_net_b3.py`` and the cash events from
``scripts/fetch_equal_weight_dividends.py``. Does not open a socket.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.corporate_actions import (  # noqa: E402
    JUMP_RATIO,
    MAX_HEURISTIC_FACTOR,
    MIN_SHARE_QTY,
    OFFICIAL_RESIDUAL_TOL,
    OFFICIAL_SESSION_SLACK_DAYS,
    PRICE_INTEGER_REL_TOL,
    REVERT_NET_REL_TOL,
    REVERT_SESSIONS,
    VOLUME_LOG_REL_TOL,
    summarize_audit,
)
from app.models.equal_weight import (  # noqa: E402
    FAMILY_ID_V2,
    LOCKED_SLEEVE,
    V1_FAMILY_TRIALS,
    render_report,
    run_study,
)
from app.models.equal_weight_io import (  # noqa: E402
    Listing,
    listings_from_tapes,
    load_cash_events,
    load_listings,
    load_strategy_tapes,
    share_events_from_companies,
)
from app.models.net_net_io import load_bundle, session_calendar  # noqa: E402


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


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


def _v1_appendix(report: dict) -> str:
    """Keep the published v1 record next to a regenerated v2 report.

    The numbers in the v1 column are the study already in
    ``docs/reports/equal-weight-b3.json`` before this rule. They are not
    recomputed here.
    """
    summary = report.get("jump_audit_summary") or {}
    by_source = summary.get("by_source") or {}
    counts = ", ".join(f"{name} {by_source.get(name, 0)}" for name in ("b3", "cvm", "heuristic", "unadjusted", "bad_print"))
    jump = f"{JUMP_RATIO:.2f}".replace(".", ",")
    volume = f"{VOLUME_LOG_REL_TOL:.2f}".replace(".", ",")
    return (
        "\n## Registro v1 ao lado desta corrida\n\n"
        "A janela de 250 dias foi retirada. "
        f"Salto a partir da razão {jump}, inteiro de 2 a {MAX_HEURISTIC_FACTOR} "
        f"com tolerância relativa de {PRICE_INTEGER_REL_TOL:.0%}, "
        f"volume com tolerância log-relativa {volume}, "
        f"mínimo de {int(MIN_SHARE_QTY)} ações, reversão em {REVERT_SESSIONS} pregões "
        f"a até {REVERT_NET_REL_TOL:.0%}, "
        f"resíduo oficial de até {OFFICIAL_RESIDUAL_TOL:.0%} "
        f"e folga de {OFFICIAL_SESSION_SLACK_DAYS} dias. "
        "`eligible_for_live_trading` permanece false.\n\n"
        "A manga travada é small, ADV de R$ 200 mil, trimestral, R$ 1 milhão. "
        "A v1 publicada: CAGR líquido OOS 23,5%, excesso sobre o CDI 14,0%, excesso sobre o Ibovespa TR 15,6 p.p., "
        "Sharpe OOS 0,56, Sharpe de desenho 0,66, DSR OOS 0,30, PSR OOS 0,98, MinTRL infinito, max DD −64,2%, "
        "giro 0,72, capacidade tênue R$ 807 mil, CAGR OOS a R$ 100 mil / R$ 1 mi / R$ 10 mi de 44,6% / 23,5% / 12,1%. "
        "N da família 55, decisão 87, transparência 111. Veredito v1: reprovado.\n\n"
        f"Nesta corrida o N da decisão é {report.get('n_trials_decision')} "
        f"(família {report.get('n_trials')} + família v1 {report.get('n_prior_family_trials')} + "
        f"net-net rejeitado {report.get('n_rejected_net_net')}). "
        f"Veredito desta corrida: {report.get('verdict')}. "
        f"Saltos por fonte: {counts}.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Equal-weight B3 study. Paper only.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--events", type=Path, default=Path("data/equal-weight/yahoo"))
    parser.add_argument("--json", type=Path, default=Path("docs/reports/equal-weight-b3.json"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/EQUAL-WEIGHT-B3.md"))
    parser.add_argument("--registry", type=Path, default=Path("data/equal-weight/trials.sqlite"))
    args = parser.parse_args()
    bundle = load_bundle(args.cache)
    filed = _listings_with_on_fallback(load_listings(args.cache), bundle["companies"])
    share_events = share_events_from_companies(bundle["companies"], filed)
    jump_audit: list[dict] = []
    tapes, trades, n_splits = load_strategy_tapes(
        args.cache, None, share_events, chart_dir=args.events, audit_out=jump_audit
    )
    sessions = session_calendar(tapes)
    listings = listings_from_tapes(tapes, filed, int(sessions[-1]) if sessions else 0)
    events = load_cash_events(args.events)
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    if args.registry.exists():
        args.registry.unlink()
    report = run_study(
        bundle["companies"],
        tapes,
        sessions,
        events,
        bundle["ibov_ords"],
        bundle["ibov_close"],
        bundle["cdi_ords"],
        bundle["cdi_rates"],
        str(args.registry),
        listings,
        published_tapes=bundle["tapes"],
        trades=trades,
        audit_sessions=bundle["sessions"],
        family_id=FAMILY_ID_V2,
        prior_family_trials=V1_FAMILY_TRIALS,
        locked_spec=LOCKED_SLEEVE,
    )
    report["sample"]["confirmed_splits_on_strategy_tapes"] = n_splits
    report["sample"]["cash_event_files"] = len(events)
    report["jump_audit_summary"] = summarize_audit(jump_audit)
    report["jump_audit"] = jump_audit
    report["adjustment_version"] = "v2"
    payload = _jsonable(report)
    v1_path = args.json.with_name("equal-weight-b3-v1.json")
    if args.json.exists() and not v1_path.exists():
        previous = json.loads(args.json.read_text(encoding="utf-8"))
        if previous.get("family_id") == "b3_equal_weight":
            v1_path.write_text(args.json.read_text(encoding="utf-8"), encoding="utf-8")
            payload["history_v1"] = {
                "file": str(v1_path),
                "family_id": previous.get("family_id"),
                "verdict": previous.get("verdict"),
                "n_trials": previous.get("n_trials"),
                "n_trials_decision": previous.get("n_trials_decision"),
                "n_trials_with_factor_trials": previous.get("n_trials_with_factor_trials"),
                "selected": (previous.get("oos_split") or {}).get("selected"),
            }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(render_report(report) + _v1_appendix(report), encoding="utf-8")
    print(report["verdict"], args.json, args.markdown, flush=True)


if __name__ == "__main__":
    main()

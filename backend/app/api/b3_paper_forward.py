"""Read-only views of the B3 forward paper books. Nothing here sends an order."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from app.models.b3_paper_forward import (
    ELIGIBLE_FOR_LIVE_TRADING,
    LedgerIntegrityError,
    PaperDataError,
    PaperError,
    build_monthly_report,
    file_sha256,
    load_book,
    paper_root,
    preregistration_path,
    public_state,
    read_entries,
    verify_ledger,
)

router = APIRouter()


def _integrity(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/state")
def state() -> dict:
    try:
        payload = public_state(paper_root())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="B3 paper book is not initialized") from exc
    except (LedgerIntegrityError, PaperError) as exc:
        raise _integrity(exc) from exc
    payload["eligible_for_live_trading"] = ELIGIBLE_FOR_LIVE_TRADING
    return payload


@router.get("/composition")
def composition() -> dict:
    payload = state()
    return {
        "eligible_for_live_trading": False,
        "signal_session": payload["signal_session"],
        "entry_session": payload["entry_session"],
        "pending_inception": payload["pending_inception"],
        "target_b": payload["composition_b_target"],
        "positions_b": payload["positions_b"],
        "positions_a": payload["positions_a"],
        "nav": payload["nav"],
    }


@router.get("/ledger")
def ledger(limit: int = Query(default=50, ge=1, le=5000)) -> dict:
    root = paper_root()
    try:
        digest = file_sha256(preregistration_path(root))
        entries = read_entries(root)
        verify_ledger(entries, digest)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="B3 paper ledger is not initialized") from exc
    except (LedgerIntegrityError, PaperError) as exc:
        raise _integrity(exc) from exc
    return {
        "eligible_for_live_trading": False,
        "verified": True,
        "preregistration_sha256": digest,
        "count": len(entries),
        "entries": entries[-limit:],
    }


@router.get("/preregistration")
def preregistration() -> dict:
    path = preregistration_path(paper_root())
    if not path.exists():
        raise HTTPException(status_code=404, detail="preregistration file is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("eligible_for_live_trading") is not False:
        raise HTTPException(status_code=409, detail="eligible_for_live_trading must stay false")
    return {
        "eligible_for_live_trading": False,
        "sha256": file_sha256(path),
        "preregistration": document,
    }


@router.get("/reports/monthly")
def monthly(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> dict:
    root = paper_root()
    try:
        loaded = load_book(root)
        snapshot = loaded["snapshot"]
        if month is None:
            months = sorted({str(row["date"])[:7] for row in snapshot["curve"] if row.get("phase") == "close"})
            return {"eligible_for_live_trading": False, "months": months}
        report = build_monthly_report(snapshot, month)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="B3 paper book is not initialized") from exc
    except PaperDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (LedgerIntegrityError, PaperError) as exc:
        raise _integrity(exc) from exc
    report["eligible_for_live_trading"] = False
    return report

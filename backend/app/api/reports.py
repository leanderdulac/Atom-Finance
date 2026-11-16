"""Reports API - PDF/CSV export."""
import csv
import io
import json
import re
from urllib.parse import quote as url_quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

_MAX_TITLE_LEN = 200
_MAX_FLATTEN_DEPTH = 5
_MAX_ROWS = 50_000
_MAX_KEYS_PER_LEVEL = 5_000
_FILENAME_RE = re.compile(r"[^A-Za-z0-9 _.-]+")


class ReportRequest(BaseModel):
    title: str = Field(default="ATOM Analysis Report", max_length=_MAX_TITLE_LEN)
    data: dict
    format: str = "csv"  # csv or json


def _safe_filename(title: str, ext: str) -> str:
    """Header-safe attachment filename: no CR/LF, quoted + RFC 5987 fallback."""
    name = title.replace("\r", "").replace("\n", "")
    name = _FILENAME_RE.sub("_", name).strip(" .")[:64] or "report"
    base = name.replace(" ", "_")
    return f'attachment; filename="{base}.{ext}"; filename*=UTF-8\'\'{url_quote(base)}.{ext}'


def _safe_cell(value: object) -> object:
    """Neutralise CSV formula injection (Excel/Sheets execute = + - @)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _flatten(writer, data: dict) -> None:
    """Depth- and row-capped flattening of an arbitrary nested dict."""
    rows = 0

    def rec(d: dict, prefix: str, depth: int) -> None:
        nonlocal rows
        if depth > _MAX_FLATTEN_DEPTH:
            raise HTTPException(status_code=422, detail="data nested too deep (max 5)")
        for i, (key, value) in enumerate(d.items()):
            if i >= _MAX_KEYS_PER_LEVEL:
                raise HTTPException(status_code=422, detail="too many keys at one level")
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                rec(value, full_key, depth + 1)
            elif isinstance(value, list):
                writer.writerow([full_key, _safe_cell(str(value[:20]))])
                rows += 1
            else:
                writer.writerow([full_key, _safe_cell(value)])
                rows += 1
            if rows > _MAX_ROWS:
                raise HTTPException(status_code=422, detail="report exceeds row cap")

    rec(data, "", 0)


@router.post("/export")
async def export_report(req: ReportRequest):
    if req.format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ATOM - Quantitative Finance Report"])
        writer.writerow(["Title", _safe_cell(req.title)])
        writer.writerow([])

        _flatten(writer, req.data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": _safe_filename(req.title, "csv")},
        )
    else:
        content = json.dumps({"title": req.title, "data": req.data}, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="application/json",
            headers={"Content-Disposition": _safe_filename(req.title, "json")},
        )

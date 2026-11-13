"""Reports API - PDF/CSV export."""
import csv
import io
import json
import re
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_NUMERIC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _safe_csv_cell(val: object) -> str:
    if isinstance(val, (int, float, bool)) or val is None:
        return "" if val is None else str(val)
    text = str(val)
    stripped = text.lstrip(" ")
    if (text.startswith(_FORMULA_PREFIXES) or stripped.startswith(_FORMULA_PREFIXES)) and not _NUMERIC_RE.fullmatch(stripped):
        return f"'{text}"
    return text


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", title.strip()).strip("_.")
    return (cleaned or "ATOM_Analysis_Report")[:80]


class ReportRequest(BaseModel):
    title: str = Field(default="ATOM Analysis Report", max_length=120)
    data: dict
    format: Literal["csv", "json"] = "csv"


@router.post("/export")
async def export_report(req: ReportRequest):
    safe_name = _safe_filename(req.title)
    if req.format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ATOM - Quantitative Finance Report"])
        writer.writerow(["Title", _safe_csv_cell(req.title)])
        writer.writerow([])

        def flatten_dict(d: dict, prefix: str = "", depth: int = 0) -> None:
            if depth >= 10:
                writer.writerow([_safe_csv_cell(prefix), _safe_csv_cell(str(d)[:500])])
                return
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    flatten_dict(value, full_key, depth + 1)
                elif isinstance(value, list):
                    writer.writerow([_safe_csv_cell(full_key), _safe_csv_cell(str(value[:20]))])
                else:
                    writer.writerow([_safe_csv_cell(full_key), _safe_csv_cell(value)])

        flatten_dict(req.data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    else:
        content = json.dumps({"title": req.title, "data": req.data}, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
        )

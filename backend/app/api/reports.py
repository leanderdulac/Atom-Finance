"""Reports API - PDF/CSV export."""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import io
import csv
import json

router = APIRouter()


class ReportRequest(BaseModel):
    title: str = "ATOM Analysis Report"
    data: dict
    format: str = "csv"  # csv or json


@router.post("/export")
async def export_report(req: ReportRequest):
    if req.format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ATOM - Quantitative Finance Report"])
        writer.writerow(["Title", req.title])
        writer.writerow([])

        def flatten_dict(d, prefix=""):
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    flatten_dict(value, full_key)
                elif isinstance(value, list):
                    writer.writerow([full_key, str(value[:20])])
                else:
                    writer.writerow([full_key, value])

        flatten_dict(req.data)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={req.title.replace(' ', '_')}.csv"},
        )
    else:
        content = json.dumps({"title": req.title, "data": req.data}, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={req.title.replace(' ', '_')}.json"},
        )

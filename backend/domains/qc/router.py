"""QC flow routes: upload, field mapping, run, results, findings, export."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from ...core import store
from ...core.api import OkResponse
from ...core.auth import require_project_access
from ...core.config import UPLOAD_DIR
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from . import export as qc_export
from . import parser as qc_parser
from . import service as qc_service
from .schemas import (
    QCAllRowsResponse,
    QCExportResponse,
    QCFieldMappingSaveResponse,
    QCFinding,
    QCPreviewResponse,
    QCReport,
    QCRun,
    QCRunStartResponse,
    QCUploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

IdPath = Annotated[int, PathParam(ge=1)]


@router.post("/qc/upload", response_model=QCUploadResponse)
async def qc_upload_route(project_id: int = Form(0), file: UploadFile = File(...)):

    if not project_id:
        raise HTTPException(400, "project_id is required")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls", ".docx", ".pptx"):
        raise HTTPException(400, "Supported formats: CSV, Excel, Word (.docx), PowerPoint (.pptx)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"qc_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    report_id = store.create_qc_report(project_id, file.filename or safe_name, str(dest))

    try:
        result = qc_parser.parse_file(str(dest))
        if "error" in result:
            store.update_qc_report(report_id, parse_status="error", parse_error=result["error"])
            return {
                "report_id": report_id,
                "file_name": file.filename,
                "parse_status": "error",
                "parse_error": result["error"],
            }
        store.update_qc_report(
            report_id,
            parse_status="done",
            row_count=result["row_count"],
            column_count=result["column_count"],
            columns_json=result["columns"],
            field_mapping=result["field_mapping"],
        )
        return {
            "report_id": report_id,
            "file_name": file.filename,
            "parse_status": "done",
        }
    except Exception as e:
        logger.error("QC parse error for report %s: %s", report_id, e)
        store.update_qc_report(report_id, parse_status="error", parse_error=str(e))
        return {
            "report_id": report_id,
            "file_name": file.filename,
            "parse_status": "error",
            "parse_error": str(e),
        }


@router.get("/qc/report/{project_id}", response_model=QCReport)
def qc_report_route(project_id: IdPath, _access: Annotated[dict, Depends(require_project_access)]):
    report = store.get_qc_report_for_project(project_id)
    if not report:
        raise HTTPException(404, "No QC report found for this project")
    return report


@router.get("/qc/report/detail/{report_id}", response_model=QCReport)
def qc_report_detail_route(report_id: IdPath):
    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


@router.get("/qc/preview/{report_id}", response_model=QCPreviewResponse)
def qc_preview_route(report_id: IdPath):

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if report["parse_status"] != "done":
        return {"status": report["parse_status"], "preview": [], "error": report.get("parse_error")}

    parsed = qc_parser.parse_file(report["file_path"])
    if "error" in parsed:
        return {"status": "error", "preview": [], "error": parsed["error"]}
    return {"status": "done", "preview": parsed.get("preview", [])[:20]}


@router.get("/qc/all-rows/{report_id}", response_model=QCAllRowsResponse)
def qc_all_rows_route(report_id: IdPath):

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    parsed = qc_parser.parse_file(report["file_path"])
    if "error" in parsed:
        return {"rows": []}
    columns = parsed.get("columns", [])
    all_preview = parsed.get("preview", [])
    if len(all_preview) < parsed.get("row_count", 0):
        mapping = report.get("field_mapping") or {}
        raw = qc_parser.get_rows_from_file(report["file_path"], mapping)
        reverse = {v: k for k, v in mapping.items()}
        all_preview = [{reverse.get(k, k): v for k, v in row.items()} for row in raw]
    return {"rows": all_preview, "columns": columns}


@router.post("/qc/field-mapping/{report_id}", response_model=QCFieldMappingSaveResponse)
def qc_save_mapping_route(report_id: IdPath, body: dict):
    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    mapping = body.get("mapping", {})
    store.save_qc_field_mapping(report_id, mapping)
    return {"ok": True, "report_id": report_id}


@router.post("/qc/run/{report_id}", response_model=QCRunStartResponse)
def qc_run_route(report_id: IdPath):

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if report["parse_status"] != "done":
        raise HTTPException(400, "Report not fully parsed")
    if not report.get("field_mapping"):
        raise HTTPException(400, "No field mapping configured")

    job_id = f"qc_run_{uuid.uuid4().hex[:12]}"
    project_id = report.get("project_id")
    store.create_job(job_id, project_id, "qc_run")

    def _run_bg():
        store.update_job(job_id, status="running", progress_pct=0,
                         progress_message="Running QC checks")
        try:
            def _on_progress(msg, pct):
                store.update_job(job_id, progress_pct=pct, progress_message=msg)
                _broadcast({"type": "qc_progress", "report_id": report_id, "message": msg, "progress_pct": pct})

            result = qc_service.run_qc(report_id, on_progress=_on_progress)
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="QC run complete", result=result)
            _broadcast({"type": "qc_complete", "report_id": report_id, "result": result})
        except Exception as e:
            logger.error("QC run error for report %s: %s", report_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "qc_error", "report_id": report_id, "error": str(e)})

    submit(_run_bg, name="qc:run")
    return {"status": "started", "report_id": report_id, "job_id": job_id}


@router.get("/qc/runs/{report_id}", response_model=list[QCRun])
def qc_runs_route(report_id: IdPath):
    return store.get_qc_runs_for_report(report_id)


@router.get("/qc/results/{run_id}", response_model=list[QCFinding])
def qc_results_route(run_id: IdPath, severity: str | None = None, check_type: str | None = None):
    findings = store.get_qc_findings(run_id, severity=severity, check_type=check_type)
    return findings


@router.get("/qc/summary/{run_id}", response_model=QCRun)
def qc_summary_route(run_id: IdPath):
    run = store.get_qc_run(run_id)
    if not run:
        raise HTTPException(404, "QC run not found")
    return run


@router.post("/qc/finding/{finding_id}/action", response_model=OkResponse)
def qc_finding_action_route(finding_id: IdPath, body: dict):
    action = body.get("action", "")
    if action not in ("accepted", "dismissed", "flagged"):
        raise HTTPException(400, "Invalid action -- use: accepted, dismissed, flagged")
    store.update_qc_finding_action(finding_id, action)
    return {"ok": True}


@router.post("/qc/export/{run_id}", response_model=QCExportResponse)
def qc_export_route(run_id: IdPath):

    result = qc_export.export_qc_results(run_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/qc/export/download/{export_id}", response_class=FileResponse)
def qc_export_download_route(export_id: IdPath):

    conn = store._conn()
    row = conn.execute("SELECT * FROM qc_exports WHERE id = ?", (export_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Export not found")
    p = Path(row["file_path"])
    if not p.exists():
        raise HTTPException(404, "Export file not found on disk")
    return FileResponse(str(p), filename=row["file_name"], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

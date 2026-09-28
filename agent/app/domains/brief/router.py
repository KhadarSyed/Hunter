"""Analyst brief routes: parse, generate, review, render, download."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

import openpyxl
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ...core import nvidia_parse_client, store
from ...core.config import UPLOAD_DIR
from ...core.events import broadcast as _broadcast
from ...core.nvidia_parse_client import NvidiaParseError
from ..research.renderer import render_brief_docx as do_render
from ..research.service import compose_brief
from . import parser as brief_parser
from .schemas import (
    ApproveBriefRequest,
    GenerateBriefRequest,
    RejectBriefRequest,
    UpdateBriefSectionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Below this many characters, primary text-layer extraction is treated as "near-empty" — most
# likely a scanned/image-only document — and the NVIDIA OCR fallback is attempted. Starting point
# only; tune once real scanned uploads have been seen (see plan chunk "3. OCR fallback").
OCR_TRIGGER_MIN_CHARS = 200
# Extensions plausible enough to be "scanned" that OCR is worth attempting. XLSX/TXT are always
# text-native, so a short result there means the file is genuinely short, not a scan.
OCR_ELIGIBLE_EXTENSIONS = {".pdf", ".pptx", ".docx"}


@router.post("/brief/parse-file")
async def parse_brief_file(file: UploadFile = File(...)):
    """Upload a brief file (DOCX, PPTX, TXT, PDF) and extract its text."""

    ext = Path(file.filename or "").suffix.lower()
    supported = {".docx", ".pptx", ".txt", ".pdf", ".xlsx", ".xls"}
    if ext not in supported:
        raise HTTPException(400, f"Unsupported format: {ext}. Use DOCX, PPTX, TXT, PDF, or Excel.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"brief_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    try:
        if ext in (".xlsx", ".xls"):
            wb = openpyxl.load_workbook(str(dest), read_only=True, data_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                line = "  ".join(str(c) for c in row if c is not None)
                if line.strip():
                    lines.append(line.strip())
            wb.close()
            text = "\n".join(lines)
        elif ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(str(dest))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            except ImportError:
                text = "(PDF parsing requires PyMuPDF — please use DOCX or PPTX instead)"
        else:
            text = brief_parser.parse_brief(dest)

        ocr_used = False
        if len(text.strip()) < OCR_TRIGGER_MIN_CHARS and ext in OCR_ELIGIBLE_EXTENSIONS:
            try:
                ocr_text = nvidia_parse_client.parse_document(content, file.filename or "")
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
                    ocr_used = True
            except (NvidiaParseError, ImportError) as e:
                # Never let a missing/misconfigured OCR fallback (very likely right now — no real
                # NVIDIA_PARSE_API_KEY yet) break the upload. Keep whatever primary-extraction text
                # we already have and report ocr_used=False.
                logger.warning("OCR fallback skipped for %s: %s", file.filename, e)

        return {"text": text, "file_name": file.filename, "ocr_used": ocr_used}
    except Exception as e:
        logger.error("Brief file parse error: %s", e)
        raise HTTPException(400, f"Could not parse file: {e}")


@router.post("/brief/generate")
def generate_analyst_brief(req: GenerateBriefRequest):
    """Generate an analyst orientation brief from completed web research."""
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    research = store.get_latest_research(req.project_id)
    if not research:
        raise HTTPException(400, "No background research found. Run web research first.")

    spec = project.get("spec", {})
    research_data = research["research"]
    llm_output = research.get("llm_output")

    try:
        result = compose_brief(req.project_id, research["id"], spec, research_data, llm_output)
    except Exception as e:
        logger.exception("Brief generation failed for project %s", req.project_id)
        raise HTTPException(500, f"Brief generation failed: {e}")

    _broadcast({"type": "intel_brief_generated", "project_id": req.project_id,
                "brief_id": result["brief_id"]})
    return result


@router.get("/brief/{project_id}")
def get_analyst_brief(project_id: int):
    """Get the latest analyst orientation brief for a project."""
    brief = store.get_latest_brief(project_id)
    if not brief:
        raise HTTPException(404, "No brief found for this project")

    research = store.get_latest_research(project_id)
    research_approved = research and research.get("approval_status") == "approved"

    return {
        "brief_id": brief["id"],
        "version": brief["version"],
        "approval_status": brief["approval_status"],
        "brief": brief["brief"],
        "docx_path": brief.get("docx_path"),
        "docx_generated_at": brief.get("docx_generated_at"),
        "research_approved": research_approved,
        "created_at": brief["created_at"],
        "updated_at": brief["updated_at"],
    }


@router.post("/brief/{brief_id}/section")
def update_brief_section(brief_id: int, req: UpdateBriefSectionRequest):
    """Update a single section of the brief with analyst edits."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.update_brief_section(brief_id, req.section_key, req.content, req.analyst_note)
    return {"ok": True}


@router.post("/brief/{brief_id}/approve")
def approve_analyst_brief(brief_id: int, req: ApproveBriefRequest):
    """Approve the analyst orientation brief, also approves background research."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    store.approve_brief(brief_id, req.reviewer)
    store.approve_research(brief["research_id"], req.reviewer)

    _broadcast({"type": "intel_brief_approved", "brief_id": brief_id})
    return {"ok": True}


@router.post("/brief/{brief_id}/reject")
def reject_analyst_brief(brief_id: int, req: RejectBriefRequest):
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.reject_brief(brief_id, req.notes)
    return {"ok": True}


@router.post("/brief/{brief_id}/render")
def render_brief_docx(brief_id: int):
    """Render the brief as a Word document and return the file path."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    filepath = do_render(brief_id)
    return {"ok": True, "docx_path": filepath}


@router.get("/brief/{brief_id}/download")
def download_brief_docx(brief_id: int):
    """Download the rendered Word document."""

    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    docx_path = brief.get("docx_path")
    if not docx_path or not os.path.exists(docx_path):
        raise HTTPException(404, "Word document not yet generated. Call /brief/{id}/render first.")

    filename = os.path.basename(docx_path)
    return FileResponse(
        path=docx_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/brief/versions/{project_id}")
def list_brief_versions(project_id: int):
    """List all brief versions for a project."""
    return store.list_brief_versions(project_id)

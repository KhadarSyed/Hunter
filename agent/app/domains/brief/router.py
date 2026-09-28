"""Analyst brief routes: parse, generate, review, render, download."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi import Path as PathParam
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from ...core import store
from ...core.api import OkResponse
from ...core.config import UPLOAD_DIR
from ...core.events import broadcast as _broadcast
from ..research.renderer import render_brief_docx as do_render
from ..research.service import compose_brief
from . import parser as brief_parser
from .schemas import (
    AnalystBriefResponse,
    ApproveBriefRequest,
    BriefRenderResponse,
    BriefVersionItem,
    GenerateBriefRequest,
    GeneratedBriefResponse,
    ParsedBriefFileResponse,
    RejectBriefRequest,
    UpdateBriefSectionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Positive integer id path parameter (`Path` is pathlib's here).
BriefIdParam = Annotated[int, PathParam(ge=1)]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # client briefs are small; reject accidental huge uploads


@router.post("/brief/parse-file", response_model=ParsedBriefFileResponse)
async def parse_brief_file(file: UploadFile = File(...)):
    """Upload a client brief (PDF, DOCX/DOC, PPTX/PPT, XLSX/XLS, TXT) and extract its text.

    NVIDIA Nemotron-Parse extracts layout-aware text (Office files are converted to PDF
    first); native extraction is the fallback. The text then goes into the New Project
    form and, on "Analyze Brief", to the GPT Brief & Scope analysis.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in brief_parser.UPLOAD_SUFFIXES:
        raise HTTPException(400, f"Unsupported format: {ext or 'unknown'}. Use PDF, DOCX, PPT(X), Excel, or TXT.")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"brief_{uuid.uuid4().hex[:8]}{ext}"
    dest.write_bytes(content)
    try:
        # Blocking (NVIDIA calls, Office conversion) — keep it off the event loop.
        result = await run_in_threadpool(brief_parser.extract_brief_text, dest)
    except Exception as e:
        logger.error("Brief file parse error for %s: %s", file.filename, e)
        raise HTTPException(400, f"Could not parse file: {e}") from e
    if not result["text"].strip():
        raise HTTPException(422, "No text could be extracted from this file")
    return {
        "text": result["text"],
        "file_name": file.filename,
        "ocr_used": result["method"] == "nvidia",
        "extraction_method": result["method"],
        "model": result["model"],
        "pages": result["pages"],
    }


@router.post("/brief/generate", response_model=GeneratedBriefResponse)
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


@router.get("/brief/{project_id}", response_model=AnalystBriefResponse)
def get_analyst_brief(project_id: BriefIdParam):
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


@router.post("/brief/{brief_id}/section", response_model=OkResponse)
def update_brief_section(brief_id: BriefIdParam, req: UpdateBriefSectionRequest):
    """Update a single section of the brief with analyst edits."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.update_brief_section(brief_id, req.section_key, req.content, req.analyst_note)
    return {"ok": True}


@router.post("/brief/{brief_id}/approve", response_model=OkResponse)
def approve_analyst_brief(brief_id: BriefIdParam, req: ApproveBriefRequest):
    """Approve the analyst orientation brief, also approves background research."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    store.approve_brief(brief_id, req.reviewer)
    store.approve_research(brief["research_id"], req.reviewer)

    _broadcast({"type": "intel_brief_approved", "brief_id": brief_id})
    return {"ok": True}


@router.post("/brief/{brief_id}/reject", response_model=OkResponse)
def reject_analyst_brief(brief_id: BriefIdParam, req: RejectBriefRequest):
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.reject_brief(brief_id, req.notes)
    return {"ok": True}


@router.post("/brief/{brief_id}/render", response_model=BriefRenderResponse)
def render_brief_docx(brief_id: BriefIdParam):
    """Render the brief as a Word document and return the file path."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    filepath = do_render(brief_id)
    return {"ok": True, "docx_path": filepath}


@router.get("/brief/{brief_id}/download", response_class=FileResponse)
def download_brief_docx(brief_id: BriefIdParam):
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


@router.get("/brief/versions/{project_id}", response_model=list[BriefVersionItem])
def list_brief_versions(project_id: BriefIdParam):
    """List all brief versions for a project."""
    return store.list_brief_versions(project_id)

"""Research Specification routes: generate, sections, approve, render, clarifications."""
from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from starlette.responses import FileResponse

from ...core import store
from ...core.anthropic_client import get_llm_client
from . import renderer as rsr
from . import service as rss
from .schemas import (
    AddClarificationRequest,
    ApproveSpecRequest,
    ApproveSpecSectionRequest,
    ClarificationStatusResponse,
    GeneratedSpecResponse,
    GenerateSpecRequest,
    LockSpecSectionRequest,
    RegenerateSpecRequest,
    RejectSpecRequest,
    ResolveClarificationRequest,
    SpecAuditEntry,
    SpecClarification,
    SpecReadinessResponse,
    SpecRenderResponse,
    SpecResponse,
    SpecSectionStatusResponse,
    SpecStatusResponse,
    SpecVersionItem,
    UpdateSpecSectionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/spec/generate", response_model=GeneratedSpecResponse)
def generate_research_spec(req: GenerateSpecRequest):
    """Generate a Research Specification from the project's stored spec."""
    try:
        llm_client = None
        if req.use_llm:
            llm_client = get_llm_client()
            if not llm_client or not llm_client.is_reachable():
                raise HTTPException(503, "No LLM provider available — ensure Ollama is running or ANTHROPIC_API_KEY is set")
        result = rss.generate_spec(
            project_id=req.project_id,
            raw_brief_text=req.raw_brief_text,
            use_llm=req.use_llm,
            llm_client=llm_client,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to generate research specification")
        raise HTTPException(500, f"Specification generation failed: {e}")


@router.get("/spec/{project_id}", response_model=SpecResponse)
def get_research_spec(project_id: Annotated[int, Path(ge=1)]):
    """Get the latest Research Specification for a project."""
    spec = store.get_latest_spec(project_id)
    if not spec:
        raise HTTPException(404, "No research specification found for this project")
    return spec


@router.get("/spec/detail/{spec_id}", response_model=SpecResponse)
def get_spec_detail(spec_id: Annotated[int, Path(ge=1)]):
    """Get a specific Research Specification by ID."""
    spec = store.get_spec_by_id(spec_id)
    if not spec:
        raise HTTPException(404, "Specification not found")
    return spec


@router.post("/spec/{spec_id}/section", response_model=SpecSectionStatusResponse)
def update_spec_section(spec_id: Annotated[int, Path(ge=1)], req: UpdateSpecSectionRequest):
    """Update a single section of a Research Specification."""
    sa = store.get_spec_by_id(spec_id)
    if not sa:
        raise HTTPException(404, "Specification not found")
    approvals = sa.get("section_approvals", {})
    section_approval = approvals.get(req.section_key, {})
    if section_approval.get("is_locked"):
        raise HTTPException(
            409,
            f"Section '{req.section_key}' is locked. Unlock it before editing.",
        )
    ok = store.update_spec_section(spec_id, req.section_key, req.content, req.analyst_note)
    if not ok:
        raise HTTPException(404, "Specification not found")
    return {"status": "updated", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/approve", response_model=SpecSectionStatusResponse)
def approve_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: ApproveSpecSectionRequest):
    """Approve a single section of a specification."""
    store.approve_spec_section(spec_id, req.section_key, req.reviewer)
    return {"status": "approved", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/lock", response_model=SpecSectionStatusResponse)
def lock_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: LockSpecSectionRequest):
    """Lock a section to prevent modifications."""
    store.lock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "locked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/unlock", response_model=SpecSectionStatusResponse)
def unlock_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: LockSpecSectionRequest):
    """Unlock a section to allow modifications."""
    store.unlock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "unlocked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/approve", response_model=SpecStatusResponse)
def approve_full_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: ApproveSpecRequest):
    """Approve the full Research Specification (Gate 1)."""
    ok = store.approve_full_spec(spec_id, req.reviewer)
    if not ok:
        raise HTTPException(
            400,
            "Cannot approve — blocking issues remain. Resolve all blocking "
            "clarifications and fill mandatory sections first.",
        )
    return {"status": "approved", "spec_id": spec_id}


@router.post("/spec/{spec_id}/reject", response_model=SpecStatusResponse)
def reject_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: RejectSpecRequest):
    """Reject / request revision of the Research Specification."""
    store.reject_spec(spec_id, req.reason, req.reviewer)
    return {"status": "revision_requested", "spec_id": spec_id}


@router.post("/spec/{spec_id}/regenerate", response_model=GeneratedSpecResponse)
def regenerate_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: RegenerateSpecRequest):
    """Regenerate a specification (preserves locked/approved sections by default)."""
    try:
        llm_client = None
        if req.use_llm:
            llm_client = get_llm_client()
            if not llm_client or not llm_client.is_reachable():
                raise HTTPException(503, "No LLM provider available — ensure Ollama is running or ANTHROPIC_API_KEY is set")
        result = rss.regenerate_spec(
            spec_id=spec_id,
            raw_brief_text=req.raw_brief_text,
            use_llm=req.use_llm,
            llm_client=llm_client,
            confirm_overwrite_locked=req.confirm_overwrite_locked,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to regenerate specification")
        raise HTTPException(500, f"Regeneration failed: {e}")


@router.get("/spec/{spec_id}/readiness", response_model=SpecReadinessResponse)
def get_spec_readiness_endpoint(spec_id: Annotated[int, Path(ge=1)]):
    """Get the readiness status of a specification."""
    readiness = store.get_spec_readiness(spec_id)
    if readiness is None:
        raise HTTPException(404, "Specification not found")
    return readiness


@router.post("/spec/{spec_id}/render", response_model=SpecRenderResponse)
def render_spec_docx(spec_id: Annotated[int, Path(ge=1)]):
    """Render the Research Specification as a Word document."""
    try:
        filepath = rsr.render_spec_docx(spec_id)
        return {"status": "rendered", "docx_path": filepath}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to render specification")
        raise HTTPException(500, f"Render failed: {e}")


@router.get("/spec/{spec_id}/download", response_class=FileResponse)
def download_spec_docx(spec_id: Annotated[int, Path(ge=1)]):
    """Download the rendered Word document for a specification."""
    spec_row = store.get_spec_by_id(spec_id)
    if not spec_row:
        raise HTTPException(404, "Specification not found")
    docx_path = spec_row.get("docx_path")
    if not docx_path or not os.path.isfile(docx_path):
        raise HTTPException(404, "Word document not yet generated. Call /spec/{id}/render first.")
    filename = os.path.basename(docx_path)
    return FileResponse(
        path=docx_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/spec/versions/{project_id}", response_model=list[SpecVersionItem])
def list_spec_versions_endpoint(project_id: Annotated[int, Path(ge=1)]):
    """List all specification versions for a project."""
    return store.list_spec_versions(project_id)


@router.get("/spec/{spec_id}/audit", response_model=list[SpecAuditEntry])
def get_spec_audit_endpoint(spec_id: Annotated[int, Path(ge=1)]):
    """Get audit trail for a specification."""
    return store.get_spec_audit(spec_id)


@router.get("/spec/{spec_id}/clarifications", response_model=list[SpecClarification])
def get_spec_clarifications(spec_id: Annotated[int, Path(ge=1)], unresolved_only: bool = False):
    """Get clarifications for a specification."""
    return store.get_clarifications(spec_id, unresolved_only=unresolved_only)


@router.post("/spec/{spec_id}/clarification", response_model=ClarificationStatusResponse)
def add_spec_clarification(spec_id: Annotated[int, Path(ge=1)], req: AddClarificationRequest):
    """Add a new clarification question."""
    cid = store.add_clarification(
        spec_id=spec_id,
        question=req.question,
        section_key=req.section_key,
        is_blocking=req.is_blocking,
    )
    return {"status": "added", "clarification_id": cid}


@router.post("/spec/clarification/{clarification_id}/resolve", response_model=ClarificationStatusResponse)
def resolve_spec_clarification(clarification_id: Annotated[int, Path(ge=1)], req: ResolveClarificationRequest):
    """Resolve a clarification question."""
    ok = store.resolve_clarification(clarification_id, req.answer, req.resolved_by)
    if not ok:
        raise HTTPException(404, "Clarification not found")
    return {"status": "resolved", "clarification_id": clarification_id}

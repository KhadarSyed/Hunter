"""Research Specification routes: generate, sections, approve, render, clarifications."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from starlette.responses import FileResponse

from ...core import store
from ...core.llm_provider import get_llm_client
from ...core.auth import (
    check_project_id_access,
    get_current_user,
    require_clarification_access,
    require_project_access,
    require_spec_access,
)
from ..agent import autorun
from ..memory import service as memory
from ...core.events import broadcast as _broadcast
from ...core.jobs import launch, resumable
from . import renderer as rsr
from . import service as rss
from .schemas import (
    AddClarificationRequest,
    ApproveSpecRequest,
    ApproveSpecSectionRequest,
    ClarificationStatusResponse,
    GenerateSpecRequest,
    LockSpecSectionRequest,
    RegenerateSpecRequest,
    RejectSpecRequest,
    ResolveClarificationRequest,
    SpecAuditEntry,
    SpecClarification,
    SpecGenerationStarted,
    SpecReadinessResponse,
    SpecRenderResponse,
    SpecResponse,
    SpecSectionStatusResponse,
    SpecStatusResponse,
    SpecVersionItem,
    UpdateSpecIndustryRequest,
    UpdateSpecSectionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

JOB_TYPE_SPEC_GENERATION = "spec_generation"
_LLM_STAGE_END_PCT = 55  # progress reached once brief_scope's interpret/retry loop finishes


def _spec_progress(step: str, payload: dict) -> tuple[int | None, str]:
    """(progress_pct or None-to-keep-current, human message) for a generate_spec() emit step."""
    if step == "brief_scope_started":
        return 10, "Reading the brief"
    if step == "brief_scope_reasoning":
        return None, "Briefing under progress..."
    if step == "brief_scope_streaming":
        chars = payload.get("chars", 0)
        return None, f"Agent writing specification... ({chars:,} characters generated so far)"
    if step == "brief_scope_attempt":
        attempt = payload.get("attempt", 1)
        return min(10 + attempt * 15, _LLM_STAGE_END_PCT - 5), f"Agent interpreting brief (attempt {attempt})"
    if step == "brief_scope_validated":
        attempt = payload.get("attempt", 1)
        errors, warnings = payload.get("errors", 0), payload.get("warnings", 0)
        pct = min(15 + attempt * 15, _LLM_STAGE_END_PCT)
        if errors:
            return pct, f"Attempt {attempt}: {errors} rule(s) not yet met — asking the agent to correct and retry"
        return pct, f"Attempt {attempt}: all rules met" + (f" ({warnings} minor warning(s))" if warnings else "")
    if step == "brief_scope_error":
        return None, payload.get("error", "Agent call issue — retrying")
    if step == "brief_scope_failed":
        return _LLM_STAGE_END_PCT, "Agent could not interpret the brief after retries"
    if step == "brief_scope_complete":
        client = payload.get("client", "")
        entities = payload.get("entity_count", 0)
        return _LLM_STAGE_END_PCT, f"Identified {client or 'the brand'} and {entities} entit{'y' if entities == 1 else 'ies'}"
    if step == "merging_form_context":
        return 60, "Applying your project details (client, geography, time period, research type)"
    if step == "building_sections":
        return 70, "Building the 20-section specification"
    if step == "identifying_clarifications":
        return 80, "Identifying open questions"
    if step == "saving":
        return 90, "Saving specification"
    if step == "done":
        return 100, "Specification ready"
    return None, step


@resumable(JOB_TYPE_SPEC_GENERATION)
def _spec_job(job_id: str, project_id: int, *, raw_brief_text: str, use_llm: bool, spec_id: int | None = None,
              confirm_overwrite_locked: bool = False) -> None:
    """Generate the project's spec, or re-analyse spec_id ("Reanalyze"), streaming progress as intel_job_update."""
    last_pct = 5

    def send(status: str, message: str, **extra) -> None:
        _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": project_id,
                    "job_type": JOB_TYPE_SPEC_GENERATION, "status": status, "progress_pct": last_pct,
                    "message": message, **extra})

    store.update_job(job_id, status="running", progress_pct=last_pct, progress_message="Starting")
    send("running", "Starting")

    def on_event(step: str, payload: dict) -> None:
        nonlocal last_pct
        pct, msg = _spec_progress(step, payload)
        if pct is not None:
            last_pct = pct
        store.update_job(job_id, progress_pct=last_pct, progress_message=msg)
        send("running", msg, step=step)

    try:
        llm_client = get_llm_client() if use_llm else None
        if spec_id is None:
            result = rss.generate_spec(project_id=project_id, raw_brief_text=raw_brief_text, use_llm=use_llm,
                                       llm_client=llm_client, emit=on_event)
        else:
            with memory.fresh():        # Reanalyze asks GPT again instead of recalling the last answer
                result = rss.regenerate_spec(spec_id=spec_id, raw_brief_text=raw_brief_text, use_llm=use_llm,
                                             llm_client=llm_client, confirm_overwrite_locked=confirm_overwrite_locked,
                                             emit=on_event)
        last_pct = 100
        store.update_job(job_id, status="completed", progress_pct=100, progress_message="Specification ready",
                         result={"spec_id": result["spec_id"]})
        send("completed", "Specification ready", spec_id=result["spec_id"])
    except ValueError as e:
        logger.warning("Spec job %s for project %s: %s", job_id, project_id, e)
        store.update_job(job_id, status="failed", error=str(e))
        send("failed", str(e))
    except Exception as e:
        logger.exception("Spec job %s for project %s failed", job_id, project_id)
        store.update_job(job_id, status="failed", error=str(e))
        send("failed", f"{'Regeneration' if spec_id else 'Specification generation'} failed: {e}")


@router.post("/spec/generate", response_model=SpecGenerationStarted)
def generate_research_spec(req: GenerateSpecRequest, user: Annotated[dict, Depends(get_current_user)]):
    """Start Research Specification generation as a background job.

    Returns immediately with a job_id; progress and the final result stream over the
    shared /ws socket as `intel_job_update` messages (see _spec_progress for the step ->
    percent/message mapping) and are also readable via GET /job/{job_id}.
    """
    check_project_id_access(req.project_id, user)

    llm_client = None
    if req.use_llm:
        llm_client = get_llm_client()
        if not llm_client or not llm_client.is_reachable():
            raise HTTPException(503, "No LLM provider available — set AZURE_OPENAI_API_KEY, "
                                     "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL")

    job_id = launch(JOB_TYPE_SPEC_GENERATION, f"spec_{uuid.uuid4().hex[:12]}", req.project_id,
                    raw_brief_text=req.raw_brief_text, use_llm=req.use_llm)
    return SpecGenerationStarted(job_id=job_id, project_id=req.project_id)


@router.get("/spec/{project_id}", response_model=SpecResponse)
def get_research_spec(project_id: Annotated[int, Path(ge=1)],
                       _access: Annotated[dict, Depends(require_project_access)]):
    """Get the latest Research Specification for a project."""
    spec = store.get_latest_spec(project_id)
    if not spec:
        raise HTTPException(404, "No research specification found for this project")
    return spec


@router.get("/spec/detail/{spec_id}", response_model=SpecResponse, dependencies=[Depends(require_spec_access)])
def get_spec_detail(spec_id: Annotated[int, Path(ge=1)]):
    """Get a specific Research Specification by ID."""
    spec = store.get_spec_by_id(spec_id)
    if not spec:
        raise HTTPException(404, "Specification not found")
    return spec


@router.post("/spec/{spec_id}/section", response_model=SpecSectionStatusResponse, dependencies=[Depends(require_spec_access)])
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


@router.post("/spec/{spec_id}/industry", response_model=SpecStatusResponse, dependencies=[Depends(require_spec_access)])
def update_spec_industry_endpoint(spec_id: Annotated[int, Path(ge=1)], req: UpdateSpecIndustryRequest):
    """Update the industry classification (a top-level field, not a section)."""
    ok = store.update_spec_industry(spec_id, req.name.strip(), req.reasoning.strip())
    if not ok:
        raise HTTPException(404, "Specification not found")
    return {"status": "updated", "spec_id": spec_id}


@router.post("/spec/{spec_id}/section/approve", response_model=SpecSectionStatusResponse, dependencies=[Depends(require_spec_access)])
def approve_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: ApproveSpecSectionRequest):
    """Approve a single section of a specification."""
    store.approve_spec_section(spec_id, req.section_key, req.reviewer)
    return {"status": "approved", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/lock", response_model=SpecSectionStatusResponse, dependencies=[Depends(require_spec_access)])
def lock_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: LockSpecSectionRequest):
    """Lock a section to prevent modifications."""
    store.lock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "locked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/unlock", response_model=SpecSectionStatusResponse, dependencies=[Depends(require_spec_access)])
def unlock_spec_section_endpoint(spec_id: Annotated[int, Path(ge=1)], req: LockSpecSectionRequest):
    """Unlock a section to allow modifications."""
    store.unlock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "unlocked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/approve", response_model=SpecStatusResponse, dependencies=[Depends(require_spec_access)])
def approve_full_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: ApproveSpecRequest,
                               user: Annotated[dict, Depends(get_current_user)]):
    """Approve the full Research Specification (Gate 1)."""
    ok = store.approve_full_spec(spec_id, req.reviewer)
    if not ok:
        raise HTTPException(
            400,
            "Cannot approve — blocking issues remain. Resolve all blocking "
            "clarifications and fill mandatory sections first.",
        )
    # every approval (Approve, Save, the API) starts the chain to Data Sources; the agent's autopilot runs those
    # steps itself, and a project that already has research is not researched again
    project_id = (store.get_spec_by_id(spec_id) or {}).get("project_id")
    if project_id and not req.reviewer.startswith("hunter-agent:") and not store.get_latest_research(project_id):
        autorun.start(project_id, user["id"])
    return {"status": "approved", "spec_id": spec_id}


@router.post("/spec/{spec_id}/reject", response_model=SpecStatusResponse, dependencies=[Depends(require_spec_access)])
def reject_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: RejectSpecRequest):
    """Reject / request revision of the Research Specification."""
    store.reject_spec(spec_id, req.reason, req.reviewer)
    return {"status": "revision_requested", "spec_id": spec_id}


@router.post("/spec/{spec_id}/regenerate", response_model=SpecGenerationStarted, dependencies=[Depends(require_spec_access)])
def regenerate_spec_endpoint(spec_id: Annotated[int, Path(ge=1)], req: RegenerateSpecRequest):
    """Start re-analysis ("Reanalyze") of an existing spec as a background job — same
    async/streaming pattern as /spec/generate. Preserves locked/approved sections unless
    ``confirm_overwrite_locked`` is set."""
    existing = store.get_spec_by_id(spec_id)
    if not existing:
        raise HTTPException(404, f"Spec {spec_id} not found")
    project_id = existing["project_id"]

    llm_client = None
    if req.use_llm:
        llm_client = get_llm_client()
        if not llm_client or not llm_client.is_reachable():
            raise HTTPException(503, "No LLM provider available — set AZURE_OPENAI_API_KEY, "
                                     "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL")

    job_id = launch(JOB_TYPE_SPEC_GENERATION, f"spec_{uuid.uuid4().hex[:12]}", project_id,
                    raw_brief_text=req.raw_brief_text, use_llm=req.use_llm, spec_id=spec_id,
                    confirm_overwrite_locked=req.confirm_overwrite_locked)
    return SpecGenerationStarted(job_id=job_id, project_id=project_id)


@router.get("/spec/{spec_id}/readiness", response_model=SpecReadinessResponse, dependencies=[Depends(require_spec_access)])
def get_spec_readiness_endpoint(spec_id: Annotated[int, Path(ge=1)]):
    """Get the readiness status of a specification."""
    readiness = store.get_spec_readiness(spec_id)
    if readiness is None:
        raise HTTPException(404, "Specification not found")
    return readiness


@router.post("/spec/{spec_id}/render", response_model=SpecRenderResponse, dependencies=[Depends(require_spec_access)])
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


@router.get("/spec/{spec_id}/download", response_class=FileResponse, dependencies=[Depends(require_spec_access)])
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
def list_spec_versions_endpoint(project_id: Annotated[int, Path(ge=1)],
                                 _access: Annotated[dict, Depends(require_project_access)]):
    """List all specification versions for a project."""
    return store.list_spec_versions(project_id)


@router.get("/spec/{spec_id}/audit", response_model=list[SpecAuditEntry], dependencies=[Depends(require_spec_access)])
def get_spec_audit_endpoint(spec_id: Annotated[int, Path(ge=1)]):
    """Get audit trail for a specification."""
    return store.get_spec_audit(spec_id)


@router.get("/spec/{spec_id}/clarifications", response_model=list[SpecClarification], dependencies=[Depends(require_spec_access)])
def get_spec_clarifications(spec_id: Annotated[int, Path(ge=1)], unresolved_only: bool = False):
    """Get clarifications for a specification."""
    return store.get_clarifications(spec_id, unresolved_only=unresolved_only)


@router.post("/spec/{spec_id}/clarification", response_model=ClarificationStatusResponse, dependencies=[Depends(require_spec_access)])
def add_spec_clarification(spec_id: Annotated[int, Path(ge=1)], req: AddClarificationRequest):
    """Add a new clarification question."""
    cid = store.add_clarification(
        spec_id=spec_id,
        question=req.question,
        section_key=req.section_key,
        is_blocking=req.is_blocking,
    )
    return {"status": "added", "clarification_id": cid}


@router.post("/spec/clarification/{clarification_id}/resolve", response_model=ClarificationStatusResponse, dependencies=[Depends(require_clarification_access)])
def resolve_spec_clarification(clarification_id: Annotated[int, Path(ge=1)], req: ResolveClarificationRequest):
    """Resolve a clarification question."""
    ok = store.resolve_clarification(clarification_id, req.answer, req.resolved_by)
    if not ok:
        raise HTTPException(404, "Clarification not found")
    return {"status": "resolved", "clarification_id": clarification_id}

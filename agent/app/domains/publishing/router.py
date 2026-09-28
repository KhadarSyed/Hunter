"""Publishing Gateway routes: validate, package, version, approvals, downloads."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from ...core import store
from . import service as pub
from .schemas import (
    ApprovalActionResponse,
    CompareOutputsResponse,
    PackageBuildResponse,
    PubApproval,
    PubApprovalRequest,
    PubAuditEntry,
    PubDiffReport,
    PubDownload,
    PublishResponse,
    PubPackage,
    PubPackageRequest,
    PubStats,
    PubValidateRequest,
    PubValidation,
    PubVersion,
    PubVersionRequest,
    ReadinessSummaryResponse,
    ValidationRunResponse,
    VersionCreateResponse,
)

router = APIRouter()

IdPath = Annotated[int, PathParam(ge=1)]
LimitQuery = Annotated[int, Query(ge=1, le=1000)]


@router.post("/publishing/validate", response_model=ValidationRunResponse)
def pub_validate_route(req: PubValidateRequest):
    result = pub.run_validation(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/compare", response_model=CompareOutputsResponse)
def pub_compare_route(req: PubValidateRequest):
    result = pub.compare_outputs(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/package", response_model=PackageBuildResponse)
def pub_package_route(req: PubPackageRequest):
    result = pub.build_package(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/version", response_model=VersionCreateResponse)
def pub_version_route(req: PubVersionRequest):
    result = pub.create_version(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/submit", response_model=ApprovalActionResponse)
def pub_submit_route(req: PubApprovalRequest):
    result = pub.submit_for_review(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/approve", response_model=ApprovalActionResponse)
def pub_approve_route(req: PubApprovalRequest):
    result = pub.approve_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/reject", response_model=ApprovalActionResponse)
def pub_reject_route(req: PubApprovalRequest):
    result = pub.reject_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/revision", response_model=ApprovalActionResponse)
def pub_revision_route(req: PubApprovalRequest):
    result = pub.request_revision(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/publish", response_model=PublishResponse)
def pub_publish_route(req: PubApprovalRequest):
    result = pub.publish_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/archive", response_model=ApprovalActionResponse)
def pub_archive_route(req: PubApprovalRequest):
    result = pub.archive_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/publishing/readiness/{project_id}/{pres_id}", response_model=ReadinessSummaryResponse)
def pub_readiness_route(project_id: IdPath, pres_id: IdPath):
    return pub.get_readiness_summary(project_id, pres_id)


@router.get("/publishing/versions/{pres_id}", response_model=list[PubVersion])
def pub_versions_route(pres_id: IdPath):
    return pub.list_versions(pres_id)


@router.get("/publishing/audit/{project_id}", response_model=list[PubAuditEntry])
def pub_audit_route(project_id: IdPath, limit: LimitQuery = 100):
    return pub.get_audit_trail(project_id, limit)


@router.get("/publishing/validation/{validation_id}", response_model=PubValidation)
def pub_validation_detail_route(validation_id: IdPath):
    result = store.get_pub_validation(validation_id)
    if not result:
        raise HTTPException(404, "Validation not found")
    return result


@router.get("/publishing/validations/{pres_id}", response_model=list[PubValidation])
def pub_validations_list_route(pres_id: IdPath):
    return store.list_pub_validations(pres_id)


@router.get("/publishing/diff/{pres_id}", response_model=PubDiffReport)
def pub_diff_route(pres_id: IdPath):
    result = store.get_latest_diff_report(pres_id)
    if not result:
        raise HTTPException(404, "No difference report found")
    return result


@router.get("/publishing/package/{package_id}", response_model=PubPackage)
def pub_package_detail_route(package_id: IdPath):
    result = store.get_pub_package(package_id)
    if not result:
        raise HTTPException(404, "Package not found")
    return result


@router.get("/publishing/packages/{pres_id}", response_model=list[PubPackage])
def pub_packages_list_route(pres_id: IdPath):
    return store.list_pub_packages(pres_id)


@router.get("/publishing/download/package/{package_id}", response_class=FileResponse)
def pub_download_package_route(package_id: IdPath):
    path = pub.get_download_path(package_id)
    if not path:
        raise HTTPException(404, "Package not found or not ready")
    filename = Path(path).name
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.get("/publishing/download/pptx/{pres_id}", response_class=FileResponse)
def pub_download_pptx_route(pres_id: IdPath):
    path = pub.get_pptx_download_path(pres_id)
    if not path:
        raise HTTPException(404, "PowerPoint file not found")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=filename)


@router.get("/publishing/download/word/{pres_id}", response_class=FileResponse)
def pub_download_word_route(pres_id: IdPath):
    path = pub.get_word_download_path(pres_id)
    if not path:
        raise HTTPException(404, "Word file not found")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=filename)


@router.get("/publishing/downloads/{project_id}", response_model=list[PubDownload])
def pub_downloads_list_route(project_id: IdPath, limit: LimitQuery = 50):
    return store.list_pub_downloads(project_id, limit)


@router.get("/publishing/approvals/{pres_id}", response_model=list[PubApproval])
def pub_approvals_route(pres_id: IdPath, limit: LimitQuery = 50):
    return store.list_pub_approvals(pres_id, limit)


@router.get("/publishing/stats/{project_id}", response_model=PubStats)
def pub_stats_route(project_id: IdPath):
    return store.get_pub_stats(project_id)

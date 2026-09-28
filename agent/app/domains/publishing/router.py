"""Publishing Gateway routes: validate, package, version, approvals, downloads."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...core import store
from . import service as pub
from .schemas import (
    PubApprovalRequest,
    PubPackageRequest,
    PubValidateRequest,
    PubVersionRequest,
)

router = APIRouter()


@router.post("/publishing/validate")
def pub_validate_route(req: PubValidateRequest):
    result = pub.run_validation(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/compare")
def pub_compare_route(req: PubValidateRequest):
    result = pub.compare_outputs(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/package")
def pub_package_route(req: PubPackageRequest):
    result = pub.build_package(req.project_id, req.presentation_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/version")
def pub_version_route(req: PubVersionRequest):
    result = pub.create_version(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/submit")
def pub_submit_route(req: PubApprovalRequest):
    result = pub.submit_for_review(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/approve")
def pub_approve_route(req: PubApprovalRequest):
    result = pub.approve_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/reject")
def pub_reject_route(req: PubApprovalRequest):
    result = pub.reject_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/revision")
def pub_revision_route(req: PubApprovalRequest):
    result = pub.request_revision(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/publish")
def pub_publish_route(req: PubApprovalRequest):
    result = pub.publish_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/publishing/archive")
def pub_archive_route(req: PubApprovalRequest):
    result = pub.archive_deliverable(req.project_id, req.presentation_id, req.actor, req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/publishing/readiness/{project_id}/{pres_id}")
def pub_readiness_route(project_id: int, pres_id: int):
    return pub.get_readiness_summary(project_id, pres_id)


@router.get("/publishing/versions/{pres_id}")
def pub_versions_route(pres_id: int):
    return pub.list_versions(pres_id)


@router.get("/publishing/audit/{project_id}")
def pub_audit_route(project_id: int, limit: int = 100):
    return pub.get_audit_trail(project_id, limit)


@router.get("/publishing/validation/{validation_id}")
def pub_validation_detail_route(validation_id: int):
    result = store.get_pub_validation(validation_id)
    if not result:
        raise HTTPException(404, "Validation not found")
    return result


@router.get("/publishing/validations/{pres_id}")
def pub_validations_list_route(pres_id: int):
    return store.list_pub_validations(pres_id)


@router.get("/publishing/diff/{pres_id}")
def pub_diff_route(pres_id: int):
    result = store.get_latest_diff_report(pres_id)
    if not result:
        raise HTTPException(404, "No difference report found")
    return result


@router.get("/publishing/package/{package_id}")
def pub_package_detail_route(package_id: int):
    result = store.get_pub_package(package_id)
    if not result:
        raise HTTPException(404, "Package not found")
    return result


@router.get("/publishing/packages/{pres_id}")
def pub_packages_list_route(pres_id: int):
    return store.list_pub_packages(pres_id)


@router.get("/publishing/download/package/{package_id}")
def pub_download_package_route(package_id: int):
    path = pub.get_download_path(package_id)
    if not path:
        raise HTTPException(404, "Package not found or not ready")
    filename = Path(path).name
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.get("/publishing/download/pptx/{pres_id}")
def pub_download_pptx_route(pres_id: int):
    path = pub.get_pptx_download_path(pres_id)
    if not path:
        raise HTTPException(404, "PowerPoint file not found")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=filename)


@router.get("/publishing/download/word/{pres_id}")
def pub_download_word_route(pres_id: int):
    path = pub.get_word_download_path(pres_id)
    if not path:
        raise HTTPException(404, "Word file not found")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=filename)


@router.get("/publishing/downloads/{project_id}")
def pub_downloads_list_route(project_id: int, limit: int = 50):
    return store.list_pub_downloads(project_id, limit)


@router.get("/publishing/approvals/{pres_id}")
def pub_approvals_route(pres_id: int, limit: int = 50):
    return store.list_pub_approvals(pres_id, limit)


@router.get("/publishing/stats/{project_id}")
def pub_stats_route(project_id: int):
    return store.get_pub_stats(project_id)

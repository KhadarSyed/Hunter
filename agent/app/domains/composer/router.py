"""Presentation Composer routes, plus SOV / theme-archetype analysis routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core import store
from ..insights import sov_analyzer, theme_classifier
from . import service as pc
from .schemas import (
    ApprovePCRequest,
    GeneratePresentationRequest,
    ReorderPCSlidesRequest,
    ReviewPCSlideRequest,
    SelectLayoutRequest,
    SelectVisualRequest,
    UpdatePCSlideRequest,
)

router = APIRouter()


@router.post("/composer/generate")
def generate_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.post("/composer/validate-prereqs")
def validate_composer_prereqs(req: GeneratePresentationRequest):
    return pc.validate_prerequisites(req.project_id)


@router.post("/sov/generate")
def generate_sov_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_sov_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/analyze/{project_id}")
def analyze_sov_route(project_id: int):
    result = sov_analyzer.analyze_sov(project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/themes/{project_id}/{entity_name}")
def classify_themes_route(project_id: int, entity_name: str):
    result = theme_classifier.classify_themes(project_id, entity_name)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/composer/{project_id}")
def list_presentations(project_id: int):
    return store.list_pc_presentations(project_id)


@router.get("/composer/{project_id}/summary")
def get_presentation_summary(project_id: int):
    return pc.get_presentation_summary(project_id)


@router.get("/composer/detail/{pres_id}")
def get_presentation_detail(pres_id: int):
    result = pc.get_presentation_detail(pres_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/composer/slides/{pres_id}")
def list_pc_slides(pres_id: int):
    return store.list_pc_slides(pres_id)


@router.get("/composer/slide/{slide_id}")
def get_pc_slide(slide_id: int):
    slide = store.get_pc_slide(slide_id)
    if not slide:
        raise HTTPException(404, f"Slide {slide_id} not found")
    return slide


@router.put("/composer/slide/{slide_id}")
def update_pc_slide_route(slide_id: int, req: UpdatePCSlideRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = pc.update_slide(slide_id, updates)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/review")
def review_pc_slide(slide_id: int, req: ReviewPCSlideRequest):
    result = pc.review_slide(slide_id, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/lock")
def lock_pc_slide(slide_id: int):
    result = pc.lock_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/unlock")
def unlock_pc_slide(slide_id: int):
    result = pc.unlock_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/layout")
def select_slide_layout(slide_id: int, req: SelectLayoutRequest):
    result = pc.select_layout(slide_id, req.layout, req.rationale)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/visual")
def select_slide_visual(slide_id: int, req: SelectVisualRequest):
    result = pc.select_visual(slide_id, req.visual)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/reorder")
def reorder_pc_slides_route(pres_id: int, req: ReorderPCSlidesRequest):
    result = pc.reorder_slides(pres_id, req.slide_ids)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/approve")
def approve_presentation_route(pres_id: int, req: ApprovePCRequest):
    result = pc.approve_presentation(pres_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/reject")
def reject_presentation_route(pres_id: int, req: ApprovePCRequest):
    result = pc.reject_presentation(pres_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/composer/{pres_id}/validate")
def validate_presentation_route(pres_id: int):
    return pc.validate_presentation(pres_id)


@router.post("/composer/{pres_id}/transitions")
def generate_transitions_route(pres_id: int):
    return pc.generate_transitions(pres_id)


@router.get("/composer/audit/{pres_id}")
def get_pc_audit(pres_id: int, limit: int = 100):
    return store.get_pc_audit(pres_id, limit)

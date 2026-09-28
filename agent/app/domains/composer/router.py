"""Presentation Composer routes, plus SOV / theme-archetype analysis routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from ...core import store
from ..insights import sov_analyzer, theme_classifier
from . import service as pc
from .schemas import (
    ApprovePCRequest,
    GeneratePresentationRequest,
    GeneratePresentationResponse,
    GenerateSOVPresentationResponse,
    PCAuditEntry,
    PCPresentation,
    PCSlide,
    PrerequisiteCheckResponse,
    PresentationDetailResponse,
    PresentationSummaryResponse,
    PresentationValidationResponse,
    ReorderPCSlidesRequest,
    ReorderSlidesResponse,
    ReviewPCSlideRequest,
    SelectLayoutRequest,
    SelectVisualRequest,
    SOVAnalysisResponse,
    ThemeClassificationResponse,
    TransitionsResponse,
    UpdatePCSlideRequest,
)

router = APIRouter()

IdPath = Annotated[int, Path(ge=1)]


@router.post("/composer/generate", response_model=GeneratePresentationResponse)
def generate_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.post("/composer/validate-prereqs", response_model=PrerequisiteCheckResponse)
def validate_composer_prereqs(req: GeneratePresentationRequest):
    return pc.validate_prerequisites(req.project_id)


@router.post("/sov/generate", response_model=GenerateSOVPresentationResponse)
def generate_sov_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_sov_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/analyze/{project_id}", response_model=SOVAnalysisResponse)
def analyze_sov_route(project_id: IdPath):
    result = sov_analyzer.analyze_sov(project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/themes/{project_id}/{entity_name}", response_model=ThemeClassificationResponse)
def classify_themes_route(project_id: IdPath, entity_name: str):
    result = theme_classifier.classify_themes(project_id, entity_name)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/composer/{project_id}", response_model=list[PCPresentation])
def list_presentations(project_id: IdPath):
    return store.list_pc_presentations(project_id)


@router.get("/composer/{project_id}/summary", response_model=PresentationSummaryResponse)
def get_presentation_summary(project_id: IdPath):
    return pc.get_presentation_summary(project_id)


@router.get("/composer/detail/{pres_id}", response_model=PresentationDetailResponse)
def get_presentation_detail(pres_id: IdPath):
    result = pc.get_presentation_detail(pres_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/composer/slides/{pres_id}", response_model=list[PCSlide])
def list_pc_slides(pres_id: IdPath):
    return store.list_pc_slides(pres_id)


@router.get("/composer/slide/{slide_id}", response_model=PCSlide)
def get_pc_slide(slide_id: IdPath):
    slide = store.get_pc_slide(slide_id)
    if not slide:
        raise HTTPException(404, f"Slide {slide_id} not found")
    return slide


@router.put("/composer/slide/{slide_id}", response_model=PCSlide)
def update_pc_slide_route(slide_id: IdPath, req: UpdatePCSlideRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = pc.update_slide(slide_id, updates)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/review", response_model=PCSlide)
def review_pc_slide(slide_id: IdPath, req: ReviewPCSlideRequest):
    result = pc.review_slide(slide_id, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/lock", response_model=PCSlide)
def lock_pc_slide(slide_id: IdPath):
    result = pc.lock_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/unlock", response_model=PCSlide)
def unlock_pc_slide(slide_id: IdPath):
    result = pc.unlock_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/layout", response_model=PCSlide)
def select_slide_layout(slide_id: IdPath, req: SelectLayoutRequest):
    result = pc.select_layout(slide_id, req.layout, req.rationale)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/slide/{slide_id}/visual", response_model=PCSlide)
def select_slide_visual(slide_id: IdPath, req: SelectVisualRequest):
    result = pc.select_visual(slide_id, req.visual)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/reorder", response_model=ReorderSlidesResponse)
def reorder_pc_slides_route(pres_id: IdPath, req: ReorderPCSlidesRequest):
    result = pc.reorder_slides(pres_id, req.slide_ids)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/approve", response_model=PCPresentation)
def approve_presentation_route(pres_id: IdPath, req: ApprovePCRequest):
    result = pc.approve_presentation(pres_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/composer/{pres_id}/reject", response_model=PCPresentation)
def reject_presentation_route(pres_id: IdPath, req: ApprovePCRequest):
    result = pc.reject_presentation(pres_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/composer/{pres_id}/validate", response_model=PresentationValidationResponse)
def validate_presentation_route(pres_id: IdPath):
    return pc.validate_presentation(pres_id)


@router.post("/composer/{pres_id}/transitions", response_model=TransitionsResponse)
def generate_transitions_route(pres_id: IdPath):
    return pc.generate_transitions(pres_id)


@router.get("/composer/audit/{pres_id}", response_model=list[PCAuditEntry])
def get_pc_audit(pres_id: IdPath, limit: Annotated[int, Query(ge=1, le=1000)] = 100):
    return store.get_pc_audit(pres_id, limit)

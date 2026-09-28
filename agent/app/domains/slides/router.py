"""Slide Intelligence routes: ingest, search, retrieve, templates, storyline matching."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from ...core import store
from . import service as si
from .schemas import (
    DetectedProjectRecord,
    DuplicateDetectionResponse,
    IngestPresentationRequest,
    IngestPresentationResponse,
    MatchStorylineRequest,
    NodeRecommendationResponse,
    PresentationRecord,
    PresentationStatusResponse,
    ProcessingLogEntry,
    RetrieveRequest,
    SlideDetailResponse,
    SlideExclusionResponse,
    SlideIntelDashboardResponse,
    SlideMetadataUpdateResponse,
    SlideRecord,
    SlideReprocessResponse,
    SlideRetrievalResponse,
    SlideSearchRequest,
    SlideSearchResponse,
    StorylineMatchesResponse,
    StorylineMatchRunResponse,
    StylePatternRecord,
    TemplateApprovalResponse,
    TemplateDetailResponse,
    TemplateFamilyRecord,
    UpdateSlideMetadataRequest,
)

router = APIRouter()

IdPath = Annotated[int, Path(ge=1)]


@router.post("/slide-intel/ingest", response_model=IngestPresentationResponse)
def ingest_presentation(req: IngestPresentationRequest):
    result = si.ingest_presentation(req.file_path)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/dashboard", response_model=SlideIntelDashboardResponse)
def slide_intel_dashboard():
    return si.get_dashboard()


@router.get("/slide-intel/presentations", response_model=list[PresentationRecord])
def list_presentations():
    return store.list_si_presentations()


@router.get("/slide-intel/presentations/{pres_id}", response_model=PresentationStatusResponse)
def get_presentation(pres_id: IdPath):
    result = si.get_processing_status(pres_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/slides", response_model=list[SlideRecord])
def list_slides(presentation_id: Optional[int] = None,
                slide_purpose: Optional[str] = None,
                layout_type: Optional[str] = None,
                visual_type: Optional[str] = None,
                client: Optional[str] = None,
                report_type: Optional[str] = None,
                search: Optional[str] = None,
                is_excluded: Optional[bool] = None,
                sort_by: str = "slide_number",
                sort_dir: str = "ASC",
                limit: Annotated[int, Query(ge=1, le=5000)] = 200,
                offset: Annotated[int, Query(ge=0)] = 0):
    return store.list_si_slides(
        presentation_id, slide_purpose=slide_purpose, layout_type=layout_type,
        visual_type=visual_type, client=client, report_type=report_type,
        is_excluded=is_excluded, search=search,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )


@router.get("/slide-intel/slides/{slide_id}", response_model=SlideDetailResponse)
def get_slide_detail(slide_id: IdPath):
    result = si.get_slide_detail(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.put("/slide-intel/slides/{slide_id}/metadata", response_model=SlideMetadataUpdateResponse)
def update_slide_metadata(slide_id: IdPath, req: UpdateSlideMetadataRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = si.update_slide_metadata(slide_id, updates)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/exclude", response_model=SlideExclusionResponse)
def exclude_slide(slide_id: IdPath):
    result = si.exclude_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/include", response_model=SlideExclusionResponse)
def include_slide(slide_id: IdPath):
    result = si.include_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/reprocess", response_model=SlideReprocessResponse)
def reprocess_slide(slide_id: IdPath):
    result = si.reprocess_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/templates", response_model=list[TemplateFamilyRecord])
def list_templates():
    return store.list_si_template_families()


@router.get("/slide-intel/templates/{family_id}", response_model=TemplateDetailResponse)
def get_template_detail(family_id: IdPath):
    result = si.get_template_detail(family_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/templates/{family_id}/approve", response_model=TemplateApprovalResponse)
def approve_template(family_id: IdPath):
    result = si.approve_template(family_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/detected-projects/{pres_id}", response_model=list[DetectedProjectRecord])
def list_detected_projects(pres_id: IdPath):
    return store.list_si_detected_projects(pres_id)


@router.get("/slide-intel/style-patterns", response_model=list[StylePatternRecord])
def list_style_patterns(presentation_id: Optional[int] = None,
                        pattern_type: Optional[str] = None):
    return store.list_si_style_patterns(presentation_id, pattern_type)


@router.post("/slide-intel/search", response_model=SlideSearchResponse)
def search_slides(req: SlideSearchRequest):
    filters = {k: v for k, v in req.model_dump().items()
               if k != "query" and k != "limit" and v is not None}
    return si.search_slides(req.query, filters, req.limit)


@router.post("/slide-intel/retrieve", response_model=SlideRetrievalResponse)
def retrieve_slides(req: RetrieveRequest):
    result = si.retrieve_slides(req.node_id, req.top_k)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/slide-intel/match-storyline", response_model=StorylineMatchRunResponse)
def match_storyline(req: MatchStorylineRequest):
    result = si.match_storyline_nodes(req.storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/storyline-matches/{storyline_id}", response_model=StorylineMatchesResponse)
def get_storyline_matches(storyline_id: IdPath):
    result = si.get_storyline_matches(storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/recommend/{node_id}", response_model=NodeRecommendationResponse)
def recommend_for_node(node_id: IdPath):
    result = si.get_node_recommendation(node_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/duplicates", response_model=DuplicateDetectionResponse)
def detect_duplicates(presentation_id: Optional[int] = None):
    return si.detect_duplicates(presentation_id)


@router.get("/slide-intel/processing-log/{pres_id}", response_model=list[ProcessingLogEntry])
def get_processing_log(pres_id: IdPath):
    return store.get_si_processing_logs(pres_id)

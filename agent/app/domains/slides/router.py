"""Slide Intelligence routes: ingest, search, retrieve, templates, storyline matching."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ...core import store
from . import service as si
from .schemas import (
    IngestPresentationRequest,
    MatchStorylineRequest,
    RetrieveRequest,
    SlideSearchRequest,
    UpdateSlideMetadataRequest,
)

router = APIRouter()


@router.post("/slide-intel/ingest")
def ingest_presentation(req: IngestPresentationRequest):
    result = si.ingest_presentation(req.file_path)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/dashboard")
def slide_intel_dashboard():
    return si.get_dashboard()


@router.get("/slide-intel/presentations")
def list_presentations():
    return store.list_si_presentations()


@router.get("/slide-intel/presentations/{pres_id}")
def get_presentation(pres_id: int):
    result = si.get_processing_status(pres_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/slides")
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
                limit: int = 200, offset: int = 0):
    return store.list_si_slides(
        presentation_id, slide_purpose=slide_purpose, layout_type=layout_type,
        visual_type=visual_type, client=client, report_type=report_type,
        is_excluded=is_excluded, search=search,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )


@router.get("/slide-intel/slides/{slide_id}")
def get_slide_detail(slide_id: int):
    result = si.get_slide_detail(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.put("/slide-intel/slides/{slide_id}/metadata")
def update_slide_metadata(slide_id: int, req: UpdateSlideMetadataRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    result = si.update_slide_metadata(slide_id, updates)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/exclude")
def exclude_slide(slide_id: int):
    result = si.exclude_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/include")
def include_slide(slide_id: int):
    result = si.include_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/slides/{slide_id}/reprocess")
def reprocess_slide(slide_id: int):
    result = si.reprocess_slide(slide_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/templates")
def list_templates():
    return store.list_si_template_families()


@router.get("/slide-intel/templates/{family_id}")
def get_template_detail(family_id: int):
    result = si.get_template_detail(family_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/slide-intel/templates/{family_id}/approve")
def approve_template(family_id: int):
    result = si.approve_template(family_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/detected-projects/{pres_id}")
def list_detected_projects(pres_id: int):
    return store.list_si_detected_projects(pres_id)


@router.get("/slide-intel/style-patterns")
def list_style_patterns(presentation_id: Optional[int] = None,
                        pattern_type: Optional[str] = None):
    return store.list_si_style_patterns(presentation_id, pattern_type)


@router.post("/slide-intel/search")
def search_slides(req: SlideSearchRequest):
    filters = {k: v for k, v in req.model_dump().items()
               if k != "query" and k != "limit" and v is not None}
    return si.search_slides(req.query, filters, req.limit)


@router.post("/slide-intel/retrieve")
def retrieve_slides(req: RetrieveRequest):
    result = si.retrieve_slides(req.node_id, req.top_k)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/slide-intel/match-storyline")
def match_storyline(req: MatchStorylineRequest):
    result = si.match_storyline_nodes(req.storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/storyline-matches/{storyline_id}")
def get_storyline_matches(storyline_id: int):
    result = si.get_storyline_matches(storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/slide-intel/recommend/{node_id}")
def recommend_for_node(node_id: int):
    result = si.get_node_recommendation(node_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/slide-intel/duplicates")
def detect_duplicates(presentation_id: Optional[int] = None):
    return si.detect_duplicates(presentation_id)


@router.get("/slide-intel/processing-log/{pres_id}")
def get_processing_log(pres_id: int):
    return store.get_si_processing_logs(pres_id)

"""PowerPoint renderer routes: render, status, download, themes, metrics.

Also contains:
- word_renderer: Word report renderer routes: render, status, download, themes, metrics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from ...core import store
from . import pptx as renderer
from . import word as word_renderer
from .schemas import (
    RenderHistoryEntry,
    RenderJob,
    RenderMetric,
    RenderPresentationRequest,
    RenderPresentationResponse,
    RenderSectionRequest,
    RenderSectionResponse,
    RenderSlideRequest,
    RenderSlideResponse,
    RenderSummaryResponse,
    RenderValidationResponse,
    RenderWordReportRequest,
    RenderWordReportResponse,
    RenderWordSectionRequest,
    RenderWordSectionResponse,
    Theme,
    WordJob,
    WordMetric,
    WordRenderSummaryResponse,
)

router = APIRouter()

IdPath = Annotated[int, PathParam(ge=1)]
LimitQuery = Annotated[int, Query(ge=1, le=1000)]


@router.post("/renderer/render", response_model=RenderPresentationResponse)
def render_presentation_route(req: RenderPresentationRequest):
    result = renderer.render_presentation(req.presentation_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/renderer/render-slide/{slide_id}", response_model=RenderSlideResponse)
def render_slide_route(slide_id: IdPath, req: RenderSlideRequest):
    result = renderer.render_slide(slide_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/renderer/render-section/{pres_id}", response_model=RenderSectionResponse)
def render_section_route(pres_id: IdPath, req: RenderSectionRequest):
    result = renderer.render_section(pres_id, req.purpose, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/renderer/status/{job_id}", response_model=RenderJob)
def render_status_route(job_id: str):
    result = renderer.get_render_status(job_id)
    if not result:
        raise HTTPException(404, "Render job not found")
    return result


@router.get("/renderer/download/{job_id}", response_class=FileResponse)
def download_pptx_route(job_id: str):
    path = renderer.get_download_path(job_id)
    if not path:
        raise HTTPException(404, "File not found or render not complete")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=filename)


@router.get("/renderer/themes", response_model=list[Theme])
def list_themes_route():
    return renderer.list_themes()


@router.post("/renderer/validate/{pres_id}", response_model=RenderValidationResponse)
def validate_for_render_route(pres_id: IdPath):
    return renderer.validate_for_render(pres_id)


@router.get("/renderer/summary/{pres_id}", response_model=RenderSummaryResponse)
def render_summary_route(pres_id: IdPath):
    return renderer.get_render_summary(pres_id)


@router.get("/renderer/jobs/{pres_id}", response_model=list[RenderJob])
def list_render_jobs_route(pres_id: IdPath):
    return store.list_render_jobs(pres_id)


@router.get("/renderer/history/{pres_id}", response_model=list[RenderHistoryEntry])
def render_history_route(pres_id: IdPath, limit: LimitQuery = 50):
    return store.get_render_history(pres_id, limit)


@router.get("/renderer/metrics/{job_id}", response_model=list[RenderMetric])
def render_metrics_route(job_id: str):
    return store.get_render_metrics(job_id)


# ─── Word Renderer ─────────────────────────────────────────────────────

@router.post("/word-renderer/render", response_model=RenderWordReportResponse)
def render_word_report_route(req: RenderWordReportRequest):
    result = word_renderer.render_report(req.presentation_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/word-renderer/render-section/{pres_id}", response_model=RenderWordSectionResponse)
def render_word_section_route(pres_id: IdPath, req: RenderWordSectionRequest):
    result = word_renderer.render_section(pres_id, req.section_name, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/word-renderer/validate/{pres_id}", response_model=RenderValidationResponse)
def validate_word_render_route(pres_id: IdPath):
    return word_renderer.validate_for_render(pres_id)


@router.get("/word-renderer/status/{job_id}", response_model=WordJob)
def word_render_status_route(job_id: str):
    result = word_renderer.get_render_status(job_id)
    if not result:
        raise HTTPException(404, "Word render job not found")
    return result


@router.get("/word-renderer/download/{job_id}", response_class=FileResponse)
def download_word_route(job_id: str):
    path = word_renderer.get_download_path(job_id)
    if not path:
        raise HTTPException(404, "File not found or render not complete")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=filename)


@router.get("/word-renderer/themes", response_model=list[Theme])
def list_word_themes_route():
    return word_renderer.list_themes()


@router.get("/word-renderer/summary/{pres_id}", response_model=WordRenderSummaryResponse)
def word_render_summary_route(pres_id: IdPath):
    return word_renderer.get_render_summary(pres_id)


@router.get("/word-renderer/jobs/{pres_id}", response_model=list[WordJob])
def list_word_jobs_route(pres_id: IdPath):
    return store.list_word_jobs(pres_id)


@router.get("/word-renderer/history/{pres_id}", response_model=list[RenderHistoryEntry])
def word_render_history_route(pres_id: IdPath, limit: LimitQuery = 50):
    return store.get_word_history(pres_id, limit)


@router.get("/word-renderer/metrics/{job_id}", response_model=list[WordMetric])
def word_render_metrics_route(job_id: str):
    return store.get_word_metrics(job_id)

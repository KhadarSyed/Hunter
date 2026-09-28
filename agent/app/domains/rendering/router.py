"""PowerPoint renderer routes: render, status, download, themes, metrics.

Also contains:
- word_renderer: Word report renderer routes: render, status, download, themes, metrics.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...core import store
from . import pptx as renderer
from . import word as word_renderer
from .schemas import (
    RenderPresentationRequest,
    RenderSectionRequest,
    RenderSlideRequest,
    RenderWordReportRequest,
    RenderWordSectionRequest,
)

router = APIRouter()


@router.post("/renderer/render")
def render_presentation_route(req: RenderPresentationRequest):
    result = renderer.render_presentation(req.presentation_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/renderer/render-slide/{slide_id}")
def render_slide_route(slide_id: int, req: RenderSlideRequest):
    result = renderer.render_slide(slide_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/renderer/render-section/{pres_id}")
def render_section_route(pres_id: int, req: RenderSectionRequest):
    result = renderer.render_section(pres_id, req.purpose, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/renderer/status/{job_id}")
def render_status_route(job_id: str):
    result = renderer.get_render_status(job_id)
    if not result:
        raise HTTPException(404, "Render job not found")
    return result


@router.get("/renderer/download/{job_id}")
def download_pptx_route(job_id: str):
    path = renderer.get_download_path(job_id)
    if not path:
        raise HTTPException(404, "File not found or render not complete")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=filename)


@router.get("/renderer/themes")
def list_themes_route():
    return renderer.list_themes()


@router.post("/renderer/validate/{pres_id}")
def validate_for_render_route(pres_id: int):
    return renderer.validate_for_render(pres_id)


@router.get("/renderer/summary/{pres_id}")
def render_summary_route(pres_id: int):
    return renderer.get_render_summary(pres_id)


@router.get("/renderer/jobs/{pres_id}")
def list_render_jobs_route(pres_id: int):
    return store.list_render_jobs(pres_id)


@router.get("/renderer/history/{pres_id}")
def render_history_route(pres_id: int, limit: int = 50):
    return store.get_render_history(pres_id, limit)


@router.get("/renderer/metrics/{job_id}")
def render_metrics_route(job_id: str):
    return store.get_render_metrics(job_id)


# ─── Word Renderer ─────────────────────────────────────────────────────

@router.post("/word-renderer/render")
def render_word_report_route(req: RenderWordReportRequest):
    result = word_renderer.render_report(req.presentation_id, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/word-renderer/render-section/{pres_id}")
def render_word_section_route(pres_id: int, req: RenderWordSectionRequest):
    result = word_renderer.render_section(pres_id, req.section_name, req.theme_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/word-renderer/validate/{pres_id}")
def validate_word_render_route(pres_id: int):
    return word_renderer.validate_for_render(pres_id)


@router.get("/word-renderer/status/{job_id}")
def word_render_status_route(job_id: str):
    result = word_renderer.get_render_status(job_id)
    if not result:
        raise HTTPException(404, "Word render job not found")
    return result


@router.get("/word-renderer/download/{job_id}")
def download_word_route(job_id: str):
    path = word_renderer.get_download_path(job_id)
    if not path:
        raise HTTPException(404, "File not found or render not complete")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=filename)


@router.get("/word-renderer/themes")
def list_word_themes_route():
    return word_renderer.list_themes()


@router.get("/word-renderer/summary/{pres_id}")
def word_render_summary_route(pres_id: int):
    return word_renderer.get_render_summary(pres_id)


@router.get("/word-renderer/jobs/{pres_id}")
def list_word_jobs_route(pres_id: int):
    return store.list_word_jobs(pres_id)


@router.get("/word-renderer/history/{pres_id}")
def word_render_history_route(pres_id: int, limit: int = 50):
    return store.get_word_history(pres_id, limit)


@router.get("/word-renderer/metrics/{job_id}")
def word_render_metrics_route(job_id: str):
    return store.get_word_metrics(job_id)

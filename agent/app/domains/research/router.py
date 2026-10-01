"""Background research routes: start, status, results, approve, revise, news-approval.

Also contains:
- brandfetch: Brandfetch logo lookup route.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from ...agents.brand_intelligence import run as run_bi
from ...core import store
from ...core.anthropic_client import get_llm_client
from ...core.api import OkResponse
from ...core.auth import require_project_access
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from . import brandfetch as brandfetch_client
from . import multi_source as multi_source_module
from . import pexels as pexels_client
from . import video_search
from .schemas import (
    ApproveRequest,
    BrandLogoResponse,
    FetchPreviewRequest,
    FetchPreviewStarted,
    NewsApprovalRequest,
    PexelsImageResponse,
    ResearchApprovalResult,
    ResearchItemsListResponse,
    ResearchItemView,
    ResearchJobStarted,
    ResearchJobStatus,
    ResearchResults,
    RevisionRequest,
    SectionVideoResponse,
    StartResearchRequest,
)
from .web_research import EntityValidator, LiveWebResearchAdapter

logger = logging.getLogger(__name__)

LLM_ENRICHMENT_TIMEOUT = 120

router = APIRouter()


@router.post("/research/start", response_model=ResearchJobStarted)
def start_background_research(req: StartResearchRequest):
    """Start a live background research job."""
    spec = req.spec
    project_id = req.project_id if req.project_id else store.get_or_create_project(spec)
    job_id = f"research_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, project_id, "background_research")

    def worker():
        logger.info("[research:%s] Starting background research for project %s", job_id, project_id)
        store.update_job(job_id, status="running", progress_pct=5,
                         progress_message="Validating brand entity")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 5, "message": "Validating brand entity"})

        try:
            adapter = LiveWebResearchAdapter()

            def on_event(event_type: str, payload: dict):
                msg_map = {
                    "research_started": ("Searching official sources", 10),
                    "research_queries_built": ("Search queries prepared", 15),
                    "fetching_topic": (
                        f"Searching: {payload.get('display_label') or payload.get('topic', '')}", None),
                    "fetch_complete": (
                        f"Fetch complete — {payload.get('items_fetched', 0)} items found", 58),
                    "research_filtering": ("Filtering irrelevant results", 60),
                    "research_deduplicating": ("Removing duplicates", 65),
                    "research_validating_entities": ("Validating entity relevance", 70),
                    "research_entity_validation_complete": ("Entity validation complete", 75),
                    "research_validating_dates": ("Validating publication dates", 80),
                    "research_classifying_sources": ("Classifying source quality", 85),
                    "research_complete": ("Research complete", 95),
                }
                if event_type in msg_map:
                    msg, pct = msg_map[event_type]
                    if event_type == "fetching_topic":
                        idx = payload.get("index", 0)
                        total = payload.get("total", 1)
                        pct = 15 + int(45 * idx / max(total, 1))
                    store.update_job(job_id, progress_pct=pct, progress_message=msg)
                    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                                "progress_pct": pct, "message": msg})

            # ── Stage 1: Web research (single execution) ──
            logger.info("[research:%s] Stage 1 — executing web research", job_id)
            web_result = adapter.run_full_research(spec, project_id=project_id, emit=on_event)

            if web_result.get("status") != "completed" or not web_result.get("web_search_executed"):
                logger.warning("[research:%s] Web search did not fully complete — continuing anyway", job_id)

            # ── Stage 2: Persist web results BEFORE LLM enrichment ──
            logger.info("[research:%s] Stage 2 — persisting validated web results (pre-LLM)", job_id)
            research_id = store.save_background_research(project_id, web_result, None)
            logger.info("[research:%s] Web results persisted as research_id=%s", job_id, research_id)

            # ── Stage 3: LLM enrichment (bounded, non-blocking) ──
            store.update_job(job_id, progress_pct=90,
                             progress_message="LLM enrichment (optional)")
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                         "progress_pct": 90, "message": "LLM enrichment (optional)"})

            llm_client = get_llm_client()
            llm_output = None
            enrichment_status = "web_only"

            if llm_client and llm_client.is_reachable():
                logger.info("[research:%s] LLM reachable — attempting enrichment (timeout=%ss)", job_id, LLM_ENRICHMENT_TIMEOUT)

                def _run_llm():
                    loop = asyncio.new_event_loop()
                    bi_result = loop.run_until_complete(
                        run_bi(spec, emit=on_event, llm_client=llm_client, web_adapter=None)
                    )
                    loop.close()
                    return bi_result.get("brand_intelligence")

                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = pool.submit(_run_llm)
                try:
                    llm_output = future.result(timeout=LLM_ENRICHMENT_TIMEOUT)
                    if llm_output and not isinstance(llm_output, dict):
                        llm_output = None
                        enrichment_status = "web_only"
                    elif llm_output and "_error" not in llm_output:
                        enrichment_status = "enriched"
                        logger.info("[research:%s] LLM enrichment succeeded", job_id)
                    else:
                        enrichment_status = "partially_enriched"
                        logger.warning("[research:%s] LLM returned error dict: %s", job_id, llm_output)
                except concurrent.futures.TimeoutError:
                    llm_output = {"_error": f"LLM enrichment timed out ({LLM_ENRICHMENT_TIMEOUT}s) — web research data preserved"}
                    enrichment_status = "web_only"
                    logger.warning("[research:%s] LLM enrichment timed out after %ss", job_id, LLM_ENRICHMENT_TIMEOUT)
                except Exception as e:
                    llm_output = {"_error": str(e)}
                    enrichment_status = "web_only"
                    logger.error("[research:%s] LLM enrichment failed: %s", job_id, e)
                pool.shutdown(wait=False)
            else:
                logger.warning("[research:%s] LLM not reachable — completing with web_only", job_id)

            # ── Stage 4: Update persisted research with LLM output + enrichment status ──
            web_result["_enrichment_status"] = enrichment_status
            store.save_background_research_update(research_id, web_result, llm_output)
            logger.info("[research:%s] Research updated — enrichment_status=%s", job_id, enrichment_status)

            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message=f"Background research complete ({enrichment_status})",
                             result={"research_id": research_id, "project_id": project_id,
                                     "enrichment_status": enrichment_status})
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                         "progress_pct": 100, "message": f"Background research complete ({enrichment_status})"})

        except Exception as e:
            logger.error("[research:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                         "error": str(e)})

    submit(worker, name="research:background")
    return {"job_id": job_id, "project_id": project_id}


@router.get("/research/status/{job_id}", response_model=ResearchJobStatus)
def get_research_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress_pct": job.get("progress_pct", 0),
        "progress_message": job.get("progress_message", ""),
        "error": job.get("error"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


def _research_blocking_reasons(web_data: dict) -> list[str]:
    """Return reasons background research cannot be approved (empty = approvable)."""
    blocking_reasons = []

    if not web_data.get("web_search_executed"):
        blocking_reasons.append("Live web search did not execute")

    news_items = web_data.get("news_items", [])
    if not news_items:
        blocking_reasons.append("No relevant sources were retained")

    has_uncited = any(not item.get("url") for item in news_items)
    if has_uncited:
        blocking_reasons.append("Current factual claims lack citations")

    gaps = web_data.get("research_gaps", [])
    if any("entity" in g.lower() or "ambiguity" in g.lower() for g in gaps):
        blocking_reasons.append("Entity ambiguity remains unresolved")

    return blocking_reasons


@router.get("/research/{project_id}", response_model=ResearchResults)
def get_research_results(project_id: Annotated[int, Path(ge=1)],
                          _access: Annotated[dict, Depends(require_project_access)]):
    research = store.get_latest_research(project_id)
    if not research:
        raise HTTPException(404, "No research found for this project")

    approvals = store.get_news_approvals(research["id"])

    web_data = research["research"]
    news_items = web_data.get("news_items", [])
    for i, item in enumerate(news_items):
        if i in approvals:
            item["approval_status"] = approvals[i]["status"]
            item["approval_notes"] = approvals[i].get("notes", "")

    blocking_reasons = _research_blocking_reasons(web_data)
    can_approve = not blocking_reasons

    enrichment_status = web_data.get("_enrichment_status", "unknown")

    return {
        "research_id": research["id"],
        "version": research["version"],
        "approval_status": research["approval_status"],
        "enrichment_status": enrichment_status,
        "research": web_data,
        "llm_output": research.get("llm_output"),
        "can_approve": can_approve,
        "blocking_reasons": blocking_reasons,
        "created_at": research["created_at"],
    }


@router.post("/research/{research_id}/approve", response_model=ResearchApprovalResult)
def approve_background_research(research_id: Annotated[int, Path(ge=1)], req: ApproveRequest):
    research = store.get_research_by_id(research_id)
    if not research:
        raise HTTPException(404, "Research not found")

    blocking_reasons = _research_blocking_reasons(research["research"])
    if blocking_reasons and not req.override_blocking:
        return {"approved": False, "blocking_reasons": blocking_reasons}

    store.approve_research(research_id, req.reviewer)
    _broadcast({"type": "intel_research_approved", "research_id": research_id})
    return {"ok": True, "approved": True, "overridden": bool(blocking_reasons)}


@router.post("/research/{research_id}/revise", response_model=OkResponse)
def request_research_revision(research_id: Annotated[int, Path(ge=1)], req: RevisionRequest):
    store.reject_research(research_id, req.notes)
    return {"ok": True}


@router.post("/research/{research_id}/news-approval", response_model=OkResponse)
def approve_news_item(research_id: Annotated[int, Path(ge=1)], req: NewsApprovalRequest):
    store.update_news_approval(research_id, req.item_index, req.status, req.notes)
    return {"ok": True}


# ─── Brandfetch ────────────────────────────────────────────────────────

@router.get("/brandfetch/logo", response_model=BrandLogoResponse)
def get_brand_logo_route(brand_name: str):
    """Logo for a brand/product: saved brand_logos table first, then Brandfetch, then Google."""
    return brandfetch_client.resolve_logo(brand_name)


# ─── Pexels ────────────────────────────────────────────────────────────────

@router.get("/pexels/image", response_model=PexelsImageResponse)
def get_pexels_image_route(query: str):
    """Dynamic background media for a query (typically a brand/project name):
    saved pexels_images table first, then the Pexels Video Search API, falling
    back to the Photo Search API when no video result exists."""
    return pexels_client.resolve_background_video(query)


# ─── Section background video (YouTube via DuckDuckGo) ─────────────────────

@router.get("/video/section", response_model=SectionVideoResponse)
def get_section_video_route(query: str, brand_name: str = ""):
    """Topically-matched YouTube video for a brief section (e.g. "Tesla Model 3 review"
    for Brand Developments): saved youtube_videos table first, then a DuckDuckGo video
    search restricted to `brand_name`'s own official channel."""
    try:
        return video_search.resolve_section_video(query, brand_name)
    except video_search.LookupUnavailable:
        return {"query": query, "video_id": None, "embed_url": None, "title": None,
                "thumbnail_url": None, "cached": False}


# ─── Multi-source fetch preview ─────────────────────────────────────────────

@router.post("/research/fetch-preview", response_model=FetchPreviewStarted)
def fetch_preview(req: FetchPreviewRequest):
    """Run the multi-source fetch engine directly (no full research/brief flow) — for testing
    the Boolean query builder + 3-source fan-out independently, and the entry point Research
    Execution (stage 6) will call later with an analyst-approved query."""
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, f"Project {req.project_id} not found")

    job_id = f"fetch_preview_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_fetch_preview")

    def worker():
        store.update_job(job_id, status="running", progress_pct=5, progress_message="Building queries")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                     "job_type": "research_fetch_preview", "status": "running",
                     "progress_pct": 5, "message": "Building queries"})
        try:
            spec = project.get("spec", {})
            topics = multi_source_module.build_boolean_queries(spec)
            adapter = LiveWebResearchAdapter()
            date_range = adapter._extract_date_range(spec)
            geography = adapter._extract_geography(spec)

            def on_event(step, payload):
                store.update_job(job_id, progress_pct=50, progress_message=step)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                             "job_type": "research_fetch_preview", "status": "running",
                             "progress_pct": 50, "message": step, "detail": payload})

            result = multi_source_module.fetch_and_persist(
                project_id=req.project_id, topics=topics, date_range=date_range,
                geography=geography, emit=on_event,
            )
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Fetch complete", result=result)
            _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                         "job_type": "research_fetch_preview", "status": "completed",
                         "progress_pct": 100, "message": "Fetch complete", **result})
        except Exception as e:
            logger.exception("fetch-preview failed for project %s", req.project_id)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                         "job_type": "research_fetch_preview", "status": "failed", "message": str(e)})

    submit(worker, name=f"research:fetch-preview:{req.project_id}")
    return FetchPreviewStarted(job_id=job_id, project_id=req.project_id)


@router.get("/research/{project_id}/items", response_model=ResearchItemsListResponse)
def get_research_items_route(project_id: Annotated[int, Path(ge=1)],
                              _access: Annotated[dict, Depends(require_project_access)]):
    """Every persisted research item for a project's latest run (scoped to that run's date
    range), enriched with which brand/competitor/product keywords each item matched and
    whether it passed entity-relevance validation — for the analyst-facing sources table.
    This is the full underlying item set, not the already-filtered news_items/source_register
    the composed Brief uses."""
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    spec = project.get("spec", {})

    research = store.get_latest_research(project_id)
    date_range = None
    if research:
        metadata = research["research"].get("metadata", {})
        start_str = metadata.get("date_range_start", "")
        end_str = metadata.get("date_range_end", "")
        if start_str and end_str:
            from datetime import datetime
            date_range = (
                datetime.fromisoformat(start_str).date(),
                datetime.fromisoformat(end_str).date(),
            )

    if date_range:
        since, until = multi_source_module.date_range_to_timestamps(date_range)
        items = store.get_research_items(project_id, since=since, until=until)
    else:
        items = store.get_research_items(project_id)

    adapter = LiveWebResearchAdapter()
    brand_name = adapter._extract_brand_name(spec)
    category = adapter._extract_category(spec)
    geography = adapter._extract_geography(spec)
    exclude_patterns = adapter._extract_exclusions(spec)
    validator = EntityValidator(brand_name, category, geography, exclude_patterns)

    entities = spec.get("validated_entities", [])
    keyword_terms = [brand_name] if brand_name else []
    keyword_terms += [e["name"] for e in entities
                       if isinstance(e, dict) and e.get("type") in ("competitor", "product") and e.get("name")]

    from urllib.parse import urlparse

    result_items = []
    for item in items:
        title = item.get("title") or ""
        content = item.get("content") or ""
        url = item.get("url") or ""
        haystack = f"{title} {content}".lower()
        matched = [t for t in keyword_terms if t and t.lower() in haystack]
        validation = validator.validate(title, content, url)
        try:
            domain = urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            domain = None
        result_items.append(ResearchItemView(
            id=item["id"], topic=item["topic"], source_api=item["source_api"],
            publication=item.get("publication"), domain=domain or None,
            title=title or None, content=content or None, url=url,
            author=item.get("author"), thumbnail_url=item.get("thumbnail_url"),
            published_date=item["published_date"],
            keywords_matched=matched, relevant=validation["relevant"],
        ))

    return ResearchItemsListResponse(items=result_items, total=len(result_items))

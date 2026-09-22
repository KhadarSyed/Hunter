"""Intelligence workflow API routes.

Mounts onto the main FastAPI app. Handles:
- Background research (start, status, results, approve, revise)
- Meltwater search strategy (generate, status, get, edit, approve)
- Query evaluation (upload sample, evaluate, get results)
- Final query approval
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import intelligence_store as store
from . import evidence_library as elib
from . import insight_generator as igen
from . import storyline_builder as sbuilder
from . import slide_intelligence as si
from . import presentation_composer as pc
from . import pptx_renderer as renderer
from . import word_renderer
from . import pipeline_orchestrator as orchestrator
from . import publishing_gateway as pub
from .config import load_settings
from .ollama_client import OllamaClient
from .anthropic_client import get_llm_client
from .web_research_adapter import LiveWebResearchAdapter

logger = logging.getLogger(__name__)

LLM_ENRICHMENT_TIMEOUT = 120
STRATEGY_LLM_TIMEOUT = 300

router = APIRouter(prefix="/api/intel", tags=["intelligence"])


def _extract_competitors_from_text(text: str, brand_name: str) -> list[str]:
    """Extract competitor names from natural-language brief text."""
    import re
    competitors = []
    patterns = [
        r'competitive set includes?\s+(.+?)(?:\.|,\s*while)',
        r'competitors?\s+(?:are|include|includes)\s+(.+?)(?:\.|$)',
        r'[Cc]ompetitors?\s*\n+(.+?)(?:\n\n|\n[A-Z]|$)',
        r'[Cc]ompetitors?:\s*(.+?)(?:\n\n|\n[A-Z]|$)',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.MULTILINE | re.DOTALL):
            chunk = m.group(1)
            names = re.split(r',\s*|\s+and\s+', chunk)
            for n in names:
                n = n.strip().rstrip('.')
                if n and len(n) > 1 and n.lower() != brand_name.lower() and n not in competitors:
                    competitors.append(n)
        if competitors:
            break
    return competitors


def _build_deterministic_strategy(spec: dict, raw_brief_text: str = "") -> dict:
    """Build a basic Meltwater Boolean strategy from the spec without LLM.

    Used as fallback when LLM times out on CPU-only hardware.
    """
    brand = spec.get("commissioning_brand", {})
    brand_name = brand.get("name", "")
    category = brand.get("category", "")
    products = brand.get("products", [])
    parent = brand.get("parent_company", "")

    excluded = spec.get("excluded_scope", [])
    not_terms = []
    for ex in excluded:
        desc = ex.get("description", "") if isinstance(ex, dict) else str(ex)
        words = [w for w in desc.split() if len(w) > 3 and w.lower() not in
                 ("references", "generic", "usage", "actor")]
        not_terms.extend(words)
    not_clause = (" NOT " + " NOT ".join(f'"{t}"' for t in not_terms)) if not_terms else ""

    brand_variants = [f'"{brand_name}"']
    clean = brand_name.replace("'", "").replace(".", "").strip()
    if clean != brand_name:
        brand_variants.append(f'"{clean}"')
    brand_or = " OR ".join(brand_variants)

    cat_terms = [f'"{category}"'] if category else []
    for p in products[:3]:
        cat_terms.append(f'"{p}"')

    broad_q = f"({brand_or}){not_clause}"
    balanced_q = f"({brand_or}) AND ({' OR '.join(cat_terms)}){not_clause}" if cat_terms else broad_q
    precise_q = f'("{brand_name}" NEAR/5 "{category}"){not_clause}' if category else balanced_q

    rq_queries = []
    for rq in spec.get("research_questions", []):
        qid = rq.get("question_id", "")
        q_text = rq.get("question", "")
        keywords = [w for w in q_text.split() if len(w) > 4 and w.lower() not in
                    ("which", "about", "their", "there", "these", "those", "where",
                     "social", "media", "what")][:3]
        kw_clause = " OR ".join(f'"{k}"' for k in keywords) if keywords else f'"{category}"'
        rq_queries.append({
            "question_id": qid,
            "question": q_text,
            "query": f'({brand_or}) AND ({kw_clause}){not_clause}',
            "rationale": "Deterministic: brand + question keywords",
        })

    scope = spec.get("included_scope", {})

    # Extract competitors from structured spec fields
    competitors = []
    for entity in spec.get("validated_entities", []):
        if entity.get("type") in ("competitor", "brand") and entity.get("name") != brand_name:
            competitors.append(entity["name"])
    if scope.get("competitors"):
        for c in scope["competitors"]:
            name = c.get("name", c) if isinstance(c, dict) else str(c)
            if name and name != brand_name and name not in competitors:
                competitors.append(name)

    # Fallback: extract competitors from raw brief text if none found in structured fields
    if not competitors:
        text_sources = [raw_brief_text]
        rs = spec.get("research_subject", {})
        if isinstance(rs, dict) and rs.get("description"):
            text_sources.append(rs["description"])
        for text in text_sources:
            if text:
                competitors = _extract_competitors_from_text(text, brand_name)
                if competitors:
                    break

    # Build competitor queries
    comp_modules = []
    comp_core_queries = []
    if competitors:
        comp_or = " OR ".join(f'"{c}"' for c in competitors)
        all_brands = f'({brand_or} OR {comp_or})'

        comp_modules.append({
            "module_id": "M3",
            "name": "Competitive landscape",
            "purpose": f"Capture competitor mentions: {', '.join(competitors)}",
            "terms": {
                "primary": competitors,
                "synonyms": [],
                "exclusions": not_terms,
                "provenance": "deterministic",
            },
        })

        comp_core_queries.append({
            "type": "competitive_landscape",
            "query": f'{all_brands} AND ({" OR ".join(cat_terms)}){not_clause}' if cat_terms else f'{all_brands}{not_clause}',
            "description": f"Brand + competitors ({', '.join(competitors)}) in category context",
            "estimated_noise_level": "medium",
            "use_case": "Competitive analysis and share of voice",
        })

        for comp in competitors[:5]:
            comp_core_queries.append({
                "type": f"competitor_{comp.lower().replace(' ', '_')}",
                "query": f'("{comp}") AND ({" OR ".join(cat_terms)}){not_clause}' if cat_terms else f'("{comp}"){not_clause}',
                "description": f"Competitor-specific: {comp}",
                "estimated_noise_level": "medium",
                "use_case": f"Track {comp} activity in category",
            })

        # Add competitive RQ queries
        rq_queries.append({
            "question_id": f"RQ{len(rq_queries) + 1}",
            "question": f"How are {brand_name} and its competitors ({', '.join(competitors[:3])}) positioned in the {category or 'market'}?",
            "query": f'{all_brands} AND ("market share" OR "competitive" OR "versus" OR "vs" OR "compared"){not_clause}',
            "rationale": "Deterministic: brand + competitors + competitive keywords",
        })
        rq_queries.append({
            "question_id": f"RQ{len(rq_queries) + 1}",
            "question": f"What is the share of voice between {brand_name} and {', '.join(competitors[:3])}?",
            "query": f'{all_brands}{not_clause}',
            "rationale": "Deterministic: all brands for share of voice calculation",
        })

    has_competitors = len(competitors) > 0
    quality_gaps = ["No synonym expansion", "No industry-specific terminology"]
    if not has_competitors:
        quality_gaps.insert(1, "No competitive brand queries")

    return {
        "strategy_summary": f"Deterministic Boolean strategy for {brand_name}. "
                           f"Generated without LLM due to CPU timeout. "
                           f"Covers broad/balanced/precise variants"
                           f"{f', {len(competitors)} competitor queries' if competitors else ''}"
                           f" and {len(rq_queries)} research question sub-queries.",
        "_strategy_source": "deterministic",
        "_note": "Generated deterministically because LLM timed out on CPU-only hardware. "
                "Queries use basic Boolean syntax and may benefit from LLM refinement.",
        "query_modules": [
            {
                "module_id": "M1",
                "name": "Brand core",
                "purpose": f"Capture mentions of {brand_name}",
                "terms": {
                    "primary": [brand_name],
                    "synonyms": [clean] if clean != brand_name else [],
                    "exclusions": not_terms,
                    "provenance": "deterministic",
                },
            },
            {
                "module_id": "M2",
                "name": "Category context",
                "purpose": f"Capture {category} category discussion",
                "terms": {
                    "primary": [category] if category else [],
                    "synonyms": products[:3],
                    "exclusions": [],
                    "provenance": "deterministic",
                },
            },
            *comp_modules,
        ],
        "core_queries": [
            {"type": "broad", "query": broad_q,
             "description": "Brand name with exclusions only",
             "estimated_noise_level": "high",
             "use_case": "Volume estimation and broad monitoring"},
            {"type": "balanced", "query": balanced_q,
             "description": "Brand + category/product context",
             "estimated_noise_level": "medium",
             "use_case": "Day-to-day monitoring"},
            {"type": "precise", "query": precise_q,
             "description": "Brand in proximity to category",
             "estimated_noise_level": "low",
             "use_case": "High-precision analysis"},
            *comp_core_queries,
        ],
        "research_question_queries": rq_queries,
        "exclusion_strategy": {
            "global_exclusions": not_clause.strip() if not_clause else "None",
            "rationale": "Derived from spec excluded_scope",
            "exclusion_categories": [
                {"category": "spec_exclusion", "terms": not_terms, "reason": "Excluded in project spec"}
            ] if not_terms else [],
        },
        "filter_recommendations": {
            "date_range": scope.get("time_period", "Past 12 months"),
            "geography": scope.get("countries", ["United States"]),
            "language": scope.get("languages", ["English"]),
            "source_types": ["news", "social", "blogs"],
            "platforms": scope.get("platforms", []),
        },
        "quality_assessment": {
            "overall_score": 6 if has_competitors else 4,
            "coverage_score": 7 if has_competitors else 5,
            "precision_score": 5 if has_competitors else 4,
            "potential_gaps": quality_gaps,
            "potential_noise": ["Broad query may capture irrelevant Mrs./Mr. references"],
            "recommendations": ["Regenerate with LLM for optimized queries with synonym expansion",
                                "Test queries in Meltwater and refine based on sample results"],
        },
    }

_ws_broadcast = None


def set_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def _broadcast(msg: dict):
    if _ws_broadcast:
        _ws_broadcast(msg)


# ─── Request/Response models ────────────────────────────────────────────────

class StartResearchRequest(BaseModel):
    spec: dict
    project_id: int | None = None

class ApproveRequest(BaseModel):
    reviewer: str = "analyst"
    notes: str = ""

class RevisionRequest(BaseModel):
    notes: str

class EditQueryRequest(BaseModel):
    query_type: str
    query_text: str

class NewsApprovalRequest(BaseModel):
    item_index: int
    status: str
    notes: str = ""

class GenerateStrategyRequest(BaseModel):
    project_id: int

class FinalApprovalRequest(BaseModel):
    reviewer: str = "analyst"
    sample_evaluation_waived: bool = False
    acknowledge_meltwater_validation: bool = False


# ─── Projects ──────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects_route(type: str | None = None):
    return store.list_projects(project_type=type)


class CreateProjectRequest(BaseModel):
    project_name: str
    spec: dict = {}
    project_type: str = "research"


@router.post("/projects")
def create_project_route(req: CreateProjectRequest):
    pid = store.create_project(req.project_name, req.spec, project_type=req.project_type)
    project = store.get_project(pid)
    return project


@router.get("/projects/{project_id}")
def get_project_route(project_id: int):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


# ─── Background Research ────────────────────────────────────────────────────

@router.post("/research/start")
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
                    "research_searching": (f"Searching: {payload.get('family', '')}", None),
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
                    if event_type == "research_searching":
                        idx = payload.get("index", 0)
                        total = payload.get("total", 1)
                        pct = 15 + int(45 * idx / max(total, 1))
                    store.update_job(job_id, progress_pct=pct, progress_message=msg)
                    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                                "progress_pct": pct, "message": msg})

            # ── Stage 1: Web research (single execution) ──
            logger.info("[research:%s] Stage 1 — executing web research", job_id)
            web_result = adapter.run_full_research(spec, emit=on_event)

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

            ollama = get_llm_client()
            llm_output = None
            enrichment_status = "web_only"

            if ollama and ollama.is_reachable():
                logger.info("[research:%s] LLM reachable — attempting enrichment (timeout=%ss)", job_id, LLM_ENRICHMENT_TIMEOUT)

                def _run_llm():
                    from .agents.brand_intelligence import run as run_bi
                    loop = asyncio.new_event_loop()
                    bi_result = loop.run_until_complete(
                        run_bi(spec, emit=on_event, ollama=ollama, web_adapter=None)
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
                logger.warning("[research:%s] Ollama not reachable — completing with web_only", job_id)

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

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "project_id": project_id}


@router.get("/research/status/{job_id}")
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


@router.get("/research/{project_id}")
def get_research_results(project_id: int):
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

    can_approve = True
    blocking_reasons = []

    if not web_data.get("web_search_executed"):
        can_approve = False
        blocking_reasons.append("Live web search did not execute")

    if not news_items:
        can_approve = False
        blocking_reasons.append("No relevant sources were retained")

    has_uncited = False
    for item in news_items:
        if not item.get("url"):
            has_uncited = True
            break
    if has_uncited:
        can_approve = False
        blocking_reasons.append("Current factual claims lack citations")

    gaps = web_data.get("research_gaps", [])
    if any("entity" in g.lower() or "ambiguity" in g.lower() for g in gaps):
        can_approve = False
        blocking_reasons.append("Entity ambiguity remains unresolved")

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


@router.post("/research/{research_id}/approve")
def approve_background_research(research_id: int, req: ApproveRequest):
    store.approve_research(research_id, req.reviewer)
    _broadcast({"type": "intel_research_approved", "research_id": research_id})
    return {"ok": True}


@router.post("/research/{research_id}/revise")
def request_research_revision(research_id: int, req: RevisionRequest):
    store.reject_research(research_id, req.notes)
    return {"ok": True}


@router.post("/research/{research_id}/news-approval")
def approve_news_item(research_id: int, req: NewsApprovalRequest):
    store.update_news_approval(research_id, req.item_index, req.status, req.notes)
    return {"ok": True}


# ─── Analyst Orientation Brief ───────────────────────────────────────────────

class GenerateBriefRequest(BaseModel):
    project_id: int

class UpdateBriefSectionRequest(BaseModel):
    section_key: str
    content: str
    analyst_note: str = ""

class ApproveBriefRequest(BaseModel):
    reviewer: str = "analyst"

class RejectBriefRequest(BaseModel):
    notes: str = ""


@router.post("/brief/parse-file")
async def parse_brief_file(file: UploadFile = File(...)):
    """Upload a brief file (DOCX, PPTX, TXT, PDF) and extract its text."""
    from . import brief_parser

    ext = Path(file.filename or "").suffix.lower()
    supported = {".docx", ".pptx", ".txt", ".pdf", ".xlsx", ".xls"}
    if ext not in supported:
        raise HTTPException(400, f"Unsupported format: {ext}. Use DOCX, PPTX, TXT, PDF, or Excel.")

    upload_dir = Path(__file__).resolve().parent.parent / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"brief_{uuid.uuid4().hex[:8]}{ext}"
    dest = upload_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)

    try:
        if ext in (".xlsx", ".xls"):
            import openpyxl
            wb = openpyxl.load_workbook(str(dest), read_only=True, data_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                line = "  ".join(str(c) for c in row if c is not None)
                if line.strip():
                    lines.append(line.strip())
            wb.close()
            text = "\n".join(lines)
        elif ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(str(dest))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            except ImportError:
                text = "(PDF parsing requires PyMuPDF — please use DOCX or PPTX instead)"
        else:
            text = brief_parser.parse_brief(dest)
        return {"text": text, "file_name": file.filename}
    except Exception as e:
        logger.error("Brief file parse error: %s", e)
        raise HTTPException(400, f"Could not parse file: {e}")


@router.post("/brief/generate")
def generate_analyst_brief(req: GenerateBriefRequest):
    """Generate an analyst orientation brief from completed web research."""
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    research = store.get_latest_research(req.project_id)
    if not research:
        raise HTTPException(400, "No background research found. Run web research first.")

    spec = project.get("spec", {})
    research_data = research["research"]
    llm_output = research.get("llm_output")

    from .background_brief_service import compose_brief
    try:
        result = compose_brief(req.project_id, research["id"], spec, research_data, llm_output)
    except Exception as e:
        logger.exception("Brief generation failed for project %s", req.project_id)
        raise HTTPException(500, f"Brief generation failed: {e}")

    _broadcast({"type": "intel_brief_generated", "project_id": req.project_id,
                "brief_id": result["brief_id"]})
    return result


@router.get("/brief/{project_id}")
def get_analyst_brief(project_id: int):
    """Get the latest analyst orientation brief for a project."""
    brief = store.get_latest_brief(project_id)
    if not brief:
        raise HTTPException(404, "No brief found for this project")

    research = store.get_latest_research(project_id)
    research_approved = research and research.get("approval_status") == "approved"

    return {
        "brief_id": brief["id"],
        "version": brief["version"],
        "approval_status": brief["approval_status"],
        "brief": brief["brief"],
        "docx_path": brief.get("docx_path"),
        "docx_generated_at": brief.get("docx_generated_at"),
        "research_approved": research_approved,
        "created_at": brief["created_at"],
        "updated_at": brief["updated_at"],
    }


@router.post("/brief/{brief_id}/section")
def update_brief_section(brief_id: int, req: UpdateBriefSectionRequest):
    """Update a single section of the brief with analyst edits."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.update_brief_section(brief_id, req.section_key, req.content, req.analyst_note)
    return {"ok": True}


@router.post("/brief/{brief_id}/approve")
def approve_analyst_brief(brief_id: int, req: ApproveBriefRequest):
    """Approve the analyst orientation brief, also approves background research."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    store.approve_brief(brief_id, req.reviewer)
    store.approve_research(brief["research_id"], req.reviewer)

    _broadcast({"type": "intel_brief_approved", "brief_id": brief_id})
    return {"ok": True}


@router.post("/brief/{brief_id}/reject")
def reject_analyst_brief(brief_id: int, req: RejectBriefRequest):
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    store.reject_brief(brief_id, req.notes)
    return {"ok": True}


@router.post("/brief/{brief_id}/render")
def render_brief_docx(brief_id: int):
    """Render the brief as a Word document and return the file path."""
    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    from .background_brief_renderer import render_brief_docx as do_render
    filepath = do_render(brief_id)
    return {"ok": True, "docx_path": filepath}


@router.get("/brief/{brief_id}/download")
def download_brief_docx(brief_id: int):
    """Download the rendered Word document."""
    from fastapi.responses import FileResponse

    brief = store.get_brief_by_id(brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")

    docx_path = brief.get("docx_path")
    if not docx_path or not os.path.exists(docx_path):
        raise HTTPException(404, "Word document not yet generated. Call /brief/{id}/render first.")

    filename = os.path.basename(docx_path)
    return FileResponse(
        path=docx_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/brief/versions/{project_id}")
def list_brief_versions(project_id: int):
    """List all brief versions for a project."""
    return store.list_brief_versions(project_id)


# ─── Research Specification ──────────────────────────────────────────────────

class GenerateSpecRequest(BaseModel):
    project_id: int
    raw_brief_text: str = ""
    use_llm: bool = False

class UpdateSpecSectionRequest(BaseModel):
    section_key: str
    content: str | dict | list
    analyst_note: str = ""

class ApproveSpecSectionRequest(BaseModel):
    section_key: str
    reviewer: str = "analyst"

class LockSpecSectionRequest(BaseModel):
    section_key: str
    locked_by: str = "analyst"

class ApproveSpecRequest(BaseModel):
    reviewer: str = "analyst"

class RejectSpecRequest(BaseModel):
    reason: str = ""
    reviewer: str = "analyst"

class RegenerateSpecRequest(BaseModel):
    raw_brief_text: str = ""
    use_llm: bool = False
    confirm_overwrite_locked: bool = False

class ResolveClarificationRequest(BaseModel):
    answer: str
    resolved_by: str = "analyst"

class AddClarificationRequest(BaseModel):
    question: str
    section_key: str = ""
    is_blocking: bool = True


@router.post("/spec/generate")
def generate_research_spec(req: GenerateSpecRequest):
    """Generate a Research Specification from the project's stored spec."""
    from . import research_spec_service as rss
    try:
        llm_client = None
        if req.use_llm:
            llm_client = get_llm_client()
            if not llm_client or not llm_client.is_reachable():
                raise HTTPException(503, "No LLM provider available — ensure Ollama is running or ANTHROPIC_API_KEY is set")
        result = rss.generate_spec(
            project_id=req.project_id,
            raw_brief_text=req.raw_brief_text,
            use_llm=req.use_llm,
            llm_client=llm_client,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to generate research specification")
        raise HTTPException(500, f"Specification generation failed: {e}")


@router.get("/spec/{project_id}")
def get_research_spec(project_id: int):
    """Get the latest Research Specification for a project."""
    spec = store.get_latest_spec(project_id)
    if not spec:
        raise HTTPException(404, "No research specification found for this project")
    return spec


@router.get("/spec/detail/{spec_id}")
def get_spec_detail(spec_id: int):
    """Get a specific Research Specification by ID."""
    spec = store.get_spec_by_id(spec_id)
    if not spec:
        raise HTTPException(404, "Specification not found")
    return spec


@router.post("/spec/{spec_id}/section")
def update_spec_section(spec_id: int, req: UpdateSpecSectionRequest):
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


@router.post("/spec/{spec_id}/section/approve")
def approve_spec_section_endpoint(spec_id: int, req: ApproveSpecSectionRequest):
    """Approve a single section of a specification."""
    store.approve_spec_section(spec_id, req.section_key, req.reviewer)
    return {"status": "approved", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/lock")
def lock_spec_section_endpoint(spec_id: int, req: LockSpecSectionRequest):
    """Lock a section to prevent modifications."""
    store.lock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "locked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/section/unlock")
def unlock_spec_section_endpoint(spec_id: int, req: LockSpecSectionRequest):
    """Unlock a section to allow modifications."""
    store.unlock_spec_section(spec_id, req.section_key, req.locked_by)
    return {"status": "unlocked", "section_key": req.section_key}


@router.post("/spec/{spec_id}/approve")
def approve_full_spec_endpoint(spec_id: int, req: ApproveSpecRequest):
    """Approve the full Research Specification (Gate 1)."""
    ok = store.approve_full_spec(spec_id, req.reviewer)
    if not ok:
        raise HTTPException(
            400,
            "Cannot approve — blocking issues remain. Resolve all blocking "
            "clarifications and fill mandatory sections first.",
        )
    return {"status": "approved", "spec_id": spec_id}


@router.post("/spec/{spec_id}/reject")
def reject_spec_endpoint(spec_id: int, req: RejectSpecRequest):
    """Reject / request revision of the Research Specification."""
    store.reject_spec(spec_id, req.reason, req.reviewer)
    return {"status": "revision_requested", "spec_id": spec_id}


@router.post("/spec/{spec_id}/regenerate")
def regenerate_spec_endpoint(spec_id: int, req: RegenerateSpecRequest):
    """Regenerate a specification (preserves locked/approved sections by default)."""
    from . import research_spec_service as rss
    try:
        llm_client = None
        if req.use_llm:
            llm_client = get_llm_client()
            if not llm_client or not llm_client.is_reachable():
                raise HTTPException(503, "No LLM provider available — ensure Ollama is running or ANTHROPIC_API_KEY is set")
        result = rss.regenerate_spec(
            spec_id=spec_id,
            raw_brief_text=req.raw_brief_text,
            use_llm=req.use_llm,
            llm_client=llm_client,
            confirm_overwrite_locked=req.confirm_overwrite_locked,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to regenerate specification")
        raise HTTPException(500, f"Regeneration failed: {e}")


@router.get("/spec/{spec_id}/readiness")
def get_spec_readiness_endpoint(spec_id: int):
    """Get the readiness status of a specification."""
    readiness = store.get_spec_readiness(spec_id)
    if readiness is None:
        raise HTTPException(404, "Specification not found")
    return readiness


@router.post("/spec/{spec_id}/render")
def render_spec_docx(spec_id: int):
    """Render the Research Specification as a Word document."""
    from . import research_spec_renderer as rsr
    try:
        filepath = rsr.render_spec_docx(spec_id)
        return {"status": "rendered", "docx_path": filepath}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Failed to render specification")
        raise HTTPException(500, f"Render failed: {e}")


@router.get("/spec/{spec_id}/download")
def download_spec_docx(spec_id: int):
    """Download the rendered Word document for a specification."""
    from starlette.responses import FileResponse
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


@router.get("/spec/versions/{project_id}")
def list_spec_versions_endpoint(project_id: int):
    """List all specification versions for a project."""
    return store.list_spec_versions(project_id)


@router.get("/spec/{spec_id}/audit")
def get_spec_audit_endpoint(spec_id: int):
    """Get audit trail for a specification."""
    return store.get_spec_audit(spec_id)


@router.get("/spec/{spec_id}/clarifications")
def get_spec_clarifications(spec_id: int, unresolved_only: bool = False):
    """Get clarifications for a specification."""
    return store.get_clarifications(spec_id, unresolved_only=unresolved_only)


@router.post("/spec/{spec_id}/clarification")
def add_spec_clarification(spec_id: int, req: AddClarificationRequest):
    """Add a new clarification question."""
    cid = store.add_clarification(
        spec_id=spec_id,
        question=req.question,
        section_key=req.section_key,
        is_blocking=req.is_blocking,
    )
    return {"status": "added", "clarification_id": cid}


@router.post("/spec/clarification/{clarification_id}/resolve")
def resolve_spec_clarification(clarification_id: int, req: ResolveClarificationRequest):
    """Resolve a clarification question."""
    ok = store.resolve_clarification(clarification_id, req.answer, req.resolved_by)
    if not ok:
        raise HTTPException(404, "Clarification not found")
    return {"status": "resolved", "clarification_id": clarification_id}


# ─── Search Strategy ─────────────────────────────────────────────────────────

@router.post("/strategy/generate")
def generate_search_strategy(req: GenerateStrategyRequest):
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    research = store.get_latest_research(req.project_id)
    if not research:
        raise HTTPException(400, "No background research found — run background research first")

    job_id = f"strategy_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "search_strategy")

    def worker():
        logger.info("[strategy:%s] Starting strategy generation for project %s", job_id, req.project_id)
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Building Meltwater query modules")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Building Meltwater query modules"})

        try:
            spec = project["spec"]
            web_research = research["research"]
            llm_output = research.get("llm_output")

            # Fetch raw brief text for competitor extraction fallback
            latest_spec_row = store.get_latest_spec(req.project_id)
            raw_brief_text = (latest_spec_row or {}).get("raw_brief_text", "") or ""

            # Select brand context: use LLM output only if it succeeded (no _error key)
            if isinstance(llm_output, dict) and "_error" not in llm_output and llm_output:
                brand_context = llm_output
                logger.info("[strategy:%s] Using LLM-enriched brand context", job_id)
            else:
                brand_context = web_research
                logger.info("[strategy:%s] Using web-only brand context (llm_output unavailable or errored)", job_id)

            ollama = get_llm_client()

            def on_event(event_type: str, payload: dict):
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": payload.get("progress_pct", 50),
                             "message": payload.get("message", event_type)})

            strategy_result = None

            if not ollama or not ollama.is_reachable():
                logger.warning("[strategy:%s] No LLM reachable — falling back to deterministic strategy", job_id)
                store.update_job(job_id, progress_pct=70,
                                 progress_message="No LLM available — building deterministic strategy")
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": 70, "message": "No LLM available — building deterministic strategy"})
                strategy_result = _build_deterministic_strategy(spec, raw_brief_text)
            else:
                store.update_job(job_id, progress_pct=30,
                                 progress_message="LLM generating query strategy")
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": 30, "message": "LLM generating query strategy"})

                logger.info("[strategy:%s] Submitting LLM strategy generation (timeout=%ss)", job_id, STRATEGY_LLM_TIMEOUT)

                def _run_strategy_llm():
                    from .agents.meltwater_query_builder import run as run_mqb
                    loop = asyncio.new_event_loop()
                    mqb_result = loop.run_until_complete(
                        run_mqb(spec, brand_context, emit=on_event, ollama=ollama)
                    )
                    loop.close()
                    return mqb_result.get("queries")

                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = pool.submit(_run_strategy_llm)
                try:
                    strategy_result = future.result(timeout=STRATEGY_LLM_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    logger.warning("[strategy:%s] LLM timed out after %ss — falling back to deterministic strategy",
                                   job_id, STRATEGY_LLM_TIMEOUT)
                    pool.shutdown(wait=False)
                    store.update_job(job_id, progress_pct=70,
                                     progress_message="LLM timed out — building deterministic strategy")
                    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                                 "progress_pct": 70, "message": "LLM timed out — building deterministic strategy"})
                    strategy_result = _build_deterministic_strategy(spec, raw_brief_text)
                except Exception as e:
                    logger.warning("[strategy:%s] LLM strategy generation failed: %s — falling back to deterministic", job_id, e)
                    store.update_job(job_id, progress_pct=70,
                                     progress_message="LLM failed — building deterministic strategy")
                    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                                 "progress_pct": 70, "message": "LLM failed — building deterministic strategy"})
                    strategy_result = _build_deterministic_strategy(spec, raw_brief_text)
                pool.shutdown(wait=False)

                if not strategy_result:
                    logger.warning("[strategy:%s] LLM returned empty — falling back to deterministic strategy", job_id)
                    store.update_job(job_id, progress_pct=70,
                                     progress_message="Building deterministic strategy")
                    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                                 "progress_pct": 70, "message": "Building deterministic strategy"})
                    strategy_result = _build_deterministic_strategy(spec, raw_brief_text)

            logger.info("[strategy:%s] LLM strategy generation succeeded — validating Boolean syntax", job_id)
            store.update_job(job_id, progress_pct=80,
                             progress_message="Validating Boolean syntax")

            from .agents.meltwater_query_builder import validate_boolean_syntax
            validation_issues = []
            if isinstance(strategy_result, dict):
                for qv in strategy_result.get("core_queries", []):
                    if isinstance(qv, dict) and qv.get("query"):
                        issues = validate_boolean_syntax(qv["query"])
                        if issues:
                            validation_issues.extend(issues)

            strategy_result["_validation_issues"] = validation_issues
            strategy_result["_validation_status"] = (
                "structurally_valid" if not validation_issues
                else "requires_meltwater_validation"
            )

            if isinstance(strategy_result, dict):
                for module in strategy_result.get("query_modules", []):
                    if isinstance(module, dict):
                        for term in module.get("terms", []):
                            if isinstance(term, dict) and not term.get("provenance"):
                                term["provenance"] = "llm_generated"

            strategy_id = store.save_search_strategy(req.project_id, strategy_result)
            logger.info("[strategy:%s] Strategy saved as strategy_id=%s", job_id, strategy_id)

            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Search strategy generated",
                             result={"strategy_id": strategy_id, "project_id": req.project_id})
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                         "progress_pct": 100, "message": "Search strategy generated"})

        except Exception as e:
            logger.error("[strategy:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed", "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/strategy/{project_id}")
def get_search_strategy(project_id: int):
    strategy = store.get_latest_strategy(project_id)
    if not strategy:
        raise HTTPException(404, "No strategy found for this project")

    versions = store.get_query_versions(strategy["id"])

    return {
        "strategy_id": strategy["id"],
        "version": strategy["version"],
        "approval_status": strategy["approval_status"],
        "strategy": strategy["strategy"],
        "query_versions": versions,
        "created_at": strategy["created_at"],
    }


@router.post("/strategy/{strategy_id}/edit-query")
def edit_query(strategy_id: int, req: EditQueryRequest):
    from .agents.meltwater_query_builder import validate_boolean_syntax
    issues = validate_boolean_syntax(req.query_text)
    version_id = store.update_strategy_query(strategy_id, req.query_type, req.query_text)
    return {
        "version_id": version_id,
        "validation_issues": issues,
        "validation_status": "structurally_valid" if not issues else "has_issues",
    }


@router.get("/strategy/{strategy_id}/versions")
def get_query_versions(strategy_id: int):
    return store.get_query_versions(strategy_id)


@router.post("/strategy/{strategy_id}/approve")
def approve_search_strategy(strategy_id: int, req: ApproveRequest):
    store.approve_strategy(strategy_id, req.reviewer)
    _broadcast({"type": "intel_strategy_approved", "strategy_id": strategy_id})
    return {"ok": True}


class EditRQRequest(BaseModel):
    question_id: str
    question: str
    query: str = ""


@router.put("/strategy/{strategy_id}/research-question")
def edit_research_question(strategy_id: int, req: EditRQRequest):
    ok = store.update_research_question(strategy_id, req.question_id, req.question, req.query)
    if not ok:
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


@router.delete("/strategy/{strategy_id}/research-question/{question_id}")
def delete_research_question(strategy_id: int, question_id: str):
    ok = store.delete_research_question(strategy_id, question_id)
    if not ok:
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


# ─── Dataset Upload ────────────────────────────────────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

MELTWATER_COLUMN_MAP = {
    "headline": ["title", "headline", "article title", "heading"],
    "snippet": ["hit sentence", "opening text", "snippet", "extract", "summary", "content snippet"],
    "url": ["url", "link", "article url", "source url"],
    "date": ["date", "publish date", "published date", "pub date", "timestamp", "date/time"],
    "source_name": ["source name", "source", "publication", "outlet", "media outlet"],
    "source_domain": ["source domain", "domain"],
    "geography": ["country", "geography", "location", "country/region"],
    "region": ["region", "state"],
    "city": ["city"],
    "media_type": ["information type", "media type", "type", "content type"],
    "source_type": ["source type", "channel"],
    "reach": ["reach", "potential reach", "impressions", "audience"],
    "global_reach": ["global reach"],
    "sentiment": ["sentiment", "brand sentiment", "tone", "sentiment score"],
    "key_phrases": ["keyphrases", "key phrases", "keywords", "tags", "key terms", "topics"],
    "language": ["language", "lang"],
    "author": ["author name", "author", "journalist", "byline", "writer"],
    "author_handle": ["author handle"],
    "engagement": ["engagement", "interactions", "social engagement"],
    "shares": ["shares", "social echo"],
    "likes": ["likes", "reactions"],
    "comments": ["comments", "replies"],
    "views": ["views", "estimated views"],
}


def _auto_map_columns(file_columns: list[str]) -> dict:
    mapping = {}
    file_cols_lower = {c.strip().lower(): c for c in file_columns}
    for target_field, aliases in MELTWATER_COLUMN_MAP.items():
        for alias in aliases:
            if alias in file_cols_lower:
                mapping[target_field] = file_cols_lower[alias]
                break
    unmapped = [c for c in file_columns if c not in mapping.values()]
    return {"mapped": mapping, "unmapped": unmapped}


KNOWN_HEADERS = {"date", "url", "headline", "title", "source name", "source", "sentiment",
                  "reach", "country", "language", "media type", "hit sentence", "opening text",
                  "author name", "document id", "source type", "information type", "keywords"}


def _parse_and_analyze(file_path: str) -> tuple[list[str], list[dict], int, dict, dict]:
    """Parse file in a single streaming pass — O(1) memory, only preview rows kept."""
    import csv
    ext = Path(file_path).suffix.lower()

    headers: list[str] = []
    preview: list[dict] = []
    total_count = 0

    # Streaming accumulators
    sheet_counts: dict[str, int] = {}
    sent_pos = sent_neg = sent_neu = sent_other = 0
    types: dict[str, int] = {}
    geos: dict[str, int] = {}
    sources: dict[str, int] = {}
    langs: dict[str, int] = {}
    date_min: str | None = None
    date_max: str | None = None
    date_count = 0
    reach_total = 0.0
    reach_max = 0.0
    reach_count = 0

    mapped: dict = {}
    sentiment_col = media_col = geo_col = source_col = date_col = reach_col = lang_col = None

    def _update_stats(row_dict: dict, sheet_name: str | None = None):
        nonlocal total_count, sent_pos, sent_neg, sent_neu, sent_other
        nonlocal date_min, date_max, date_count, reach_total, reach_max, reach_count
        total_count += 1
        if len(preview) < 20:
            preview.append({k: str(v or "") for k, v in row_dict.items()})
        if sheet_name:
            sheet_counts[sheet_name] = sheet_counts.get(sheet_name, 0) + 1
        if sentiment_col:
            sv = str(row_dict.get(sentiment_col, "")).strip().lower()
            if sv in ("positive", "pos"): sent_pos += 1
            elif sv in ("negative", "neg"): sent_neg += 1
            elif sv in ("neutral", "neu"): sent_neu += 1
            elif sv: sent_other += 1
        if media_col:
            t = str(row_dict.get(media_col, "")).strip()
            if t: types[t] = types.get(t, 0) + 1
        if geo_col:
            g = str(row_dict.get(geo_col, "")).strip()
            if g: geos[g] = geos.get(g, 0) + 1
        if source_col:
            s = str(row_dict.get(source_col, "")).strip()
            if s: sources[s] = sources.get(s, 0) + 1
        if lang_col:
            la = str(row_dict.get(lang_col, "")).strip()
            if la: langs[la] = langs.get(la, 0) + 1
        if date_col:
            d = str(row_dict.get(date_col, "")).strip()
            if d:
                date_count += 1
                if date_min is None or d < date_min: date_min = d
                if date_max is None or d > date_max: date_max = d
        if reach_col:
            try:
                rv = float(str(row_dict.get(reach_col, "0")).replace(",", ""))
                reach_total += rv
                reach_count += 1
                if rv > reach_max: reach_max = rv
            except (ValueError, TypeError):
                pass

    def _init_mapped(hdrs: list[str]):
        nonlocal mapped, sentiment_col, media_col, geo_col, source_col, date_col, reach_col, lang_col
        column_mapping = _auto_map_columns(hdrs)
        mapped = column_mapping.get("mapped", {})
        sentiment_col = mapped.get("sentiment")
        media_col = mapped.get("media_type")
        geo_col = mapped.get("geography")
        source_col = mapped.get("source_name")
        date_col = mapped.get("date")
        reach_col = mapped.get("reach")
        lang_col = mapped.get("language")

    if ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            sheet_headers: list[str] = []
            col_count = 0
            found_header = False
            for row in ws.iter_rows(values_only=True):
                if not found_header:
                    cells = [str(c or "").strip().lower() for c in row]
                    non_empty = [c for c in cells if c]
                    if sum(1 for c in non_empty if c in KNOWN_HEADERS) >= 3:
                        sheet_headers = [str(c or "").strip() for c in row]
                        sheet_headers = [h for h in sheet_headers if h]
                        col_count = len(sheet_headers)
                        found_header = True
                        if not headers:
                            headers = sheet_headers
                            _init_mapped(headers)
                    continue
                vals = list(row)[:col_count]
                if all(v is None for v in vals):
                    continue
                row_dict = {sheet_headers[j]: v for j, v in enumerate(vals)}
                _update_stats(row_dict, ws.title)
        wb.close()
        if not headers:
            raise ValueError("Could not detect column headers in any sheet")
    else:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            _init_mapped(headers)
            for row in reader:
                _update_stats(row)

    column_mapping = _auto_map_columns(headers)
    stats: dict = {"total_records": total_count}
    if sheet_counts:
        stats["sheets"] = sheet_counts
    sent_total = sent_pos + sent_neg + sent_neu + sent_other
    if sent_total:
        stats["sentiment"] = {"positive": sent_pos, "negative": sent_neg, "neutral": sent_neu, "other": sent_other}
    if types:
        stats["media_types"] = dict(sorted(types.items(), key=lambda x: -x[1])[:10])
    if geos:
        stats["geographies"] = dict(sorted(geos.items(), key=lambda x: -x[1])[:10])
    if sources:
        stats["top_sources"] = dict(sorted(sources.items(), key=lambda x: -x[1])[:10])
        stats["unique_source_count"] = len(sources)
    if date_min and date_max:
        stats["date_range"] = {"earliest": date_min, "latest": date_max, "count": date_count}
    if reach_count:
        stats["reach"] = {"total": reach_total, "avg": round(reach_total / reach_count), "max": reach_max}
    if langs:
        stats["languages"] = dict(sorted(langs.items(), key=lambda x: -x[1])[:5])

    return headers, preview, total_count, column_mapping, stats


def _process_dataset_bg(dataset_id: int, file_path: str, file_name: str, project_id: int):
    """Background thread: parse file and update the dataset record."""
    try:
        columns, preview, total_count, column_mapping, stats = _parse_and_analyze(file_path)
        store.update_dataset_parsed(dataset_id, total_count, column_mapping, stats, preview)
        logger.info("Dataset %d parsed: %d records from %s", dataset_id, total_count, file_name)
    except Exception as e:
        logger.error("Dataset %d parse failed: %s", dataset_id, e)
        store.update_dataset_error(dataset_id, str(e))


@router.post("/dataset/upload")
async def upload_dataset(
    project_id: int,
    file: UploadFile = File(...),
    research_question_id: str | None = None,
):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "dataset.csv").suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(400, "Only CSV and XLSX files are supported")

    safe_name = f"dataset_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    dataset_id = store.save_dataset(
        project_id, file.filename or safe_name, str(dest),
        0, {}, {}, [], processing_status="processing",
        research_question_id=research_question_id,
    )

    threading.Thread(
        target=_process_dataset_bg,
        args=(dataset_id, str(dest), file.filename or safe_name, project_id),
        daemon=True,
    ).start()

    return {
        "dataset_id": dataset_id,
        "file_name": file.filename,
        "processing_status": "processing",
        "research_question_id": research_question_id,
    }


@router.get("/dataset/{project_id}")
def get_dataset(project_id: int, scope: str = "latest"):
    if scope == "all":
        return store.get_datasets_by_project(project_id)
    dataset = store.get_latest_dataset(project_id)
    if not dataset:
        raise HTTPException(404, "No dataset found")
    return dataset


@router.post("/dataset/{dataset_id}/approve")
def approve_dataset(dataset_id: int):
    store.approve_dataset(dataset_id)
    _broadcast({"type": "intel_dataset_approved", "dataset_id": dataset_id})
    return {"ok": True}


@router.delete("/dataset/{dataset_id}")
def delete_dataset(dataset_id: int):
    store.delete_dataset(dataset_id)
    return {"ok": True}


# ─── Sample Evaluation ──────────────────────────────────────────────────────


@router.post("/evaluation/upload")
async def upload_sample_dataset(
    project_id: int,
    strategy_id: int,
    file: UploadFile = File(...),
):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "sample.csv").suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(400, "Only CSV and XLSX files are supported")

    safe_name = f"sample_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    eval_id = store.save_sample_evaluation(project_id, strategy_id, file.filename or safe_name, str(dest))

    job_id = f"eval_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, project_id, "sample_evaluation")

    def worker():
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Detecting Meltwater export structure")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Detecting Meltwater export structure"})

        try:
            project = store.get_project(project_id)
            strategy = store.get_latest_strategy(project_id)

            if not project or not strategy:
                store.update_job(job_id, status="failed", error="Project or strategy not found")
                return

            from .agents.query_evaluator import evaluate_sample
            evaluation = evaluate_sample(
                str(dest),
                project["spec"],
                strategy["strategy"],
            )

            store.update_evaluation(eval_id, evaluation)
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Evaluation complete",
                             result={"eval_id": eval_id, "evaluation": evaluation})
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                         "progress_pct": 100, "message": "Evaluation complete"})

        except Exception as e:
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed", "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "eval_id": eval_id}


@router.get("/evaluation/{project_id}")
def get_evaluation(project_id: int):
    evaluation = store.get_latest_evaluation(project_id)
    if not evaluation:
        raise HTTPException(404, "No evaluation found")
    return evaluation


# ─── Final Query Approval ────────────────────────────────────────────────────

@router.post("/strategy/{project_id}/final-approve")
def final_query_approval(project_id: int, req: FinalApprovalRequest):
    strategy = store.get_latest_strategy(project_id)
    if not strategy:
        raise HTTPException(404, "No strategy found")

    research = store.get_latest_research(project_id)

    blocking = []
    strat_data = strategy["strategy"]
    if isinstance(strat_data, dict):
        issues = strat_data.get("_validation_issues", [])
        if issues:
            blocking.append("Boolean structure has validation issues")

        status = strat_data.get("_validation_status", "")
        if status not in ("structurally_valid", "confirmed_in_meltwater"):
            blocking.append("Query has not been validated")

    evaluation = store.get_latest_evaluation(project_id)
    if not evaluation and not req.sample_evaluation_waived:
        blocking.append("Sample evaluation not completed (and not waived)")

    if not req.acknowledge_meltwater_validation:
        blocking.append("Must acknowledge that Meltwater platform validation may still be required")

    if blocking:
        return {"approved": False, "blocking_reasons": blocking}

    store.approve_strategy(strategy["id"], req.reviewer)

    result = {
        "approved": True,
        "strategy_id": strategy["id"],
        "strategy_version": strategy["version"],
        "approval_date": time.time(),
        "reviewer": req.reviewer,
        "background_research_version": research["version"],
        "sample_evaluation_waived": req.sample_evaluation_waived,
        "sample_dataset_used": evaluation["file_name"] if evaluation else None,
        "evaluation_results": evaluation.get("evaluation") if evaluation else None,
    }

    _broadcast({"type": "intel_final_approval", "project_id": project_id, "strategy_id": strategy["id"]})
    return result


# ─── Research Plan ────────────────────────────────────────────────────────────

class PlanApproveRequest(BaseModel):
    reviewer: str = "analyst"

class PlanRejectRequest(BaseModel):
    notes: str = ""

class PlanRegenerateRequest(BaseModel):
    project_id: int


@router.post("/plan/generate")
def generate_research_plan(req: GenerateStrategyRequest):
    """Generate a Research Plan for the given project."""
    from . import planner_service

    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    prereqs = planner_service.validate_prerequisites(req.project_id)
    if not prereqs["ready"]:
        return {
            "status": "blocked",
            "error": "Prerequisites not met",
            "prerequisites": prereqs["prerequisites"],
        }

    job_id = f"plan_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_plan")

    def worker():
        logger.info("[plan:%s] Starting plan generation for project %s", job_id, req.project_id)
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Validating prerequisites")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Validating prerequisites"})

        try:
            def emit(event_type, payload):
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": 50, "message": str(payload.get("status", event_type))})

            result = planner_service.generate_plan(req.project_id, emit=emit)

            if result.get("status") == "completed":
                store.update_job(job_id, status="completed", progress_pct=100,
                                 progress_message="Research plan generated",
                                 result={"plan_id": result["plan_id"], "project_id": req.project_id})
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                             "progress_pct": 100, "message": "Research plan generated"})
            else:
                error = result.get("error", "Plan generation failed")
                store.update_job(job_id, status="failed", error=error)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                             "error": error})

        except Exception as e:
            logger.error("[plan:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed", "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/plan/{project_id}")
def get_research_plan(project_id: int):
    """Get the latest Research Plan for a project."""
    plan = store.get_latest_plan(project_id)
    if not plan:
        raise HTTPException(404, "No research plan found for this project")
    return plan


@router.post("/plan/{plan_id}/approve")
def approve_research_plan(plan_id: int, req: PlanApproveRequest):
    """Approve a Research Plan."""
    ok = store.approve_plan(plan_id, req.reviewer)
    if not ok:
        raise HTTPException(404, "Plan not found")
    _broadcast({"type": "intel_plan_approved", "plan_id": plan_id})
    return {"ok": True}


@router.post("/plan/{plan_id}/reject")
def reject_research_plan(plan_id: int, req: PlanRejectRequest):
    """Reject a Research Plan."""
    ok = store.reject_plan(plan_id, req.notes)
    if not ok:
        raise HTTPException(404, "Plan not found")
    return {"ok": True}


@router.post("/plan/regenerate")
def regenerate_research_plan(req: PlanRegenerateRequest):
    """Regenerate a plan — same as generate but implies a prior plan exists."""
    return generate_research_plan(GenerateStrategyRequest(project_id=req.project_id))


@router.post("/plan/validate")
def validate_plan_prerequisites(req: GenerateStrategyRequest):
    """Check whether prerequisites are met for plan generation."""
    from . import planner_service
    return planner_service.validate_prerequisites(req.project_id)


# ─── Research Execution ────────────────────────────────────────────────────────

class ExecutionStartRequest(BaseModel):
    project_id: int

class RetryUnitRequest(BaseModel):
    project_id: int


@router.post("/execution/start")
def start_execution(req: ExecutionStartRequest):
    """Start executing the approved Research Plan."""
    from . import executor_service

    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    job_id = f"exec_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_execution")

    def worker():
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Starting execution")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                     "progress_pct": 10, "message": "Starting execution"})

        try:
            def emit(event_type, payload):
                total = payload.get("total", 1)
                completed = payload.get("completed", 0)
                pct = min(90, 10 + int(80 * completed / max(total, 1)))
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": pct,
                             "message": f"{event_type}: {payload.get('unit_id', '')}"})
                _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                             "event": event_type, "payload": payload})

            result = executor_service.start_execution(req.project_id, emit=emit)

            if result.get("status") in ("completed", "completed_with_errors"):
                store.update_job(job_id, status="completed", progress_pct=100,
                                 progress_message="Execution complete",
                                 result=result)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                             "progress_pct": 100, "message": "Execution complete"})
            elif result.get("status") == "blocked":
                store.update_job(job_id, status="failed", error=result.get("error", "Blocked"))
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                             "error": result.get("error")})
            else:
                store.update_job(job_id, status=result.get("status", "failed"),
                                 error=result.get("error"))
                _broadcast({"type": "intel_job_update", "job_id": job_id,
                             "status": result.get("status", "failed"),
                             "error": result.get("error")})

            _broadcast({"type": "intel_execution_complete", "project_id": req.project_id,
                         "result": result})

        except Exception as e:
            logger.error("[execution:%s] Unhandled error: %s", job_id, e, exc_info=True)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                         "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/execution/{project_id}")
def get_execution_status(project_id: int):
    """Get the current execution status for a project."""
    from . import executor_service
    status = executor_service.get_execution_status(project_id)
    if not status:
        raise HTTPException(404, "No execution found for this project")
    return status


@router.post("/execution/{run_id}/pause")
def pause_execution(run_id: int):
    """Pause a running execution."""
    from . import executor_service
    ok = executor_service.pause_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not pausable")
    _broadcast({"type": "intel_execution_update", "event": "paused", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/resume")
def resume_execution(run_id: int, req: ExecutionStartRequest):
    """Resume a paused execution."""
    from . import executor_service

    job_id = f"exec_resume_{uuid.uuid4().hex[:8]}"
    store.create_job(job_id, req.project_id, "research_execution_resume")

    def worker():
        store.update_job(job_id, status="running", progress_pct=10,
                         progress_message="Resuming execution")

        try:
            def emit(event_type, payload):
                _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                             "event": event_type, "payload": payload})

            result = executor_service.resume_execution(req.project_id, run_id, emit=emit)
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Resume complete", result=result)
            _broadcast({"type": "intel_execution_complete", "project_id": req.project_id,
                         "result": result})
        except Exception as e:
            store.update_job(job_id, status="failed", error=str(e))

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@router.post("/execution/{run_id}/cancel")
def cancel_execution(run_id: int):
    """Cancel a running execution."""
    from . import executor_service
    ok = executor_service.cancel_execution(run_id)
    if not ok:
        raise HTTPException(404, "Run not found or not cancellable")
    _broadcast({"type": "intel_execution_update", "event": "cancelled", "run_id": run_id})
    return {"ok": True}


@router.post("/execution/{run_id}/retry/{unit_id}")
def retry_execution_unit(run_id: int, unit_id: str, req: RetryUnitRequest):
    """Retry a single failed execution unit."""
    from . import executor_service

    result = executor_service.retry_unit(req.project_id, run_id, unit_id)
    if result.get("status") == "error":
        raise HTTPException(400, result.get("error", "Retry failed"))
    _broadcast({"type": "intel_execution_update", "project_id": req.project_id,
                 "event": "unit_retried", "payload": {"unit_id": unit_id, "result": result}})
    return result


@router.get("/execution/{run_id}/evidence")
def get_execution_evidence(run_id: int, unit_id: Optional[str] = None):
    """Get evidence collected during execution."""
    return store.get_evidence(run_id, unit_id)


@router.get("/execution/{run_id}/logs")
def get_execution_logs(run_id: int, limit: int = 100):
    """Get execution logs."""
    return store.get_execution_logs(run_id, limit)


# ─── Job status ──────────────────────────────────────────────────────────────

@router.get("/jobs/{project_id}")
def list_project_jobs(project_id: int, job_type: Optional[str] = None):
    return store.list_jobs(project_id, job_type)


@router.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ─── Evidence Library ──────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    project_id: int
    run_id: int


class ReviewRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    note: Optional[str] = None


class AnnotateRequest(BaseModel):
    note: str
    author: str = "analyst"


class BulkReviewRequest(BaseModel):
    item_ids: list[int]
    status: str
    reviewer: str = "analyst"


class ClassifyRequest(BaseModel):
    objective_id: Optional[str] = None
    unit_id: Optional[str] = None
    confidence: Optional[str] = None
    reviewer: str = "analyst"


class RepresentativeRequest(BaseModel):
    is_representative: bool = True


class HighValueRequest(BaseModel):
    is_high_value: bool = True


@router.post("/library/ingest")
def ingest_library_evidence(req: IngestRequest):
    return elib.ingest_evidence(req.project_id, req.run_id)


@router.post("/library/bulk-review")
def bulk_review_library(req: BulkReviewRequest):
    result = elib.bulk_review(req.item_ids, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/library/detail/{item_id}")
def get_library_detail(item_id: int):
    result = elib.get_evidence_detail(item_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/library/audit/{item_id}")
def get_library_audit(item_id: int):
    return store.get_library_audit(item_id)


@router.get("/library/{project_id}")
def list_library(
    project_id: int,
    review_status: Optional[str] = None,
    objective_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    method: Optional[str] = None,
    platform: Optional[str] = None,
    confidence: Optional[str] = None,
    is_representative: Optional[bool] = None,
    is_high_value: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: str = "quality_score",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    return elib.search_evidence(
        project_id,
        query=search,
        review_status=review_status,
        objective_id=objective_id,
        unit_id=unit_id,
        method=method,
        platform=platform,
        confidence=confidence,
        is_representative=is_representative,
        is_high_value=is_high_value,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/library/{project_id}/summary")
def get_library_summary(project_id: int):
    return elib.get_summary_metrics(project_id)


@router.get("/library/{project_id}/coverage")
def get_library_coverage(project_id: int):
    return elib.get_coverage_report(project_id)


@router.get("/library/{project_id}/duplicates")
def get_library_duplicates(project_id: int):
    return store.get_duplicate_groups(project_id)


@router.post("/library/{item_id}/review")
def review_library_item(item_id: int, req: ReviewRequest):
    result = elib.review_evidence(item_id, req.status, req.reviewer, req.note)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/library/{item_id}/annotate")
def annotate_library_item(item_id: int, req: AnnotateRequest):
    ann_id = elib.add_annotation(item_id, req.note, req.author)
    return {"annotation_id": ann_id}


@router.post("/library/{item_id}/classify")
def classify_library_item(item_id: int, req: ClassifyRequest):
    result = elib.update_classification(
        item_id, objective_id=req.objective_id, unit_id=req.unit_id,
        confidence=req.confidence, reviewer=req.reviewer,
    )
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/representative")
def mark_library_representative(item_id: int, req: RepresentativeRequest):
    result = elib.mark_representative(item_id, req.is_representative)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/high-value")
def mark_library_high_value(item_id: int, req: HighValueRequest):
    result = elib.mark_high_value(item_id, req.is_high_value)
    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(404, result.get("error", "Not found"))
    return {"ok": True}


@router.post("/library/{item_id}/restore")
def restore_library_item(item_id: int):
    result = elib.restore_rejected(item_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ─── Insight Generator ─────────────────────────────────────────────────────

class GenerateInsightsRequest(BaseModel):
    project_id: int

class ReviewInsightRequest(BaseModel):
    status: str
    reviewer: str = "analyst"
    notes: str | None = None

class RevisionRequest(BaseModel):
    notes: str
    reviewer: str = "analyst"

class NotesRequest(BaseModel):
    notes: str
    reviewer: str = "analyst"

class ValidatePrereqsRequest(BaseModel):
    project_id: int


@router.post("/insights/generate")
def generate_insights(req: GenerateInsightsRequest):
    result = igen.generate_insights(req.project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/validate-prereqs")
def validate_insight_prereqs(req: ValidatePrereqsRequest):
    return igen.validate_prerequisites(req.project_id)


@router.get("/insights/detail/{insight_id}")
def get_insight_detail(insight_id: int):
    result = igen.get_insight_detail(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/insights/{insight_id}/validate")
def validate_insight_quality(insight_id: int):
    return igen.validate_insight_quality(insight_id)


@router.get("/insights/{insight_id}/evidence")
def get_insight_evidence(insight_id: int):
    return igen.get_supporting_evidence(insight_id)


@router.get("/insights/{project_id}")
def list_insights(
    project_id: int,
    objective_id: str | None = None,
    insight_type: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    return store.list_insights(
        project_id,
        objective_id=objective_id,
        insight_type=insight_type,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/insights/{project_id}/summary")
def get_insights_summary(project_id: int):
    return igen.get_insights_summary(project_id)


@router.post("/insights/{insight_id}/review")
def review_insight(insight_id: int, req: ReviewInsightRequest):
    result = igen.review_insight(insight_id, req.status, reviewer=req.reviewer, notes=req.notes)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/revision")
def request_insight_revision(insight_id: int, req: RevisionRequest):
    result = igen.request_revision(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/notes")
def update_insight_notes(insight_id: int, req: NotesRequest):
    result = igen.update_analyst_notes(insight_id, req.notes, reviewer=req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/insights/{insight_id}/regenerate")
def regenerate_insight(insight_id: int):
    result = igen.regenerate_insight(insight_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ─── Storyline Builder ────────────────────────────────────────────────────

class GenerateStorylineRequest(BaseModel):
    project_id: int
    reviewer: str = "system"

class ReviewNodeRequest(BaseModel):
    status: str
    reviewer: str = "analyst"

class ReorderRequest(BaseModel):
    node_ids: list[int]
    actor: str = "analyst"

class MergeRequest(BaseModel):
    node_id_a: int
    node_id_b: int
    actor: str = "analyst"

class SplitRequest(BaseModel):
    actor: str = "analyst"

class UpdateNodeRequest(BaseModel):
    title: str | None = None
    narrative_summary: str | None = None
    purpose: str | None = None
    suggested_visual: str | None = None
    priority: str | None = None
    is_key_message: bool | None = None
    is_locked: bool | None = None

class StorylineApprovalRequest(BaseModel):
    reviewer: str = "analyst"

class ValidateStorylinePrereqsRequest(BaseModel):
    project_id: int


@router.post("/storyline/generate")
def generate_storyline(req: GenerateStorylineRequest):
    result = sbuilder.generate_storyline(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/validate-prereqs")
def validate_storyline_prereqs(req: ValidateStorylinePrereqsRequest):
    return sbuilder.validate_prerequisites(req.project_id)


@router.get("/storyline/detail/{storyline_id}")
def get_storyline_detail(storyline_id: int):
    result = sbuilder.get_storyline_detail(storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/storyline/{storyline_id}/validate")
def validate_storyline(storyline_id: int):
    return sbuilder.validate_storyline(storyline_id)


@router.get("/storyline/{storyline_id}/nodes")
def list_storyline_nodes(storyline_id: int):
    return store.list_story_nodes(storyline_id)


@router.get("/storyline/{project_id}")
def get_storyline(project_id: int):
    result = store.get_latest_storyline(project_id)
    if not result:
        return []
    return [result]


@router.get("/storyline/{project_id}/summary")
def get_storyline_summary(project_id: int):
    return sbuilder.get_storyline_summary(project_id)


@router.post("/storyline/{storyline_id}/reorder")
def reorder_storyline_nodes(storyline_id: int, req: ReorderRequest):
    result = sbuilder.reorder_nodes(storyline_id, req.node_ids, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/merge")
def merge_storyline_nodes(storyline_id: int, req: MergeRequest):
    result = sbuilder.merge_nodes(req.node_id_a, req.node_id_b, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/approve")
def approve_storyline(storyline_id: int, req: StorylineApprovalRequest):
    result = sbuilder.approve_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/reject")
def reject_storyline(storyline_id: int, req: StorylineApprovalRequest):
    result = sbuilder.reject_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/review")
def review_storyline_node(node_id: int, req: ReviewNodeRequest):
    result = sbuilder.review_node(node_id, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/split")
def split_storyline_node(node_id: int, req: SplitRequest):
    result = sbuilder.split_node(node_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.put("/storyline/node/{node_id}")
def update_storyline_node(node_id: int, req: UpdateNodeRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    ok = store.update_story_node(node_id, **updates)
    if not ok:
        raise HTTPException(404, f"Node {node_id} not found")
    return store.get_story_node(node_id)


# ─── Slide Intelligence ────────────────────────────────────────────────────

class IngestPresentationRequest(BaseModel):
    file_path: str

class UpdateSlideMetadataRequest(BaseModel):
    slide_purpose: Optional[str] = None
    layout_type: Optional[str] = None
    visual_type: Optional[str] = None
    narrative_role: Optional[str] = None
    report_type: Optional[str] = None
    industry: Optional[str] = None
    client: Optional[str] = None
    brand: Optional[str] = None
    data_density: Optional[str] = None
    executive_suitability: Optional[str] = None
    visual_complexity: Optional[str] = None

class SlideSearchRequest(BaseModel):
    query: str
    slide_purpose: Optional[str] = None
    layout_type: Optional[str] = None
    visual_type: Optional[str] = None
    client: Optional[str] = None
    report_type: Optional[str] = None
    limit: int = 50

class RetrieveRequest(BaseModel):
    node_id: int
    top_k: int = 10

class MatchStorylineRequest(BaseModel):
    storyline_id: int


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


# ─── Presentation Composer ─────────────────────────────────────────────────

class GeneratePresentationRequest(BaseModel):
    project_id: int
    reviewer: str = "system"


class UpdatePCSlideRequest(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    narrative: Optional[str] = None
    key_message: Optional[str] = None
    recommended_visual: Optional[str] = None
    recommended_chart: Optional[str] = None
    layout_recommendation: Optional[str] = None
    speaker_notes: Optional[str] = None
    slide_purpose: Optional[str] = None


class ReorderPCSlidesRequest(BaseModel):
    slide_ids: list[int]


class SelectLayoutRequest(BaseModel):
    layout: str
    rationale: str = ""


class SelectVisualRequest(BaseModel):
    visual: str


class ReviewPCSlideRequest(BaseModel):
    status: str
    reviewer: str = "analyst"


class ApprovePCRequest(BaseModel):
    reviewer: str = "analyst"


@router.post("/composer/generate")
def generate_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.post("/composer/validate-prereqs")
def validate_composer_prereqs(req: GeneratePresentationRequest):
    return pc.validate_prerequisites(req.project_id)


# ─── SOV / Theme Archetype Endpoints ──────────────────────────────────────


@router.post("/sov/generate")
def generate_sov_presentation_route(req: GeneratePresentationRequest):
    result = pc.generate_sov_presentation(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/analyze/{project_id}")
def analyze_sov_route(project_id: int):
    from . import sov_analyzer
    result = sov_analyzer.analyze_sov(project_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result)
    return result


@router.get("/sov/themes/{project_id}/{entity_name}")
def classify_themes_route(project_id: int, entity_name: str):
    from . import theme_classifier
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


# ── PowerPoint Renderer ─────────────────────────────────────────────

class RenderPresentationRequest(BaseModel):
    presentation_id: int
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderSlideRequest(BaseModel):
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderSectionRequest(BaseModel):
    purpose: str
    theme_id: str = "hunter_default"
    actor: str = "system"


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
    from fastapi.responses import FileResponse
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


# ── Pipeline Orchestrator ─────────────────────────────────────────────

class StartPipelineRequest(BaseModel):
    project_id: int
    mode: str = "full"
    start_stage: Optional[str] = None
    single_stage: Optional[str] = None
    user: str = "system"


class RetryStageRequest(BaseModel):
    stage_id: str


class ClearCacheRequest(BaseModel):
    stage_id: Optional[str] = None


@router.post("/pipeline/start")
def start_pipeline_route(req: StartPipelineRequest):
    return orchestrator.start_pipeline(
        req.project_id, mode=req.mode,
        start_stage=req.start_stage,
        single_stage=req.single_stage,
        user=req.user,
    )


@router.post("/pipeline/{run_id}/pause")
def pause_pipeline_route(run_id: str):
    return orchestrator.pause_pipeline(run_id)


@router.post("/pipeline/{run_id}/resume")
def resume_pipeline_route(run_id: str):
    return orchestrator.resume_pipeline(run_id)


@router.post("/pipeline/{run_id}/cancel")
def cancel_pipeline_route(run_id: str):
    return orchestrator.cancel_pipeline(run_id)


@router.post("/pipeline/{run_id}/retry")
def retry_stage_route(run_id: str, req: RetryStageRequest):
    return orchestrator.retry_stage(run_id, req.stage_id)


@router.post("/pipeline/run-stage")
def run_single_stage_route(req: StartPipelineRequest):
    return orchestrator.run_single_stage(
        req.project_id, req.single_stage or req.start_stage or "brief_scope",
        user=req.user,
    )


@router.post("/pipeline/run-from")
def run_from_stage_route(req: StartPipelineRequest):
    return orchestrator.run_from_stage(
        req.project_id, req.start_stage or "brief_scope",
        user=req.user,
    )


@router.get("/pipeline/status/{run_id}")
def pipeline_status_route(run_id: str):
    result = orchestrator.get_pipeline_status(run_id)
    if not result:
        raise HTTPException(404, "Pipeline run not found")
    return result


@router.get("/pipeline/project/{project_id}")
def project_pipeline_status_route(project_id: int):
    return orchestrator.get_project_status(project_id)


@router.get("/pipeline/timeline/{run_id}")
def pipeline_timeline_route(run_id: str):
    return orchestrator.get_execution_timeline(run_id)


@router.get("/pipeline/logs/{run_id}")
def pipeline_logs_route(run_id: str, stage_id: Optional[str] = None):
    return orchestrator.get_pipeline_logs(run_id, stage_id)


@router.get("/pipeline/metrics/{project_id}")
def pipeline_metrics_route(project_id: int):
    return orchestrator.get_performance_metrics(project_id)


@router.get("/pipeline/cache/{project_id}")
def pipeline_cache_route(project_id: int):
    return orchestrator.get_cache_metrics(project_id)


@router.post("/pipeline/cache/{project_id}/clear")
def clear_pipeline_cache_route(project_id: int, req: ClearCacheRequest):
    if req.stage_id:
        count = orchestrator.clear_stage_cache(project_id, req.stage_id)
    else:
        count = orchestrator.clear_project_cache(project_id)
    return {"cleared": count}


@router.get("/pipeline/graph")
def dependency_graph_route():
    return orchestrator.get_dependency_graph()


@router.get("/pipeline/stages/{project_id}")
def project_stages_route(project_id: int):
    return orchestrator.get_project_stage_statuses(project_id)


# ── Word Report Renderer ──────────────────────────────────────────────

class RenderWordReportRequest(BaseModel):
    presentation_id: int
    theme_id: str = "hunter_default"
    actor: str = "system"


class RenderWordSectionRequest(BaseModel):
    section_name: str
    theme_id: str = "hunter_default"
    actor: str = "system"


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
    from fastapi.responses import FileResponse
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


# ── Publishing & Quality Gateway ──────────────────────────────────────────

class PubValidateRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"


class PubApprovalRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"
    notes: str | None = None


class PubPackageRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"


class PubVersionRequest(BaseModel):
    project_id: int
    presentation_id: int
    actor: str = "system"
    notes: str | None = None


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
    from fastapi.responses import FileResponse
    path = pub.get_download_path(package_id)
    if not path:
        raise HTTPException(404, "Package not found or not ready")
    filename = Path(path).name
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.get("/publishing/download/pptx/{pres_id}")
def pub_download_pptx_route(pres_id: int):
    from fastapi.responses import FileResponse
    path = pub.get_pptx_download_path(pres_id)
    if not path:
        raise HTTPException(404, "PowerPoint file not found")
    filename = Path(path).name
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=filename)


@router.get("/publishing/download/word/{pres_id}")
def pub_download_word_route(pres_id: int):
    from fastapi.responses import FileResponse
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


# ─── Monitoring QC ──────────────────────────────────────────────────────────

@router.post("/qc/upload")
async def qc_upload_route(project_id: int = Form(0), file: UploadFile = File(...)):
    from . import qc_parser

    if not project_id:
        raise HTTPException(400, "project_id is required")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls", ".docx", ".pptx"):
        raise HTTPException(400, "Supported formats: CSV, Excel, Word (.docx), PowerPoint (.pptx)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"qc_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    report_id = store.create_qc_report(project_id, file.filename or safe_name, str(dest))

    try:
        result = qc_parser.parse_file(str(dest))
        if "error" in result:
            store.update_qc_report(report_id, parse_status="error", parse_error=result["error"])
            return {
                "report_id": report_id,
                "file_name": file.filename,
                "parse_status": "error",
                "parse_error": result["error"],
            }
        store.update_qc_report(
            report_id,
            parse_status="done",
            row_count=result["row_count"],
            column_count=result["column_count"],
            columns_json=result["columns"],
            field_mapping=result["field_mapping"],
        )
        return {
            "report_id": report_id,
            "file_name": file.filename,
            "parse_status": "done",
        }
    except Exception as e:
        logger.error("QC parse error for report %s: %s", report_id, e)
        store.update_qc_report(report_id, parse_status="error", parse_error=str(e))
        return {
            "report_id": report_id,
            "file_name": file.filename,
            "parse_status": "error",
            "parse_error": str(e),
        }


@router.get("/qc/report/{project_id}")
def qc_report_route(project_id: int):
    report = store.get_qc_report_for_project(project_id)
    if not report:
        raise HTTPException(404, "No QC report found for this project")
    return report


@router.get("/qc/report/detail/{report_id}")
def qc_report_detail_route(report_id: int):
    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


@router.get("/qc/preview/{report_id}")
def qc_preview_route(report_id: int):
    from . import qc_parser

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if report["parse_status"] != "done":
        return {"status": report["parse_status"], "preview": [], "error": report.get("parse_error")}

    parsed = qc_parser.parse_file(report["file_path"])
    if "error" in parsed:
        return {"status": "error", "preview": [], "error": parsed["error"]}
    return {"status": "done", "preview": parsed.get("preview", [])[:20]}


@router.get("/qc/all-rows/{report_id}")
def qc_all_rows_route(report_id: int):
    from . import qc_parser

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    parsed = qc_parser.parse_file(report["file_path"])
    if "error" in parsed:
        return {"rows": []}
    columns = parsed.get("columns", [])
    all_preview = parsed.get("preview", [])
    if len(all_preview) < parsed.get("row_count", 0):
        mapping = report.get("field_mapping") or {}
        raw = qc_parser.get_rows_from_file(report["file_path"], mapping)
        reverse = {v: k for k, v in mapping.items()}
        all_preview = [{reverse.get(k, k): v for k, v in row.items()} for row in raw]
    return {"rows": all_preview, "columns": columns}


@router.post("/qc/field-mapping/{report_id}")
def qc_save_mapping_route(report_id: int, body: dict):
    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    mapping = body.get("mapping", {})
    store.save_qc_field_mapping(report_id, mapping)
    return {"ok": True, "report_id": report_id}


@router.post("/qc/run/{report_id}")
def qc_run_route(report_id: int):
    from . import qc_service

    report = store.get_qc_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    if report["parse_status"] != "done":
        raise HTTPException(400, "Report not fully parsed")
    if not report.get("field_mapping"):
        raise HTTPException(400, "No field mapping configured")

    job_id = f"qc_run_{uuid.uuid4().hex[:12]}"

    def _run_bg():
        try:
            def _on_progress(msg, pct):
                _broadcast({"type": "qc_progress", "report_id": report_id, "message": msg, "progress_pct": pct})

            result = qc_service.run_qc(report_id, on_progress=_on_progress)
            _broadcast({"type": "qc_complete", "report_id": report_id, "result": result})
        except Exception as e:
            logger.error("QC run error for report %s: %s", report_id, e, exc_info=True)
            _broadcast({"type": "qc_error", "report_id": report_id, "error": str(e)})

    threading.Thread(target=_run_bg, daemon=True).start()
    return {"status": "started", "report_id": report_id, "job_id": job_id}


@router.get("/qc/runs/{report_id}")
def qc_runs_route(report_id: int):
    return store.get_qc_runs_for_report(report_id)


@router.get("/qc/results/{run_id}")
def qc_results_route(run_id: int, severity: str | None = None, check_type: str | None = None):
    findings = store.get_qc_findings(run_id, severity=severity, check_type=check_type)
    return findings


@router.get("/qc/summary/{run_id}")
def qc_summary_route(run_id: int):
    run = store.get_qc_run(run_id)
    if not run:
        raise HTTPException(404, "QC run not found")
    return run


@router.post("/qc/finding/{finding_id}/action")
def qc_finding_action_route(finding_id: int, body: dict):
    action = body.get("action", "")
    if action not in ("accepted", "dismissed", "flagged"):
        raise HTTPException(400, "Invalid action -- use: accepted, dismissed, flagged")
    store.update_qc_finding_action(finding_id, action)
    return {"ok": True}


@router.post("/qc/export/{run_id}")
def qc_export_route(run_id: int):
    from . import qc_export

    result = qc_export.export_qc_results(run_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/qc/export/download/{export_id}")
def qc_export_download_route(export_id: int):
    from fastapi.responses import FileResponse

    conn = store._conn()
    row = conn.execute("SELECT * FROM qc_exports WHERE id = ?", (export_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Export not found")
    from pathlib import Path
    p = Path(row["file_path"])
    if not p.exists():
        raise HTTPException(404, "Export file not found on disk")
    return FileResponse(str(p), filename=row["file_name"], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

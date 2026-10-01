"""Meltwater search strategy routes: generate, edit, approve, final-approve.

Also contains:
- dataset_evaluation: Meltwater dataset upload/parsing and sample-evaluation routes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Annotated

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Path as PathParam

from ...agents.meltwater_query_builder import run as run_mqb
from ...agents.meltwater_query_builder import validate_boolean_syntax
from ...agents.query_evaluator import evaluate_sample
from ...core import store
from ...core.anthropic_client import get_llm_client
from ...core.api import OkResponse
from ...core.auth import require_project_access
from ...core.config import UPLOAD_DIR
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from ..research.schemas import ApproveRequest
from .schemas import (
    DatasetRecord,
    DatasetUploadResponse,
    EditQueryRequest,
    EditQueryResponse,
    EditRQRequest,
    EvaluationUploadResponse,
    FinalApprovalRequest,
    FinalApprovalResult,
    GenerateStrategyRequest,
    QueryVersion,
    SampleEvaluationRecord,
    SearchStrategyResponse,
    StrategyJobStarted,
)

logger = logging.getLogger(__name__)

STRATEGY_LLM_TIMEOUT = 300

IdPath = Annotated[int, PathParam(ge=1)]

router = APIRouter()


def _extract_competitors_from_text(text: str, brand_name: str) -> list[str]:
    """Extract competitor names from natural-language brief text."""
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

    # Third AND-group: concepts/issues/events/people, drawn from entities not already
    # covered by cat_terms (brand/category/product).
    concept_terms = []
    for entity in spec.get("validated_entities", []):
        if entity.get("type") in ("event", "topic", "executive") and entity.get("name"):
            concept_terms.append(f'"{entity["name"]}"')

    broad_q = f"({brand_or}){not_clause}"
    if cat_terms and concept_terms:
        balanced_q = (
            f"({brand_or}) AND ({' OR '.join(cat_terms)}) "
            f"AND ({' OR '.join(concept_terms)}){not_clause}"
        )
    elif cat_terms:
        balanced_q = f"({brand_or}) AND ({' OR '.join(cat_terms)}){not_clause}"
    elif concept_terms:
        balanced_q = f"({brand_or}) AND ({' OR '.join(concept_terms)}){not_clause}"
    else:
        balanced_q = broad_q
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

        if cat_terms and concept_terms:
            landscape_q = (
                f'{all_brands} AND ({" OR ".join(cat_terms)}) '
                f'AND ({" OR ".join(concept_terms)}){not_clause}'
            )
        elif cat_terms:
            landscape_q = f'{all_brands} AND ({" OR ".join(cat_terms)}){not_clause}'
        elif concept_terms:
            landscape_q = f'{all_brands} AND ({" OR ".join(concept_terms)}){not_clause}'
        else:
            landscape_q = f'{all_brands}{not_clause}'

        comp_core_queries.append({
            "type": "competitive_landscape",
            "query": landscape_q,
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

    # Build concepts/issues/events/people module (only when concept entities exist)
    concept_modules = []
    if concept_terms:
        concept_modules.append({
            "module_id": "M4",
            "name": "Concepts, issues & people",
            "purpose": "Capture concept, issue, event, and people-related context",
            "terms": {
                "primary": concept_terms,
                "synonyms": [],
                "exclusions": [],
                "provenance": "deterministic",
            },
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
            *concept_modules,
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


@router.post("/strategy/generate", response_model=StrategyJobStarted)
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

    submit(worker, name="strategy:generate")
    return {"job_id": job_id, "project_id": req.project_id}


@router.get("/strategy/{project_id}", response_model=SearchStrategyResponse)
def get_search_strategy(project_id: IdPath, _access: Annotated[dict, Depends(require_project_access)]):
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


@router.post("/strategy/{strategy_id}/edit-query", response_model=EditQueryResponse)
def edit_query(strategy_id: IdPath, req: EditQueryRequest):
    issues = validate_boolean_syntax(req.query_text)
    version_id = store.update_strategy_query(strategy_id, req.query_type, req.query_text)
    return {
        "version_id": version_id,
        "validation_issues": issues,
        "validation_status": "structurally_valid" if not issues else "has_issues",
    }


@router.get("/strategy/{strategy_id}/versions", response_model=list[QueryVersion])
def get_query_versions(strategy_id: IdPath):
    return store.get_query_versions(strategy_id)


@router.post("/strategy/{strategy_id}/approve", response_model=OkResponse)
def approve_search_strategy(strategy_id: IdPath, req: ApproveRequest):
    store.approve_strategy(strategy_id, req.reviewer)
    _broadcast({"type": "intel_strategy_approved", "strategy_id": strategy_id})
    return {"ok": True}


@router.put("/strategy/{strategy_id}/research-question", response_model=OkResponse)
def edit_research_question(strategy_id: IdPath, req: EditRQRequest):
    ok = store.update_research_question(strategy_id, req.question_id, req.question, req.query)
    if not ok:
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


@router.delete("/strategy/{strategy_id}/research-question/{question_id}", response_model=OkResponse)
def delete_research_question(strategy_id: IdPath, question_id: str):
    ok = store.delete_research_question(strategy_id, question_id)
    if not ok:
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


@router.post("/strategy/{project_id}/final-approve", response_model=FinalApprovalResult)
def final_query_approval(project_id: IdPath, req: FinalApprovalRequest,
                          _access: Annotated[dict, Depends(require_project_access)]):
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


# ─── Dataset Evaluation ────────────────────────────────────────────────

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


def _process_dataset_bg(dataset_id: int, file_path: str, file_name: str, project_id: int,
                        job_id: str):
    """Background thread: parse file and update the dataset record."""
    store.update_job(job_id, status="running", progress_pct=10,
                     progress_message="Parsing dataset")
    _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                 "progress_pct": 10, "message": "Parsing dataset"})
    try:
        columns, preview, total_count, column_mapping, stats = _parse_and_analyze(file_path)
        store.update_dataset_parsed(dataset_id, total_count, column_mapping, stats, preview)
        logger.info("Dataset %d parsed: %d records from %s", dataset_id, total_count, file_name)
        store.update_job(job_id, status="completed", progress_pct=100,
                         progress_message="Dataset parsed",
                         result={"dataset_id": dataset_id, "total_count": total_count})
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "completed",
                     "progress_pct": 100, "message": "Dataset parsed"})
    except Exception as e:
        logger.error("Dataset %d parse failed: %s", dataset_id, e)
        store.update_dataset_error(dataset_id, str(e))
        store.update_job(job_id, status="failed", error=str(e))
        _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "failed",
                     "error": str(e)})


@router.post("/dataset/upload", response_model=DatasetUploadResponse)
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

    job_id = str(uuid.uuid4())
    store.create_job(job_id, project_id, "dataset_upload")

    submit(_process_dataset_bg, dataset_id, str(dest), file.filename or safe_name, project_id, job_id,
           name="strategy:dataset-parse")

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "file_name": file.filename,
        "processing_status": "processing",
        "research_question_id": research_question_id,
    }


@router.get("/dataset/{project_id}", response_model=DatasetRecord | list[DatasetRecord])
def get_dataset(project_id: IdPath, _access: Annotated[dict, Depends(require_project_access)],
                 scope: str = "latest"):
    if scope == "all":
        return store.get_datasets_by_project(project_id)
    dataset = store.get_latest_dataset(project_id)
    if not dataset:
        raise HTTPException(404, "No dataset found")
    return dataset


@router.post("/dataset/{dataset_id}/approve", response_model=OkResponse)
def approve_dataset(dataset_id: IdPath):
    store.approve_dataset(dataset_id)
    _broadcast({"type": "intel_dataset_approved", "dataset_id": dataset_id})
    return {"ok": True}


@router.delete("/dataset/{dataset_id}", response_model=OkResponse)
def delete_dataset(dataset_id: IdPath):
    store.delete_dataset(dataset_id)
    return {"ok": True}


@router.post("/evaluation/upload", response_model=EvaluationUploadResponse)
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

    submit(worker, name="strategy:sample-evaluation")
    return {"job_id": job_id, "eval_id": eval_id}


@router.get("/evaluation/{project_id}", response_model=SampleEvaluationRecord)
def get_evaluation(project_id: IdPath, _access: Annotated[dict, Depends(require_project_access)]):
    evaluation = store.get_latest_evaluation(project_id)
    if not evaluation:
        raise HTTPException(404, "No evaluation found")
    return evaluation

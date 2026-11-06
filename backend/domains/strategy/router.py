"""Meltwater search strategy routes: generate, edit, approve, final-approve.

Also contains:
- dataset_evaluation: Meltwater dataset upload/parsing and sample-evaluation routes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import csv
import io
import itertools
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import Path as PathParam

from ...agents.meltwater_query_builder import run as run_mqb
from ...agents.meltwater_query_builder import quote_bare_phrases, validate_boolean_syntax
from ...agents.query_evaluator import evaluate_sample
from ...core import store
from ...core.llm_provider import extract_json_object as _extract_json_object, get_llm_client
from ...core.api import OkResponse
from ...core.auth import (
    check_project_id_access,
    get_current_user,
    require_dataset_access,
    require_project_access,
    require_strategy_access,
)
from ...core.config import UPLOAD_DIR
from ...core.events import broadcast as _broadcast
from ...core.jobs import submit
from ...core.tabular import decode_text, sniff_delimiter
from ..research.schemas import ApproveRequest
from ..research.web_research import COMPETITOR_PATTERNS
from .schemas import (
    DatasetRecord,
    DatasetUploadResponse,
    EditQueryRequest,
    EditQueryResponse,
    AddRQRequest,
    AddRQResult,
    EditRQRequest,
    RQStatusRequest,
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


def _date_range(values: list[str]) -> dict:
    """Earliest and latest as real dates (ISO), so day-first exports (25-09-2026) are not compared as text, and the
    count of dates that parsed; when none parse, the text order of the raw values."""
    from ..deliverable.ingest import infer_date_order, parse_date
    order = infer_date_order(values)
    dates = sorted(d for d in (parse_date(v, order) for v in values) if d)
    if dates:
        return {"earliest": dates[0].isoformat(), "latest": dates[-1].isoformat(), "count": len(dates)}
    return {"earliest": min(values), "latest": max(values), "count": len(values)}


def _extract_competitors_from_text(text: str, brand_name: str) -> list[str]:
    """Extract competitor names from natural-language brief text."""
    competitors = []
    for pat in COMPETITOR_PATTERNS:
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

    # One query per brief question (never invented ones): the brand, plus the competitors when the question compares
    # them, AND the question's topic terms.
    rq_queries = []
    for rq in spec.get("research_questions", []):
        q_text = rq.get("question", "")
        names = [brand_name] + (competitors if _COMPARES.search(q_text) else [])
        brands_or = " OR ".join(f'"{n}"' for n in names if n)
        terms = _topic_terms(q_text, spec, names) or ([f'"{category}"'] if category else [])
        rq_queries.append({
            "question_id": rq.get("question_id", ""),
            "question": q_text,
            "query": f'({brands_or}) AND ({" OR ".join(terms)}){not_clause}' if terms else f'({brands_or}){not_clause}',
            "rationale": "Deterministic: brand + the question's topic terms",
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
                           f"Generated without the LLM (unavailable, timed out or failed). "
                           f"Covers broad/balanced/precise variants"
                           f"{f', {len(competitors)} competitor queries' if competitors else ''}"
                           f" and {len(rq_queries)} research question sub-queries.",
        "_strategy_source": "deterministic",
        "_note": "Generated deterministically because the LLM strategy was unavailable, timed out or failed. "
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
        # Keyed dict (not a list) to match the schema the LLM generation path and the
        # frontend both use — see query_versions usage in SearchStrategy.tsx.
        "query_versions": {
            "broad": {"query": broad_q,
                      "description": "Brand name with exclusions only",
                      "estimated_noise_level": "high",
                      "use_case": "Volume estimation and broad monitoring"},
            "balanced": {"query": balanced_q,
                         "description": "Brand + category/product context",
                         "estimated_noise_level": "medium",
                         "use_case": "Day-to-day monitoring"},
            "precise": {"query": precise_q,
                        "description": "Brand in proximity to category",
                        "estimated_noise_level": "low",
                        "use_case": "High-precision analysis"},
        },
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


# Questions about all of a brand's coverage, not one topic in it
_BRAND_WIDE = re.compile(r"share of voice|\bsov\b|\bvolume\b|\bspikes?\b|\bpeaks?\b|overall sentiment|"
                         r"sentiment (?:breakout|breakdown|overview|distribution|split|mix)|"
                         r"(?:prominent|key|top|main)(?: \w+)? themes", re.IGNORECASE)
_COMPARES = re.compile(r"competitor|share of voice|\bsov\b|each brand|which brand|\bversus\b|\bvs\b", re.IGNORECASE)
# Words a question is phrased with, not what its articles say ("Within coverage of ...", "sentiment distribution toward").
_FILLER = frozenset("""a an the and or nor of in on to for with within without by from at as into is are was were be been
being what which who whom whose how why when where whether does do did much many most more less least than toward towards
about across between among each every any all its it their they his her this that these those there such very also
coverage covered media social news editorial outlets conversation conversations discussion discussions mention mentions
brand brands company companies competitor competitors named positioned position positioning compare compared comparison
versus vs relative concern concerns concerning related relating associated drivers driver distribution sentiment tone
share voice volume period during over e g eg exposed major key top main prominent overall us u s united states
such often frequently reference references referenced discuss discussed discussing discussion talk talked described
framed portrayed perceived perception cause caused drove drive driving moments stories story impact role""".split())
_MONTHS = re.compile(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*$")
# A question's concept word -> the words its articles use for it (a trailing * also matches plurals).
_CONCEPT_TERMS = {
    "autonom": ["self-driving", "autonomous", "autonomy", "FSD", "Full Self-Driving", "Autopilot", "robotaxi*"],
    "self-driving": ["self-driving", "autonomous", "FSD", "Full Self-Driving", "Autopilot", "robotaxi*"],
    "charging": ["charging", "charger*", "Supercharger*", "charging network"],
    "recall": ["recall*", "NHTSA", "investigation*"],
    "safety": ["safety", "NHTSA", "crash*", "investigation*"],
    "pricing": ["price*", "pricing"],
    "leadership": ["CEO", "leadership", "executive*"],
}


def _topic_terms(question: str, spec: dict, brand_names: list[str]) -> list[str]:
    """A question's topic as quoted query terms: the items it lists in parentheses, the articles' words for the
    concepts it names, the scope entities (and brand keywords) it mentions, then its remaining content words with
    filler, brand names and dates dropped."""
    lower = question.lower()
    skip = {n.lower() for n in brand_names if n}
    found: list[str] = []
    for group in re.findall(r"\(([^)]*)\)", question):
        found += [t.strip() for t in re.split(r",|\bor\b|\band\b", re.sub(r"\be\.?g\.?,?", "", group)) if t.strip()]
    for concept, words in _CONCEPT_TERMS.items():
        if concept in lower:
            found += words
    for ent in spec.get("validated_entities") or []:
        if not isinstance(ent, dict):
            continue
        for name in [ent.get("name") or ""] + ((ent.get("keywords") or []) if ent.get("type") == "brand" else []):
            if name and re.search(rf"\b{re.escape(name.lower())}\b", lower):
                found.append(name)
    in_terms = {w for t in found for w in re.findall(r"[\w'-]+", t.lower())}
    for word in re.findall(r"[A-Za-z][\w'-]*", re.sub(r"\([^)]*\)", " ", question)):
        w = word.lower().strip("'")
        if len(w) > 2 and w not in _FILLER and w not in in_terms and not _MONTHS.match(w):
            found.append(f"{w[:-1]}*" if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    terms, seen = [], set()
    for t in found:
        key = re.sub(r"s?\*?$", "", t.lower())   # "recalls" and "recall*" are one term
        if key in seen or key in skip or key in _FILLER:
            continue
        seen.add(key)
        terms.append(f'"{t}"')
    return terms[:15]


def _only_brief_questions(strategy: dict, spec: dict) -> dict:
    """The strategy answers the brief's questions only: an RQ the brief does not have (an LLM's or a template's extra
    RQ7/RQ8) is dropped."""
    ids = {rq.get("question_id") for rq in spec.get("research_questions") or [] if isinstance(rq, dict)}
    if ids and strategy.get("research_question_queries"):
        strategy["research_question_queries"] = [q for q in strategy["research_question_queries"]
                                                 if q.get("question_id") in ids]
    return strategy


def _brand_wide_queries(strategy: dict, spec: dict) -> dict:
    """A share-of-voice / volume / spikes / sentiment-overview / top-themes question gets the brand query (plus the
    competitors when it compares them) with no topic group: uploaded articles reach a question without its own upload
    only by matching its query, so an "electric vehicle" AND-group starved SOV of most of its coverage."""
    brand = (spec.get("commissioning_brand") or {}).get("name") or ""
    competitors = [e["name"] for e in spec.get("validated_entities") or []
                   if isinstance(e, dict) and e.get("type") == "competitor" and e.get("name") and e["name"] != brand]
    if not brand:
        return strategy
    for rq in strategy.get("research_question_queries") or []:
        question = rq.get("question") or ""
        if not _BRAND_WIDE.search(question):
            continue
        names = [brand] + (competitors if _COMPARES.search(question) else [])
        # the question keeps its own query (searching, display); uploaded articles are matched to it on the brand
        # group and exclusions only, so a topic AND-group can't starve an overall-volume question of its articles
        rq["match_query"] = _without_topic_groups(rq.get("query") or "", brand, names)
    return strategy


def _top_level(query: str) -> list[tuple[str, str]]:
    """[(operator, clause)] split on the AND / NOT that sit outside any parentheses; the first operator is ""."""
    parts, depth, start, op, i, quoted = [], 0, 0, "", 0, False
    while i < len(query):
        ch = query[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        elif not quoted and depth == 0 and (m := re.match(r"\s+(AND NOT|AND|NOT)\s+", query[i:])):
            parts.append((op, query[start:i].strip()))
            op, start = m.group(1), i + m.end()
            i += m.end()
            continue
        i += 1
    parts.append((op, query[start:].strip()))
    return [(o, c) for o, c in parts if c]


def _without_topic_groups(query: str, brand: str, names: list[str]) -> str:
    """The query's own structure minus its topic AND-groups: the brand group (with the variants the builder wrote) and
    the NOT exclusions stay; a compared competitor missing from the brand group is added to it."""
    clauses = _top_level(query)
    group = next((c for o, c in clauses if o in ("", "AND") and brand.lower() in c.lower()), "")
    inner = group[1:-1].strip() if group.startswith("(") and group.endswith(")") else group
    terms = [t for t in re.split(r"\s+OR\s+", inner) if t.strip()] if inner else []
    have = {t.strip().strip('"').lower() for t in terms}
    terms += [f'"{n}"' for n in names if n.lower() not in have]
    keep = f"({' OR '.join(terms)})" if len(terms) > 1 else (terms[0] if terms else f'"{brand}"')
    nots = [c for o, c in clauses if "NOT" in o]
    return " ".join([keep] + [f"NOT {c}" for c in nots])


# shortcut: the common countries, regions and their short forms, not every place name; extend when a brief needs more
_GEO_TERMS = frozenset(t.strip() for t in """
us,usa,u.s.,america,united states,uk,u.k.,britain,great britain,united kingdom,england,scotland,wales,ireland,eu,europe,
european,asia,asian,africa,african,apac,emea,latam,latin america,middle east,north america,south america,oceania,canada,
mexico,brazil,argentina,chile,colombia,australia,new zealand,india,pakistan,bangladesh,china,chinese,hong kong,taiwan,
japan,korea,south korea,north korea,singapore,malaysia,indonesia,thailand,vietnam,philippines,germany,france,italy,spain,
portugal,netherlands,belgium,switzerland,austria,sweden,norway,denmark,finland,poland,russia,ukraine,turkey,israel,uae,
dubai,saudi arabia,qatar,egypt,nigeria,kenya,south africa""".split(","))
_NOT_GROUP = re.compile(r"\s*\bNOT\s*\(([^()]*)\)")
_NOT_TERM = re.compile(r"\s*\bNOT\s+(\"[^\"]+\"|'[^']+'|[\w.]+)")


def _is_geo(term: str) -> bool:
    return term.strip().strip("\"'").strip().lower() in _GEO_TERMS


def _strip_geo_not(query: str) -> str:
    """The query without countries or regions among its NOT terms: excluding "China" drops BYD's coverage, and the
    country is the source/country filter's job, not the query's."""
    def group(m: re.Match) -> str:
        kept = [t for t in re.split(r"\s+OR\s+", m.group(1).strip()) if t and not _is_geo(t)]
        return f" NOT ({' OR '.join(kept)})" if kept else ""
    query = _NOT_GROUP.sub(group, query or "")
    return _NOT_TERM.sub(lambda m: "" if _is_geo(m.group(1)) else m.group(0), query).strip()


def _no_geographic_exclusions(strategy: dict) -> dict:
    """Geography is set by the country/source filters: no query excludes a country or region with NOT."""
    for rq in strategy.get("research_question_queries") or []:
        if rq.get("query"):
            rq["query"] = _strip_geo_not(rq["query"])
    for qv in (strategy.get("query_versions") or {}).values():
        if isinstance(qv, dict) and qv.get("query"):
            qv["query"] = _strip_geo_not(qv["query"])
    exclusion = strategy.get("exclusion_strategy")
    if isinstance(exclusion, dict):
        if exclusion.get("global_exclusions"):
            exclusion["global_exclusions"] = _strip_geo_not(exclusion["global_exclusions"])
        exclusion["exclusion_categories"] = [c for c in exclusion.get("exclusion_categories") or []
                                             if not (isinstance(c, dict) and c.get("category") == "geographic")]
    return strategy


def _quoted_phrases(strategy: dict) -> dict:
    """Every query's bare multi-word terms quoted (`NPR crisis` -> "NPR crisis"), so none silently means A AND B."""
    for q in [*(strategy.get("research_question_queries") or []), *(strategy.get("query_versions") or {}).values()]:
        if isinstance(q, dict) and q.get("query"):
            q["query"] = quote_bare_phrases(q["query"])
    exclusion = strategy.get("exclusion_strategy")
    if isinstance(exclusion, dict) and exclusion.get("global_exclusions"):
        exclusion["global_exclusions"] = quote_bare_phrases(exclusion["global_exclusions"])
    return strategy


@router.post("/strategy/generate", response_model=StrategyJobStarted)
def generate_search_strategy(req: GenerateStrategyRequest, user: Annotated[dict, Depends(get_current_user)]):
    check_project_id_access(req.project_id, user)
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    research = store.get_latest_research(req.project_id)
    if not research:
        raise HTTPException(400, "No background research found — run background research first")

    job_id = f"strategy_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "search_strategy")

    def worker():
        from ..usage.service import scope as usage_scope
        with usage_scope(project_id=req.project_id, stage="search_strategy"):
            _work()

    def _work():
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

            llm_client = get_llm_client()

            # Maps meltwater_query_builder's internal lifecycle events to the
            # progress_pct/progress_message the frontend polls via GET /jobs/{id} —
            # _broadcast alone only reaches WebSocket listeners, and this page polls.
            _event_messages = {
                "query_builder_started": (32, "Preparing query generation request"),
                "query_builder_attempt": (35, "LLM generating Boolean queries"),
                "query_builder_reasoning": (45, "LLM generating Boolean queries..."),
                "query_builder_validated": (60, "Validating Boolean query syntax"),
                "query_builder_error": (45, "Retrying after an LLM error"),
                "query_builder_complete": (65, "Query strategy drafted — finalizing"),
            }

            def on_event(event_type: str, payload: dict):
                if event_type == "query_builder_streaming":
                    pct, message = 45, f"LLM generating Boolean queries... ({payload.get('chars', 0):,} characters so far)"
                else:
                    default_pct, default_message = _event_messages.get(event_type, (50, event_type))
                    pct = payload.get("progress_pct", default_pct)
                    message = payload.get("message", default_message)
                store.update_job(job_id, progress_pct=pct, progress_message=message)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "status": "running",
                             "progress_pct": pct, "message": message})

            strategy_result = None

            if not llm_client or not llm_client.is_reachable():
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
                        run_mqb(spec, brand_context, emit=on_event, llm_client=llm_client)
                    )
                    loop.close()
                    return mqb_result.get("queries")

                pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = pool.submit(contextvars.copy_context().run, _run_strategy_llm)
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

            strategy_result = _no_geographic_exclusions(
                _only_brief_questions(_brand_wide_queries(_quoted_phrases(strategy_result), spec), spec))
            logger.info("[strategy:%s] LLM strategy generation succeeded — validating Boolean syntax", job_id)
            store.update_job(job_id, progress_pct=80,
                             progress_message="Validating Boolean syntax")

            validation_issues = []
            if isinstance(strategy_result, dict):
                for qv in strategy_result.get("query_versions", {}).values():
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
def edit_query(strategy_id: IdPath, req: EditQueryRequest,
               _access: Annotated[dict, Depends(require_strategy_access)]):
    issues = validate_boolean_syntax(req.query_text)
    version_id = store.update_strategy_query(strategy_id, req.query_type, req.query_text)
    return {
        "version_id": version_id,
        "validation_issues": issues,
        "validation_status": "structurally_valid" if not issues else "has_issues",
    }


@router.get("/strategy/{strategy_id}/versions", response_model=list[QueryVersion])
def get_query_versions(strategy_id: IdPath,
                       _access: Annotated[dict, Depends(require_strategy_access)]):
    return store.get_query_versions(strategy_id)


@router.post("/strategy/{strategy_id}/approve", response_model=OkResponse)
def approve_search_strategy(strategy_id: IdPath, req: ApproveRequest,
                            _access: Annotated[dict, Depends(require_strategy_access)]):
    store.approve_strategy(strategy_id, req.reviewer)
    _broadcast({"type": "intel_strategy_approved", "strategy_id": strategy_id})
    return {"ok": True}


@router.post("/strategy/{strategy_id}/research-question", response_model=AddRQResult)
def add_research_question(strategy_id: IdPath, req: AddRQRequest,
                          _access: Annotated[dict, Depends(require_strategy_access)]):
    question_id = store.add_research_question(strategy_id, req.question, req.query)
    if question_id is None:
        raise HTTPException(404, "Strategy not found")
    return {"question_id": question_id}


@router.put("/strategy/{strategy_id}/research-question", response_model=OkResponse)
def edit_research_question(strategy_id: IdPath, req: EditRQRequest,
                           _access: Annotated[dict, Depends(require_strategy_access)]):
    ok = store.update_research_question(strategy_id, req.question_id, req.question, req.query)
    if not ok:
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


@router.post("/strategy/{strategy_id}/research-question/{question_id}/status", response_model=OkResponse)
def set_research_question_status(strategy_id: IdPath, question_id: str, req: RQStatusRequest,
                                 _access: Annotated[dict, Depends(require_strategy_access)]):
    if not store.set_research_question_status(strategy_id, question_id, req.status):
        raise HTTPException(404, "Research question not found")
    return {"ok": True}


@router.delete("/strategy/{strategy_id}/research-question/{question_id}", response_model=OkResponse)
def delete_research_question(strategy_id: IdPath, question_id: str,
                             _access: Annotated[dict, Depends(require_strategy_access)]):
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

    # Sample evaluation is no longer a gate (Sample Eval tab removed per manager feedback); an existing
    # evaluation is still reported in the result for traceability.
    evaluation = store.get_latest_evaluation(project_id)

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
    "headline": ["title", "headline", "article title", "heading", "article"],
    "snippet": ["hit sentence", "opening text", "snippet", "extract", "summary", "content snippet",
                "full content", "content", "article text", "body", "text"],
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


def _llm_assisted_column_mapping(headers: list[str], sample_rows: list[dict]) -> dict:
    """Fall back to an LLM when MELTWATER_COLUMN_MAP's static alias list can't identify
    a file's headline/snippet/media_type columns — lets users upload exports with
    arbitrary, non-Meltwater column names and still get correctly parsed. Runs only
    when the deterministic pass left key fields unmapped (see _init_mapped below); it
    never replaces that pass, only fills its gaps.

    Returns {"mapped": {...}, "unmapped": [...], "media_type_rule": {...} | None} —
    the same shape as _auto_map_columns, plus a media_type_rule for deriving
    article-vs-post per row from its URL domain when no media-type-like column
    exists in the file at all.
    """
    llm_client = get_llm_client()
    if not llm_client or not llm_client.is_reachable():
        return {"mapped": {}, "unmapped": list(headers), "media_type_rule": None}

    sample_preview = [
        {k: (str(v)[:200] if v is not None else "") for k, v in row.items()}
        for row in sample_rows[:5]
    ]
    prompt = (
        "Map this media-monitoring export's column headers to a canonical schema.\n"
        f"Columns: {json.dumps(headers)}\n"
        f"Sample rows: {json.dumps(sample_preview)}\n\n"
        "Return ONLY this JSON shape:\n"
        '{"mapping": {"headline": "<exact header or null>", "snippet": "<...>", '
        '"url": "<...>", "date": "<...>", "source_name": "<...>", "media_type": "<...>", '
        '"geography": "<...>", "language": "<...>", "author": "<...>", "reach": "<...>", '
        '"sentiment": "<...>"}, '
        '"media_type_rule": {"domain_map": {"<domain>": "Article"|"Post"}, '
        '"default": "Article"|"Post"} or null}\n'
        "Rules: every value in \"mapping\" must be one of the exact strings from "
        "Columns above, or null if nothing fits. Set \"media_type_rule\" only when no "
        "column in \"mapping\" was set to \"media_type\" — infer it from the sample "
        "rows' URL domains: news/press/outlet-style domains are \"Article\", "
        "social/forum/review-platform domains (reddit, x/twitter, instagram, facebook, "
        "forums, review sites) are \"Post\"."
    )
    try:
        raw = llm_client.chat(
            [
                {"role": "system", "content": "You map data export columns to a canonical schema. Output only JSON."},
                {"role": "user", "content": prompt},
            ],
            format_json=True,
        )
        data = _extract_json_object(raw)
    except Exception as e:
        logger.warning("LLM-assisted column mapping failed: %s", e)
        return {"mapped": {}, "unmapped": list(headers), "media_type_rule": None}

    header_set = set(headers)
    mapped = {
        field: col for field, col in (data.get("mapping") or {}).items()
        if col and col in header_set
    }
    return {
        "mapped": mapped,
        "unmapped": [c for c in headers if c not in mapped.values()],
        "media_type_rule": data.get("media_type_rule"),
    }


KNOWN_HEADERS = ({alias for aliases in MELTWATER_COLUMN_MAP.values() for alias in aliases}
                 | {"document id", "input name"})
_MIN_KNOWN_HEADERS = 2


def _is_header_row(row) -> bool:
    """A sheet's header row: at least two cells are recognised column names (URL + Title is enough for a
    hand-made sheet). A title line above the table never has two."""
    cells = [str(c or "").strip().lower() for c in row]
    return sum(1 for c in cells if c in KNOWN_HEADERS) >= _MIN_KNOWN_HEADERS


def _read_csv_text(file_path: str) -> str:
    """CSV text in whatever encoding the export used: Meltwater writes UTF-16 LE (tab-separated), Excel on
    Windows writes cp1252 (curly quotes as 0x92). See core.tabular.decode_text."""
    return decode_text(Path(file_path).read_bytes())


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
    date_values: list[str] = []
    reach_total = 0.0
    reach_max = 0.0
    reach_count = 0

    mapped: dict = {}
    sentiment_col = media_col = geo_col = source_col = date_col = reach_col = lang_col = url_col = None
    media_type_rule: dict | None = None

    def _row_media_type(row_dict: dict) -> str:
        """media_col is the normal path; media_type_rule (LLM-derived, from URL domain)
        only applies when the file has no media-type-equivalent column at all."""
        if media_col:
            return str(row_dict.get(media_col, "")).strip()
        if media_type_rule and url_col:
            raw_url = str(row_dict.get(url_col, "")).strip()
            if raw_url:
                try:
                    domain = (urlparse(raw_url).hostname or "").lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                except ValueError:
                    domain = ""
                if domain:
                    return media_type_rule.get("domain_map", {}).get(domain, media_type_rule.get("default", ""))
        return ""

    def _update_stats(row_dict: dict, sheet_name: str | None = None):
        nonlocal total_count, sent_pos, sent_neg, sent_neu, sent_other
        nonlocal reach_total, reach_max, reach_count
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
        t = _row_media_type(row_dict)
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
                date_values.append(d)
        if reach_col:
            try:
                rv = float(str(row_dict.get(reach_col, "0")).replace(",", ""))
                reach_total += rv
                reach_count += 1
                if rv > reach_max: reach_max = rv
            except (ValueError, TypeError):
                pass

    def _init_mapped(hdrs: list[str], sample_rows: list[dict] | None = None):
        nonlocal mapped, sentiment_col, media_col, geo_col, source_col, date_col, reach_col, lang_col
        nonlocal url_col, media_type_rule
        mapped = _auto_map_columns(hdrs).get("mapped", {})
        # The static alias list above only recognizes Meltwater's own header spellings.
        # When it leaves headline/snippet or media_type unmapped, ask the LLM once to
        # resolve the remaining headers (and, if no media-type column exists at all, to
        # infer an article-vs-post rule from the sample rows' URL domains) so uploads
        # with arbitrary, non-Meltwater column names still parse correctly.
        missing_core = not (mapped.get("headline") and mapped.get("snippet"))
        if missing_core or not mapped.get("media_type"):
            llm_result = _llm_assisted_column_mapping(hdrs, sample_rows or [])
            for field, col in llm_result["mapped"].items():
                mapped.setdefault(field, col)
            media_type_rule = llm_result.get("media_type_rule")
        sentiment_col = mapped.get("sentiment")
        media_col = mapped.get("media_type")
        geo_col = mapped.get("geography")
        source_col = mapped.get("source_name")
        date_col = mapped.get("date")
        reach_col = mapped.get("reach")
        lang_col = mapped.get("language")
        url_col = mapped.get("url")

    if ext in (".xlsx", ".xls"):
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            sheet_headers: list[str] = []
            col_count = 0
            found_header = False
            for row in ws.iter_rows(values_only=True):
                if not found_header:
                    if _is_header_row(row):
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
        with io.StringIO(_read_csv_text(file_path), newline="") as f:
            reader = csv.DictReader(f, delimiter=sniff_delimiter(f.getvalue()))
            headers = list(reader.fieldnames or [])
            buffered_rows = list(itertools.islice(reader, 5))
            _init_mapped(headers, buffered_rows)
            for row in buffered_rows:
                _update_stats(row)
            for row in reader:
                _update_stats(row)

    column_mapping = {"mapped": mapped, "unmapped": [c for c in headers if c not in mapped.values()]}
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
    if date_values:
        stats["date_range"] = _date_range(date_values)
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
    user: Annotated[dict, Depends(get_current_user)],
    file: UploadFile = File(...),
    research_question_id: str | None = None,
):
    check_project_id_access(project_id, user)
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


@router.post("/dataset/{dataset_id}/approve", response_model=OkResponse, dependencies=[Depends(require_dataset_access)])
def approve_dataset(dataset_id: IdPath):
    store.approve_dataset(dataset_id)
    _broadcast({"type": "intel_dataset_approved", "dataset_id": dataset_id})
    return {"ok": True}


@router.delete("/dataset/{dataset_id}", response_model=OkResponse, dependencies=[Depends(require_dataset_access)])
def delete_dataset(dataset_id: IdPath):
    store.delete_dataset(dataset_id)
    return {"ok": True}


@router.post("/evaluation/upload", response_model=EvaluationUploadResponse)
async def upload_sample_dataset(
    project_id: int,
    strategy_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    file: UploadFile = File(...),
):
    check_project_id_access(project_id, user)
    if store.get_strategy_project_id(strategy_id) != project_id:
        raise HTTPException(404, "Strategy not found for this project")
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

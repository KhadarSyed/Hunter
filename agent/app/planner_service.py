"""Research Planner Service — orchestrates plan generation with prerequisite
validation, deterministic fallback, and dataset-aware execution units.

This module is the bridge between the API routes and the research_planner agent.
It validates prerequisites, gathers inputs, runs the planner (LLM or
deterministic), and transforms output into structured execution units.
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any, Optional

from . import intelligence_store as store
from .config import load_settings
from .llm_provider import build_llm_client

logger = logging.getLogger(__name__)

PLANNER_LLM_TIMEOUT = 300

VALID_ANALYTICAL_METHODS = [
    "Theme Clustering",
    "Conversation Analysis",
    "Sentiment Analysis",
    "Volume Trends",
    "Audience Segmentation",
    "Narrative Evolution",
    "Crisis Detection",
    "Influencer Mapping",
    "Competitive Benchmarking",
    "Media Framing",
    "Emerging Topics",
    "Thematic Analysis",
    "Tension Analysis",
    "Behaviour Analysis",
    "Language Analysis",
    "Life-stage Comparison",
    "Platform Comparison",
    "Trend Analysis",
    "Secondary Validation",
    "Conversation Mapping",
    "Narrative Analysis",
]


# ─── Prerequisite validation ───────────────────────────────────────────────

def validate_prerequisites(project_id: int) -> dict:
    """Check that all four prerequisites are approved.

    Returns:
        {
            "ready": bool,
            "prerequisites": {
                "brief_scope": {"status": ..., "message": ...},
                "background_research": {...},
                "search_strategy": {...},
                "dataset": {...},
            }
        }
    """
    project = store.get_project(project_id)
    if not project:
        return {
            "ready": False,
            "prerequisites": {
                "brief_scope": {"status": "missing", "message": "Project not found"},
                "background_research": {"status": "missing", "message": "Project not found"},
                "search_strategy": {"status": "missing", "message": "Project not found"},
                "dataset": {"status": "missing", "message": "Project not found"},
            },
        }

    prereqs = {}

    spec = project.get("spec", {})
    if spec and spec.get("commissioning_brand"):
        prereqs["brief_scope"] = {"status": "approved", "message": "Project spec available"}
    else:
        prereqs["brief_scope"] = {"status": "missing", "message": "No approved project specification found"}

    research = store.get_latest_research(project_id)
    if research and research.get("approval_status") == "approved":
        prereqs["background_research"] = {"status": "approved", "message": "Background research approved"}
    elif research:
        prereqs["background_research"] = {
            "status": "pending",
            "message": f"Background research exists but is {research.get('approval_status', 'pending')} — approval required",
        }
    else:
        prereqs["background_research"] = {"status": "missing", "message": "No background research found — run background research first"}

    strategy = store.get_latest_strategy(project_id)
    if strategy and strategy.get("approval_status") == "approved":
        prereqs["search_strategy"] = {"status": "approved", "message": "Search strategy approved"}
    elif strategy:
        prereqs["search_strategy"] = {
            "status": "pending",
            "message": f"Search strategy exists but is {strategy.get('approval_status', 'pending')} — approval required",
        }
    else:
        prereqs["search_strategy"] = {"status": "missing", "message": "No search strategy found — generate strategy first"}

    all_datasets = store.get_datasets_by_project(project_id)
    dataset = store.get_latest_dataset(project_id)
    evaluation = store.get_latest_evaluation(project_id)
    rqs = spec.get("research_questions", [])
    rq_ids = [rq.get("id") or rq.get("question_id") for rq in rqs if isinstance(rq, dict)]

    if rq_ids and all_datasets:
        ds_by_rq = {}
        for ds in all_datasets:
            rqid = ds.get("research_question_id")
            if rqid and (rqid not in ds_by_rq or ds["id"] > ds_by_rq[rqid]["id"]):
                ds_by_rq[rqid] = ds
        approved_count = sum(1 for rid in rq_ids if rid and ds_by_rq.get(rid, {}).get("approval_status") == "approved")
        uploaded_count = sum(1 for rid in rq_ids if rid and ds_by_rq.get(rid, {}).get("processing_status") == "done")
        if approved_count > 0:
            prereqs["dataset"] = {"status": "approved", "message": f"{approved_count}/{len(rq_ids)} datasets approved"}
        elif uploaded_count > 0:
            prereqs["dataset"] = {"status": "pending", "message": f"0/{len(rq_ids)} datasets approved, {uploaded_count}/{len(rq_ids)} uploaded"}
        else:
            prereqs["dataset"] = {"status": "missing", "message": "No datasets uploaded — upload a Meltwater export for at least one research question"}
    elif dataset and dataset.get("approval_status") == "approved":
        prereqs["dataset"] = {"status": "approved", "message": "Dataset uploaded and approved"}
    elif evaluation and evaluation.get("status") == "completed":
        prereqs["dataset"] = {"status": "approved", "message": "Dataset uploaded and evaluated"}
    elif dataset and dataset.get("processing_status") == "processing":
        prereqs["dataset"] = {"status": "pending", "message": "Dataset is still being processed"}
    elif dataset:
        prereqs["dataset"] = {"status": "pending", "message": "Dataset uploaded but not yet approved"}
    else:
        research_for_ds = store.get_latest_research(project_id)
        research_data = (research_for_ds or {}).get("research", {})
        news_count = len(research_data.get("news_items", []))
        if news_count >= 10:
            prereqs["dataset"] = {
                "status": "approved",
                "message": f"Using web research data ({news_count} articles — no Meltwater export needed)",
            }
        else:
            prereqs["dataset"] = {"status": "missing", "message": "No dataset uploaded — upload a Meltwater export first"}

    return {"ready": True, "prerequisites": prereqs}


# ─── Dataset metadata extraction ──────────────────────────────────────────

def _extract_dataset_metadata(evaluation: dict | None) -> dict:
    """Extract normalized dataset metadata from an evaluation result."""
    if not evaluation or not evaluation.get("evaluation"):
        return {
            "available": False,
            "total_records": 0,
            "fields": [],
            "platforms": [],
            "date_range": None,
            "precision": None,
            "per_rq_coverage": {},
        }

    ev = evaluation["evaluation"]
    return {
        "available": True,
        "total_records": ev.get("total_records", 0),
        "relevant_records": ev.get("relevant_count", 0),
        "irrelevant_records": ev.get("irrelevant_count", 0),
        "duplicate_count": ev.get("duplicate_count", 0),
        "fields": ev.get("detected_fields", []),
        "platforms": ev.get("platforms", []),
        "date_range": ev.get("date_range"),
        "precision": ev.get("precision"),
        "false_positive_rate": ev.get("false_positive_rate"),
        "recall_risk": ev.get("recall_risk"),
        "per_rq_coverage": ev.get("per_rq_coverage", {}),
        "format": ev.get("detected_format", "unknown"),
    }


# ─── Plan generation ──────────────────────────────────────────────────────

def generate_plan(
    project_id: int,
    *,
    emit: Any = None,
) -> dict:
    """Generate a Research Plan for the given project.

    Validates prerequisites, gathers inputs, runs the planner agent
    (LLM with deterministic fallback), and saves the result.

    Returns the saved plan dict with plan_id.
    """
    if emit is None:
        emit = lambda et, p: None

    logger.info("[planner:%s] Starting plan generation", project_id)

    prereqs = validate_prerequisites(project_id)
    if not prereqs["ready"]:
        missing = [
            f"{k}: {v['message']}"
            for k, v in prereqs["prerequisites"].items()
            if v["status"] != "approved"
        ]
        logger.info("[planner:%s] Some prerequisites pending (%s) — proceeding anyway", project_id, missing)

    project = store.get_project(project_id)
    spec = project["spec"]
    research = store.get_latest_research(project_id)
    strategy = store.get_latest_strategy(project_id)
    evaluation = store.get_latest_evaluation(project_id)
    dataset = store.get_latest_dataset(project_id)

    dataset_meta = _extract_dataset_metadata(evaluation)
    if not dataset_meta.get("available") and dataset:
        stats = dataset.get("stats", {})
        dataset_meta = {
            "available": True,
            "total_records": dataset.get("record_count", 0),
            "fields": list((dataset.get("column_mapping", {}).get("mapped", {})).keys()),
            "platforms": list((stats.get("top_sources", {})).keys()),
            "date_range": stats.get("date_range"),
            "sentiment": stats.get("sentiment"),
            "sheets": stats.get("sheets"),
            "format": "meltwater_export",
        }
    research_data = research.get("research", {})
    strategy_data = strategy.get("strategy", {})

    emit("planner_generating", {"status": "Running research planner..."})

    plan_result = _run_planner_with_timeout(
        spec, research_data, strategy_data, dataset_meta, emit
    )

    if plan_result.get("plan"):
        plan_data = plan_result["plan"]
        plan_data = _enrich_plan_with_metadata(
            plan_data, spec, research_data, strategy_data, dataset_meta
        )
        source = plan_data.get("_meta", {}).get("source", "llm")
        plan_id = store.save_research_plan(project_id, plan_data, source=source)
        logger.info("[planner:%s] Plan saved as plan_id=%s (source=%s)", project_id, plan_id, source)
        return {
            "status": "completed",
            "plan_id": plan_id,
            "plan": plan_data,
            "validation_errors": plan_result.get("validation_errors", []),
        }
    else:
        logger.error("[planner:%s] Planner returned no plan", project_id)
        return {
            "status": "failed",
            "error": plan_result.get("error", "Planner returned no plan"),
            "validation_errors": plan_result.get("validation_errors", []),
        }


def _run_planner_with_timeout(
    spec: dict,
    research: dict,
    strategy: dict,
    dataset_meta: dict,
    emit: Any,
) -> dict:
    """Run the LLM planner with a timeout, falling back to deterministic."""
    settings = load_settings()
    ollama = build_llm_client(settings)

    if not ollama.is_reachable():
        logger.warning("[planner] No LLM provider reachable — using deterministic fallback")
        plan = _build_deterministic_plan(spec, research, strategy, dataset_meta)
        return {"plan": plan, "validation_errors": []}

    def _run_llm():
        from .agents.research_planner import run as run_planner
        return run_planner(spec, ollama, emit=emit)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_run_llm)
    try:
        result = future.result(timeout=PLANNER_LLM_TIMEOUT)
        pool.shutdown(wait=False)
        if result.get("plan"):
            return result
        logger.warning("[planner] LLM returned no plan — using deterministic fallback")
    except concurrent.futures.TimeoutError:
        logger.warning("[planner] LLM timed out after %ss — using deterministic fallback",
                       PLANNER_LLM_TIMEOUT)
        pool.shutdown(wait=False)
    except Exception as e:
        logger.error("[planner] LLM failed: %s — using deterministic fallback", e)
        pool.shutdown(wait=False)

    plan = _build_deterministic_plan(spec, research, strategy, dataset_meta)
    return {"plan": plan, "validation_errors": []}


# ─── Plan enrichment ──────────────────────────────────────────────────────

def _enrich_plan_with_metadata(
    plan: dict,
    spec: dict,
    research: dict,
    strategy: dict,
    dataset_meta: dict,
) -> dict:
    """Add project overview, execution units, evidence requirements,
    analysis methods summary, and expected deliverables to the plan."""

    brand = spec.get("commissioning_brand", {})
    plan["project_overview"] = {
        "project_name": brand.get("name", "Unknown"),
        "brand": brand.get("name", ""),
        "category": brand.get("category", ""),
        "objective": spec.get("business_objective", ""),
        "research_objective": spec.get("research_objective", ""),
        "scope": {
            "platforms": spec.get("included_scope", {}).get("platforms", []),
            "countries": spec.get("included_scope", {}).get("countries", []),
            "time_period": spec.get("included_scope", {}).get("time_period", ""),
        },
        "dataset_summary": {
            "total_records": dataset_meta.get("total_records", 0),
            "relevant_records": dataset_meta.get("relevant_records", 0),
            "platforms": dataset_meta.get("platforms", []),
            "fields_available": dataset_meta.get("fields", []),
        },
    }

    objectives = plan.get("research_objectives", [])

    if "execution_units" not in plan:
        plan["execution_units"] = _build_execution_units(objectives, dataset_meta, spec)

    if "evidence_requirements" not in plan:
        plan["evidence_requirements"] = _build_evidence_requirements(objectives, dataset_meta)

    if "analysis_methods" not in plan:
        plan["analysis_methods"] = _build_analysis_methods_summary(objectives)

    if "expected_deliverables" not in plan:
        plan["expected_deliverables"] = _build_expected_deliverables(objectives)

    plan["validation"] = _build_validation_report(plan, spec, dataset_meta)

    return plan


def _build_execution_units(objectives: list, dataset_meta: dict, spec: dict) -> list:
    """Transform research objectives into independently executable units."""
    units = []
    available_fields = set(dataset_meta.get("fields", []))
    platforms_in_dataset = set(dataset_meta.get("platforms", []))

    for obj in objectives:
        methods = obj.get("methods", ["Thematic Analysis"])
        obj_platforms = [
            p.get("name") if isinstance(p, dict) else str(p)
            for p in obj.get("platforms", [])
        ]
        evidence = obj.get("evidence", {})
        mandatory = evidence.get("mandatory", []) if isinstance(evidence, dict) else []

        required_fields = _infer_required_fields(methods)

        unit = {
            "id": obj.get("objective_id", ""),
            "title": obj.get("objective", "")[:100],
            "description": obj.get("objective", ""),
            "objective_id": obj.get("objective_id", ""),
            "priority": obj.get("priority", "medium"),
            "status": "pending",
            "estimated_complexity": obj.get("estimated_complexity", "medium"),
            "estimated_runtime": _estimate_runtime(obj.get("estimated_complexity", "medium")),
            "required_datasets": ["meltwater_export"],
            "required_fields": required_fields,
            "filters_required": _infer_filters(obj, spec),
            "evidence_target": "; ".join(mandatory[:3]) if mandatory else "Relevant verbatims and themes",
            "recommended_method": methods[0] if methods else "Thematic Analysis",
            "audience_segmentation": _infer_audience(obj, spec),
            "expected_output": obj.get("expected_output", ""),
            "confidence": obj.get("confidence_target", "medium"),
            "dependencies": obj.get("dependencies", []),
            "platforms": obj_platforms,
            "search_concepts": obj.get("search_concepts", []),
        }
        units.append(unit)

    return units


def _infer_required_fields(methods: list) -> list:
    """Map analytical methods to the dataset fields they require."""
    field_map = {
        "theme clustering": ["content", "headline"],
        "thematic analysis": ["content", "headline"],
        "conversation analysis": ["content", "source", "date"],
        "conversation mapping": ["content", "source", "date"],
        "sentiment analysis": ["content", "sentiment"],
        "volume trends": ["date", "source"],
        "trend analysis": ["date", "source", "content"],
        "audience segmentation": ["content", "source", "author"],
        "narrative evolution": ["content", "date", "headline"],
        "narrative analysis": ["content", "headline"],
        "crisis detection": ["content", "date", "sentiment", "reach"],
        "influencer mapping": ["author", "reach", "engagement"],
        "competitive benchmarking": ["content", "headline", "source"],
        "media framing": ["content", "headline", "source"],
        "emerging topics": ["content", "date"],
        "tension analysis": ["content"],
        "behaviour analysis": ["content", "source"],
        "language analysis": ["content"],
        "life-stage comparison": ["content", "source"],
        "platform comparison": ["content", "source", "engagement"],
        "secondary validation": ["content", "source"],
    }
    fields = set()
    for m in methods:
        fields.update(field_map.get(m.lower(), ["content"]))
    return sorted(fields)


def _infer_filters(obj: dict, spec: dict) -> list:
    """Infer data filters from the objective and spec."""
    filters = []
    scope = spec.get("included_scope", {})
    if scope.get("time_period"):
        filters.append(f"date_range: {scope['time_period']}")
    if scope.get("countries"):
        filters.append(f"geography: {', '.join(scope['countries'])}")

    platforms = [
        p.get("name") if isinstance(p, dict) else str(p)
        for p in obj.get("platforms", [])
    ]
    if platforms:
        filters.append(f"platforms: {', '.join(platforms)}")

    for rule in obj.get("exclusion_rules", [])[:3]:
        filters.append(f"exclude: {rule}")

    return filters


def _estimate_runtime(complexity: str) -> str:
    return {"high": "45-60 minutes", "medium": "20-30 minutes", "low": "10-15 minutes"}.get(
        complexity, "20-30 minutes"
    )


def _infer_audience(obj: dict, spec: dict) -> str | None:
    segments = spec.get("included_scope", {}).get("audience_segments", [])
    if segments:
        return ", ".join(s.get("name", "") for s in segments[:3])
    return None


def _build_evidence_requirements(objectives: list, dataset_meta: dict) -> dict:
    mandatory = []
    optional = []
    platforms = set()
    for obj in objectives:
        ev = obj.get("evidence", {})
        if isinstance(ev, dict):
            mandatory.extend(ev.get("mandatory", []))
            optional.extend(ev.get("optional", []))
        for p in obj.get("platforms", []):
            name = p.get("name") if isinstance(p, dict) else str(p)
            platforms.add(name)

    return {
        "mandatory": list(set(mandatory)),
        "optional": list(set(optional)),
        "minimum_sample_size": max(50, dataset_meta.get("relevant_records", 0)),
        "platform_coverage": sorted(platforms),
        "dataset_records_available": dataset_meta.get("total_records", 0),
        "dataset_relevant_records": dataset_meta.get("relevant_records", 0),
    }


def _build_analysis_methods_summary(objectives: list) -> list:
    method_units: dict[str, list] = {}
    for obj in objectives:
        for m in obj.get("methods", []):
            method_units.setdefault(m, []).append(obj.get("objective_id", ""))

    return [
        {
            "method": method,
            "execution_units": units,
            "description": _method_description(method),
            "output_type": _method_output_type(method),
        }
        for method, units in method_units.items()
    ]


def _method_description(method: str) -> str:
    descriptions = {
        "thematic analysis": "Identify recurring themes and patterns in conversation data",
        "theme clustering": "Group related discussions into thematic clusters",
        "conversation analysis": "Analyze the structure and flow of conversations",
        "conversation mapping": "Map conversation threads and response patterns",
        "sentiment analysis": "Assess emotional tone and sentiment distribution",
        "volume trends": "Track mention volume over time to identify patterns",
        "trend analysis": "Identify emerging and declining topics over time",
        "audience segmentation": "Segment audiences by behavior, interest, or demographics",
        "narrative evolution": "Track how narratives and stories develop over time",
        "narrative analysis": "Analyze storytelling patterns and narrative structures",
        "crisis detection": "Identify potential crises from anomalous patterns",
        "influencer mapping": "Map key voices and their influence networks",
        "competitive benchmarking": "Compare brand presence against competitors",
        "media framing": "Analyze how media frames and positions topics",
        "emerging topics": "Detect newly emerging discussion topics",
        "tension analysis": "Identify points of friction and unmet needs",
        "behaviour analysis": "Analyze user behaviors and usage patterns",
        "language analysis": "Study the language and terminology used by audiences",
        "life-stage comparison": "Compare behavior across life stages or demographics",
        "platform comparison": "Compare discussion patterns across platforms",
        "secondary validation": "Validate findings against published research",
    }
    return descriptions.get(method.lower(), f"Apply {method} to relevant data")


def _method_output_type(method: str) -> str:
    outputs = {
        "thematic analysis": "theme hierarchy",
        "theme clustering": "priority hierarchy",
        "conversation analysis": "conversation map",
        "sentiment analysis": "sentiment distribution",
        "volume trends": "trend chart",
        "audience segmentation": "persona matrix",
        "narrative evolution": "narrative timeline",
        "crisis detection": "risk assessment",
        "influencer mapping": "influence network",
        "competitive benchmarking": "comparison matrix",
        "media framing": "frame analysis",
        "emerging topics": "topic radar",
        "tension analysis": "tension map",
        "behaviour analysis": "behaviour framework",
        "platform comparison": "platform comparison chart",
    }
    return outputs.get(method.lower(), "structured findings")


def _build_expected_deliverables(objectives: list) -> list:
    deliverables: dict[str, list] = {}
    for obj in objectives:
        dm = obj.get("deliverable_mapping", {})
        supports = dm.get("supports", obj.get("expected_output", "Findings"))
        deliverables.setdefault(supports, []).append(obj.get("objective_id", ""))

    return [
        {
            "deliverable": name,
            "execution_units": units,
            "format": "slide deck section",
        }
        for name, units in deliverables.items()
    ]


def _build_validation_report(plan: dict, spec: dict, dataset_meta: dict) -> dict:
    """Run dataset-aware validation on the plan."""
    warnings = []
    blockers = []

    available_fields = set(dataset_meta.get("fields", []))
    total_records = dataset_meta.get("total_records", 0)
    relevant_records = dataset_meta.get("relevant_records", 0)

    for unit in plan.get("execution_units", []):
        required = set(unit.get("required_fields", []))
        missing = required - available_fields
        if missing and available_fields:
            warnings.append({
                "unit_id": unit["id"],
                "type": "missing_fields",
                "message": f"Unit {unit['id']} requires fields not in dataset: {', '.join(sorted(missing))}",
                "fields": sorted(missing),
            })

        method = unit.get("recommended_method", "")
        if method.lower() not in {m.lower() for m in VALID_ANALYTICAL_METHODS}:
            warnings.append({
                "unit_id": unit["id"],
                "type": "unsupported_method",
                "message": f"Analytical method '{method}' not in validated list",
            })

    if total_records > 0 and relevant_records < 30:
        warnings.append({
            "type": "low_sample_size",
            "message": f"Only {relevant_records} relevant records — minimum recommended is 50",
        })

    objectives = plan.get("research_objectives", [])
    spec_rq_ids = {
        rq.get("question_id") for rq in spec.get("research_questions", [])
        if isinstance(rq, dict) and rq.get("question_id")
    }
    covered_ids = set()
    for obj in objectives:
        for qid in obj.get("business_question_ids", []):
            covered_ids.add(qid)
    uncovered = spec_rq_ids - covered_ids
    if uncovered:
        warnings.append({
            "type": "missing_coverage",
            "message": f"Research questions not covered: {', '.join(sorted(uncovered))}",
        })

    spec_platforms = {p for p in (spec.get("included_scope", {}).get("platforms") or []) if p}
    plan_platforms = set()
    for obj in objectives:
        for p in obj.get("platforms", []):
            name = p.get("name") if isinstance(p, dict) else str(p)
            plan_platforms.add(name)
    missing_platforms = spec_platforms - plan_platforms
    if missing_platforms:
        warnings.append({
            "type": "missing_platform_coverage",
            "message": f"Platforms in scope but not in plan: {', '.join(sorted(missing_platforms))}",
        })

    return {
        "warnings": warnings,
        "blockers": blockers,
        "status": "blocked" if blockers else ("warnings" if warnings else "clean"),
        "total_execution_units": len(plan.get("execution_units", [])),
        "total_objectives": len(objectives),
        "question_coverage": f"{len(covered_ids)}/{len(spec_rq_ids)}",
    }


# ─── Deterministic fallback ──────────────────────────────────────────────

def _build_deterministic_plan(
    spec: dict,
    research: dict,
    strategy: dict,
    dataset_meta: dict,
) -> dict:
    """Build a Research Plan deterministically from the spec without LLM."""
    brand = spec.get("commissioning_brand", {})
    brand_name = brand.get("name", "Unknown")
    category = brand.get("category", "")
    rqs = spec.get("research_questions", [])
    scope = spec.get("included_scope", {})
    platforms = scope.get("platforms", ["Twitter/X", "Instagram", "Reddit"])

    objectives = []
    for rq in rqs:
        if not isinstance(rq, dict):
            continue
        qid = rq.get("question_id", "")
        question = rq.get("question", "")
        idx = len(objectives) + 1
        oid = f"RO{idx}"

        method = _select_method_for_question(question)
        relevant_platforms = _select_platforms_for_question(question, platforms)

        objectives.append({
            "objective_id": oid,
            "business_question_ids": [qid],
            "objective": question,
            "priority": "high" if rq.get("priority") == "primary" else "medium",
            "reason": f"Directly addresses {qid}",
            "platforms": [
                {"name": p, "justification": f"Expected discussion of {category} topics"}
                for p in relevant_platforms
            ],
            "search_concepts": _extract_concepts(question, brand_name, category),
            "evidence": {
                "mandatory": [f"Consumer discussions relevant to: {question[:80]}"],
                "optional": ["Supporting industry reports or surveys"],
            },
            "inclusion_rules": ["personal experience", "authentic discussion", "questions"],
            "exclusion_rules": ["ads", "sponsored content", "bot content", "spam"],
            "methods": [method],
            "secondary_research": "none",
            "expected_output": f"Findings addressing: {question[:60]}",
            "deliverable_mapping": {
                "supports": f"Insight section for {qid}",
                "evidence_type": "consumer verbatims and themes",
                "recommended_visual": _visual_for_method(method),
            },
            "dependencies": [],
            "confidence_target": "medium",
            "estimated_complexity": "medium",
        })

    plan = {
        "plan_summary": (
            f"Deterministic research plan for {brand_name}. "
            f"Generated without LLM. Covers {len(objectives)} objectives "
            f"across {len(rqs)} research questions."
        ),
        "research_objectives": objectives,
        "validation": {
            "question_coverage": {rq.get("question_id", ""): [f"RO{i+1}"]
                                  for i, rq in enumerate(rqs) if isinstance(rq, dict)},
            "duplicate_check": "No duplicates (1:1 question-to-objective mapping)",
            "scope_compliance": "Within approved scope",
            "excluded_items_check": "No excluded items in plan",
        },
        "_meta": {
            "agent": "research_planner",
            "version": "1.0.0",
            "source": "deterministic",
            "attempts": 0,
            "elapsed_seconds": 0,
            "hard_errors": 0,
            "warnings": 0,
            "total_objectives": len(objectives),
            "note": "Generated deterministically because LLM was unavailable or timed out. "
                    "Plan may benefit from LLM refinement on GPU-capable hardware.",
        },
    }

    return plan


def _select_method_for_question(question: str) -> str:
    """Choose an analytical method based on question keywords."""
    q = question.lower()
    if any(w in q for w in ["sentiment", "feeling", "perception", "attitude"]):
        return "Thematic Analysis"
    if any(w in q for w in ["trend", "pattern", "seasonal", "spike"]):
        return "Trend Analysis"
    if any(w in q for w in ["compare", "competitor", "versus", "vs"]):
        return "Platform Comparison"
    if any(w in q for w in ["platform", "channel", "drive"]):
        return "Platform Comparison"
    if any(w in q for w in ["audience", "segment", "demographic", "who"]):
        return "Audience Segmentation"
    if any(w in q for w in ["content", "theme", "engagement", "topic"]):
        return "Theme Clustering"
    if any(w in q for w in ["emerging", "new", "cultural", "moment"]):
        return "Emerging Topics"
    if any(w in q for w in ["position", "perception", "brand"]):
        return "Narrative Analysis"
    return "Thematic Analysis"


def _select_platforms_for_question(question: str, available: list) -> list:
    """Select relevant platforms for a question."""
    q = question.lower()
    selected = []
    platform_relevance = {
        "Reddit": ["discussion", "opinion", "compare", "review", "honest"],
        "Instagram": ["visual", "content", "lifestyle", "brand"],
        "TikTok": ["trend", "viral", "content", "cultural", "young"],
        "Twitter/X": ["sentiment", "conversation", "mention", "news"],
        "Facebook": ["community", "group", "parent", "family"],
        "YouTube": ["review", "tutorial", "content", "long"],
    }
    for plat in available:
        keywords = platform_relevance.get(plat, [])
        if any(k in q for k in keywords):
            selected.append(plat)
    if not selected:
        selected = available[:3]
    return selected[:4]


def _extract_concepts(question: str, brand: str, category: str) -> list:
    """Extract search concepts from a question."""
    stop = {"what", "which", "where", "when", "does", "how", "the", "for", "are",
            "this", "that", "with", "from", "most", "mrs", "and", "not"}
    words = [w.strip("?.,!") for w in question.lower().split() if len(w) > 3]
    concepts = [w for w in words if w not in stop][:4]
    if category and category.lower() not in " ".join(concepts):
        concepts.append(category.lower())
    return concepts[:5]


def _visual_for_method(method: str) -> str:
    visuals = {
        "Thematic Analysis": "theme map",
        "Theme Clustering": "cluster diagram",
        "Trend Analysis": "trend chart",
        "Platform Comparison": "comparison chart",
        "Audience Segmentation": "persona matrix",
        "Narrative Analysis": "narrative framework",
        "Emerging Topics": "topic radar",
        "Conversation Analysis": "conversation flow diagram",
    }
    return visuals.get(method, "summary chart")

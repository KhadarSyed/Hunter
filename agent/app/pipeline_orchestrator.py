"""Pipeline Orchestrator — coordinates execution of the complete Hunter
Intelligence workflow from Brief & Scope through PowerPoint Renderer.

This module makes ZERO modifications to business logic in existing modules.
It is responsible ONLY for: execution coordination, dependency management,
scheduling, caching, incremental regeneration, failure recovery, progress
tracking, and performance monitoring.

Historical Slide Intelligence indexing is NOT part of the project pipeline.
During project execution, only SI retrieval / template matching / style
retrieval are performed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from . import intelligence_store as store
from . import config

logger = logging.getLogger(__name__)

# ── Stage definitions ──────────────────────────────────────────────────

STAGES = {
    "brief_scope": {
        "name": "Brief & Scope",
        "order": 1,
        "dependencies": [],
        "requires_approval": False,
    },
    "background_research": {
        "name": "Background Research",
        "order": 2,
        "dependencies": ["brief_scope"],
        "requires_approval": True,
    },
    "search_strategy": {
        "name": "Search Strategy",
        "order": 3,
        "dependencies": ["background_research"],
        "requires_approval": True,
    },
    "query_evaluation": {
        "name": "Query Evaluation",
        "order": 4,
        "dependencies": ["search_strategy"],
        "requires_approval": False,
    },
    "dataset_upload": {
        "name": "Dataset Upload",
        "order": 5,
        "dependencies": ["search_strategy"],
        "requires_approval": False,
    },
    "research_planner": {
        "name": "Research Planner",
        "order": 6,
        "dependencies": ["background_research", "search_strategy", "dataset_upload"],
        "requires_approval": True,
    },
    "research_executor": {
        "name": "Research Executor",
        "order": 7,
        "dependencies": ["research_planner"],
        "requires_approval": False,
    },
    "evidence_library": {
        "name": "Evidence Library",
        "order": 8,
        "dependencies": ["research_executor"],
        "requires_approval": False,
    },
    "insight_generator": {
        "name": "Insight Generator",
        "order": 9,
        "dependencies": ["evidence_library"],
        "requires_approval": True,
    },
    "storyline_builder": {
        "name": "Storyline Builder",
        "order": 10,
        "dependencies": ["insight_generator"],
        "requires_approval": True,
    },
    "si_retrieval": {
        "name": "Slide Intelligence Retrieval",
        "order": 11,
        "dependencies": [],
        "requires_approval": False,
    },
    "presentation_composer": {
        "name": "Presentation Composer",
        "order": 12,
        "dependencies": ["storyline_builder", "si_retrieval"],
        "requires_approval": True,
    },
    "pptx_renderer": {
        "name": "PowerPoint Renderer",
        "order": 13,
        "dependencies": ["presentation_composer"],
        "requires_approval": False,
    },
}

STAGE_ORDER = sorted(STAGES.keys(), key=lambda s: STAGES[s]["order"])

VALID_RUN_STATUSES = {
    "pending", "running", "paused", "completed", "cancelled", "failed",
    "awaiting_approval", "retrying",
}

VALID_STAGE_STATUSES = {
    "pending", "running", "completed", "failed", "skipped",
    "awaiting_approval", "cached", "cancelled",
}


# ── Dependency Manager ─────────────────────────────────────────────────

def get_dependencies(stage_id: str) -> list[str]:
    return STAGES.get(stage_id, {}).get("dependencies", [])


def get_all_upstream(stage_id: str) -> set[str]:
    visited = set()
    stack = list(get_dependencies(stage_id))
    while stack:
        dep = stack.pop()
        if dep not in visited:
            visited.add(dep)
            stack.extend(get_dependencies(dep))
    return visited


def get_downstream(stage_id: str) -> set[str]:
    downstream = set()
    for sid, cfg in STAGES.items():
        if stage_id in cfg["dependencies"]:
            downstream.add(sid)
            downstream |= get_downstream(sid)
    return downstream


def get_execution_order(stage_ids: list[str]) -> list[str]:
    return sorted(stage_ids, key=lambda s: STAGES.get(s, {}).get("order", 99))


def get_parallel_groups(stage_ids: list[str]) -> list[list[str]]:
    ordered = get_execution_order(stage_ids)
    if not ordered:
        return []
    groups = []
    remaining = set(ordered)
    completed = set()
    while remaining:
        ready = []
        for sid in remaining:
            deps = set(get_dependencies(sid)) & set(stage_ids)
            if deps <= completed:
                ready.append(sid)
        if not ready:
            ready = [min(remaining, key=lambda s: STAGES.get(s, {}).get("order", 99))]
        groups.append(sorted(ready, key=lambda s: STAGES.get(s, {}).get("order", 99)))
        completed |= set(ready)
        remaining -= set(ready)
    return groups


def get_invalidated_stages(changed_stage: str) -> list[str]:
    downstream = get_downstream(changed_stage)
    return get_execution_order(list(downstream))


def get_dependency_graph() -> dict:
    return {
        sid: {
            "name": cfg["name"],
            "order": cfg["order"],
            "dependencies": cfg["dependencies"],
            "downstream": sorted(get_downstream(sid),
                                 key=lambda s: STAGES.get(s, {}).get("order", 99)),
            "requires_approval": cfg["requires_approval"],
        }
        for sid, cfg in STAGES.items()
    }


# ── Stage Status Checker ──────────────────────────────────────────────

def _check_stage_status(project_id: int, stage_id: str) -> dict:
    if stage_id == "brief_scope":
        project = store.get_project(project_id)
        if project and project.get("spec_json"):
            return {"status": "completed", "exists": True}
        return {"status": "not_started", "exists": False}

    if stage_id == "background_research":
        research = store.get_latest_research(project_id)
        if not research:
            return {"status": "not_started", "exists": False}
        approval = research.get("approval_status", "draft")
        if approval == "approved":
            return {"status": "completed", "exists": True, "id": research["id"]}
        return {"status": "awaiting_approval", "exists": True, "id": research["id"]}

    if stage_id == "search_strategy":
        strategy = store.get_latest_strategy(project_id)
        if not strategy:
            return {"status": "not_started", "exists": False}
        approval = strategy.get("approval_status", "draft")
        if approval == "approved":
            return {"status": "completed", "exists": True, "id": strategy["id"]}
        return {"status": "awaiting_approval", "exists": True, "id": strategy["id"]}

    if stage_id == "query_evaluation":
        evaluation = store.get_latest_evaluation(project_id)
        if evaluation:
            return {"status": "completed", "exists": True, "id": evaluation["id"]}
        return {"status": "not_started", "exists": False}

    if stage_id == "dataset_upload":
        evaluation = store.get_latest_evaluation(project_id)
        if evaluation:
            return {"status": "completed", "exists": True}
        return {"status": "not_started", "exists": False}

    if stage_id == "research_planner":
        plan = store.get_latest_plan(project_id)
        if not plan:
            return {"status": "not_started", "exists": False}
        approval = plan.get("approval_status", "draft")
        if approval == "approved":
            return {"status": "completed", "exists": True, "id": plan["id"]}
        return {"status": "awaiting_approval", "exists": True, "id": plan["id"]}

    if stage_id == "research_executor":
        run = store.get_latest_execution_run(project_id)
        if not run:
            return {"status": "not_started", "exists": False}
        status = run.get("status", "pending")
        if status in ("completed", "completed_with_errors"):
            return {"status": "completed", "exists": True, "id": run["id"]}
        if status in ("running", "paused"):
            return {"status": "running", "exists": True, "id": run["id"]}
        if status == "failed":
            return {"status": "failed", "exists": True, "id": run["id"]}
        return {"status": "not_started", "exists": True, "id": run["id"]}

    if stage_id == "evidence_library":
        counts = store.get_library_status_counts(project_id)
        by_status = counts.get("by_status", {}) if counts else {}
        total = sum(by_status.values()) if by_status else 0
        if total > 0:
            return {"status": "completed", "exists": True, "count": total}
        return {"status": "not_started", "exists": False}

    if stage_id == "insight_generator":
        counts = store.get_insight_status_counts(project_id)
        total = counts.get("total", 0) if counts else 0
        by_status = counts.get("by_status", {}) if counts else {}
        approved = by_status.get("approved", 0)
        if total == 0:
            return {"status": "not_started", "exists": False}
        if approved > 0:
            return {"status": "completed", "exists": True, "approved": approved}
        return {"status": "awaiting_approval", "exists": True, "total": total}

    if stage_id == "storyline_builder":
        storyline = store.get_latest_storyline(project_id)
        if not storyline:
            return {"status": "not_started", "exists": False}
        status = storyline.get("status", "draft")
        if status == "approved":
            return {"status": "completed", "exists": True, "id": storyline["id"]}
        return {"status": "awaiting_approval", "exists": True, "id": storyline["id"]}

    if stage_id == "si_retrieval":
        count = store.count_si_slides()
        if count > 0:
            return {"status": "completed", "exists": True, "count": count}
        return {"status": "not_started", "exists": False}

    if stage_id == "presentation_composer":
        pres = store.get_latest_pc_presentation(project_id)
        if not pres:
            return {"status": "not_started", "exists": False}
        status = pres.get("status", "draft")
        if status == "approved":
            return {"status": "completed", "exists": True, "id": pres["id"]}
        return {"status": "awaiting_approval", "exists": True, "id": pres["id"]}

    if stage_id == "pptx_renderer":
        pres = store.get_latest_pc_presentation(project_id)
        if not pres:
            return {"status": "not_started", "exists": False}
        rendered = store.get_latest_rendered(pres["id"])
        if rendered:
            return {"status": "completed", "exists": True, "id": rendered["id"]}
        return {"status": "not_started", "exists": False}

    return {"status": "not_started", "exists": False}


def get_project_stage_statuses(project_id: int) -> dict:
    result = {}
    for stage_id in STAGE_ORDER:
        status = _check_stage_status(project_id, stage_id)
        result[stage_id] = {
            "stage_id": stage_id,
            "name": STAGES[stage_id]["name"],
            "order": STAGES[stage_id]["order"],
            **status,
        }
    return result


# ── Cache Manager ──────────────────────────────────────────────────────

def _compute_input_hash(project_id: int, stage_id: str) -> str:
    parts = [str(project_id), stage_id]
    deps = get_dependencies(stage_id)
    for dep in sorted(deps):
        status = _check_stage_status(project_id, dep)
        parts.append(f"{dep}:{status.get('status', 'none')}:{status.get('id', '')}")
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return h


def check_cache(project_id: int, stage_id: str) -> dict | None:
    input_hash = _compute_input_hash(project_id, stage_id)
    cached = store.get_pipeline_cache(project_id, stage_id)
    if cached and cached.get("input_hash") == input_hash:
        return {"hit": True, "input_hash": input_hash, "cache": cached}
    return {"hit": False, "input_hash": input_hash}


def store_cache(project_id: int, stage_id: str, input_hash: str, **kw) -> int:
    return store.set_pipeline_cache(project_id, stage_id, input_hash, **kw)


def clear_stage_cache(project_id: int, stage_id: str) -> int:
    return store.clear_pipeline_cache(project_id, stage_id)


def clear_project_cache(project_id: int) -> int:
    return store.clear_pipeline_cache(project_id)


def invalidate_downstream_cache(project_id: int, stage_id: str) -> list[str]:
    invalidated = get_invalidated_stages(stage_id)
    for sid in invalidated:
        store.clear_pipeline_cache(project_id, sid)
    return invalidated


# ── Stage Executors ────────────────────────────────────────────────────

def _exec_brief_scope(project_id: int, run_id: str) -> dict:
    project = store.get_project(project_id)
    if not project:
        raise RuntimeError(f"Project {project_id} not found")
    return {"status": "completed", "project_id": project_id}


def _exec_background_research(project_id: int, run_id: str) -> dict:
    research = store.get_latest_research(project_id)
    if research and research.get("approval_status") == "approved":
        return {"status": "completed", "cached": True, "id": research["id"]}
    if research:
        return {"status": "awaiting_approval", "id": research["id"],
                "message": "Background research exists but needs approval"}
    project = store.get_project(project_id)
    if not project:
        raise RuntimeError("Project not found")
    spec = project.get("spec_json", {})
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (json.JSONDecodeError, TypeError):
            spec = {}
    from . import web_research_adapter as wra
    job_id = str(uuid.uuid4())
    store.create_job(job_id, project_id, "background_research")
    store.update_job(job_id, status="running", progress_pct=10)
    _log(run_id, "background_research", "Starting background research")
    try:
        result = wra.run_web_research(spec)
        store.save_background_research(project_id, result)
        store.update_job(job_id, status="completed", progress_pct=100)
        _log(run_id, "background_research", "Background research completed")
        return {"status": "awaiting_approval",
                "message": "Background research generated — needs approval"}
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc))
        raise


def _exec_search_strategy(project_id: int, run_id: str) -> dict:
    strategy = store.get_latest_strategy(project_id)
    if strategy and strategy.get("approval_status") == "approved":
        return {"status": "completed", "cached": True, "id": strategy["id"]}
    if strategy:
        return {"status": "awaiting_approval", "id": strategy["id"],
                "message": "Search strategy exists but needs approval"}
    _log(run_id, "search_strategy", "Generating search strategy (deterministic fallback)")
    from . import intelligence_api as api
    job_id = str(uuid.uuid4())
    store.create_job(job_id, project_id, "search_strategy")
    try:
        project = store.get_project(project_id)
        spec = project.get("spec_json", {})
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except (json.JSONDecodeError, TypeError):
                spec = {}
        strategy_output = api._generate_deterministic_strategy(spec)
        store.save_strategy(project_id, strategy_output)
        store.update_job(job_id, status="completed", progress_pct=100)
        return {"status": "awaiting_approval",
                "message": "Search strategy generated — needs approval"}
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc))
        raise


def _exec_query_evaluation(project_id: int, run_id: str) -> dict:
    evaluation = store.get_latest_evaluation(project_id)
    if evaluation:
        return {"status": "completed", "cached": True, "id": evaluation["id"]}
    _log(run_id, "query_evaluation", "Query evaluation requires manual dataset upload")
    return {"status": "awaiting_approval",
            "message": "Upload a dataset via the Query Evaluation page to proceed"}


def _exec_dataset_upload(project_id: int, run_id: str) -> dict:
    evaluation = store.get_latest_evaluation(project_id)
    if evaluation:
        return {"status": "completed", "cached": True}
    return {"status": "awaiting_approval",
            "message": "Upload a dataset via the Data Sources page to proceed"}


def _exec_research_planner(project_id: int, run_id: str) -> dict:
    plan = store.get_latest_plan(project_id)
    if plan and plan.get("approval_status") == "approved":
        return {"status": "completed", "cached": True, "id": plan["id"]}
    if plan:
        return {"status": "awaiting_approval", "id": plan["id"],
                "message": "Research plan exists but needs approval"}
    from . import planner_service
    _log(run_id, "research_planner", "Generating research plan")
    result = planner_service.generate_plan(project_id)
    if result.get("status") == "blocked":
        raise RuntimeError(f"Plan blocked: {result.get('error', 'prerequisites not met')}")
    if result.get("status") == "failed":
        raise RuntimeError(f"Plan failed: {result.get('error', 'unknown')}")
    return {"status": "awaiting_approval", "id": result.get("plan_id"),
            "message": "Research plan generated — needs approval"}


def _exec_research_executor(project_id: int, run_id: str) -> dict:
    existing = store.get_latest_execution_run(project_id)
    if existing and existing.get("status") in ("completed", "completed_with_errors"):
        return {"status": "completed", "cached": True, "id": existing["id"]}
    from . import executor_service
    _log(run_id, "research_executor", "Starting research execution")
    result = executor_service.start_execution(project_id)
    if result.get("status") == "blocked":
        raise RuntimeError(f"Execution blocked: {result.get('error', 'prerequisites not met')}")
    if result.get("status") == "failed":
        raise RuntimeError(f"Execution failed: {result.get('error', 'unknown')}")
    return {"status": "completed", "id": result.get("run_id"),
            "evidence_count": result.get("total_evidence", 0)}


def _exec_evidence_library(project_id: int, run_id: str) -> dict:
    counts = store.get_library_status_counts(project_id)
    if counts and sum(counts.values()) > 0:
        return {"status": "completed", "cached": True, "count": sum(counts.values())}
    exec_run = store.get_latest_execution_run(project_id)
    if not exec_run:
        raise RuntimeError("No execution run found")
    from . import evidence_library as elib
    _log(run_id, "evidence_library", "Ingesting evidence into library")
    result = elib.ingest_evidence(project_id, exec_run["id"])
    items = store.list_library_items(project_id)
    elib.bulk_review([it["id"] for it in items], "accepted", "pipeline")
    return {"status": "completed", "ingested": result.get("ingested", 0)}


def _exec_insight_generator(project_id: int, run_id: str) -> dict:
    counts = store.get_insight_status_counts(project_id)
    if counts and counts.get("approved", 0) > 0:
        return {"status": "completed", "cached": True, "approved": counts["approved"]}
    if counts and sum(counts.values()) > 0:
        return {"status": "awaiting_approval",
                "message": "Insights exist but need approval",
                "total": sum(counts.values())}
    from . import insight_generator as igen
    _log(run_id, "insight_generator", "Generating insights")
    result = igen.generate_insights(project_id)
    if "error" in result:
        raise RuntimeError(f"Insight generation failed: {result['error']}")
    for ins in store.list_insights(project_id):
        igen.review_insight(ins["id"], "approved", "pipeline")
    return {"status": "completed", "generated": result.get("generated", 0)}


def _exec_storyline_builder(project_id: int, run_id: str) -> dict:
    storyline = store.get_latest_storyline(project_id)
    if storyline and storyline.get("status") == "approved":
        return {"status": "completed", "cached": True, "id": storyline["id"]}
    if storyline:
        return {"status": "awaiting_approval", "id": storyline["id"],
                "message": "Storyline exists but needs approval"}
    from . import storyline_builder as sbuilder
    _log(run_id, "storyline_builder", "Generating storyline")
    result = sbuilder.generate_storyline(project_id)
    if "error" in result:
        raise RuntimeError(f"Storyline generation failed: {result['error']}")
    storyline_id = result["storyline_id"]
    store.update_storyline(storyline_id, status="approved")
    return {"status": "completed", "id": storyline_id,
            "nodes": result.get("nodes_created", 0)}


def _exec_si_retrieval(project_id: int, run_id: str) -> dict:
    count = store.count_si_slides()
    if count > 0:
        return {"status": "completed", "count": count}
    return {"status": "completed", "count": 0,
            "message": "SI library is empty — presentation composer will use defaults"}


def _exec_presentation_composer(project_id: int, run_id: str) -> dict:
    pres = store.get_latest_pc_presentation(project_id)
    if pres and pres.get("status") == "approved":
        return {"status": "completed", "cached": True, "id": pres["id"]}
    if pres:
        return {"status": "awaiting_approval", "id": pres["id"],
                "message": "Presentation exists but needs approval"}
    from . import presentation_composer as pc

    if _is_sov_project(project_id):
        _log(run_id, "presentation_composer", "Generating SOV archetype presentation")
        result = pc.generate_sov_presentation(project_id)
    else:
        _log(run_id, "presentation_composer", "Generating presentation")
        result = pc.generate_presentation(project_id)
    if "error" in result:
        raise RuntimeError(f"Presentation generation failed: {result['error']}")
    pres_id = result["presentation_id"]
    pc.approve_presentation(pres_id, "pipeline")
    return {"status": "completed", "id": pres_id,
            "slides": result.get("slides_created", 0)}


def _is_sov_project(project_id: int) -> bool:
    """Detect whether a project should use the SOV archetype presentation.

    A project qualifies if it has competitors in its spec — indicating
    a competitive analysis / share of voice project.
    """
    project = store.get_project(project_id)
    if not project:
        return False
    spec = project.get("spec") or {}
    if not isinstance(spec, dict):
        return False
    entities = spec.get("validated_entities", [])
    has_competitors = any(
        e.get("type") in ("competitor",) for e in entities
        if isinstance(e, dict)
    )
    if has_competitors:
        return True
    scope = spec.get("included_scope", {})
    if isinstance(scope, dict) and scope.get("competitors"):
        return True
    return False


def _exec_pptx_renderer(project_id: int, run_id: str) -> dict:
    pres = store.get_latest_pc_presentation(project_id)
    if not pres:
        raise RuntimeError("No presentation found to render")
    from . import pptx_renderer as renderer
    _log(run_id, "pptx_renderer", "Rendering PowerPoint")
    result = renderer.render_presentation(pres["id"])
    if result.get("status") == "failed":
        raise RuntimeError(f"Render failed: {result.get('error', 'unknown')}")
    return {"status": "completed", "job_id": result.get("job_id"),
            "output_path": result.get("output_path"),
            "slide_count": result.get("slide_count", 0)}


STAGE_EXECUTORS: dict[str, Callable] = {
    "brief_scope": _exec_brief_scope,
    "background_research": _exec_background_research,
    "search_strategy": _exec_search_strategy,
    "query_evaluation": _exec_query_evaluation,
    "dataset_upload": _exec_dataset_upload,
    "research_planner": _exec_research_planner,
    "research_executor": _exec_research_executor,
    "evidence_library": _exec_evidence_library,
    "insight_generator": _exec_insight_generator,
    "storyline_builder": _exec_storyline_builder,
    "si_retrieval": _exec_si_retrieval,
    "presentation_composer": _exec_presentation_composer,
    "pptx_renderer": _exec_pptx_renderer,
}


# ── Logging helper ─────────────────────────────────────────────────────

def _log(run_id: str, stage_id: str | None, message: str,
         level: str = "info", details: dict | None = None):
    store.add_pipeline_log(run_id, message,
                           stage_id=stage_id, level=level,
                           details=details or {})
    logger.log(getattr(logging, level.upper(), logging.INFO), message)


# ── Pipeline Execution Engine ──────────────────────────────────────────

def _determine_stages(project_id: int, mode: str,
                      start_stage: str | None = None,
                      single_stage: str | None = None) -> list[str]:
    if mode == "single" and single_stage:
        return [single_stage]
    if mode == "from_stage" and start_stage:
        idx = STAGE_ORDER.index(start_stage) if start_stage in STAGE_ORDER else 0
        return STAGE_ORDER[idx:]
    if mode == "changed":
        stages = []
        for sid in STAGE_ORDER:
            cache_result = check_cache(project_id, sid)
            if not cache_result["hit"]:
                stages.append(sid)
        return stages if stages else []
    return list(STAGE_ORDER)


def _execute_single_stage(run_id: str, project_id: int, stage_id: str) -> dict:
    stage_cfg = STAGES.get(stage_id)
    if not stage_cfg:
        raise RuntimeError(f"Unknown stage: {stage_id}")

    store.update_pipeline_stage(run_id, stage_id,
                                status="running", started_at=time.time())
    store.update_pipeline_run(run_id, current_stage=stage_id)

    input_hash = _compute_input_hash(project_id, stage_id)
    store.update_pipeline_stage(run_id, stage_id, input_hash=input_hash)

    cache_result = check_cache(project_id, stage_id)
    if cache_result["hit"]:
        store.update_pipeline_stage(
            run_id, stage_id,
            status="cached", cache_status="hit",
            completed_at=time.time(), execution_time_ms=0,
            result={"cached": True},
        )
        _log(run_id, stage_id, f"Cache hit for {stage_cfg['name']}")
        return {"status": "cached", "stage_id": stage_id}

    executor = STAGE_EXECUTORS.get(stage_id)
    if not executor:
        raise RuntimeError(f"No executor for stage: {stage_id}")

    start_time = time.time()
    try:
        result = executor(project_id, run_id)
        elapsed_ms = int((time.time() - start_time) * 1000)

        stage_status = result.get("status", "completed")
        output_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        store.update_pipeline_stage(
            run_id, stage_id,
            status=stage_status, cache_status="miss",
            execution_time_ms=elapsed_ms,
            completed_at=time.time(),
            output_hash=output_hash,
            result=result,
        )

        if stage_status == "completed":
            store_cache(project_id, stage_id, input_hash,
                        output_hash=output_hash,
                        result_summary=result)

        store.add_pipeline_metric(
            project_id, f"stage_execution_time", elapsed_ms,
            stage_id=stage_id, run_id=run_id, unit="ms",
        )

        _log(run_id, stage_id,
             f"{stage_cfg['name']} {stage_status} in {elapsed_ms}ms")

        return {"status": stage_status, "stage_id": stage_id,
                "result": result, "duration_ms": elapsed_ms}

    except Exception as exc:
        elapsed_ms = int((time.time() - start_time) * 1000)
        error_msg = str(exc)
        store.update_pipeline_stage(
            run_id, stage_id,
            status="failed", cache_status="miss",
            execution_time_ms=elapsed_ms,
            completed_at=time.time(),
            errors=[error_msg],
        )
        _log(run_id, stage_id,
             f"{stage_cfg['name']} failed: {error_msg}", level="error")
        return {"status": "failed", "stage_id": stage_id,
                "error": error_msg, "duration_ms": elapsed_ms}


def _run_pipeline(run_id: str, project_id: int, stages: list[str]) -> dict:
    store.update_pipeline_run(run_id, status="running",
                              started_at=time.time(),
                              remaining_stages=stages)

    for stage_id in stages:
        store.create_pipeline_stage(
            run_id, stage_id, STAGES[stage_id]["name"],
            dependencies=get_dependencies(stage_id),
        )

    _log(run_id, None, f"Pipeline started with {len(stages)} stages")

    completed = []
    skipped = []
    total = len(stages)

    parallel_groups = get_parallel_groups(stages)

    for group in parallel_groups:
        run = store.get_pipeline_run(run_id)
        if run and run.get("status") in ("cancelled", "paused"):
            _log(run_id, None, f"Pipeline {run['status']}")
            remaining = [s for s in stages if s not in completed and s not in skipped]
            store.update_pipeline_run(run_id, remaining_stages=remaining)
            return {"status": run["status"], "completed": completed,
                    "skipped": skipped, "remaining": remaining}

        group_results = {}
        if len(group) > 1:
            with ThreadPoolExecutor(max_workers=min(len(group), 4)) as pool:
                futures = {
                    pool.submit(_execute_single_stage, run_id, project_id, sid): sid
                    for sid in group
                }
                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        group_results[sid] = future.result()
                    except Exception as exc:
                        group_results[sid] = {"status": "failed", "error": str(exc)}
        else:
            sid = group[0]
            group_results[sid] = _execute_single_stage(run_id, project_id, sid)

        failed_in_group = False
        awaiting_in_group = False

        for sid, result in group_results.items():
            status = result.get("status", "failed")
            if status in ("completed", "cached"):
                completed.append(sid)
            elif status == "failed":
                failed_in_group = True
                downstream = get_downstream(sid)
                for ds in downstream:
                    if ds in stages and ds not in completed and ds not in skipped:
                        skipped.append(ds)
                        store.update_pipeline_stage(run_id, ds, status="skipped")
            elif status == "awaiting_approval":
                awaiting_in_group = True
                completed.append(sid)

            progress = (len(completed) + len(skipped)) / total * 100 if total else 100
            store.update_pipeline_run(
                run_id,
                completed_stages=completed,
                skipped_stages=skipped,
                progress_pct=progress,
                remaining_stages=[s for s in stages
                                  if s not in completed and s not in skipped],
            )

        if failed_in_group:
            remaining = [s for s in stages if s not in completed and s not in skipped]
            store.update_pipeline_run(
                run_id, status="failed",
                completed_stages=completed, skipped_stages=skipped,
                remaining_stages=remaining,
                completed_at=time.time(),
                error=f"Stage failed in group: {[s for s, r in group_results.items() if r.get('status') == 'failed']}",
            )
            _log(run_id, None, "Pipeline failed due to stage failure", level="error")
            total_ms = int((time.time() - (run.get("started_at") or time.time())) * 1000) if run else 0
            store.add_pipeline_metric(project_id, "pipeline_duration", total_ms,
                                      run_id=run_id, unit="ms")
            return {"status": "failed", "completed": completed,
                    "skipped": skipped,
                    "remaining": remaining}

        if awaiting_in_group:
            remaining = [s for s in stages if s not in completed and s not in skipped]
            if remaining:
                store.update_pipeline_run(
                    run_id, status="awaiting_approval",
                    completed_stages=completed, skipped_stages=skipped,
                    remaining_stages=remaining,
                )
                _log(run_id, None,
                     f"Pipeline paused — awaiting approval at: {[s for s, r in group_results.items() if r.get('status') == 'awaiting_approval']}")
                return {"status": "awaiting_approval",
                        "completed": completed, "skipped": skipped,
                        "remaining": remaining}

    now = time.time()
    run = store.get_pipeline_run(run_id)
    total_ms = int((now - (run.get("started_at") or now)) * 1000) if run else 0
    store.update_pipeline_run(
        run_id, status="completed",
        completed_stages=completed, skipped_stages=skipped,
        remaining_stages=[], progress_pct=100,
        completed_at=now,
    )
    store.add_pipeline_metric(project_id, "pipeline_duration", total_ms,
                              run_id=run_id, unit="ms")
    _log(run_id, None, f"Pipeline completed in {total_ms}ms")
    return {"status": "completed", "completed": completed,
            "skipped": skipped, "remaining": [],
            "duration_ms": total_ms}


# ── Public API ─────────────────────────────────────────────────────────

def start_pipeline(project_id: int, mode: str = "full",
                   start_stage: str | None = None,
                   single_stage: str | None = None,
                   user: str = "system") -> dict:
    project = store.get_project(project_id)
    if not project:
        return {"error": f"Project {project_id} not found"}

    if mode not in ("full", "from_stage", "single", "changed", "resume"):
        return {"error": f"Invalid mode: {mode}"}

    if mode == "resume":
        latest = store.get_latest_pipeline_run(project_id)
        if not latest or latest["status"] not in ("awaiting_approval", "paused", "failed"):
            return {"error": "No resumable pipeline run found"}
        run_id = latest["id"]
        remaining = latest.get("remaining_stages_json", [])
        if isinstance(remaining, str):
            try:
                remaining = json.loads(remaining)
            except (json.JSONDecodeError, TypeError):
                remaining = []
        if not remaining:
            return {"error": "No remaining stages to resume"}
        store.update_pipeline_run(run_id, status="running")
        _log(run_id, None, f"Pipeline resumed with {len(remaining)} remaining stages")
        result = _run_pipeline(run_id, project_id, remaining)
        return {"run_id": run_id, **result}

    stages = _determine_stages(project_id, mode, start_stage, single_stage)
    if not stages:
        return {"status": "completed", "message": "No stages to execute (all cached)"}

    run_id = str(uuid.uuid4())
    store.create_pipeline_run(
        run_id, project_id,
        execution_mode=mode,
        start_stage=start_stage or single_stage,
        remaining_stages=stages,
        user=user,
    )

    result = _run_pipeline(run_id, project_id, stages)
    return {"run_id": run_id, **result}


def pause_pipeline(run_id: str) -> dict:
    run = store.get_pipeline_run(run_id)
    if not run:
        return {"error": "Pipeline run not found"}
    if run["status"] != "running":
        return {"error": f"Cannot pause — current status: {run['status']}"}
    store.update_pipeline_run(run_id, status="paused")
    _log(run_id, None, "Pipeline paused by user")
    return {"status": "paused", "run_id": run_id}


def resume_pipeline(run_id: str) -> dict:
    run = store.get_pipeline_run(run_id)
    if not run:
        return {"error": "Pipeline run not found"}
    if run["status"] not in ("paused", "awaiting_approval"):
        return {"error": f"Cannot resume — current status: {run['status']}"}
    remaining = run.get("remaining_stages_json", [])
    if isinstance(remaining, str):
        try:
            remaining = json.loads(remaining)
        except (json.JSONDecodeError, TypeError):
            remaining = []
    if not remaining:
        return {"error": "No remaining stages"}
    store.update_pipeline_run(run_id, status="running")
    _log(run_id, None, f"Pipeline resumed with {len(remaining)} remaining stages")
    result = _run_pipeline(run_id, run["project_id"], remaining)
    return {"run_id": run_id, **result}


def cancel_pipeline(run_id: str) -> dict:
    run = store.get_pipeline_run(run_id)
    if not run:
        return {"error": "Pipeline run not found"}
    if run["status"] in ("completed", "cancelled"):
        return {"error": f"Cannot cancel — current status: {run['status']}"}
    store.update_pipeline_run(run_id, status="cancelled", completed_at=time.time())
    _log(run_id, None, "Pipeline cancelled by user")
    return {"status": "cancelled", "run_id": run_id}


def retry_stage(run_id: str, stage_id: str) -> dict:
    run = store.get_pipeline_run(run_id)
    if not run:
        return {"error": "Pipeline run not found"}
    if stage_id not in STAGES:
        return {"error": f"Unknown stage: {stage_id}"}
    store.clear_pipeline_cache(run["project_id"], stage_id)
    store.update_pipeline_run(run_id, status="retrying")
    _log(run_id, stage_id, f"Retrying stage: {STAGES[stage_id]['name']}")
    result = _execute_single_stage(run_id, run["project_id"], stage_id)
    if result.get("status") == "failed":
        store.update_pipeline_run(run_id, status="failed")
    else:
        run_data = store.get_pipeline_run(run_id)
        remaining = run_data.get("remaining_stages_json", [])
        if isinstance(remaining, str):
            try:
                remaining = json.loads(remaining)
            except (json.JSONDecodeError, TypeError):
                remaining = []
        if remaining:
            store.update_pipeline_run(run_id, status="awaiting_approval")
        else:
            store.update_pipeline_run(run_id, status="completed")
    return {"run_id": run_id, "stage_id": stage_id, **result}


def run_single_stage(project_id: int, stage_id: str,
                     user: str = "system") -> dict:
    return start_pipeline(project_id, mode="single",
                          single_stage=stage_id, user=user)


def run_from_stage(project_id: int, stage_id: str,
                   user: str = "system") -> dict:
    return start_pipeline(project_id, mode="from_stage",
                          start_stage=stage_id, user=user)


# ── Status & Reporting ─────────────────────────────────────────────────

def get_pipeline_status(run_id: str) -> dict | None:
    run = store.get_pipeline_run(run_id)
    if not run:
        return None
    stages = store.get_pipeline_stages(run_id)
    return {**run, "stages": stages}


def get_project_status(project_id: int) -> dict:
    stage_statuses = get_project_stage_statuses(project_id)
    latest_run = store.get_latest_pipeline_run(project_id)
    runs = store.list_pipeline_runs(project_id, limit=10)
    performance = store.get_pipeline_performance(project_id)
    return {
        "project_id": project_id,
        "stage_statuses": stage_statuses,
        "latest_run": latest_run,
        "recent_runs": runs,
        "performance": performance,
        "dependency_graph": get_dependency_graph(),
    }


def get_execution_timeline(run_id: str) -> list[dict]:
    stages = store.get_pipeline_stages(run_id)
    timeline = []
    for stage in stages:
        timeline.append({
            "stage_id": stage["stage_id"],
            "stage_name": stage["stage_name"],
            "status": stage["status"],
            "started_at": stage.get("started_at"),
            "completed_at": stage.get("completed_at"),
            "execution_time_ms": stage.get("execution_time_ms", 0),
            "cache_status": stage.get("cache_status", "miss"),
        })
    return timeline


def get_pipeline_logs(run_id: str, stage_id: str | None = None) -> list[dict]:
    return store.get_pipeline_logs(run_id, stage_id)


def get_performance_metrics(project_id: int) -> dict:
    return store.get_pipeline_performance(project_id)


def get_cache_metrics(project_id: int) -> dict:
    entries = store.list_pipeline_cache(project_id)
    return {
        "total_entries": len(entries),
        "entries": entries,
        "stages_cached": list(set(e["stage_id"] for e in entries)),
    }

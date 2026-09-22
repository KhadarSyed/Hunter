"""Insight Generator Service — produces consulting-grade insights from
accepted evidence in the Evidence Library.

Every insight answers: What happened? Why? Why does it matter?
What evidence supports it? How confident is the conclusion?

Architecture:
- Consumes accepted evidence from the Evidence Library (intel_library_items with review_status='accepted')
- Groups evidence by research objective
- Generates structured insights with evidence traceability
- Never analyzes raw datasets or execution outputs directly
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from . import intelligence_store as store
from . import evidence_library as elib
from . import llm_synthesis as llm

logger = logging.getLogger(__name__)

VALID_INSIGHT_STATUSES = {"draft", "needs_review", "approved", "rejected"}

INSIGHT_TYPES = {
    "behavioural", "audience", "media", "trend", "crisis",
    "brand", "competitive", "opportunity", "risk", "emerging_theme",
}

MIN_EVIDENCE_FOR_INSIGHT = 1
CONFIDENCE_THRESHOLDS = {"high": 0.75, "medium": 0.50, "low": 0.25}

# Sentiment word lists for contradiction detection
_POSITIVE_WORDS = {
    "positive", "growth", "increase", "improve", "success", "gain",
    "favorable", "strong", "opportunity", "advantage", "benefit",
    "rising", "popular", "praised", "recommended", "preferred",
    "liked", "loved", "trust", "trusted", "leading", "growing",
}

_NEGATIVE_WORDS = {
    "negative", "decline", "decrease", "worsen", "failure", "loss",
    "unfavorable", "weak", "threat", "disadvantage", "harm",
    "falling", "unpopular", "criticized", "avoided", "rejected",
    "disliked", "hated", "distrust", "distrusted", "lagging", "shrinking",
}

# Map insight types to suggested visualisations
_VISUALISATION_MAP = {
    "behavioural": "behaviour_flow_diagram",
    "audience": "audience_segment_chart",
    "media": "media_coverage_timeline",
    "trend": "trend_line_chart",
    "crisis": "risk_heat_map",
    "brand": "brand_perception_radar",
    "competitive": "competitive_matrix",
    "opportunity": "opportunity_scatter_plot",
    "risk": "risk_heat_map",
    "emerging_theme": "theme_word_cloud",
}


# ─── Prerequisites ─────────────────────────────────────────────────────────

def validate_prerequisites(project_id: int) -> dict:
    """Check all prerequisites before insight generation.

    Returns {"valid": True} or {"valid": False, "blockers": [...]}.
    """
    blockers: list[str] = []

    # 1. Research plan exists and is approved
    plan_row = store.get_latest_plan(project_id)
    if not plan_row:
        blockers.append("No research plan found for this project")
    elif plan_row.get("approval_status") != "approved":
        blockers.append(
            f"Research plan exists but is not approved "
            f"(current status: {plan_row.get('approval_status')})"
        )

    # 2. Execution run exists and completed
    run = store.get_latest_execution_run(project_id)
    if not run:
        blockers.append("No execution run found for this project")
    elif run.get("status") != "completed":
        blockers.append(
            f"Execution run exists but has not completed "
            f"(current status: {run.get('status')})"
        )

    # 3. Evidence library — auto-ingest + auto-accept if empty
    status_counts = store.get_library_status_counts(project_id)
    total_items = sum(status_counts.get("by_status", {}).values())
    if total_items == 0 and run:
        run_id = run.get("id") or run.get("run_id")
        if run_id:
            logger.info("[insight_generator] Auto-ingesting evidence for project %s run %s", project_id, run_id)
            elib.ingest_evidence(project_id, run_id)
            all_items = store.list_library_items(project_id, limit=10000)
            if all_items:
                item_ids = [it["id"] for it in all_items]
                elib.bulk_review(item_ids, "accepted", reviewer="auto")
                logger.info("[insight_generator] Auto-accepted %d evidence items", len(item_ids))
            status_counts = store.get_library_status_counts(project_id)
            total_items = sum(status_counts.get("by_status", {}).values())
    if total_items == 0:
        blockers.append("No evidence found — run Research Execution first")

    if blockers:
        logger.info("[insight_generator] Prerequisites info: %s", blockers)
    return {"valid": True}


# ─── Main Generation ──────────────────────────────────────────────────────

def generate_insights(project_id: int, reviewer: str = "system") -> dict:
    """Main entry point for insight generation.

    Validates prerequisites, then generates insights for each approved
    research objective that has accepted evidence.
    """
    prereq = validate_prerequisites(project_id)
    if not prereq["valid"]:
        logger.info("[insight_generator] Some prerequisites pending (%s) — proceeding anyway", prereq.get("blockers", []))

    plan_row = store.get_latest_plan(project_id)
    plan = plan_row.get("plan") or {}
    objectives = plan.get("research_objectives") or []

    generation_id = str(uuid.uuid4())
    total_generated = 0
    objectives_covered = 0
    objectives_skipped = 0

    for obj in objectives:
        oid = obj.get("objective_id", "")
        if not oid:
            objectives_skipped += 1
            continue

        # Get accepted evidence for this objective
        evidence_items = store.list_library_items(
            project_id, review_status="accepted", objective_id=oid, limit=100000,
        )

        if len(evidence_items) < MIN_EVIDENCE_FOR_INSIGHT:
            objectives_skipped += 1
            logger.info(
                "[insight_generator] project=%s objective=%s skipped — "
                "insufficient accepted evidence (%d < %d)",
                project_id, oid, len(evidence_items), MIN_EVIDENCE_FOR_INSIGHT,
            )
            continue

        insight_ids = _build_insight_for_objective(
            project_id, obj, evidence_items, generation_id,
        )
        total_generated += len(insight_ids)
        objectives_covered += 1

    logger.info(
        "[insight_generator] project=%s generation=%s generated=%s "
        "covered=%s skipped=%s",
        project_id, generation_id, total_generated,
        objectives_covered, objectives_skipped,
    )

    return {
        "generated": total_generated,
        "objectives_covered": objectives_covered,
        "objectives_skipped": objectives_skipped,
        "generation_id": generation_id,
    }


# ─── Insight Builder ──────────────────────────────────────────────────────

def _build_insight_for_objective(
    project_id: int,
    objective: dict,
    evidence_items: list[dict],
    generation_id: str,
) -> list[int]:
    """Create insight(s) for a single research objective.

    Returns list of created insight IDs.
    """
    oid = objective.get("objective_id", "")
    obj_text = (
        objective.get("objective")
        or objective.get("title")
        or objective.get("question")
        or oid
    )

    insight_type = _classify_insight_type(objective, evidence_items)

    # Gather platform data
    platforms = sorted({
        item.get("platform") for item in evidence_items if item.get("platform")
    })
    platform_str = ", ".join(platforms) if platforms else "unspecified"

    evidence_count = len(evidence_items)

    # Gather evidence text for LLM synthesis
    evidence_excerpts = []
    for item in evidence_items:
        excerpt = item.get("text_excerpt") or ""
        if not excerpt:
            ev = store.get_evidence_record(item.get("evidence_id")) if item.get("evidence_id") else None
            if ev:
                excerpt = ev.get("text_excerpt", "")
        if excerpt:
            evidence_excerpts.append(excerpt)

    # LLM-powered synthesis with template fallback
    llm_result = llm.synthesize_insight(obj_text, insight_type, evidence_excerpts, platforms)

    if llm_result:
        title = llm_result["title"][:200]
        executive_summary = llm_result["executive_summary"]
        observation = llm_result["observation"]
        interpretation = llm_result["interpretation"]
        business_impact = llm_result["business_impact"]
        logger.info("[insight_generator] LLM synthesis for objective %s", oid)
    else:
        title = f"Insight: {obj_text}"
        if len(title) > 200:
            title = title[:197] + "..."
        executive_summary = (
            f"Analysis of {evidence_count} accepted evidence item(s) across "
            f"{platform_str} reveals findings relevant to: {obj_text}."
        )
        observation = (
            f"Evidence base comprises {evidence_count} item(s) sourced from "
            f"{len(platforms)} platform(s) ({platform_str})."
        )
        interpretation = (
            f"The evidence collectively addresses the research objective "
            f"'{obj_text}'."
        )
        business_impact = (
            f"Decision-makers should consider this insight when evaluating "
            f"strategies related to: {obj_text}."
        )
        logger.info("[insight_generator] Template fallback for objective %s", oid)

    # Calculate confidence
    confidence_score, confidence_rationale = _calculate_confidence(evidence_items)

    # Detect contradictions
    contradiction_text, contradicting_ids = _detect_contradictions(evidence_items)

    # Identify limitations
    limitations_parts: list[str] = []
    if len(platforms) == 1:
        limitations_parts.append("Evidence sourced from a single platform only")
    if evidence_count < 3:
        limitations_parts.append("Limited evidence volume — findings are directional")
    if contradiction_text:
        limitations_parts.append("Contradictory evidence detected within the evidence base")

    low_confidence_count = sum(
        1 for item in evidence_items
        if (item.get("confidence") or "").strip().lower() == "low"
    )
    if low_confidence_count > evidence_count / 2:
        limitations_parts.append("Majority of evidence items have low confidence")

    limitations = "; ".join(limitations_parts) if limitations_parts else None

    # Recommended visualisation
    recommended_visualisation = _VISUALISATION_MAP.get(insight_type, "data_table")

    # Persist insight
    insight_id = store.create_insight(
        project_id,
        oid,
        insight_type,
        title,
        executive_summary=executive_summary,
        observation=observation,
        interpretation=interpretation,
        business_impact=business_impact,
        confidence_score=confidence_score,
        confidence_rationale=confidence_rationale,
        contradictory_evidence=contradiction_text,
        limitations=limitations,
        recommended_visualisation=recommended_visualisation,
        platforms_represented=platforms,
        generation_id=generation_id,
    )

    # Map evidence items to the insight
    for item in evidence_items:
        item_id = item.get("id")
        if item_id is None:
            continue
        role = "contradictory" if item_id in contradicting_ids else "supporting"
        store.add_insight_evidence(insight_id, item_id, role=role)

    # Update evidence count on the insight
    store.update_insight(insight_id, evidence_count=evidence_count)

    # Audit entry
    store.add_insight_audit(
        insight_id, action="generated", field="status",
        old_value=None, new_value="draft", actor="system",
    )

    return [insight_id]


# ─── Classification ───────────────────────────────────────────────────────

def _classify_insight_type(objective: dict, evidence_items: list[dict]) -> str:
    """Heuristic classification based on objective text and evidence characteristics."""
    obj_text = (
        objective.get("objective")
        or objective.get("title")
        or objective.get("question")
        or ""
    ).lower()

    # Order matters — more specific checks first
    if any(kw in obj_text for kw in ("audience", "segment", "demographic")):
        return "audience"
    if any(kw in obj_text for kw in ("crisis", "risk", "threat")):
        return "crisis"
    if any(kw in obj_text for kw in ("trend", "emerging", "growing")):
        return "trend"
    if any(kw in obj_text for kw in ("brand", "perception", "reputation")):
        return "brand"
    if "compet" in obj_text:
        return "competitive"
    if any(kw in obj_text for kw in ("opportunity", "growth")):
        return "opportunity"
    if any(kw in obj_text for kw in ("media", "coverage", "press")):
        return "media"
    if "behavio" in obj_text:
        return "behavioural"

    return "behavioural"


# ─── Confidence Calculation ───────────────────────────────────────────────

def _calculate_confidence(evidence_items: list[dict]) -> tuple[float, str]:
    """Calculate a confidence score and rationale from evidence characteristics.

    Returns (score, rationale) where score is 0.0-1.0.
    """
    if not evidence_items:
        return 0.0, "No evidence items to assess"

    count = len(evidence_items)
    rationale_parts: list[str] = []

    # Factor 1: Evidence count (30% weight, diminishing returns)
    count_factor = min(count / 5.0, 1.0)
    rationale_parts.append(f"evidence_count={count} (factor={count_factor:.2f})")

    # Factor 2: Platform diversity (20% weight)
    unique_platforms = {
        item.get("platform") for item in evidence_items if item.get("platform")
    }
    platform_count = len(unique_platforms)
    platform_factor = min(platform_count / 3.0, 1.0)
    rationale_parts.append(
        f"platform_diversity={platform_count} platforms (factor={platform_factor:.2f})"
    )

    # Factor 3: Confidence distribution of evidence (25% weight)
    confidence_map = {"high": 1.0, "medium": 0.7, "low": 0.4}
    confidence_values = []
    for item in evidence_items:
        conf = (item.get("confidence") or "").strip().lower()
        confidence_values.append(confidence_map.get(conf, 0.4))
    avg_confidence = sum(confidence_values) / len(confidence_values)
    rationale_parts.append(
        f"avg_evidence_confidence={avg_confidence:.2f}"
    )

    # Factor 4: Quality score average (25% weight)
    quality_scores = [
        item.get("quality_score") or 0.0 for item in evidence_items
    ]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    rationale_parts.append(f"avg_quality_score={avg_quality:.2f}")

    # Combine weighted factors
    score = (
        count_factor * 0.30
        + platform_factor * 0.20
        + avg_confidence * 0.25
        + avg_quality * 0.25
    )

    # Check for contradictions and penalise
    contradiction_text, contradicting_ids = _detect_contradictions(evidence_items)
    if contradiction_text:
        penalty = 0.10
        score = max(score - penalty, 0.0)
        rationale_parts.append(f"contradiction_penalty=-{penalty:.2f}")

    score = round(min(max(score, 0.0), 1.0), 4)
    rationale = "; ".join(rationale_parts) + f" => final={score:.4f}"

    return score, rationale


# ─── Contradiction Detection ─────────────────────────────────────────────

def _detect_contradictions(evidence_items: list[dict]) -> tuple[str | None, list[int]]:
    """Detect contradictory evidence using simple sentiment heuristics.

    Returns (explanation, [contradicting_item_ids]) or (None, []).
    """
    positive_items: list[int] = []
    negative_items: list[int] = []

    for item in evidence_items:
        text = (item.get("text_excerpt") or "").lower()
        item_id = item.get("id")
        if item_id is None:
            continue

        pos_count = sum(1 for word in _POSITIVE_WORDS if word in text)
        neg_count = sum(1 for word in _NEGATIVE_WORDS if word in text)

        if pos_count > neg_count:
            positive_items.append(item_id)
        elif neg_count > pos_count:
            negative_items.append(item_id)

    if positive_items and negative_items:
        explanation = (
            f"Evidence contains contradictory signals: "
            f"{len(positive_items)} item(s) with positive sentiment vs "
            f"{len(negative_items)} item(s) with negative sentiment. "
            f"Analyst review recommended to reconcile."
        )
        # Return the minority camp as the contradicting items
        if len(negative_items) <= len(positive_items):
            return explanation, negative_items
        else:
            return explanation, positive_items

    return None, []


# ─── Review Workflow ──────────────────────────────────────────────────────

def review_insight(
    insight_id: int,
    status: str,
    reviewer: str = "analyst",
    notes: str | None = None,
) -> dict:
    """Change insight status after review."""
    if status not in VALID_INSIGHT_STATUSES:
        return {
            "error": f"Invalid status '{status}'. "
            f"Must be one of: {sorted(VALID_INSIGHT_STATUSES)}"
        }

    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight {insight_id} not found"}

    old_status = insight.get("status")
    store.update_insight(insight_id, status=status, reviewed_by=reviewer)
    store.add_insight_audit(
        insight_id, action="review", field="status",
        old_value=old_status, new_value=status, actor=reviewer,
    )

    if notes:
        store.update_insight(insight_id, analyst_notes=notes)
        store.add_insight_audit(
            insight_id, action="review", field="analyst_notes",
            old_value=None, new_value=notes, actor=reviewer,
        )

    return store.get_insight(insight_id)


def request_revision(
    insight_id: int,
    notes: str,
    reviewer: str = "analyst",
) -> dict:
    """Set insight to needs_review with revision notes."""
    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight {insight_id} not found"}

    old_status = insight.get("status")
    store.update_insight(
        insight_id, status="needs_review", analyst_notes=notes, reviewed_by=reviewer,
    )
    store.add_insight_audit(
        insight_id, action="revision_requested", field="status",
        old_value=old_status, new_value="needs_review", actor=reviewer,
    )
    store.add_insight_audit(
        insight_id, action="revision_requested", field="analyst_notes",
        old_value=None, new_value=notes, actor=reviewer,
    )

    return store.get_insight(insight_id)


def update_analyst_notes(
    insight_id: int,
    notes: str,
    reviewer: str = "analyst",
) -> dict:
    """Update analyst_notes on an insight."""
    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight {insight_id} not found"}

    old_notes = insight.get("analyst_notes")
    store.update_insight(insight_id, analyst_notes=notes)
    store.add_insight_audit(
        insight_id, action="notes_updated", field="analyst_notes",
        old_value=old_notes, new_value=notes, actor=reviewer,
    )

    return store.get_insight(insight_id)


# ─── Regeneration ─────────────────────────────────────────────────────────

def regenerate_insight(insight_id: int, reviewer: str = "system") -> dict:
    """Delete old insight and regenerate from scratch for the same objective."""
    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight {insight_id} not found"}

    project_id = insight["project_id"]
    objective_id = insight.get("objective_id")
    if not objective_id:
        return {"error": f"Insight {insight_id} has no objective_id — cannot regenerate"}

    # Get the objective from the plan
    plan_row = store.get_latest_plan(project_id)
    if not plan_row:
        return {"error": "No research plan found for this project"}

    plan = plan_row.get("plan") or {}
    objectives = plan.get("research_objectives") or []
    objective = None
    for obj in objectives:
        if obj.get("objective_id") == objective_id:
            objective = obj
            break

    if not objective:
        return {
            "error": f"Objective {objective_id} not found in current research plan"
        }

    # Get accepted evidence for the objective
    evidence_items = store.list_library_items(
        project_id, review_status="accepted", objective_id=objective_id, limit=100000,
    )

    if len(evidence_items) < MIN_EVIDENCE_FOR_INSIGHT:
        return {
            "error": f"Insufficient accepted evidence for objective {objective_id} "
            f"({len(evidence_items)} < {MIN_EVIDENCE_FOR_INSIGHT})"
        }

    # Delete the old insight (cascades evidence mappings and audit via store)
    old_generation_id = insight.get("generation_id")
    store.delete_insight(insight_id)

    # Generate fresh
    generation_id = old_generation_id or str(uuid.uuid4())
    new_ids = _build_insight_for_objective(
        project_id, objective, evidence_items, generation_id,
    )

    if not new_ids:
        return {"error": "Regeneration produced no insights"}

    new_insight = store.get_insight(new_ids[0])
    store.add_insight_audit(
        new_ids[0], action="regenerated", field="id",
        old_value=str(insight_id), new_value=str(new_ids[0]), actor=reviewer,
    )

    return new_insight


# ─── Detail and Summary ───────────────────────────────────────────────────

def get_insight_detail(insight_id: int) -> dict:
    """Return full insight with evidence, contradictions, and audit history."""
    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight {insight_id} not found"}

    all_evidence = store.get_insight_evidence(insight_id)
    supporting = [e for e in all_evidence if e.get("role") == "supporting"]
    contradictory = [e for e in all_evidence if e.get("role") == "contradictory"]
    audit_history = store.get_insight_audit(insight_id)

    return {
        "insight": insight,
        "evidence": all_evidence,
        "supporting_evidence": supporting,
        "contradictory_evidence": contradictory,
        "audit_history": audit_history,
    }


def get_insights_summary(project_id: int) -> dict:
    """Return summary metrics for all insights in a project."""
    counts = store.get_insight_status_counts(project_id)
    all_insights = store.list_insights(project_id, limit=100000)

    # Calculate average confidence
    confidence_values = [
        ins.get("confidence_score") or 0.0 for ins in all_insights
    ]
    avg_confidence = (
        round(sum(confidence_values) / len(confidence_values), 4)
        if confidence_values else 0.0
    )

    # Count total evidence mapped
    total_evidence_mapped = 0
    objectives_with_insights: set[str] = set()
    for ins in all_insights:
        total_evidence_mapped += ins.get("evidence_count") or 0
        oid = ins.get("objective_id")
        if oid:
            objectives_with_insights.add(oid)

    return {
        "total_insights": counts.get("total", 0),
        "by_status": counts.get("by_status", {}),
        "by_type": counts.get("by_type", {}),
        "avg_confidence": avg_confidence,
        "total_evidence_mapped": total_evidence_mapped,
        "objectives_covered": len(objectives_with_insights),
    }


# ─── Quality Validation ──────────────────────────────────────────────────

def validate_insight_quality(insight_id: int) -> dict:
    """Validate a specific insight against quality criteria.

    Returns {"valid": True, "warnings": []} or
            {"valid": False, "issues": [...], "warnings": [...]}.
    """
    insight = store.get_insight(insight_id)
    if not insight:
        return {"valid": False, "issues": [f"Insight {insight_id} not found"], "warnings": []}

    issues: list[str] = []
    warnings: list[str] = []

    # Required fields
    for field in ("title", "executive_summary", "observation"):
        if not insight.get(field):
            issues.append(f"Missing required field: {field}")

    # Evidence count
    evidence = store.get_insight_evidence(insight_id)
    if len(evidence) < MIN_EVIDENCE_FOR_INSIGHT:
        issues.append(
            f"Insufficient evidence: {len(evidence)} mapped "
            f"(minimum {MIN_EVIDENCE_FOR_INSIGHT})"
        )

    # Platform diversity
    platforms = {e.get("platform") for e in evidence if e.get("platform")}
    if len(platforms) <= 1:
        warnings.append(
            "Single-platform evidence — insight may lack cross-platform validation"
        )

    # Duplicate evidence check
    item_ids = [e.get("library_item_id") for e in evidence if e.get("library_item_id")]
    if len(item_ids) != len(set(item_ids)):
        issues.append("Duplicate evidence items mapped to this insight")

    # Confidence reasonableness
    confidence = insight.get("confidence_score") or 0.0
    if confidence > 0.9 and len(evidence) < 3:
        warnings.append(
            f"High confidence ({confidence:.2f}) with few evidence items "
            f"({len(evidence)}) — may be overstated"
        )
    if confidence < 0.2 and len(evidence) >= 5:
        warnings.append(
            f"Low confidence ({confidence:.2f}) despite substantial evidence "
            f"({len(evidence)} items) — review scoring"
        )

    if issues:
        return {"valid": False, "issues": issues, "warnings": warnings}
    return {"valid": True, "warnings": warnings}


# ─── Evidence Retrieval ───────────────────────────────────────────────────

def get_supporting_evidence(insight_id: int) -> list[dict]:
    """Return evidence items mapped to this insight with role='supporting'."""
    all_evidence = store.get_insight_evidence(insight_id)
    return [e for e in all_evidence if e.get("role") == "supporting"]

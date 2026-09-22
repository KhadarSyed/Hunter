"""Evidence Library Service — ingests, deduplicates, scores, and manages
evidence from completed execution runs.

The Evidence Library is the single source of truth for all downstream
insights. It does NOT generate insights.

Architecture:
- The Research Executor stores raw evidence in `intel_evidence` (via
  `intelligence_store.save_evidence`).
- The Evidence Library adds a metadata layer (`intel_library_items`) that
  references those records by `evidence_id`. Raw evidence is never copied
  or duplicated here — only referenced and annotated.
"""
from __future__ import annotations

import logging
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Optional

from . import intelligence_store as store

logger = logging.getLogger(__name__)

VALID_REVIEW_STATUSES = {"accepted", "rejected", "needs_review", "unreviewed", "superseded"}

NEAR_DUPLICATE_TEXT_THRESHOLD = 0.85
SAME_SOURCE_HEADLINE_THRESHOLD = 0.80

QUALITY_WEIGHTS = {
    "source_quality": 0.20,
    "completeness": 0.15,
    "relevance": 0.20,
    "recency": 0.10,
    "confidence_factor": 0.15,
    "engagement": 0.10,
    "duplicate_risk": 0.10,
}

CONFIDENCE_FACTOR_MAP = {"high": 1.0, "medium": 0.7, "low": 0.4}

_COMPLETENESS_FIELDS = ["text_excerpt", "source", "platform", "date", "url", "metrics", "rationale", "confidence"]

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
]


# ─── Evidence Ingestion ─────────────────────────────────────────────────────

def ingest_evidence(project_id: int, run_id: int) -> dict:
    """Pull evidence from a completed execution run into the library.

    Idempotent: evidence already ingested (by evidence_id) is skipped.
    Runs deduplication and quality scoring on newly ingested items only.
    """
    evidence_records = store.get_evidence(run_id)
    evidence_by_id = {ev["id"]: ev for ev in evidence_records}

    ingested = 0
    skipped = 0
    new_item_ids: list[int] = []

    for ev in evidence_records:
        existing = store.get_library_item_by_evidence_id(ev["id"])
        if existing:
            skipped += 1
            continue

        item_id = store.create_library_item(
            project_id, ev["id"], ev.get("objective_id"), ev.get("unit_id"),
        )
        new_item_ids.append(item_id)
        ingested += 1

    duplicates_found = 0
    if new_item_ids:
        duplicates_found = _detect_duplicates(project_id, new_item_ids)

        for item_id in new_item_ids:
            library_item = store.get_library_item(item_id)
            if not library_item:
                continue
            evidence_record = evidence_by_id.get(library_item["evidence_id"], {})
            score, components = _calculate_quality_score(evidence_record, library_item)
            store.update_library_item(item_id, quality_score=score, quality_components=components)

    logger.info(
        "[evidence_library] project=%s run=%s ingested=%s skipped=%s duplicates=%s total=%s",
        project_id, run_id, ingested, skipped, duplicates_found, len(evidence_records),
    )

    return {
        "ingested": ingested,
        "skipped": skipped,
        "duplicates_found": duplicates_found,
        "total": len(evidence_records),
    }


# ─── Deduplication ──────────────────────────────────────────────────────────

def _extract_url(record: dict) -> Optional[str]:
    """Best-effort URL lookup. `url` is not a first-class evidence column
    today, so fall back to a `url` key inside the metrics blob if present."""
    url = record.get("url")
    if not url:
        metrics = record.get("metrics") or {}
        if isinstance(metrics, dict):
            url = metrics.get("url")
    if not url:
        return None
    return str(url).strip().lower() or None


def _extract_author(record: dict) -> Optional[str]:
    author = record.get("author")
    if not author:
        metrics = record.get("metrics") or {}
        if isinstance(metrics, dict):
            author = metrics.get("author")
    return author or None


def _detect_duplicates(project_id: int, new_item_ids: list[int]) -> int:
    """Compare each newly ingested item against every other library item for
    the project. Duplicates are linked (never deleted or rejected).

    Returns the count of new items found to duplicate something else.
    """
    all_items = store.list_library_items(project_id, limit=100000, sort_by="created_at", sort_dir="asc")
    duplicates_found = 0

    for new_id in new_item_ids:
        new_item = store.get_library_item(new_id)
        if not new_item:
            continue

        new_url = _extract_url(new_item)
        new_text = (new_item.get("text_excerpt") or "").strip().lower()
        new_source = (new_item.get("source") or "").strip().lower()

        found_match = False

        for other in all_items:
            if other["id"] == new_id:
                continue

            other_url = _extract_url(other)
            other_text = (other.get("text_excerpt") or "").strip().lower()
            other_source = (other.get("source") or "").strip().lower()

            is_dup = False
            if new_url and other_url and new_url == other_url:
                is_dup = True
            elif new_text and other_text:
                ratio = SequenceMatcher(None, new_text, other_text).ratio()
                if ratio >= NEAR_DUPLICATE_TEXT_THRESHOLD:
                    is_dup = True
                elif (
                    new_source and other_source and new_source == other_source
                    and ratio >= SAME_SOURCE_HEADLINE_THRESHOLD
                ):
                    is_dup = True

            if is_dup:
                _link_duplicates(new_id, other["id"])
                found_match = True
                # Refresh so subsequent comparisons see the updated group/canonical.
                new_item = store.get_library_item(new_id) or new_item
                new_url = _extract_url(new_item)
                new_text = (new_item.get("text_excerpt") or "").strip().lower()
                new_source = (new_item.get("source") or "").strip().lower()

        if found_match:
            duplicates_found += 1

    return duplicates_found


def _link_duplicates(item_a_id: int, item_b_id: int) -> None:
    """Assign both items to the same duplicate_group and pick a canonical.

    `item_b` is treated as the pre-existing reference: on a quality-score
    tie, the existing item wins canonical status, per spec.
    """
    item_a = store.get_library_item(item_a_id)
    item_b = store.get_library_item(item_b_id)
    if not item_a or not item_b:
        return

    group = item_a.get("duplicate_group") or item_b.get("duplicate_group") or str(uuid.uuid4())

    existing_canonical = item_a.get("canonical_id") or item_b.get("canonical_id")
    if existing_canonical:
        canonical_id = existing_canonical
    else:
        score_a = item_a.get("quality_score") or 0.0
        score_b = item_b.get("quality_score") or 0.0
        canonical_id = item_b["id"] if score_b >= score_a else item_a["id"]

    for item in (item_a, item_b):
        old_group = item.get("duplicate_group")
        old_canonical = item.get("canonical_id")
        if old_group == group and old_canonical == canonical_id:
            continue
        store.update_library_item(item["id"], duplicate_group=group, canonical_id=canonical_id)
        store.add_library_audit(
            item["id"], action="duplicate_detected", field="duplicate_group",
            old_value=old_group, new_value=group, actor="system",
        )


# ─── Quality Scoring ────────────────────────────────────────────────────────

def _is_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _has_parseable_date(date_value: Any) -> bool:
    if not date_value:
        return False
    text = str(date_value).strip()
    if not text:
        return False

    for fmt in _DATE_FORMATS:
        try:
            time.strptime(text, fmt)
            return True
        except ValueError:
            continue

    # Tolerate ISO timestamps with fractional seconds / timezone suffixes.
    trimmed = text.split(".")[0]
    for suffix in ("Z", "+00:00"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
    try:
        time.strptime(trimmed, "%Y-%m-%dT%H:%M:%S")
        return True
    except ValueError:
        return False


def _calculate_quality_score(evidence_record: dict, library_item: dict) -> tuple[float, dict]:
    """Compute a transparent 0.0-1.0 quality score from independently
    scored components. Returns (overall_score, components_dict)."""
    components: dict[str, float] = {}

    url = _extract_url(evidence_record) or _extract_url(library_item)
    author = _extract_author(evidence_record) or _extract_author(library_item)
    source = (evidence_record.get("source") or "").strip()

    # source_quality
    source_quality = 0.8 if source else 0.3
    if url:
        source_quality += 0.1
    if author:
        source_quality += 0.1
    components["source_quality"] = round(min(source_quality, 1.0), 3)

    # completeness
    populated = 0
    for field in _COMPLETENESS_FIELDS:
        if field == "url":
            value: Any = url
        else:
            value = evidence_record.get(field)
        if _is_populated(value):
            populated += 1
    components["completeness"] = round(populated / len(_COMPLETENESS_FIELDS), 3)

    # relevance — placeholder until objectives are analyzed
    components["relevance"] = 0.7

    # recency
    components["recency"] = 0.8 if _has_parseable_date(evidence_record.get("date")) else 0.4

    # confidence_factor
    confidence = (evidence_record.get("confidence") or "").strip().lower()
    components["confidence_factor"] = CONFIDENCE_FACTOR_MAP.get(confidence, 0.4)

    # engagement
    metrics = evidence_record.get("metrics") or {}
    has_positive_metric = False
    if isinstance(metrics, dict):
        for value in metrics.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                has_positive_metric = True
                break
    components["engagement"] = 0.8 if has_positive_metric else 0.3

    # duplicate_risk
    duplicate_group = library_item.get("duplicate_group")
    canonical_id = library_item.get("canonical_id")
    item_id = library_item.get("id")
    if not duplicate_group:
        duplicate_risk = 1.0
    elif canonical_id == item_id:
        duplicate_risk = 0.8
    else:
        duplicate_risk = 0.4
    components["duplicate_risk"] = duplicate_risk

    overall = sum(components[key] * weight for key, weight in QUALITY_WEIGHTS.items())
    overall = round(min(max(overall, 0.0), 1.0), 4)

    return overall, components


# ─── Review Workflow ────────────────────────────────────────────────────────

def review_evidence(item_id: int, status: str, reviewer: str = "analyst", note: str | None = None) -> dict:
    if status not in VALID_REVIEW_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {sorted(VALID_REVIEW_STATUSES)}"}

    item = store.get_library_item(item_id)
    if not item:
        return {"error": f"Library item {item_id} not found"}

    old_status = item.get("review_status")
    store.update_library_item(item_id, review_status=status, reviewed_by=reviewer)
    store.add_library_audit(
        item_id, action="review", field="review_status",
        old_value=old_status, new_value=status, actor=reviewer,
    )

    if note:
        add_annotation(item_id, note, author=reviewer)

    return store.get_library_item(item_id)


def add_annotation(item_id: int, note: str, author: str = "analyst") -> int:
    annotation_id = store.add_library_annotation(item_id, note, author=author)
    store.add_library_audit(
        item_id, action="annotation", field="note",
        old_value=None, new_value=note, actor=author,
    )
    return annotation_id


def update_classification(item_id: int, *, objective_id: str | None = None, unit_id: str | None = None,
                           confidence: str | None = None, reviewer: str = "analyst") -> dict:
    """Reclassify a library item's objective/unit assignment, and/or override
    the evidence's confidence level (high/medium/low)."""
    item = store.get_library_item(item_id)
    if not item:
        return {"success": False, "error": f"Library item {item_id} not found"}

    updates: dict[str, Any] = {}
    changes: list[tuple[str, Any, Any]] = []

    if objective_id is not None and objective_id != item.get("objective_id"):
        updates["objective_id"] = objective_id
        changes.append(("objective_id", item.get("objective_id"), objective_id))
    if unit_id is not None and unit_id != item.get("unit_id"):
        updates["unit_id"] = unit_id
        changes.append(("unit_id", item.get("unit_id"), unit_id))
    if confidence is not None and confidence != item.get("confidence"):
        updates["confidence"] = confidence
        changes.append(("confidence", item.get("confidence"), confidence))

    if not updates:
        return {"success": True, "changed": False}

    store.update_library_item(item_id, **updates)
    for field, old_value, new_value in changes:
        store.add_library_audit(
            item_id, action="classification_update", field=field,
            old_value=old_value, new_value=new_value, actor=reviewer,
        )

    return {"success": True, "changed": True, "fields": [c[0] for c in changes]}


def mark_representative(item_id: int, is_representative: bool = True, reviewer: str = "analyst") -> dict:
    item = store.get_library_item(item_id)
    if not item:
        return {"success": False, "error": f"Library item {item_id} not found"}

    old_value = item.get("is_representative")
    store.update_library_item(item_id, is_representative=is_representative)
    store.add_library_audit(
        item_id, action="mark_representative", field="is_representative",
        old_value=old_value, new_value=is_representative, actor=reviewer,
    )
    return {"success": True}


def mark_high_value(item_id: int, is_high_value: bool = True, reviewer: str = "analyst") -> dict:
    item = store.get_library_item(item_id)
    if not item:
        return {"success": False, "error": f"Library item {item_id} not found"}

    old_value = item.get("is_high_value")
    store.update_library_item(item_id, is_high_value=is_high_value)
    store.add_library_audit(
        item_id, action="mark_high_value", field="is_high_value",
        old_value=old_value, new_value=is_high_value, actor=reviewer,
    )
    return {"success": True}


def restore_rejected(item_id: int, reviewer: str = "analyst") -> dict:
    item = store.get_library_item(item_id)
    if not item:
        return {"error": f"Library item {item_id} not found"}
    if item.get("review_status") != "rejected":
        return {"error": f"Item {item_id} is not rejected (current status: {item.get('review_status')})"}

    store.update_library_item(item_id, review_status="needs_review", reviewed_by=reviewer)
    store.add_library_audit(
        item_id, action="restore", field="review_status",
        old_value="rejected", new_value="needs_review", actor=reviewer,
    )
    return store.get_library_item(item_id)


def bulk_review(item_ids: list[int], status: str, reviewer: str = "analyst") -> dict:
    if status not in VALID_REVIEW_STATUSES:
        return {"error": f"Invalid status '{status}'. Must be one of: {sorted(VALID_REVIEW_STATUSES)}"}

    updated = store.bulk_update_library_items(item_ids, review_status=status, reviewed_by=reviewer)
    for item_id in item_ids:
        store.add_library_audit(
            item_id, action="bulk_review", field="review_status",
            old_value=None, new_value=status, actor=reviewer,
        )
    return {"updated": updated}


# ─── Coverage Validation ────────────────────────────────────────────────────

def get_coverage_report(project_id: int) -> dict:
    plan_row = store.get_latest_plan(project_id)
    if not plan_row or plan_row.get("approval_status") != "approved":
        return {"error": "No approved research plan for this project"}

    plan = plan_row.get("plan") or {}
    objectives = plan.get("research_objectives") or []
    coverage_rows = store.get_objective_coverage(project_id)
    coverage_by_objective = {r["objective_id"]: r for r in coverage_rows}

    objective_reports = []
    covered = 0
    partial = 0
    insufficient = 0
    blocking_gaps: list[str] = []

    for obj in objectives:
        oid = obj.get("objective_id", "")
        priority = obj.get("priority", "medium")
        obj_platforms = [
            (p.get("name") if isinstance(p, dict) else p)
            for p in obj.get("platforms", [])
        ]
        obj_platforms = [p for p in obj_platforms if p]

        stats = coverage_by_objective.get(oid, {
            "total": 0, "accepted": 0, "rejected": 0, "unreviewed": 0,
        })
        accepted = stats.get("accepted", 0)

        if accepted >= 5:
            coverage_status = "sufficient"
            covered += 1
        elif accepted >= 1:
            coverage_status = "partial"
            partial += 1
        else:
            coverage_status = "insufficient"
            insufficient += 1

        # The store's aggregate view doesn't break out platforms/confidence,
        # so pull the objective's items to derive those directly.
        items = store.list_library_items(project_id, objective_id=oid, limit=100000) if oid else []
        covered_platforms = {it.get("platform") for it in items if it.get("platform")}
        confidence_counts = {"high": 0, "medium": 0, "low": 0}
        for it in items:
            conf = (it.get("confidence") or "").strip().lower()
            if conf in confidence_counts:
                confidence_counts[conf] += 1
        platform_gaps = [p for p in obj_platforms if p not in covered_platforms]

        is_blocking = accepted == 0 and priority == "high"
        if is_blocking:
            blocking_gaps.append(oid)

        objective_reports.append({
            "objective_id": oid,
            "objective": obj.get("objective") or obj.get("title") or obj.get("question") or oid,
            "priority": priority,
            "total_evidence": stats.get("total", 0),
            "accepted_evidence": accepted,
            "rejected_evidence": stats.get("rejected", 0),
            "unreviewed_evidence": stats.get("unreviewed", 0),
            "coverage_status": coverage_status,
            "platform_gaps": platform_gaps,
            "confidence_distribution": confidence_counts,
            "is_blocking_gap": is_blocking,
        })

    return {
        "objectives": objective_reports,
        "summary": {
            "total_objectives": len(objectives),
            "covered": covered,
            "partial": partial,
            "insufficient": insufficient,
            "blocking_gaps": len(blocking_gaps),
        },
    }


# ─── Search and Filtering ───────────────────────────────────────────────────

def search_evidence(
    project_id: int,
    *,
    query: str | None = None,
    review_status: str | None = None,
    objective_id: str | None = None,
    unit_id: str | None = None,
    method: str | None = None,
    platform: str | None = None,
    confidence: str | None = None,
    is_representative: bool | None = None,
    is_high_value: bool | None = None,
    sort_by: str = "quality_score",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    return store.list_library_items(
        project_id,
        search=query,
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


def get_summary_metrics(project_id: int) -> dict:
    status_counts = store.get_library_status_counts(project_id)
    by_status = status_counts.get("by_status", {})
    coverage_rows = store.get_objective_coverage(project_id)

    return {
        "total_items": sum(by_status.values()),
        "by_status": {
            "unreviewed": by_status.get("unreviewed", 0),
            "accepted": by_status.get("accepted", 0),
            "rejected": by_status.get("rejected", 0),
            "needs_review": by_status.get("needs_review", 0),
            "superseded": by_status.get("superseded", 0),
        },
        "representative": status_counts.get("representative", 0),
        "high_value": status_counts.get("high_value", 0),
        "duplicate_groups": status_counts.get("duplicate_groups", 0),
        "objective_coverage": {
            row["objective_id"]: {
                "total_evidence": row.get("total", 0),
                "accepted_evidence": row.get("accepted", 0),
            }
            for row in coverage_rows
        },
    }


# ─── Evidence Detail ────────────────────────────────────────────────────────

def get_evidence_detail(item_id: int) -> dict:
    item = store.get_library_item(item_id)
    if not item:
        return {"error": f"Library item {item_id} not found"}

    annotations = store.get_library_annotations(item_id)
    audit_history = store.get_library_audit(item_id)

    duplicate_group_members = []
    if item.get("duplicate_group"):
        duplicate_group_members = [
            member for member in store.get_duplicate_group_members(item["duplicate_group"])
            if member["id"] != item_id
        ]

    return {
        "item": item,
        "annotations": annotations,
        "audit_history": audit_history,
        "duplicate_group_members": duplicate_group_members,
    }

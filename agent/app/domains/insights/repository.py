"""Insights repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

# ─── Insights ──────────────────────────────────────────────────────────────

_INSIGHT_SORT_COLUMNS = {
    "created_at", "updated_at", "title", "insight_type", "status",
    "confidence_score", "evidence_count", "objective_id", "id",
}


_INSIGHT_UPDATABLE_FIELDS = {
    "objective_id", "insight_type", "title", "executive_summary", "observation",
    "interpretation", "business_impact", "confidence_score", "confidence_rationale",
    "evidence_count", "platforms_represented", "date_coverage",
    "contradictory_evidence", "limitations", "recommended_visualisation",
    "analyst_notes", "status", "reviewed_by", "reviewed_at", "generation_id",
}


def create_insight(
    project_id: int,
    objective_id: str,
    insight_type: str,
    title: str,
    *,
    executive_summary: str | None = None,
    observation: str | None = None,
    interpretation: str | None = None,
    business_impact: str | None = None,
    confidence_score: float = 0.5,
    confidence_rationale: str | None = None,
    contradictory_evidence: str | None = None,
    limitations: str | None = None,
    recommended_visualisation: str | None = None,
    platforms_represented: list[str] | None = None,
    date_coverage: str | None = None,
    generation_id: str | None = None,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insights "
        "(project_id, objective_id, insight_type, title, executive_summary, observation, "
        "interpretation, business_impact, confidence_score, confidence_rationale, "
        "contradictory_evidence, limitations, recommended_visualisation, "
        "platforms_represented, date_coverage, generation_id, "
        "status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
        (
            project_id, objective_id, insight_type, title,
            executive_summary, observation, interpretation, business_impact,
            confidence_score, confidence_rationale,
            contradictory_evidence, limitations, recommended_visualisation,
            json.dumps(platforms_represented) if platforms_represented is not None else None,
            date_coverage, generation_id,
            now, now,
        ),
    )
    insight_id = cur.lastrowid
    conn.commit()
    conn.close()
    return insight_id


def _parse_insight_row(d: dict) -> dict:
    if d.get("platforms_represented"):
        try:
            d["platforms_represented"] = json.loads(d["platforms_represented"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_insight(insight_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_insights WHERE id = ?", (insight_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_insight_row(dict(row))


def list_insights(
    project_id: int,
    *,
    objective_id: str | None = None,
    insight_type: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    conn = _conn()
    where = ["project_id = ?"]
    vals: list[Any] = [project_id]

    if objective_id is not None:
        where.append("objective_id = ?")
        vals.append(objective_id)
    if insight_type is not None:
        where.append("insight_type = ?")
        vals.append(insight_type)
    if status is not None:
        where.append("status = ?")
        vals.append(status)

    sort_col = sort_by if sort_by in _INSIGHT_SORT_COLUMNS else "created_at"
    sort_direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    query = (
        f"SELECT * FROM intel_insights WHERE {' AND '.join(where)} "
        f"ORDER BY {sort_col} {sort_direction} LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])

    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [_parse_insight_row(dict(r)) for r in rows]


def update_insight(insight_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    for key, value in kwargs.items():
        if key not in _INSIGHT_UPDATABLE_FIELDS:
            continue
        if key == "platforms_represented" and isinstance(value, list):
            parts.append("platforms_represented = ?")
            vals.append(json.dumps(value))
        else:
            parts.append(f"{key} = ?")
            vals.append(value)

    # Auto-set reviewed_at when reviewed_by is provided
    if "reviewed_by" in kwargs and "reviewed_at" not in kwargs:
        parts.append("reviewed_at = ?")
        vals.append(time.time())

    vals.append(insight_id)
    cur = conn.execute(f"UPDATE intel_insights SET {', '.join(parts)} WHERE id = ?", vals)
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_insight(insight_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_insight_evidence WHERE insight_id = ?", (insight_id,))
    conn.execute("DELETE FROM intel_insight_audit WHERE insight_id = ?", (insight_id,))
    cur = conn.execute("DELETE FROM intel_insights WHERE id = ?", (insight_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_insight_evidence(insight_id: int, library_item_id: int, role: str = "supporting") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insight_evidence (insight_id, library_item_id, role, created_at) "
        "VALUES (?, ?, ?, ?)",
        (insight_id, library_item_id, role, now),
    )
    mapping_id = cur.lastrowid
    conn.commit()
    conn.close()
    return mapping_id


def get_insight_evidence(insight_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT ie.id AS mapping_id, ie.insight_id AS insight_id, "
        "ie.library_item_id AS library_item_id, ie.role AS role, "
        "ie.created_at AS mapping_created_at, "
        "li.id AS li_id, li.project_id AS project_id, li.evidence_id AS evidence_id, "
        "li.review_status AS review_status, li.quality_score AS quality_score, "
        "li.quality_components_json AS quality_components_json, li.relevance_score AS relevance_score, "
        "li.is_representative AS is_representative, li.is_high_value AS is_high_value, "
        "li.canonical_id AS canonical_id, li.duplicate_group AS duplicate_group, "
        "li.objective_id AS objective_id, li.unit_id AS unit_id, li.reviewed_by AS reviewed_by, "
        "li.reviewed_at AS reviewed_at, li.created_at AS created_at, li.updated_at AS updated_at, "
        "ev.run_id AS run_id, ev.evidence_type AS evidence_type, ev.platform AS platform, "
        "ev.source AS source, ev.date AS date, ev.text_excerpt AS text_excerpt, "
        "ev.metrics_json AS metrics_json, ev.confidence AS confidence, ev.method AS method, "
        "ev.rationale AS rationale, ev.dataset AS dataset, ev.created_at AS evidence_created_at "
        "FROM intel_insight_evidence ie "
        "JOIN intel_library_items li ON ie.library_item_id = li.id "
        "JOIN intel_evidence ev ON li.evidence_id = ev.id "
        "WHERE ie.insight_id = ? ORDER BY ie.id",
        (insight_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("quality_components_json"):
            d["quality_components"] = json.loads(d["quality_components_json"])
        if d.get("metrics_json"):
            d["metrics"] = json.loads(d["metrics_json"])
        result.append(d)
    return result


def remove_insight_evidence(insight_id: int, library_item_id: int) -> bool:
    conn = _conn()
    cur = conn.execute(
        "DELETE FROM intel_insight_evidence WHERE insight_id = ? AND library_item_id = ?",
        (insight_id, library_item_id),
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_insight_audit(
    insight_id: int,
    action: str,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    actor: str = "analyst",
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insight_audit (insight_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            insight_id, action, field,
            str(old_value) if old_value is not None else None,
            str(new_value) if new_value is not None else None,
            actor, now,
        ),
    )
    audit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def get_insight_audit(insight_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_insight_audit WHERE insight_id = ? ORDER BY created_at DESC",
        (insight_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_insights(project_id: int, *, status: str | None = None) -> int:
    conn = _conn()
    if status is not None:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ? AND status = ?",
            (project_id, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0


def get_insight_status_counts(project_id: int) -> dict:
    conn = _conn()
    status_rows = conn.execute(
        "SELECT status, COUNT(*) as c FROM intel_insights WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()
    type_rows = conn.execute(
        "SELECT insight_type, COUNT(*) as c FROM intel_insights WHERE project_id = ? GROUP BY insight_type",
        (project_id,),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    return {
        "by_status": {r["status"]: r["c"] for r in status_rows},
        "by_type": {r["insight_type"]: r["c"] for r in type_rows},
        "total": total_row["c"] if total_row else 0,
    }


def add_node_insight(node_id: int, insight_id: int, role: str = "supporting") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_story_node_insights (node_id, insight_id, role, created_at) "
        "VALUES (?, ?, ?, ?)",
        (node_id, insight_id, role, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_node_insights(node_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT sni.id AS mapping_id, sni.node_id, sni.insight_id, sni.role, "
        "sni.created_at AS mapping_created_at, "
        "ins.project_id, ins.objective_id, ins.insight_type, ins.title AS insight_title, "
        "ins.executive_summary AS insight_summary, ins.confidence_score AS insight_confidence, "
        "ins.evidence_count, ins.status AS insight_status "
        "FROM intel_story_node_insights sni "
        "JOIN intel_insights ins ON sni.insight_id = ins.id "
        "WHERE sni.node_id = ? ORDER BY sni.id",
        (node_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_node_insight(node_id: int, insight_id: int) -> bool:
    conn = _conn()
    cur = conn.execute(
        "DELETE FROM intel_story_node_insights WHERE node_id = ? AND insight_id = ?",
        (node_id, insight_id),
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

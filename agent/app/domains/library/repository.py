"""Evidence Library repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

# ─── Evidence Library ───────────────────────────────────────────────────────

_LIBRARY_JOIN_SELECT = (
    "SELECT li.id AS id, li.project_id AS project_id, li.evidence_id AS evidence_id, "
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
    "FROM intel_library_items li JOIN intel_evidence ev ON li.evidence_id = ev.id"
)


_LIBRARY_SORT_COLUMNS = {
    "created_at", "updated_at", "quality_score", "relevance_score", "review_status",
    "reviewed_at", "date", "evidence_type", "platform", "source", "method", "confidence",
    "objective_id", "unit_id", "id",
}


def _row_to_library_item(d: dict) -> dict:
    if d.get("quality_components_json"):
        d["quality_components"] = json.loads(d["quality_components_json"])
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    return d


def create_library_item(project_id: int, evidence_id: int, objective_id: str | None = None,
                         unit_id: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_items (project_id, evidence_id, review_status, objective_id, unit_id, "
        "created_at, updated_at) VALUES (?, ?, 'unreviewed', ?, ?, ?, ?)",
        (project_id, evidence_id, objective_id, unit_id, now, now),
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def get_library_item(item_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(f"{_LIBRARY_JOIN_SELECT} WHERE li.id = ?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_library_item(dict(row))


def get_library_item_by_evidence_id(evidence_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(f"{_LIBRARY_JOIN_SELECT} WHERE li.evidence_id = ?", (evidence_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_library_item(dict(row))


def list_library_items(project_id: int, *, review_status: str | None = None, objective_id: str | None = None,
                        unit_id: str | None = None, method: str | None = None, platform: str | None = None,
                        confidence: str | None = None, is_representative: bool | None = None,
                        is_high_value: bool | None = None, search: str | None = None,
                        sort_by: str = "created_at", sort_dir: str = "desc",
                        limit: int = 200, offset: int = 0) -> list[dict]:
    conn = _conn()
    where = ["li.project_id = ?"]
    vals: list[Any] = [project_id]

    if review_status is not None:
        where.append("li.review_status = ?")
        vals.append(review_status)
    if objective_id is not None:
        where.append("li.objective_id = ?")
        vals.append(objective_id)
    if unit_id is not None:
        where.append("li.unit_id = ?")
        vals.append(unit_id)
    if method is not None:
        where.append("ev.method = ?")
        vals.append(method)
    if platform is not None:
        where.append("ev.platform = ?")
        vals.append(platform)
    if confidence is not None:
        where.append("ev.confidence = ?")
        vals.append(confidence)
    if is_representative is not None:
        where.append("li.is_representative = ?")
        vals.append(1 if is_representative else 0)
    if is_high_value is not None:
        where.append("li.is_high_value = ?")
        vals.append(1 if is_high_value else 0)
    if search:
        where.append(
            "(ev.text_excerpt LIKE ? OR ev.source LIKE ? OR ev.platform LIKE ? OR ev.rationale LIKE ?)"
        )
        like = f"%{search}%"
        vals.extend([like, like, like, like])

    sort_col = sort_by if sort_by in _LIBRARY_SORT_COLUMNS else "created_at"
    sort_direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    query = (
        f"{_LIBRARY_JOIN_SELECT} WHERE {' AND '.join(where)} "
        f"ORDER BY {sort_col} {sort_direction} LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])

    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [_row_to_library_item(dict(r)) for r in rows]


def count_library_items(project_id: int, *, review_status: str | None = None) -> int:
    conn = _conn()
    if review_status is not None:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND review_status = ?",
            (project_id, review_status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0


def update_library_item(item_id: int, *, review_status: str | None = None, quality_score: float | None = None,
                         quality_components: dict | None = None, relevance_score: float | None = None,
                         is_representative: bool | None = None, is_high_value: bool | None = None,
                         canonical_id: int | None = None, duplicate_group: str | None = None,
                         objective_id: str | None = None, unit_id: str | None = None,
                         reviewed_by: str | None = None, confidence: str | None = None) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    if review_status is not None:
        parts.append("review_status = ?")
        vals.append(review_status)
    if quality_score is not None:
        parts.append("quality_score = ?")
        vals.append(quality_score)
    if quality_components is not None:
        parts.append("quality_components_json = ?")
        vals.append(json.dumps(quality_components))
    if relevance_score is not None:
        parts.append("relevance_score = ?")
        vals.append(relevance_score)
    if is_representative is not None:
        parts.append("is_representative = ?")
        vals.append(1 if is_representative else 0)
    if is_high_value is not None:
        parts.append("is_high_value = ?")
        vals.append(1 if is_high_value else 0)
    if canonical_id is not None:
        parts.append("canonical_id = ?")
        vals.append(canonical_id)
    if duplicate_group is not None:
        parts.append("duplicate_group = ?")
        vals.append(duplicate_group)
    if objective_id is not None:
        parts.append("objective_id = ?")
        vals.append(objective_id)
    if unit_id is not None:
        parts.append("unit_id = ?")
        vals.append(unit_id)
    if reviewed_by is not None:
        parts.append("reviewed_by = ?")
        parts.append("reviewed_at = ?")
        vals.append(reviewed_by)
        vals.append(time.time())

    vals.append(item_id)
    cur = conn.execute(f"UPDATE intel_library_items SET {', '.join(parts)} WHERE id = ?", vals)
    changed = cur.rowcount > 0

    if confidence is not None:
        conn.execute(
            "UPDATE intel_evidence SET confidence = ? WHERE id = "
            "(SELECT evidence_id FROM intel_library_items WHERE id = ?)",
            (confidence, item_id),
        )

    conn.commit()
    conn.close()
    return changed


def bulk_update_library_items(item_ids: list[int], *, review_status: str | None = None,
                               reviewed_by: str | None = None) -> int:
    if not item_ids:
        return 0

    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    if review_status is not None:
        parts.append("review_status = ?")
        vals.append(review_status)
    if reviewed_by is not None:
        parts.append("reviewed_by = ?")
        parts.append("reviewed_at = ?")
        vals.append(reviewed_by)
        vals.append(time.time())

    placeholders = ", ".join("?" for _ in item_ids)
    query = f"UPDATE intel_library_items SET {', '.join(parts)} WHERE id IN ({placeholders})"
    cur = conn.execute(query, vals + list(item_ids))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def add_library_annotation(library_item_id: int, note: str, author: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_annotations (library_item_id, author, note, created_at) VALUES (?, ?, ?, ?)",
        (library_item_id, author, note, now),
    )
    ann_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ann_id


def get_library_annotations(library_item_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_library_annotations WHERE library_item_id = ? ORDER BY created_at DESC",
        (library_item_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_library_audit(library_item_id: int, action: str, field: str | None = None,
                       old_value: str | None = None, new_value: str | None = None,
                       actor: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_audit (library_item_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (library_item_id, action, field, old_value, new_value, actor, now),
    )
    audit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def get_library_audit(library_item_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_library_audit WHERE library_item_id = ? ORDER BY created_at DESC",
        (library_item_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_duplicate_groups(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT duplicate_group as group_, COUNT(*) as count, MAX(canonical_id) as canonical_id "
        "FROM intel_library_items WHERE project_id = ? AND duplicate_group IS NOT NULL "
        "GROUP BY duplicate_group",
        (project_id,),
    ).fetchall()
    conn.close()
    return [
        {"group": r["group_"], "count": r["count"], "canonical_id": r["canonical_id"]}
        for r in rows
    ]


def get_objective_coverage(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT objective_id, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN review_status = 'accepted' THEN 1 ELSE 0 END) as accepted, "
        "SUM(CASE WHEN review_status = 'rejected' THEN 1 ELSE 0 END) as rejected, "
        "SUM(CASE WHEN review_status = 'unreviewed' THEN 1 ELSE 0 END) as unreviewed "
        "FROM intel_library_items WHERE project_id = ? GROUP BY objective_id",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_library_status_counts(project_id: int) -> dict:
    conn = _conn()
    rows = conn.execute(
        "SELECT review_status, COUNT(*) as c FROM intel_library_items WHERE project_id = ? GROUP BY review_status",
        (project_id,),
    ).fetchall()
    rep = conn.execute(
        "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND is_representative = 1",
        (project_id,),
    ).fetchone()
    hv = conn.execute(
        "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND is_high_value = 1",
        (project_id,),
    ).fetchone()
    dup = conn.execute(
        "SELECT COUNT(DISTINCT duplicate_group) as c FROM intel_library_items "
        "WHERE project_id = ? AND duplicate_group IS NOT NULL",
        (project_id,),
    ).fetchone()
    conn.close()
    return {
        "by_status": {r["review_status"]: r["c"] for r in rows},
        "representative": rep["c"] if rep else 0,
        "high_value": hv["c"] if hv else 0,
        "duplicate_groups": dup["c"] if dup else 0,
    }


def get_duplicate_group_members(duplicate_group: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        f"{_LIBRARY_JOIN_SELECT} WHERE li.duplicate_group = ? ORDER BY li.id",
        (duplicate_group,),
    ).fetchall()
    conn.close()
    return [_row_to_library_item(dict(r)) for r in rows]

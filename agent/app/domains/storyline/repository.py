"""Storyline Store repository (connection helper: core/db.py)."""

from __future__ import annotations

import time
from typing import Any, Optional

from ...core.db import _conn

# ─── Storyline Store ──────────────────────────────────────────────────────

_STORYLINE_SORT_COLUMNS = {
    "created_at", "updated_at", "title", "status", "narrative_pattern", "id",
}


_STORYLINE_UPDATABLE_FIELDS = {
    "narrative_pattern", "title", "executive_summary", "total_duration_minutes",
    "node_count", "status", "generated_by", "approved_by", "approved_at",
    "generation_id",
}


_NODE_SORT_COLUMNS = {
    "order_position", "created_at", "title", "priority", "status",
    "confidence_score", "id",
}


_NODE_UPDATABLE_FIELDS = {
    "section_type", "title", "purpose", "narrative_summary", "suggested_visual",
    "priority", "estimated_duration_minutes", "confidence_score",
    "transition_text", "is_key_message", "is_locked", "order_position",
    "status", "reviewed_by", "reviewed_at",
}


def create_storyline(
    project_id: int,
    narrative_pattern: str,
    title: str,
    *,
    executive_summary: str | None = None,
    total_duration_minutes: float = 0,
    node_count: int = 0,
    generated_by: str = "system",
    generation_id: str | None = None,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_storylines "
        "(project_id, narrative_pattern, title, executive_summary, "
        "total_duration_minutes, node_count, status, generated_by, "
        "generation_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
        (
            project_id, narrative_pattern, title, executive_summary,
            total_duration_minutes, node_count, generated_by,
            generation_id, now, now,
        ),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_storyline(storyline_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_storylines WHERE id = ?", (storyline_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_storyline(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_storylines WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_storylines(project_id: int, *, status: str | None = None,
                    limit: int = 50, offset: int = 0) -> list[dict]:
    conn = _conn()
    where = ["project_id = ?"]
    vals: list[Any] = [project_id]
    if status is not None:
        where.append("status = ?")
        vals.append(status)
    query = (
        f"SELECT * FROM intel_storylines WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])
    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_storyline(storyline_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]
    for key, value in kwargs.items():
        if key not in _STORYLINE_UPDATABLE_FIELDS:
            continue
        parts.append(f"{key} = ?")
        vals.append(value)
    if "approved_by" in kwargs and "approved_at" not in kwargs:
        parts.append("approved_at = ?")
        vals.append(time.time())
    vals.append(storyline_id)
    cur = conn.execute(
        f"UPDATE intel_storylines SET {', '.join(parts)} WHERE id = ?", vals,
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_storyline(storyline_id: int) -> bool:
    conn = _conn()
    node_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM intel_story_nodes WHERE storyline_id = ?",
            (storyline_id,),
        ).fetchall()
    ]
    for nid in node_ids:
        conn.execute("DELETE FROM intel_story_node_insights WHERE node_id = ?", (nid,))
    conn.execute("DELETE FROM intel_story_nodes WHERE storyline_id = ?", (storyline_id,))
    conn.execute("DELETE FROM intel_storyline_audit WHERE storyline_id = ?", (storyline_id,))
    cur = conn.execute("DELETE FROM intel_storylines WHERE id = ?", (storyline_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def create_story_node(
    storyline_id: int,
    section_type: str,
    title: str,
    order_position: int,
    *,
    purpose: str | None = None,
    narrative_summary: str | None = None,
    suggested_visual: str = "table",
    priority: str = "medium",
    estimated_duration_minutes: float = 2.0,
    confidence_score: float = 0.5,
    transition_text: str | None = None,
    is_key_message: bool = False,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_story_nodes "
        "(storyline_id, section_type, title, order_position, purpose, "
        "narrative_summary, suggested_visual, priority, estimated_duration_minutes, "
        "confidence_score, transition_text, is_key_message, is_locked, "
        "status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft', ?, ?)",
        (
            storyline_id, section_type, title, order_position,
            purpose, narrative_summary, suggested_visual, priority,
            estimated_duration_minutes, confidence_score, transition_text,
            1 if is_key_message else 0, now, now,
        ),
    )
    node_id = cur.lastrowid
    conn.commit()
    conn.close()
    return node_id


def get_story_node(node_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_story_nodes WHERE id = ?", (node_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["is_key_message"] = bool(d.get("is_key_message"))
    d["is_locked"] = bool(d.get("is_locked"))
    return d


def list_story_nodes(storyline_id: int, *, status: str | None = None) -> list[dict]:
    conn = _conn()
    where = ["storyline_id = ?"]
    vals: list[Any] = [storyline_id]
    if status is not None:
        where.append("status = ?")
        vals.append(status)
    rows = conn.execute(
        f"SELECT * FROM intel_story_nodes WHERE {' AND '.join(where)} "
        f"ORDER BY order_position ASC",
        vals,
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["is_key_message"] = bool(d.get("is_key_message"))
        d["is_locked"] = bool(d.get("is_locked"))
        result.append(d)
    return result


def update_story_node(node_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]
    for key, value in kwargs.items():
        if key not in _NODE_UPDATABLE_FIELDS:
            continue
        if key in ("is_key_message", "is_locked"):
            parts.append(f"{key} = ?")
            vals.append(1 if value else 0)
        else:
            parts.append(f"{key} = ?")
            vals.append(value)
    if "reviewed_by" in kwargs and "reviewed_at" not in kwargs:
        parts.append("reviewed_at = ?")
        vals.append(time.time())
    vals.append(node_id)
    cur = conn.execute(
        f"UPDATE intel_story_nodes SET {', '.join(parts)} WHERE id = ?", vals,
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_story_node(node_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_story_node_insights WHERE node_id = ?", (node_id,))
    cur = conn.execute("DELETE FROM intel_story_nodes WHERE id = ?", (node_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_storyline_audit(
    storyline_id: int,
    action: str,
    *,
    node_id: int | None = None,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    actor: str = "analyst",
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_storyline_audit "
        "(storyline_id, node_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            storyline_id, node_id, action, field,
            str(old_value) if old_value is not None else None,
            str(new_value) if new_value is not None else None,
            actor, now,
        ),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_storyline_audit(storyline_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_storyline_audit WHERE storyline_id = ? ORDER BY created_at DESC",
        (storyline_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reorder_story_nodes(storyline_id: int, node_ids_in_order: list[int]) -> bool:
    conn = _conn()
    now = time.time()
    for pos, nid in enumerate(node_ids_in_order):
        conn.execute(
            "UPDATE intel_story_nodes SET order_position = ?, updated_at = ? "
            "WHERE id = ? AND storyline_id = ? AND is_locked = 0",
            (pos, now, nid, storyline_id),
        )
    conn.commit()
    conn.close()
    return True

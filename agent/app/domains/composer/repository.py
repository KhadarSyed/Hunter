"""Presentation Composer repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time

from ...core.db import _conn

# ─── Presentation Composer ─────────────────────────────────────────────────

def create_pc_presentation(project_id: int, storyline_id: int, title: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_presentations "
        "(project_id, storyline_id, title, executive_summary, narrative_pattern, "
        "total_slides, estimated_duration_minutes, status, generated_by, generation_id, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, storyline_id, title,
         kw.get("executive_summary"), kw.get("narrative_pattern"),
         kw.get("total_slides", 0), kw.get("estimated_duration_minutes", 0),
         kw.get("status", "draft"), kw.get("generated_by", "system"),
         kw.get("generation_id"), now, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pc_presentation(pres_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pc_presentations WHERE id=?", (pres_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pc_presentations(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_presentations WHERE project_id=? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_pc_presentation(project_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pc_presentations WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_pc_presentation(pres_id: int, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    for k, v in kw.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(pres_id)
    conn = _conn()
    conn.execute(
        f"UPDATE intel_pc_presentations SET {', '.join(sets)} WHERE id=?", vals,
    )
    conn.commit()
    conn.close()


def delete_pc_presentation(pres_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM intel_pc_audit WHERE presentation_id=?", (pres_id,))
    conn.execute("DELETE FROM intel_pc_slides WHERE presentation_id=?", (pres_id,))
    conn.execute("DELETE FROM intel_pc_presentations WHERE id=?", (pres_id,))
    conn.commit()
    conn.close()


def create_pc_slide(presentation_id: int, slide_number: int, slide_purpose: str,
                    title: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_slides "
        "(presentation_id, slide_number, slide_purpose, node_id, title, subtitle, "
        "narrative, business_objective, key_message, speaker_notes, "
        "recommended_visual, recommended_chart, layout_recommendation, layout_rationale, "
        "alt_layout_1, alt_layout_1_rationale, alt_layout_2, alt_layout_2_rationale, "
        "template_family_id, content_blocks_json, evidence_ids_json, insight_ids_json, "
        "historical_refs_json, confidence_json, overall_confidence, transition_to_next, "
        "status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (presentation_id, slide_number, slide_purpose,
         kw.get("node_id"), title, kw.get("subtitle"),
         kw.get("narrative"), kw.get("business_objective"), kw.get("key_message"),
         kw.get("speaker_notes"),
         kw.get("recommended_visual"), kw.get("recommended_chart"),
         kw.get("layout_recommendation"), kw.get("layout_rationale"),
         kw.get("alt_layout_1"), kw.get("alt_layout_1_rationale"),
         kw.get("alt_layout_2"), kw.get("alt_layout_2_rationale"),
         kw.get("template_family_id"),
         json.dumps(kw.get("content_blocks", [])),
         json.dumps(kw.get("evidence_ids", [])),
         json.dumps(kw.get("insight_ids", [])),
         json.dumps(kw.get("historical_refs", [])),
         json.dumps(kw.get("confidence", {})),
         kw.get("overall_confidence", 0.5),
         kw.get("transition_to_next"),
         kw.get("status", "draft"), now, now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_pc_slide(slide_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pc_slides WHERE id=?", (slide_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for jf in ("content_blocks_json", "evidence_ids_json", "insight_ids_json",
               "historical_refs_json", "confidence_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_pc_slides(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_slides WHERE presentation_id=? ORDER BY slide_number",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for jf in ("content_blocks_json", "evidence_ids_json", "insight_ids_json",
                    "historical_refs_json", "confidence_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pc_slide(slide_id: int, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    json_fields = {"content_blocks": "content_blocks_json",
                   "evidence_ids": "evidence_ids_json",
                   "insight_ids": "insight_ids_json",
                   "historical_refs": "historical_refs_json",
                   "confidence": "confidence_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(slide_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pc_slides SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_pc_slide(slide_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM intel_pc_slides WHERE id=?", (slide_id,))
    conn.commit()
    conn.close()


def reorder_pc_slides(presentation_id: int, slide_ids: list[int]) -> None:
    conn = _conn()
    now = time.time()
    for pos, sid in enumerate(slide_ids):
        conn.execute(
            "UPDATE intel_pc_slides SET slide_number=?, updated_at=? WHERE id=? AND presentation_id=?",
            (pos, now, sid, presentation_id),
        )
    conn.commit()
    conn.close()


def add_pc_audit(presentation_id: int, action: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_audit "
        "(presentation_id, slide_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (presentation_id, kw.get("slide_id"), action,
         kw.get("field"), kw.get("old_value"), kw.get("new_value"),
         kw.get("actor", "system"), now),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_pc_audit(presentation_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_audit WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_pc_slides(presentation_id: int, status: str | None = None) -> int:
    conn = _conn()
    if status:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM intel_pc_slides WHERE presentation_id=? AND status=?",
            (presentation_id, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM intel_pc_slides WHERE presentation_id=?",
            (presentation_id,),
        ).fetchone()
    conn.close()
    return row["cnt"] if row else 0

"""Analyst Orientation Briefs repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Analyst Orientation Briefs ─────────────────────────────────────────────

def save_background_brief(project_id: int, research_id: int, brief: dict) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_background_briefs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1
    cur = conn.execute(
        "INSERT INTO intel_background_briefs (project_id, research_id, version, brief_json, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?)",
        (project_id, research_id, version, json.dumps(brief), now, now),
    )
    bid = cur.lastrowid
    conn.commit()
    conn.close()
    return bid


def get_latest_brief(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_briefs WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["brief"] = json.loads(d["brief_json"])
    return d


def get_brief_by_id(brief_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_background_briefs WHERE id = ?", (brief_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["brief"] = json.loads(d["brief_json"])
    return d


def update_brief(brief_id: int, brief: dict):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET brief_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(brief), time.time(), brief_id),
    )
    conn.commit()
    conn.close()


def update_brief_section(brief_id: int, section_key: str, content: str, analyst_note: str = ""):
    conn = _conn()
    now = time.time()
    row = conn.execute("SELECT brief_json FROM intel_background_briefs WHERE id = ?", (brief_id,)).fetchone()
    if row:
        brief = json.loads(row["brief_json"])
        if section_key in brief.get("sections", {}):
            brief["sections"][section_key]["content"] = content
            brief["sections"][section_key]["edited"] = True
            conn.execute(
                "UPDATE intel_background_briefs SET brief_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(brief), now, brief_id),
            )
        conn.execute(
            "INSERT INTO intel_brief_section_edits (brief_id, section_key, edited_content, analyst_note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (brief_id, section_key, content, analyst_note, now),
        )
    conn.commit()
    conn.close()


def approve_brief(brief_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET approval_status = 'approved', approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?",
        (reviewer, time.time(), time.time(), brief_id),
    )
    conn.commit()
    conn.close()
    return True


def reject_brief(brief_id: int, notes: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET approval_status = 'revision_requested', notes = ?, updated_at = ? WHERE id = ?",
        (notes, time.time(), brief_id),
    )
    conn.commit()
    conn.close()
    return True


def update_brief_docx(brief_id: int, docx_path: str):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET docx_path = ?, docx_generated_at = ?, updated_at = ? WHERE id = ?",
        (docx_path, time.time(), time.time(), brief_id),
    )
    conn.commit()
    conn.close()


def list_brief_versions(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, version, status, approval_status, docx_path, created_at, updated_at FROM intel_background_briefs "
        "WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

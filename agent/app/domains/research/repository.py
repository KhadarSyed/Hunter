"""Background Research repository (connection helper: core/db.py).

Also contains:
- news_approval: News Item Approvals repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Background Research ─────────────────────────────────────────────────────

def save_background_research(project_id: int, research: dict, llm_output: dict | None = None) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_background_research WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_background_research (project_id, version, status, research_json, llm_output_json, created_at) "
        "VALUES (?, ?, 'draft', ?, ?, ?)",
        (project_id, version, json.dumps(research), json.dumps(llm_output) if llm_output else None, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def save_background_research_update(research_id: int, research: dict, llm_output: dict | None = None):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET research_json = ?, llm_output_json = ? WHERE id = ?",
        (json.dumps(research), json.dumps(llm_output) if llm_output else None, research_id),
    )
    conn.commit()
    conn.close()


def get_latest_research(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_research WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def get_research_by_id(research_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_research WHERE id = ?",
        (research_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def approve_research(research_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), research_id),
    )
    conn.commit()
    conn.close()
    return True


def reject_research(research_id: int, notes: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'revision_requested', notes = ? WHERE id = ?",
        (notes, research_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── News Approval ─────────────────────────────────────────────────────

# ─── News Item Approvals ────────────────────────────────────────────────────

def update_news_approval(research_id: int, item_index: int, status: str, notes: str = ""):
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT id FROM intel_news_approvals WHERE research_id = ? AND item_index = ?",
        (research_id, item_index),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE intel_news_approvals SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
            (status, notes, now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO intel_news_approvals (research_id, item_index, status, notes, updated_at) VALUES (?, ?, ?, ?, ?)",
            (research_id, item_index, status, notes, now),
        )
    conn.commit()
    conn.close()


def get_news_approvals(research_id: int) -> dict[int, dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_news_approvals WHERE research_id = ?",
        (research_id,),
    ).fetchall()
    conn.close()
    return {row["item_index"]: dict(row) for row in rows}

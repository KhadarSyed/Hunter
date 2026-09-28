"""Research Plans repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Research Plans ────────────────────────────────────────────────────────

def save_research_plan(project_id: int, plan: dict, source: str = "llm") -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_research_plans WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_research_plans (project_id, version, status, plan_json, source, created_at) "
        "VALUES (?, ?, 'draft', ?, ?, ?)",
        (project_id, version, json.dumps(plan), source, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_latest_plan(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_plans WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan_json"])
    return d


def approve_plan(plan_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE intel_research_plans SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), plan_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def reject_plan(plan_id: int, notes: str = "") -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE intel_research_plans SET approval_status = 'rejected', notes = ? WHERE id = ?",
        (notes, plan_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def update_plan_status(plan_id: int, status: str) -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_research_plans SET status = ? WHERE id = ?",
        (status, plan_id),
    )
    conn.commit()
    conn.close()
    return True

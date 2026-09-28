"""Projects repository (connection helper: core/db.py).

Also contains:
- jobs: Jobs repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Projects ────────────────────────────────────────────────────────────────

def create_project(name: str, spec: dict, project_type: str = "research") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_projects (project_name, spec_json, project_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (name, json.dumps(spec), project_type, now, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_project(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {**dict(row), "spec": json.loads(row["spec_json"])}


def list_projects(project_type: str | None = None) -> list[dict]:
    conn = _conn()
    if project_type:
        rows = conn.execute(
            "SELECT id, project_name, project_type, created_at, updated_at FROM intel_projects WHERE project_type = ? ORDER BY updated_at DESC",
            (project_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, project_name, project_type, created_at, updated_at FROM intel_projects ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_project(project_id: int, project_name: str | None = None, spec: dict | None = None) -> bool:
    """Partially update a project's name and/or spec. Both params optional; only provided fields change."""
    conn = _conn()
    conn.execute(
        "UPDATE intel_projects SET project_name = COALESCE(?, project_name), "
        "spec_json = COALESCE(?, spec_json), updated_at = ? WHERE id = ?",
        (project_name, json.dumps(spec) if spec is not None else None, time.time(), project_id),
    )
    conn.commit()
    conn.close()
    return True


def get_or_create_project(spec: dict) -> int:
    name = ""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict):
        name = cb.get("name", "")
    if not name:
        name = spec.get("project_name", "Untitled")

    conn = _conn()
    row = conn.execute(
        "SELECT id FROM intel_projects WHERE project_name = ? ORDER BY created_at DESC LIMIT 1",
        (name,),
    ).fetchone()
    conn.close()

    if row:
        return row["id"]
    return create_project(name, spec)


# ─── Jobs ──────────────────────────────────────────────────────────────

# ─── Jobs ────────────────────────────────────────────────────────────────────

def create_job(job_id: str, project_id: int, job_type: str) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_jobs (id, project_id, job_type, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (job_id, project_id, job_type, now),
    )
    conn.commit()
    conn.close()
    return job_id


def update_job(job_id: str, *, status: str | None = None, progress_pct: int | None = None,
               progress_message: str | None = None, result: dict | None = None, error: str | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if progress_pct is not None:
        parts.append("progress_pct = ?")
        vals.append(progress_pct)
    if progress_message is not None:
        parts.append("progress_message = ?")
        vals.append(progress_message)
    if result is not None:
        parts.append("result_json = ?")
        vals.append(json.dumps(result))
    if error is not None:
        parts.append("error = ?")
        vals.append(error)

    if parts:
        vals.append(job_id)
        conn.execute(f"UPDATE intel_jobs SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def list_jobs(project_id: int, job_type: str | None = None) -> list[dict]:
    conn = _conn()
    if job_type:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? AND job_type = ? ORDER BY created_at DESC",
            (project_id, job_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        result.append(d)
    return result


def cancel_stale_running_jobs():
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_jobs SET status = 'cancelled', finished_at = ?, error = 'Cancelled: stale running job from prior session' "
        "WHERE status = 'running'",
        (now,),
    )
    conn.commit()
    conn.close()

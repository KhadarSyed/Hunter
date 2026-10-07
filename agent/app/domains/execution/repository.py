"""Execution Runs repository (connection helper: core/db.py).

Also contains:
- evidence: Evidence (raw) repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── Execution Runs ────────────────────────────────────────────────────────

def create_execution_run(project_id: int, plan_id: int, total_units: int) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_execution_runs (project_id, plan_id, status, total_units, created_at) "
        "VALUES (?, ?, 'pending', ?, ?)",
        (project_id, plan_id, total_units, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_execution_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_execution_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def get_latest_execution_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_execution_runs WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def update_execution_run(run_id: int, *, status: str | None = None, completed_units: int | None = None,
                          failed_units: int | None = None, skipped_units: int | None = None,
                          total_evidence: int | None = None, started_at: float | None = None,
                          finished_at: float | None = None):
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
    if completed_units is not None:
        parts.append("completed_units = ?")
        vals.append(completed_units)
    if failed_units is not None:
        parts.append("failed_units = ?")
        vals.append(failed_units)
    if skipped_units is not None:
        parts.append("skipped_units = ?")
        vals.append(skipped_units)
    if total_evidence is not None:
        parts.append("total_evidence = ?")
        vals.append(total_evidence)
    if started_at is not None:
        parts.append("started_at = ?")
        vals.append(started_at)
    if finished_at is not None:
        parts.append("finished_at = ?")
        vals.append(finished_at)

    if parts:
        vals.append(run_id)
        conn.execute(f"UPDATE intel_execution_runs SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def create_execution_unit(run_id: int, unit_id: str, objective_id: str, method: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_execution_units (run_id, unit_id, objective_id, method, status, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (run_id, unit_id, objective_id, method, now),
    )
    eu_id = cur.lastrowid
    conn.commit()
    conn.close()
    return eu_id


def update_execution_unit(eu_id: int, *, status: str | None = None, progress_pct: int | None = None,
                           records_processed: int | None = None, evidence_count: int | None = None,
                           error: str | None = None, result: dict | None = None,
                           started_at: float | None = None, finished_at: float | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled", "skipped"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if progress_pct is not None:
        parts.append("progress_pct = ?")
        vals.append(progress_pct)
    if records_processed is not None:
        parts.append("records_processed = ?")
        vals.append(records_processed)
    if evidence_count is not None:
        parts.append("evidence_count = ?")
        vals.append(evidence_count)
    if error is not None:
        parts.append("error = ?")
        vals.append(error)
    if result is not None:
        parts.append("result_json = ?")
        vals.append(json.dumps(result))
    if started_at is not None:
        parts.append("started_at = ?")
        vals.append(started_at)
    if finished_at is not None:
        parts.append("finished_at = ?")
        vals.append(finished_at)

    if parts:
        vals.append(eu_id)
        conn.execute(f"UPDATE intel_execution_units SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_execution_units(run_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_execution_units WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        d["coverage_volume"] = (d.get("result") or {}).get("coverage_volume")
        result.append(d)
    return result


def get_execution_unit_by_unit_id(run_id: int, unit_id: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_execution_units WHERE run_id = ? AND unit_id = ?",
        (run_id, unit_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def add_execution_log(run_id: int, message: str, unit_id: str | None = None, level: str = "info"):
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_execution_logs (run_id, unit_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, unit_id, level, message, now),
    )
    conn.commit()
    conn.close()


def get_execution_logs(run_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_execution_logs WHERE run_id = ? ORDER BY id DESC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Evidence ──────────────────────────────────────────────────────────

def save_evidence(run_id: int, unit_id: str, objective_id: str, evidence_type: str, method: str,
                   *, platform: str | None = None, source: str | None = None, date: str | None = None,
                   text_excerpt: str | None = None, metrics: dict | None = None,
                   confidence: str = "medium", rationale: str | None = None,
                   dataset: str = "meltwater_export") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_evidence (run_id, unit_id, objective_id, evidence_type, platform, source, date, "
        "text_excerpt, metrics_json, confidence, method, rationale, dataset, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, unit_id, objective_id, evidence_type, platform, source, date,
         text_excerpt, json.dumps(metrics) if metrics is not None else None,
         confidence, method, rationale, dataset, now),
    )
    ev_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ev_id


def get_evidence(run_id: int, unit_id: str | None = None) -> list[dict]:
    conn = _conn()
    if unit_id:
        rows = conn.execute(
            "SELECT * FROM intel_evidence WHERE run_id = ? AND unit_id = ? ORDER BY id",
            (run_id, unit_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_evidence WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("metrics_json"):
            d["metrics"] = json.loads(d["metrics_json"])
        result.append(d)
    return result


def get_evidence_record(evidence_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_evidence WHERE id = ?", (evidence_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    return d


def count_evidence(run_id: int, unit_id: str | None = None) -> int:
    conn = _conn()
    if unit_id:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_evidence WHERE run_id = ? AND unit_id = ?",
            (run_id, unit_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_evidence WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0

"""QC Flow repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

# ─── QC Reports ─────────────────────────────────────────────────────────────

def create_qc_report(project_id: int, file_name: str, file_path: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_reports (project_id, file_name, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, file_name, file_path, now, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_qc_report(report_id: int, **kwargs) -> None:
    conn = _conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("row_count", "column_count", "columns_json", "field_mapping", "parse_status", "parse_error"):
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    if sets:
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(report_id)
        conn.execute(f"UPDATE qc_reports SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_qc_report(report_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM qc_reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("columns_json", "field_mapping"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def get_qc_report_for_project(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM qc_reports WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("columns_json", "field_mapping"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def save_qc_field_mapping(report_id: int, mapping: dict) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE qc_reports SET field_mapping = ?, updated_at = ? WHERE id = ?",
        (json.dumps(mapping), time.time(), report_id),
    )
    conn.commit()
    conn.close()


# ─── QC Runs ────────────────────────────────────────────────────────────────

def create_qc_run(report_id: int) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_runs (report_id, status, created_at) VALUES (?, 'pending', ?)",
        (report_id, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_qc_run(run_id: int, **kwargs) -> None:
    conn = _conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("status", "total_rows", "total_checks", "total_findings", "score", "score_breakdown", "started_at", "completed_at"):
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    if sets:
        vals.append(run_id)
        conn.execute(f"UPDATE qc_runs SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_qc_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM qc_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("score_breakdown"):
        try:
            d["score_breakdown"] = json.loads(d["score_breakdown"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_qc_runs_for_report(report_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM qc_runs WHERE report_id = ? ORDER BY created_at DESC", (report_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── QC Findings ────────────────────────────────────────────────────────────

def add_qc_finding(run_id: int, report_id: int, check_type: str, severity: str,
                   message: str, row_number: int | None = None, column_name: str | None = None,
                   expected: str | None = None, actual: str | None = None,
                   source_url: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_findings (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, now),
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def add_qc_findings_batch(findings: list[dict]) -> int:
    if not findings:
        return 0
    conn = _conn()
    now = time.time()
    rows = [
        (f["run_id"], f["report_id"], f["check_type"], f.get("row_number"),
         f.get("column_name"), f["severity"], f["message"],
         f.get("expected"), f.get("actual"), f.get("source_url"), now)
        for f in findings
    ]
    conn.executemany(
        "INSERT INTO qc_findings (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def get_qc_findings(run_id: int, severity: str | None = None, check_type: str | None = None) -> list[dict]:
    conn = _conn()
    sql = "SELECT * FROM qc_findings WHERE run_id = ?"
    params: list = [run_id]
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    if check_type:
        sql += " AND check_type = ?"
        params.append(check_type)
    sql += " ORDER BY row_number ASC, severity ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_qc_finding_action(finding_id: int, action: str) -> None:
    conn = _conn()
    conn.execute("UPDATE qc_findings SET analyst_action = ? WHERE id = ?", (action, finding_id))
    conn.commit()
    conn.close()

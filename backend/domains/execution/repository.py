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


# ─── Evidence ──────────────────────────────────────────────────────────

def save_evidence(run_id: int, unit_id: str, objective_id: str, evidence_type: str, method: str,
                   *, platform: str | None = None, source: str | None = None, date: str | None = None,
                   text_excerpt: str | None = None, metrics: dict | None = None,
                   confidence: str = "medium", rationale: str | None = None,
                   dataset: str = "meltwater_export", url: str | None = None,
                   document_id: str | None = None, source_file: str | None = None,
                   row_index: int | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_evidence (run_id, unit_id, objective_id, evidence_type, platform, source, date, "
        "text_excerpt, metrics_json, confidence, method, rationale, dataset, url, document_id, source_file, "
        "row_index, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, unit_id, objective_id, evidence_type, platform, source, date,
         text_excerpt, json.dumps(metrics) if metrics is not None else None,
         confidence, method, rationale, dataset, url, document_id, source_file, row_index, now),
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



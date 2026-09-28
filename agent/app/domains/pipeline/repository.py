"""Pipeline Orchestrator repository (connection helper: core/db.py)."""

from __future__ import annotations

import json
import time

from ...core.db import _conn

# ─── Pipeline Orchestrator ─────────────────────────────────────────────────

def create_pipeline_run(run_id: str, project_id: int, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_pipeline_runs "
        "(id,project_id,status,execution_mode,current_stage,start_stage,"
        "completed_stages_json,remaining_stages_json,skipped_stages_json,"
        "progress_pct,estimated_remaining_ms,user,started_at,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, project_id,
         kw.get("status", "pending"),
         kw.get("execution_mode", "full"),
         kw.get("current_stage"),
         kw.get("start_stage"),
         json.dumps(kw.get("completed_stages", [])),
         json.dumps(kw.get("remaining_stages", [])),
         json.dumps(kw.get("skipped_stages", [])),
         kw.get("progress_pct", 0),
         kw.get("estimated_remaining_ms", 0),
         kw.get("user", "system"),
         kw.get("started_at", now), now),
    )
    conn.commit()
    conn.close()
    return run_id


def get_pipeline_run(run_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pipeline_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_pipeline_runs(project_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pipeline_run(run_id: str, **kw) -> None:
    parts, vals = [], []
    for col in ("status", "current_stage", "progress_pct",
                "estimated_remaining_ms", "error", "started_at", "completed_at"):
        if col in kw:
            parts.append(f"{col}=?")
            vals.append(kw[col])
    for col in ("completed_stages", "remaining_stages", "skipped_stages"):
        json_col = f"{col}_json"
        if col in kw:
            parts.append(f"{json_col}=?")
            vals.append(json.dumps(kw[col]))
    if not parts:
        return
    vals.append(run_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pipeline_runs SET {','.join(parts)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_latest_pipeline_run(project_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def create_pipeline_stage(run_id: str, stage_id: str, stage_name: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_stages "
        "(run_id,stage_id,stage_name,status,version,input_hash,output_hash,"
        "dependencies_json,execution_time_ms,cache_status,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, stage_id, stage_name,
         kw.get("status", "pending"),
         kw.get("version", 1),
         kw.get("input_hash"),
         kw.get("output_hash"),
         json.dumps(kw.get("dependencies", [])),
         kw.get("execution_time_ms", 0),
         kw.get("cache_status", "miss"), now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_pipeline_stages(run_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_stages WHERE run_id=? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("dependencies_json", "logs_json", "warnings_json", "errors_json", "result_json"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pipeline_stage(run_id: str, stage_id: str, **kw) -> None:
    parts, vals = [], []
    for col in ("status", "input_hash", "output_hash", "execution_time_ms",
                "started_at", "completed_at", "cache_status", "version"):
        if col in kw:
            parts.append(f"{col}=?")
            vals.append(kw[col])
    for col in ("logs", "warnings", "errors", "result", "dependencies"):
        json_col = f"{col}_json"
        if col in kw:
            parts.append(f"{json_col}=?")
            vals.append(json.dumps(kw[col]))
    if not parts:
        return
    vals.extend([run_id, stage_id])
    conn = _conn()
    conn.execute(
        f"UPDATE intel_pipeline_stages SET {','.join(parts)} WHERE run_id=? AND stage_id=?",
        vals,
    )
    conn.commit()
    conn.close()


def get_pipeline_stage(run_id: str, stage_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_stages WHERE run_id=? AND stage_id=?",
        (run_id, stage_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("dependencies_json", "logs_json", "warnings_json", "errors_json", "result_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def set_pipeline_cache(project_id: int, stage_id: str, input_hash: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    conn.execute(
        "DELETE FROM intel_pipeline_cache WHERE project_id=? AND stage_id=?",
        (project_id, stage_id),
    )
    cur = conn.execute(
        "INSERT INTO intel_pipeline_cache "
        "(project_id,stage_id,input_hash,output_hash,version,result_summary_json,created_at,expires_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, stage_id, input_hash,
         kw.get("output_hash"),
         kw.get("version", 1),
         json.dumps(kw.get("result_summary", {})),
         now, kw.get("expires_at")),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_pipeline_cache(project_id: int, stage_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_cache WHERE project_id=? AND stage_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id, stage_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_summary_json"):
        try:
            d["result_summary_json"] = json.loads(d["result_summary_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def clear_pipeline_cache(project_id: int, stage_id: str | None = None) -> int:
    conn = _conn()
    if stage_id:
        cur = conn.execute(
            "DELETE FROM intel_pipeline_cache WHERE project_id=? AND stage_id=?",
            (project_id, stage_id),
        )
    else:
        cur = conn.execute(
            "DELETE FROM intel_pipeline_cache WHERE project_id=?",
            (project_id,),
        )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def list_pipeline_cache(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_cache WHERE project_id=? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_summary_json"):
            try:
                d["result_summary_json"] = json.loads(d["result_summary_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_pipeline_log(run_id: str, message: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_logs (run_id,stage_id,level,message,details_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, kw.get("stage_id"), kw.get("level", "info"),
         message, json.dumps(kw.get("details", {})), now),
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return lid


def get_pipeline_logs(run_id: str, stage_id: str | None = None, limit: int = 200) -> list[dict]:
    conn = _conn()
    if stage_id:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_logs WHERE run_id=? AND stage_id=? ORDER BY created_at ASC LIMIT ?",
            (run_id, stage_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_logs WHERE run_id=? ORDER BY created_at ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json"):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_pipeline_metric(project_id: int, metric_type: str, value: float, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_metrics (project_id,stage_id,run_id,metric_type,value,unit,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, kw.get("stage_id"), kw.get("run_id"),
         metric_type, value, kw.get("unit", "ms"), now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_pipeline_metrics(project_id: int, run_id: str | None = None) -> list[dict]:
    conn = _conn()
    if run_id:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_metrics WHERE project_id=? AND run_id=? ORDER BY created_at DESC",
            (project_id, run_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_metrics WHERE project_id=? ORDER BY created_at DESC LIMIT 200",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_performance(project_id: int) -> dict:
    conn = _conn()
    runs = conn.execute(
        "SELECT COUNT(*) as total, "
        "AVG(CASE WHEN completed_at IS NOT NULL AND started_at IS NOT NULL "
        "THEN (completed_at - started_at) * 1000 END) as avg_duration_ms, "
        "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed "
        "FROM intel_pipeline_runs WHERE project_id=?",
        (project_id,),
    ).fetchone()
    cache_stats = conn.execute(
        "SELECT COUNT(*) as total_entries FROM intel_pipeline_cache WHERE project_id=?",
        (project_id,),
    ).fetchone()
    stage_avgs = conn.execute(
        "SELECT stage_id, AVG(execution_time_ms) as avg_ms, COUNT(*) as runs "
        "FROM intel_pipeline_stages WHERE run_id IN "
        "(SELECT id FROM intel_pipeline_runs WHERE project_id=?) "
        "AND execution_time_ms > 0 GROUP BY stage_id",
        (project_id,),
    ).fetchall()
    cache_hits = conn.execute(
        "SELECT cache_status, COUNT(*) as cnt "
        "FROM intel_pipeline_stages WHERE run_id IN "
        "(SELECT id FROM intel_pipeline_runs WHERE project_id=?) "
        "GROUP BY cache_status",
        (project_id,),
    ).fetchall()
    conn.close()
    hit_map = {r["cache_status"]: r["cnt"] for r in cache_hits}
    total_cache = sum(hit_map.values()) or 1
    return {
        "total_runs": runs["total"] if runs else 0,
        "completed_runs": runs["completed"] if runs else 0,
        "failed_runs": runs["failed"] if runs else 0,
        "avg_duration_ms": runs["avg_duration_ms"] if runs else 0,
        "cache_entries": cache_stats["total_entries"] if cache_stats else 0,
        "cache_hit_ratio": hit_map.get("hit", 0) / total_cache,
        "stage_averages": {r["stage_id"]: {"avg_ms": r["avg_ms"], "runs": r["runs"]} for r in stage_avgs},
        "cache_breakdown": hit_map,
    }

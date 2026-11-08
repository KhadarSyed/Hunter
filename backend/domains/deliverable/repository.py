"""SQLite access for the deliverable engine: runs, streamed sections, classification cache, template index."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

_RUN_FIELDS = {"status", "stage", "pptx_path", "docx_path", "thumbs_dir", "error", "finished_at",
               "html_path", "pdf_path", "studio_pptx_path", "deck_dir"}


def create_deliverable_run(project_id: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_deliverable_runs (project_id, status, stages_json, created_at) "
        "VALUES (?, 'running', '{}', ?)", (project_id, time.time()))
    conn.commit()
    conn.close()
    return cur.lastrowid


def update_deliverable_run(run_id: int, **fields: Any) -> None:
    sets, vals = [], []
    for key, value in fields.items():
        if key == "stages_json":
            sets.append("stages_json = ?")
            vals.append(json.dumps(value))
        elif key in _RUN_FIELDS:
            sets.append(f"{key} = ?")
            vals.append(value)
    if not sets:
        return
    conn = _conn()
    conn.execute(f"UPDATE intel_deliverable_runs SET {', '.join(sets)} WHERE id = ?", (*vals, run_id))
    conn.commit()
    conn.close()


def _run(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d["stages"] = json.loads(d.pop("stages_json") or "{}")
    return d


def get_deliverable_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return _run(row)


def recent_run_durations(limit: int = 5) -> list[float]:
    """Wall-clock seconds of the latest completed runs, newest first (the progress bar's typical duration)."""
    conn = _conn()
    rows = conn.execute("SELECT finished_at - created_at AS d FROM intel_deliverable_runs WHERE status = 'completed' "
                        "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [r["d"] for r in rows if r["d"] and r["d"] > 0]


def get_latest_deliverable_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE project_id = ? "
                       "ORDER BY created_at DESC, id DESC LIMIT 1", (project_id,)).fetchone()
    conn.close()
    return _run(row)


def fail_interrupted_deliverable_runs() -> int:
    """Runs still 'running' at startup died with the previous process; without this they block Generate."""
    conn = _conn()
    # a Fix on a finished deck (its deck_dir is set only once the run has finished) was interrupted, not the run:
    # the deck as last saved is still the deliverable
    repaired = conn.execute("UPDATE intel_deliverable_runs SET status = 'completed' WHERE status = 'running' "
                            "AND stage = 'repair' AND deck_dir IS NOT NULL").rowcount
    cur = conn.execute("UPDATE intel_deliverable_runs SET status = 'failed', "
                       "error = 'interrupted by a server restart', finished_at = ? WHERE status = 'running'",
                       (time.time(),))
    conn.commit()
    conn.close()
    return cur.rowcount + repaired


def get_active_deliverable_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE project_id = ? AND status = 'running' "
                       "ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    conn.close()
    return _run(row)


def save_deliverable_section(run_id: int, section: dict) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_deliverable_sections (run_id, section_key, rq_id, module, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, section.get("id", ""), section.get("rq_id"), section.get("module"),
         json.dumps(section, ensure_ascii=False, default=str), time.time()))
    conn.commit()
    conn.close()
    return cur.lastrowid


def replace_deliverable_section(run_id: int, section: dict) -> int:
    """One row per key (the run log is rewritten as it grows)."""
    conn = _conn()
    conn.execute("DELETE FROM intel_deliverable_sections WHERE run_id = ? AND section_key = ?",
                 (run_id, section.get("id", "")))
    conn.commit()
    conn.close()
    return save_deliverable_section(run_id, section)


def list_deliverable_sections(run_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT payload_json FROM intel_deliverable_sections WHERE run_id = ? ORDER BY id",
                        (run_id,)).fetchall()
    conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


CLASSIFICATION_MAX_AGE_S = 30 * 86400


def get_cached_classification(norm_url: str, field: str, model: str | None = None) -> Optional[list]:
    """A saved classification, reused only while it is under 30 days old and (when given) made by the same model:
    a better model, or an article that changed, gets classified again."""
    conn = _conn()
    sql = "SELECT value_json FROM intel_article_classifications WHERE norm_url = ? AND field = ? AND created_at > ?"
    params: list = [norm_url, field, time.time() - CLASSIFICATION_MAX_AGE_S]
    if model:
        sql += " AND model = ?"
        params.append(model)
    row = conn.execute(sql, tuple(params)).fetchone()
    conn.close()
    return json.loads(row["value_json"]) if row else None


def save_cached_classification(norm_url: str, field: str, value: list, model: str) -> None:
    conn = _conn()
    conn.execute("INSERT INTO intel_article_classifications (norm_url, field, value_json, model, created_at) "
                 "VALUES (?, ?, ?, ?, ?) ON CONFLICT (norm_url, field) DO UPDATE SET value_json = excluded.value_json, "
                 "model = excluded.model, created_at = excluded.created_at",
                 (norm_url, field, json.dumps(value, ensure_ascii=False), model, time.time()))
    conn.commit()
    conn.close()


def save_reference_deck(path: str, text: str, embedding: Optional[list[float]], model: str = "") -> None:
    conn = _conn()
    conn.execute("INSERT INTO intel_reference_decks (path, text, embedding_json, indexed_at, model) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT (path) DO UPDATE SET text = excluded.text, embedding_json = excluded.embedding_json, "
                 "indexed_at = excluded.indexed_at, model = excluded.model",
                 (path, text, json.dumps(embedding) if embedding is not None else None, time.time(), model))
    conn.commit()
    conn.close()


def list_reference_decks() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT path, text, embedding_json, model FROM intel_reference_decks").fetchall()
    conn.close()
    return [{"path": r["path"], "text": r["text"] or "", "model": r["model"] or "",
             "embedding": json.loads(r["embedding_json"]) if r["embedding_json"] else None} for r in rows]


def get_deliverable_plans(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, plan, source}: each question's last analysis plan (see engine's plan stage)."""
    conn = _conn()
    rows = conn.execute("SELECT rq_id, signature, plan_json, source FROM intel_deliverable_plans WHERE project_id = ?",
                        (project_id,)).fetchall()
    conn.close()
    return {r["rq_id"]: {"signature": r["signature"], "plan": json.loads(r["plan_json"]), "source": r["source"]}
            for r in rows}


def save_deliverable_plan(project_id: int, rq_id: str, signature: str, plan: dict, source: str) -> None:
    conn = _conn()
    conn.execute("INSERT INTO intel_deliverable_plans (project_id, rq_id, signature, plan_json, source, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, rq_id) DO UPDATE SET "
                 "signature = excluded.signature, plan_json = excluded.plan_json, source = excluded.source, "
                 "updated_at = excluded.updated_at",
                 (project_id, rq_id, signature, json.dumps(plan), source, time.time()))
    conn.commit()
    conn.close()


# ─── "Refresh latest 24h" ───────────────────────────────────────────────────

_REFRESH_JSON = ("counts", "summary", "charts", "articles")


def create_latest24h_refresh(project_id: int) -> int:
    """A new running refresh (the older ones are dropped once it completes, so a failed refresh keeps the last good one)."""
    conn = _conn()
    cur = conn.execute("INSERT INTO intel_latest24h_refreshes (project_id, status, started_at) VALUES (?, 'running', ?)",
                       (project_id, time.time()))
    conn.commit()
    conn.close()
    return cur.lastrowid


def finish_latest24h_refresh(refresh_id: int, status: str, counts: dict, fetched: int, kept: int,
                             summary: Any = None, charts: Any = None, articles: Any = None,
                             error: Optional[str] = None) -> None:
    conn = _conn()
    conn.execute("UPDATE intel_latest24h_refreshes SET status = ?, finished_at = ?, counts_json = ?, fetched = ?, "
                 "kept = ?, summary_json = ?, charts_json = ?, articles_json = ?, error = ? WHERE id = ?",
                 (status, time.time(), json.dumps(counts), fetched, kept, json.dumps(summary), json.dumps(charts),
                  json.dumps(articles), error, refresh_id))
    if status == "completed":        # only the latest is ever read: a completed refresh replaces the older ones
        conn.execute("DELETE FROM intel_latest24h_refreshes WHERE id != ? AND status != 'running' AND project_id = "
                     "(SELECT project_id FROM intel_latest24h_refreshes WHERE id = ?)", (refresh_id, refresh_id))
    conn.commit()
    conn.close()


def get_latest_latest24h_refresh(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_latest24h_refreshes WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                       (project_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for key in _REFRESH_JSON:
        d[key] = json.loads(d.pop(f"{key}_json") or "null")
    return d


def fail_interrupted_latest24h_refreshes() -> int:
    """A server restart ends any refresh mid-flight; mark it so the page never waits on it forever."""
    conn = _conn()
    n = conn.execute("UPDATE intel_latest24h_refreshes SET status = 'failed', error = 'Interrupted by a server restart', "
                     "finished_at = ? WHERE status = 'running'", (time.time(),)).rowcount
    conn.commit()
    conn.close()
    return n


# ─── A finished deck's files (deck_store.py) ────────────────────────────────

def save_deck_files(run_id: int, project_id: int, parts) -> int:
    """Replace the run's stored files with `parts` ((name, part, gz, bytes[, s3_key]) tuples, read one at a time) and drop the
    project's other runs, in one transaction: a failed save keeps the previous run. Returns the bytes stored."""
    conn = _conn()
    total = 0
    try:
        with conn:
            conn.execute("DELETE FROM intel_deliverable_files WHERE run_id = ?", (run_id,))
            now = time.time()
            for name, part, gz, content, *rest in parts:
                conn.execute("INSERT INTO intel_deliverable_files (run_id, project_id, name, part, gz, content, "
                             "created_at, s3_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (run_id, project_id, name, part, gz, content, now, rest[0] if rest else None))
                total += len(content)
            conn.execute("DELETE FROM intel_deliverable_files WHERE project_id = ? AND run_id != ?", (project_id, run_id))
    finally:
        conn.close()
    return total


def deck_file_names(run_id: int) -> list[str]:
    conn = _conn()
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT name FROM intel_deliverable_files WHERE run_id = ?",
                                           (run_id,))]
    finally:
        conn.close()


def project_deck_s3_keys(project_id: int) -> list[tuple[int, str]]:
    """(run_id, S3 key) of every file of the project's stored decks that lives in S3."""
    conn = _conn()
    try:
        return [(r[0], r[1]) for r in conn.execute(
            "SELECT run_id, s3_key FROM intel_deliverable_files WHERE project_id = ? AND s3_key IS NOT NULL",
            (project_id,))]
    finally:
        conn.close()


def deck_file_s3_key(run_id: int, name: str) -> Optional[str]:
    """The S3 key the file was stored under, or None when it is kept as chunks."""
    conn = _conn()
    try:
        row = conn.execute("SELECT s3_key FROM intel_deliverable_files WHERE run_id = ? AND name = ? AND part = 0",
                           (run_id, name)).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def deck_file_parts(run_id: int, name: str):
    """(gz, bytes) of each stored part in order, fetched one at a time so a large file never sits in memory whole."""
    conn = _conn()
    try:
        parts = [r[0] for r in conn.execute("SELECT part FROM intel_deliverable_files WHERE run_id = ? AND name = ? "
                                            "ORDER BY part", (run_id, name))]
        for part in parts:
            row = conn.execute("SELECT gz, content FROM intel_deliverable_files WHERE run_id = ? AND name = ? AND "
                               "part = ?", (run_id, name, part)).fetchone()
            yield row[0], bytes(row[1])
    finally:
        conn.close()

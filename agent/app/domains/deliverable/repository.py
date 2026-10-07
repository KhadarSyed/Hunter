"""SQLite access for the deliverable engine: runs, streamed sections, classification cache, template index."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

_RUN_FIELDS = {"status", "stage", "pptx_path", "docx_path", "thumbs_dir", "error", "finished_at"}


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


def get_latest_deliverable_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE project_id = ? "
                       "ORDER BY created_at DESC, id DESC LIMIT 1", (project_id,)).fetchone()
    conn.close()
    return _run(row)


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


def list_deliverable_sections(run_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT payload_json FROM intel_deliverable_sections WHERE run_id = ? ORDER BY id",
                        (run_id,)).fetchall()
    conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


def get_cached_classification(norm_url: str, field: str) -> Optional[list]:
    conn = _conn()
    row = conn.execute("SELECT value_json FROM intel_article_classifications WHERE norm_url = ? AND field = ?",
                       (norm_url, field)).fetchone()
    conn.close()
    return json.loads(row["value_json"]) if row else None


def save_cached_classification(norm_url: str, field: str, value: list, model: str) -> None:
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO intel_article_classifications VALUES (?, ?, ?, ?, ?)",
                 (norm_url, field, json.dumps(value, ensure_ascii=False), model, time.time()))
    conn.commit()
    conn.close()


def save_reference_deck(path: str, text: str, embedding: Optional[list[float]]) -> None:
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO intel_reference_decks VALUES (?, ?, ?, ?)",
                 (path, text, json.dumps(embedding) if embedding is not None else None, time.time()))
    conn.commit()
    conn.close()


def list_reference_decks() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT path, text, embedding_json FROM intel_reference_decks").fetchall()
    conn.close()
    return [{"path": r["path"], "text": r["text"] or "",
             "embedding": json.loads(r["embedding_json"]) if r["embedding_json"] else None} for r in rows]

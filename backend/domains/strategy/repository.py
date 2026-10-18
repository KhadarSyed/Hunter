"""Search Strategies repository (connection helper: core/db.py).

Also contains:
- dataset: Datasets repository (connection helper: core/db.py).
- evaluation: Sample Evaluations repository (connection helper: core/db.py).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from ...core import config
from database.db import _conn

logger = logging.getLogger(__name__)

# ─── Search Strategies ───────────────────────────────────────────────────────

def save_search_strategy(project_id: int, strategy: dict) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_search_strategies WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_search_strategies (project_id, version, status, strategy_json, created_at) "
        "VALUES (?, ?, 'draft', ?, ?)",
        (project_id, version, json.dumps(strategy), now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_latest_strategy(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_search_strategies WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["strategy"] = json.loads(d["strategy_json"])
    return d


def approve_strategy(strategy_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_search_strategies SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


def update_strategy_query(strategy_id: int, query_type: str, query_text: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_query_versions (strategy_id, version_label, query_type, query_text, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (strategy_id, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)), query_type, query_text, now),
    )
    vid = cur.lastrowid
    conn.commit()

    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if row:
        strategy = json.loads(row["strategy_json"])
        query_versions = strategy.get("query_versions", {})
        if query_type in query_versions:
            query_versions[query_type]["query"] = query_text
            strategy["query_versions"] = query_versions
            conn.execute(
                "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
                (json.dumps(strategy), strategy_id),
            )
            conn.commit()

    conn.close()
    return vid


def get_query_versions(strategy_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_query_versions WHERE strategy_id = ? ORDER BY created_at DESC",
        (strategy_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_research_question(strategy_id: int, question_id: str, question: str, query: str) -> bool:
    conn = _conn()
    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        conn.close()
        return False
    strategy = json.loads(row["strategy_json"])
    rqs = strategy.get("research_question_queries", [])
    for rq in rqs:
        if rq.get("question_id") == question_id:
            rq["question"] = question
            rq["query"] = query
            break
    else:
        conn.close()
        return False
    strategy["research_question_queries"] = rqs
    conn.execute(
        "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
        (json.dumps(strategy), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


def get_strategy_project_id(strategy_id: int) -> int | None:
    conn = _conn()
    row = conn.execute("SELECT project_id FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    conn.close()
    return row["project_id"] if row else None


def add_research_question(strategy_id: int, question: str, query: str) -> str | None:
    """Append an analyst-added RQ numbered after the highest existing RQn; returns its id (None if no strategy).
    The row is locked before the read (FOR UPDATE), so two concurrent adds can't pick the same RQn."""
    conn = _conn()
    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ? FOR UPDATE",
                       (strategy_id,)).fetchone()
    if not row:
        conn.close()
        return None
    strategy = json.loads(row["strategy_json"])
    rqs = strategy.get("research_question_queries", [])
    numbers = [int(rq["question_id"][2:]) for rq in rqs
               if str(rq.get("question_id", "")).startswith("RQ") and str(rq["question_id"])[2:].isdigit()]
    question_id = f"RQ{max(numbers, default=0) + 1}"
    rqs.append({"question_id": question_id, "question": question, "query": query, "user_added": True})
    strategy["research_question_queries"] = rqs
    conn.execute("UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?", (json.dumps(strategy), strategy_id))
    conn.commit()
    conn.close()
    return question_id


def delete_research_question(strategy_id: int, question_id: str) -> bool:
    conn = _conn()
    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        conn.close()
        return False
    strategy = json.loads(row["strategy_json"])
    rqs = strategy.get("research_question_queries", [])
    original_len = len(rqs)
    rqs = [rq for rq in rqs if rq.get("question_id") != question_id]
    if len(rqs) == original_len:
        conn.close()
        return False
    strategy["research_question_queries"] = rqs
    conn.execute(
        "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
        (json.dumps(strategy), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── Dataset ───────────────────────────────────────────────────────────

# ─── Datasets ───────────────────────────────────────────────────────────────

def save_dataset(project_id: int, file_name: str, file_path: str,
                 record_count: int, column_mapping: dict, stats: dict,
                 preview: list, processing_status: str = "done",
                 research_question_id: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_datasets (project_id, file_name, file_path, record_count, "
        "column_mapping_json, stats_json, preview_json, processing_status, "
        "research_question_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, file_name, file_path, record_count,
         json.dumps(column_mapping), json.dumps(stats), json.dumps(preview),
         processing_status, research_question_id, now),
    )
    dataset_id = cur.lastrowid
    conn.commit()
    conn.close()
    _keep_file(dataset_id, file_name, file_path)
    return dataset_id


def _keep_file(dataset_id: int, file_name: str, file_path: str) -> None:
    """The upload's bytes go in the database too: the server's disk may not survive a restart. A failure here is
    logged, never raised: the dataset itself is already saved."""
    try:
        content = Path(file_path).read_bytes()
    except OSError as e:
        logger.warning("dataset %s: file %s not kept in the database (%s)", dataset_id, file_path, e)
        return
    conn = _conn()
    try:
        conn.execute("DELETE FROM intel_dataset_files WHERE dataset_id = ?", (dataset_id,))
        conn.execute("INSERT INTO intel_dataset_files (dataset_id, file_name, content, created_at) "
                     "VALUES (?, ?, ?, ?)", (dataset_id, file_name, content, time.time()))
        conn.commit()
    except Exception as e:
        logger.error("dataset %s: could not keep its file in the database (%s)", dataset_id, e)
    finally:
        conn.close()


def _restored(d: dict) -> dict:
    """A dataset whose file is gone from disk (a restarted server) gets it back from the database, always under
    UPLOAD_DIR. Written to a temporary name and renamed, so a concurrent reader never sees half a file."""
    path = Path(d.get("file_path") or "")
    if not d.get("id") or not path.name or path.is_file():
        return d
    upload_dir = Path(config.UPLOAD_DIR).resolve()
    target = upload_dir / path.name
    if target.is_file():                     # restored by another request, or recorded under an old folder
        return _repointed(d, target)
    conn = _conn()
    try:
        row = conn.execute("SELECT content FROM intel_dataset_files WHERE dataset_id = ?", (d["id"],)).fetchone()
    finally:
        conn.close()
    if row is None:
        return d
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        partial.write_bytes(bytes(row[0]))
        os.replace(partial, target)
    except OSError as e:
        logger.error("dataset %s: could not restore its file (%s)", d["id"], e)
        return d
    logger.info("dataset %s: file restored from the database to %s", d["id"], target)
    return _repointed(d, target)


def _repointed(d: dict, target: Path) -> dict:
    if str(target) != str(d.get("file_path")):
        conn = _conn()
        try:
            conn.execute("UPDATE intel_datasets SET file_path = ? WHERE id = ?", (str(target), d["id"]))
            conn.commit()
        finally:
            conn.close()
    return {**d, "file_path": str(target)}


def update_dataset_parsed(dataset_id: int, record_count: int,
                          column_mapping: dict, stats: dict, preview: list):
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET record_count=?, column_mapping_json=?, "
        "stats_json=?, preview_json=?, processing_status='done' WHERE id=?",
        (record_count, json.dumps(column_mapping), json.dumps(stats),
         json.dumps(preview), dataset_id),
    )
    conn.commit()
    conn.close()


def update_dataset_error(dataset_id: int, error: str):
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET processing_status='error', processing_error=? WHERE id=?",
        (error, dataset_id),
    )
    conn.commit()
    conn.close()


def get_latest_dataset(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d["column_mapping_json"] else {}
    d["stats"] = json.loads(d["stats_json"]) if d["stats_json"] else {}
    d["preview"] = json.loads(d["preview_json"]) if d["preview_json"] else []
    return _restored(d)


def get_datasets_by_project(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
        d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
        d["preview"] = json.loads(d["preview_json"]) if d.get("preview_json") else []
        results.append(_restored(d))
    return results


def get_dataset_for_rq(project_id: int, research_question_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? AND research_question_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id, research_question_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
    d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
    d["preview"] = json.loads(d["preview_json"]) if d.get("preview_json") else []
    return _restored(d)


def approve_dataset(dataset_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), dataset_id),
    )
    conn.commit()
    conn.close()
    return True


def delete_dataset(dataset_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_datasets WHERE id = ?", (dataset_id,))
    conn.execute("DELETE FROM intel_dataset_files WHERE dataset_id = ?", (dataset_id,))
    conn.commit()
    conn.close()
    return True


def get_dataset_by_id(dataset_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_datasets WHERE id = ?", (dataset_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
    d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
    return _restored(d)


def update_enriched_record(dataset_id: int, record_id: str, updates: dict) -> dict | None:
    """Merge analyst edits (review_status, or any corrected tag field) into one
    record within a dataset's enrichment_json array. Returns the updated record,
    or None if the dataset has no enrichment yet or the record id isn't in it."""
    conn = _conn()
    row = conn.execute("SELECT enrichment_json FROM intel_datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not row or not row["enrichment_json"]:
        conn.close()
        return None
    records = json.loads(row["enrichment_json"])
    updated = None
    for rec in records:
        if str(rec.get("id")) == str(record_id):
            rec.update(updates)
            updated = rec
            break
    if updated is not None:
        conn.execute("UPDATE intel_datasets SET enrichment_json = ? WHERE id = ?", (json.dumps(records), dataset_id))
        conn.commit()
    conn.close()
    return updated


def update_dataset_enrichment(dataset_id: int, status: str, enrichment: list | None = None, error: str | None = None):
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET enrichment_status = ?, enrichment_json = ?, enrichment_error = ? WHERE id = ?",
        (status, json.dumps(enrichment) if enrichment is not None else None, error, dataset_id),
    )
    conn.commit()
    conn.close()


def get_enriched_records_by_project(project_id: int) -> list[dict]:
    """Every enriched record across every dataset for this project, each tagged
    with its source dataset_id/file_name/research_question_id — the Data Sources
    Review tab's feed, aggregated across however many files were enriched."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, file_name, research_question_id, enrichment_json FROM intel_datasets "
        "WHERE project_id = ? AND enrichment_status = 'done' AND enrichment_json IS NOT NULL "
        "ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    conn.close()
    out: list[dict] = []
    for row in rows:
        records = json.loads(row["enrichment_json"]) or []
        for rec in records:
            out.append({
                **rec,
                "dataset_id": row["id"],
                "dataset_file_name": row["file_name"],
                "research_question_id": row["research_question_id"],
            })
    return out


# ─── Evaluation ────────────────────────────────────────────────────────

# ─── Sample Evaluations ─────────────────────────────────────────────────────

def save_sample_evaluation(project_id: int, strategy_id: int, file_name: str,
                           file_path: str, evaluation: dict | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_sample_evaluations (project_id, strategy_id, file_name, file_path, evaluation_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, strategy_id, file_name, file_path,
         json.dumps(evaluation) if evaluation else None,
         "completed" if evaluation else "pending", now),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def get_latest_evaluation(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_sample_evaluations WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("evaluation_json"):
        d["evaluation"] = json.loads(d["evaluation_json"])
    return d


def update_evaluation(eval_id: int, evaluation: dict):
    conn = _conn()
    conn.execute(
        "UPDATE intel_sample_evaluations SET evaluation_json = ?, status = 'completed' WHERE id = ?",
        (json.dumps(evaluation), eval_id),
    )
    conn.commit()
    conn.close()


# ─── Question dimensions ─────────────────────────────────────────────────────

def get_question_dimensions(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, dimensions, source} for every question whose dimensions were derived."""
    conn = _conn()
    rows = conn.execute("SELECT rq_id, signature, dimensions_json, source FROM intel_question_dimensions "
                        "WHERE project_id = ?", (project_id,)).fetchall()
    conn.close()
    return {r["rq_id"]: {"signature": r["signature"], "dimensions": json.loads(r["dimensions_json"]),
                         "source": r["source"]} for r in rows}


def get_question_tag_schemas(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, schema, source} for every question whose dynamic tag schema was derived."""
    conn = _conn()
    rows = conn.execute("SELECT rq_id, signature, schema_json, source FROM intel_question_tag_schemas "
                        "WHERE project_id = ?", (project_id,)).fetchall()
    conn.close()
    return {r["rq_id"]: {"signature": r["signature"], "schema": json.loads(r["schema_json"]), "source": r["source"]}
            for r in rows}


def save_question_tag_schema(project_id: int, rq_id: str, signature: str, schema: dict, source: str) -> None:
    conn = _conn()
    conn.execute("INSERT INTO intel_question_tag_schemas (project_id, rq_id, signature, schema_json, source, "
                 "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, rq_id) DO UPDATE SET "
                 "signature = excluded.signature, schema_json = excluded.schema_json, "
                 "source = excluded.source, updated_at = excluded.updated_at",
                 (project_id, rq_id, signature, json.dumps(schema), source, time.time()))
    conn.commit()
    conn.close()


def save_question_dimensions(project_id: int, rq_id: str, signature: str, dimensions: list, source: str) -> None:
    conn = _conn()
    conn.execute("INSERT INTO intel_question_dimensions (project_id, rq_id, signature, dimensions_json, source, "
                 "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, rq_id) DO UPDATE SET "
                 "signature = excluded.signature, dimensions_json = excluded.dimensions_json, "
                 "source = excluded.source, updated_at = excluded.updated_at",
                 (project_id, rq_id, signature, json.dumps(dimensions), source, time.time()))
    conn.commit()
    conn.close()

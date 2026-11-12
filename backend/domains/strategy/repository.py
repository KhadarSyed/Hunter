"""Search Strategy repository through SQLAlchemy Core (models.py): strategy versions and their research questions,
query versions, uploaded datasets (bytes also kept in Postgres), sample evaluations, question dimensions and tag
schemas. Research-question edits lock the strategy row (FOR UPDATE) so concurrent edits never collide."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import config, sa
from .models import intel_article_rq, intel_dataset_files, intel_datasets, intel_query_versions
from .models import intel_question_dimensions, intel_question_tag_schemas, intel_sample_evaluations
from .models import intel_search_strategies

# core/store.py star-imports this module: export only the repository functions
__all__ = ["save_search_strategy", "get_latest_strategy", "approve_strategy", "update_strategy_query",
           "get_query_versions", "update_research_question", "get_strategy_project_id", "add_research_question",
           "set_research_question_status", "delete_research_question", "save_dataset", "update_dataset_parsed",
           "update_dataset_error", "get_latest_dataset", "get_datasets_by_project", "approve_dataset",
           "delete_dataset", "get_dataset_by_id", "save_sample_evaluation", "get_latest_evaluation",
           "update_evaluation", "get_question_dimensions", "get_question_tag_schemas", "save_question_tag_schema",
           "save_question_dimensions"]

logger = logging.getLogger(__name__)
S, QV, D, DF, E = (intel_search_strategies, intel_query_versions, intel_datasets, intel_dataset_files,
                   intel_sample_evaluations)


def _first(query) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(query).first()
    return dict(row._mapping) if row else None


# ─── Search Strategies ───────────────────────────────────────────────────────

def save_search_strategy(project_id: int, strategy: dict) -> int:
    """The project's next strategy version, as a draft (version read and row written in one transaction)."""
    with sa.begin() as conn:
        version = (conn.execute(select(func.max(S.c.version)).where(S.c.project_id == project_id)).scalar() or 0) + 1
        return conn.execute(insert(S).values(project_id=project_id, version=version, status="draft",
                                             strategy_json=json.dumps(strategy), created_at=time.time())
                            .returning(S.c.id)).scalar_one()


def get_latest_strategy(project_id: int) -> Optional[dict]:
    d = _first(select(S).where(S.c.project_id == project_id).order_by(S.c.version.desc()).limit(1))
    if not d:
        return None
    d["strategy"] = json.loads(d["strategy_json"])
    return d


def approve_strategy(strategy_id: int, reviewer: str = "analyst") -> bool:
    with sa.begin() as conn:
        conn.execute(update(S).where(S.c.id == strategy_id).values(approval_status="approved", approved_by=reviewer,
                                                                   approved_at=time.time()))
    return True


def update_strategy_query(strategy_id: int, query_type: str, query_text: str) -> int:
    """A new query version, and the strategy's matching query type updated to it (one transaction)."""
    now = time.time()
    with sa.begin() as conn:
        vid = conn.execute(insert(QV).values(
            strategy_id=strategy_id, version_label=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
            query_type=query_type, query_text=query_text, created_at=now).returning(QV.c.id)).scalar_one()
        raw = conn.execute(select(S.c.strategy_json).where(S.c.id == strategy_id)).scalar()
        if raw:
            strategy = json.loads(raw)
            query_versions = strategy.get("query_versions", {})
            if query_type in query_versions:
                query_versions[query_type]["query"] = query_text
                strategy["query_versions"] = query_versions
                conn.execute(update(S).where(S.c.id == strategy_id).values(strategy_json=json.dumps(strategy)))
    return vid


def get_query_versions(strategy_id: int) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(select(QV).where(QV.c.strategy_id == strategy_id)
                                                       .order_by(QV.c.created_at.desc()))]


def _locked(conn, strategy_id: int, *cols):
    """The strategy row, locked until the transaction ends (FOR UPDATE)."""
    return conn.execute(select(*(cols or (S.c.strategy_json,))).where(S.c.id == strategy_id).with_for_update()).first()


def _save(conn, strategy_id: int, strategy: dict) -> None:
    conn.execute(update(S).where(S.c.id == strategy_id).values(strategy_json=json.dumps(strategy)))


def update_research_question(strategy_id: int, question_id: str, question: str, query: str,
                             drop_match_query: bool = False) -> bool:
    """drop_match_query: the caller compared the edit with the effective query (match_query or query) and it differs."""
    with sa.begin() as conn:
        row = _locked(conn, strategy_id)
        if not row:
            return False
        strategy = json.loads(row.strategy_json)
        rqs = strategy.get("research_question_queries", [])
        for rq in rqs:
            if rq.get("question_id") == question_id:
                if drop_match_query or rq.get("query") != query:   # tagging reads match_query first; the edit must win
                    rq.pop("match_query", None)
                rq["question"] = question
                rq["query"] = query
                break
        else:
            return False
        strategy["research_question_queries"] = rqs
        _save(conn, strategy_id, strategy)
    return True


def get_strategy_project_id(strategy_id: int) -> int | None:
    with sa.begin() as conn:
        return conn.execute(select(S.c.project_id).where(S.c.id == strategy_id)).scalar()


def add_research_question(strategy_id: int, question: str, query: str) -> str | None:
    """Append an analyst-added RQ numbered after the highest RQn ever used (a deleted id is never reused); returns its
    id (None if no strategy). The row is locked before the read (FOR UPDATE), so two concurrent adds can't pick the same RQn."""
    with sa.begin() as conn:
        row = _locked(conn, strategy_id)
        if not row:
            return None
        strategy = json.loads(row.strategy_json)
        rqs = strategy.get("research_question_queries", [])
        numbers = [int(rq["question_id"][2:]) for rq in rqs
                   if str(rq.get("question_id", "")).startswith("RQ") and str(rq["question_id"])[2:].isdigit()]
        number = max([*numbers, int(strategy.get("last_rq_number") or 0)], default=0) + 1
        question_id = f"RQ{number}"
        strategy["last_rq_number"] = number
        rqs.append({"question_id": question_id, "question": question, "query": query, "user_added": True,
                    "status": "draft"})
        strategy["research_question_queries"] = rqs
        _save(conn, strategy_id, strategy)
    return question_id


def set_research_question_status(strategy_id: int, question_id: str, status: str) -> bool:
    """Mark one RQ draft or approved (only approved RQs are tagged in the data set); False when it is not found."""
    with sa.begin() as conn:
        row = _locked(conn, strategy_id)
        if not row:
            return False
        strategy = json.loads(row.strategy_json)
        for rq in strategy.get("research_question_queries", []):
            if rq.get("question_id") == question_id:
                rq["status"] = status
                break
        else:
            return False
        _save(conn, strategy_id, strategy)
    return True


def delete_research_question(strategy_id: int, question_id: str) -> bool:
    """Remove the RQ and its Data set rows (tags and decisions), and remember its number so it is never reused."""
    with sa.begin() as conn:
        row = _locked(conn, strategy_id, S.c.project_id, S.c.strategy_json)
        if not row:
            return False
        strategy = json.loads(row.strategy_json)
        rqs = strategy.get("research_question_queries", [])
        kept = [rq for rq in rqs if rq.get("question_id") != question_id]
        if len(kept) == len(rqs):
            return False
        strategy["research_question_queries"] = kept
        if question_id.startswith("RQ") and question_id[2:].isdigit():
            strategy["last_rq_number"] = max(int(strategy.get("last_rq_number") or 0), int(question_id[2:]))
        _save(conn, strategy_id, strategy)
        conn.execute(delete(intel_article_rq).where(intel_article_rq.c.project_id == row.project_id,
                                                    intel_article_rq.c.rq_id == question_id))
    return True


# ─── Datasets ───────────────────────────────────────────────────────────────

def _with_dataset_json(d: dict, preview: bool = True) -> dict:
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
    d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
    if preview:
        d["preview"] = json.loads(d["preview_json"]) if d.get("preview_json") else []
    return d


def save_dataset(project_id: int, file_name: str, file_path: str,
                 record_count: int, column_mapping: dict, stats: dict,
                 preview: list, processing_status: str = "done",
                 research_question_id: str | None = None) -> int:
    with sa.begin() as conn:
        dataset_id = conn.execute(insert(D).values(
            project_id=project_id, file_name=file_name, file_path=file_path, record_count=record_count,
            column_mapping_json=json.dumps(column_mapping), stats_json=json.dumps(stats),
            preview_json=json.dumps(preview), processing_status=processing_status,
            research_question_id=research_question_id, created_at=time.time()).returning(D.c.id)).scalar_one()
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
    try:
        with sa.begin() as conn:            # no RETURNING: the row holds the file bytes
            conn.execute(delete(DF).where(DF.c.dataset_id == dataset_id))
            conn.execute(insert(DF).values(dataset_id=dataset_id, file_name=file_name, content=content,
                                           created_at=time.time()))
    except Exception as e:
        logger.error("dataset %s: could not keep its file in the database (%s)", dataset_id, e)


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
    with sa.begin() as conn:
        content = conn.execute(select(DF.c.content).where(DF.c.dataset_id == d["id"])).scalar()
    if content is None:
        return d
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        partial.write_bytes(bytes(content))
        os.replace(partial, target)
    except OSError as e:
        logger.error("dataset %s: could not restore its file (%s)", d["id"], e)
        return d
    logger.info("dataset %s: file restored from the database to %s", d["id"], target)
    return _repointed(d, target)


def _repointed(d: dict, target: Path) -> dict:
    if str(target) != str(d.get("file_path")):
        with sa.begin() as conn:
            conn.execute(update(D).where(D.c.id == d["id"]).values(file_path=str(target)))
    return {**d, "file_path": str(target)}


def update_dataset_parsed(dataset_id: int, record_count: int,
                          column_mapping: dict, stats: dict, preview: list):
    with sa.begin() as conn:
        conn.execute(update(D).where(D.c.id == dataset_id).values(
            record_count=record_count, column_mapping_json=json.dumps(column_mapping), stats_json=json.dumps(stats),
            preview_json=json.dumps(preview), processing_status="done"))


def update_dataset_error(dataset_id: int, error: str):
    with sa.begin() as conn:
        conn.execute(update(D).where(D.c.id == dataset_id).values(processing_status="error", processing_error=error))


def get_latest_dataset(project_id: int) -> Optional[dict]:
    d = _first(select(D).where(D.c.project_id == project_id).order_by(D.c.created_at.desc(), D.c.id.desc()).limit(1))
    return _restored(_with_dataset_json(d)) if d else None


def get_datasets_by_project(project_id: int) -> list[dict]:
    with sa.begin() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(D).where(D.c.project_id == project_id)
                                                       .order_by(D.c.created_at.desc()))]
    return [_restored(_with_dataset_json(d)) for d in rows]


def approve_dataset(dataset_id: int, reviewer: str = "analyst") -> bool:
    with sa.begin() as conn:
        conn.execute(update(D).where(D.c.id == dataset_id).values(approval_status="approved", approved_by=reviewer,
                                                                  approved_at=time.time()))
    return True


def delete_dataset(dataset_id: int) -> bool:
    with sa.begin() as conn:
        conn.execute(delete(D).where(D.c.id == dataset_id))
        conn.execute(delete(DF).where(DF.c.dataset_id == dataset_id))
    return True


def get_dataset_by_id(dataset_id: int) -> dict | None:
    d = _first(select(D).where(D.c.id == dataset_id))
    return _restored(_with_dataset_json(d, preview=False)) if d else None


# ─── Sample Evaluations ─────────────────────────────────────────────────────

def save_sample_evaluation(project_id: int, strategy_id: int, file_name: str,
                           file_path: str, evaluation: dict | None = None) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(E).values(
            project_id=project_id, strategy_id=strategy_id, file_name=file_name, file_path=file_path,
            evaluation_json=json.dumps(evaluation) if evaluation else None,
            status="completed" if evaluation else "pending", created_at=time.time()).returning(E.c.id)).scalar_one()


def get_latest_evaluation(project_id: int) -> Optional[dict]:
    d = _first(select(E).where(E.c.project_id == project_id).order_by(E.c.created_at.desc(), E.c.id.desc()).limit(1))
    if d and d.get("evaluation_json"):
        d["evaluation"] = json.loads(d["evaluation_json"])
    return d


def update_evaluation(eval_id: int, evaluation: dict):
    with sa.begin() as conn:
        conn.execute(update(E).where(E.c.id == eval_id).values(evaluation_json=json.dumps(evaluation),
                                                               status="completed"))


# ─── Question dimensions and tag schemas ─────────────────────────────────────

def get_question_dimensions(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, dimensions, source} for every question whose dimensions were derived."""
    t = intel_question_dimensions
    with sa.begin() as conn:
        rows = conn.execute(select(t.c.rq_id, t.c.signature, t.c.dimensions_json, t.c.source)
                            .where(t.c.project_id == project_id)).all()
    return {r.rq_id: {"signature": r.signature, "dimensions": json.loads(r.dimensions_json), "source": r.source}
            for r in rows}


def get_question_tag_schemas(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, schema, source} for every question whose dynamic tag schema was derived."""
    t = intel_question_tag_schemas
    with sa.begin() as conn:
        rows = conn.execute(select(t.c.rq_id, t.c.signature, t.c.schema_json, t.c.source)
                            .where(t.c.project_id == project_id)).all()
    return {r.rq_id: {"signature": r.signature, "schema": json.loads(r.schema_json), "source": r.source} for r in rows}


def _upsert_per_question(t, project_id: int, rq_id: str, values: dict) -> None:
    stmt = pg_insert(t).values(project_id=project_id, rq_id=rq_id, updated_at=time.time(), **values)
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[t.c.project_id, t.c.rq_id], set_={
            c: stmt.excluded[c] for c in (*values, "updated_at")}))


def save_question_tag_schema(project_id: int, rq_id: str, signature: str, schema: dict, source: str) -> None:
    _upsert_per_question(intel_question_tag_schemas, project_id, rq_id,
                         {"signature": signature, "schema_json": json.dumps(schema), "source": source})


def save_question_dimensions(project_id: int, rq_id: str, signature: str, dimensions: list, source: str) -> None:
    _upsert_per_question(intel_question_dimensions, project_id, rq_id,
                         {"signature": signature, "dimensions_json": json.dumps(dimensions), "source": source})

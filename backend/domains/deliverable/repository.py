"""The deliverable engine's storage through SQLAlchemy Core (models.py): runs, streamed sections, classification
cache, reference-deck index, analysis plans, "Refresh latest 7 days" results and a finished deck's files."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import intel_article_classifications as classifications
from .models import intel_deliverable_files as files
from .models import intel_deliverable_plans as plans
from .models import intel_deliverable_runs as runs
from .models import intel_deliverable_sections as sections
from .models import intel_latest24h_refreshes as refreshes
from .models import intel_reference_decks as reference_decks

# core/store.py star-imports this module: export only the repository functions and the cache age
__all__ = ["create_deliverable_run", "update_deliverable_run", "get_deliverable_run", "recent_run_durations",
           "get_latest_deliverable_run", "fail_interrupted_deliverable_runs", "get_active_deliverable_run",
           "save_deliverable_section", "replace_deliverable_section", "list_deliverable_sections",
           "CLASSIFICATION_MAX_AGE_S", "get_cached_classification", "save_cached_classification",
           "save_reference_deck", "list_reference_decks", "get_deliverable_plans", "save_deliverable_plan",
           "create_latest24h_refresh", "finish_latest24h_refresh", "get_latest_latest24h_refresh",
           "fail_interrupted_latest24h_refreshes", "save_deck_files", "deck_file_names", "project_deck_s3_keys",
           "deck_file_s3_key", "deck_file_parts"]

_RUN_FIELDS = {"status", "stage", "pptx_path", "docx_path", "thumbs_dir", "error", "finished_at",
               "html_path", "pdf_path", "studio_pptx_path", "deck_dir"}
CLASSIFICATION_MAX_AGE_S = 30 * 86400
_REFRESH_JSON = ("counts", "summary", "charts", "articles")


def _first(query) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(query).first()
    return dict(row._mapping) if row else None


def _with_stages(d: Optional[dict]) -> Optional[dict]:
    if d is None:
        return None
    d["stages"] = json.loads(d.pop("stages_json") or "{}")
    return d


# ─── runs ───────────────────────────────────────────────────────────────────

def create_deliverable_run(project_id: int) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(runs).values(project_id=project_id, status="running", stages_json="{}",
                                                created_at=time.time()).returning(runs.c.id)).scalar_one()


def update_deliverable_run(run_id: int, **fields: Any) -> None:
    values = {k: v for k, v in fields.items() if k in _RUN_FIELDS}      # other keys are ignored
    if "stages_json" in fields:
        values["stages_json"] = json.dumps(fields["stages_json"])
    if values:
        with sa.begin() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id).values(**values))


def get_deliverable_run(run_id: int) -> Optional[dict]:
    return _with_stages(_first(select(runs).where(runs.c.id == run_id)))


def recent_run_durations(limit: int = 5) -> list[float]:
    """Wall-clock seconds of the latest completed runs, newest first (the progress bar's typical duration)."""
    q = (select((runs.c.finished_at - runs.c.created_at).label("d"))
         .where(runs.c.status == "completed", runs.c.finished_at.is_not(None)).order_by(runs.c.id.desc()).limit(limit))
    with sa.begin() as conn:
        return [d for d in conn.execute(q).scalars() if d and d > 0]


def get_latest_deliverable_run(project_id: int) -> Optional[dict]:
    return _with_stages(_first(select(runs).where(runs.c.project_id == project_id)
                               .order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(1)))


def fail_interrupted_deliverable_runs() -> int:
    """Runs still 'running' at startup died with the previous process; without this they block Generate."""
    with sa.begin() as conn:
        # a Fix on a finished deck (its deck_dir is set only once the run has finished) was interrupted, not the run:
        # the deck as last saved is still the deliverable
        repaired = conn.execute(update(runs).where(runs.c.status == "running", runs.c.stage == "repair",
                                                   runs.c.deck_dir.is_not(None)).values(status="completed")).rowcount
        failed = conn.execute(update(runs).where(runs.c.status == "running").values(
            status="failed", error="interrupted by a server restart", finished_at=time.time())).rowcount
    return failed + repaired


def get_active_deliverable_run(project_id: int) -> Optional[dict]:
    return _with_stages(_first(select(runs).where(runs.c.project_id == project_id, runs.c.status == "running")
                               .order_by(runs.c.id.desc()).limit(1)))


# ─── streamed sections ──────────────────────────────────────────────────────

def _section_values(run_id: int, section: dict) -> dict:
    return {"run_id": run_id, "section_key": section.get("id", ""), "rq_id": section.get("rq_id"),
            "module": section.get("module"), "payload_json": json.dumps(section, ensure_ascii=False, default=str),
            "created_at": time.time()}


def save_deliverable_section(run_id: int, section: dict) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(sections).values(**_section_values(run_id, section))
                            .returning(sections.c.id)).scalar_one()


def replace_deliverable_section(run_id: int, section: dict) -> int:
    """One row per key (the run log is rewritten as it grows); delete and insert in one transaction."""
    with sa.begin() as conn:
        conn.execute(delete(sections).where(sections.c.run_id == run_id,
                                            sections.c.section_key == section.get("id", "")))
        return conn.execute(insert(sections).values(**_section_values(run_id, section))
                            .returning(sections.c.id)).scalar_one()


def list_deliverable_sections(run_id: int) -> list[dict]:
    with sa.begin() as conn:
        return [json.loads(p) for p in conn.execute(select(sections.c.payload_json)
                                                    .where(sections.c.run_id == run_id).order_by(sections.c.id))
                .scalars()]


# ─── caches and indexes ─────────────────────────────────────────────────────

def get_cached_classification(norm_url: str, field: str, model: str | None = None) -> Optional[list]:
    """A saved classification, reused only while it is under 30 days old and (when given) made by the same model:
    a better model, or an article that changed, gets classified again."""
    q = select(classifications.c.value_json).where(
        classifications.c.norm_url == norm_url, classifications.c.field == field,
        classifications.c.created_at > time.time() - CLASSIFICATION_MAX_AGE_S)
    if model:
        q = q.where(classifications.c.model == model)
    row = _first(q)
    return json.loads(row["value_json"]) if row else None


def save_cached_classification(norm_url: str, field: str, value: list, model: str) -> None:
    stmt = pg_insert(classifications).values(norm_url=norm_url, field=field, model=model, created_at=time.time(),
                                             value_json=json.dumps(value, ensure_ascii=False))
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[classifications.c.norm_url, classifications.c.field],
                                                set_={c: stmt.excluded[c] for c in ("value_json", "model", "created_at")}))


def save_reference_deck(path: str, text: str, embedding: Optional[list[float]], model: str = "") -> None:
    stmt = pg_insert(reference_decks).values(path=path, text=text, indexed_at=time.time(), model=model,
                                             embedding_json=json.dumps(embedding) if embedding is not None else None)
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[reference_decks.c.path], set_={
            c: stmt.excluded[c] for c in ("text", "embedding_json", "indexed_at", "model")}))


def list_reference_decks() -> list[dict]:
    q = select(reference_decks.c.path, reference_decks.c.text, reference_decks.c.embedding_json,
               reference_decks.c.model)
    with sa.begin() as conn:
        rows = conn.execute(q).all()
    return [{"path": r.path, "text": r.text or "", "model": r.model or "",
             "embedding": json.loads(r.embedding_json) if r.embedding_json else None} for r in rows]


def get_deliverable_plans(project_id: int) -> dict[str, dict]:
    """rq_id -> {signature, plan, source}: each question's last analysis plan (see engine's plan stage)."""
    q = select(plans.c.rq_id, plans.c.signature, plans.c.plan_json, plans.c.source).where(
        plans.c.project_id == project_id)
    with sa.begin() as conn:
        rows = conn.execute(q).all()
    return {r.rq_id: {"signature": r.signature, "plan": json.loads(r.plan_json), "source": r.source} for r in rows}


def save_deliverable_plan(project_id: int, rq_id: str, signature: str, plan: dict, source: str) -> None:
    stmt = pg_insert(plans).values(project_id=project_id, rq_id=rq_id, signature=signature,
                                   plan_json=json.dumps(plan), source=source, updated_at=time.time())
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[plans.c.project_id, plans.c.rq_id], set_={
            c: stmt.excluded[c] for c in ("signature", "plan_json", "source", "updated_at")}))


# ─── "Refresh latest 24h" ───────────────────────────────────────────────────

def create_latest24h_refresh(project_id: int) -> int:
    """A new running refresh (the older ones are dropped once it completes, so a failed refresh keeps the last good one)."""
    with sa.begin() as conn:
        return conn.execute(insert(refreshes).values(project_id=project_id, status="running", started_at=time.time())
                            .returning(refreshes.c.id)).scalar_one()


def finish_latest24h_refresh(refresh_id: int, status: str, counts: dict, fetched: int, kept: int,
                             summary: Any = None, charts: Any = None, articles: Any = None,
                             error: Optional[str] = None) -> None:
    with sa.begin() as conn:
        conn.execute(update(refreshes).where(refreshes.c.id == refresh_id).values(
            status=status, finished_at=time.time(), counts_json=json.dumps(counts), fetched=fetched, kept=kept,
            summary_json=json.dumps(summary), charts_json=json.dumps(charts), articles_json=json.dumps(articles),
            error=error))
        if status == "completed":        # only the latest is ever read: a completed refresh replaces the older ones
            same_project = select(refreshes.c.project_id).where(refreshes.c.id == refresh_id).scalar_subquery()
            conn.execute(delete(refreshes).where(refreshes.c.id != refresh_id, refreshes.c.status != "running",
                                                 refreshes.c.project_id == same_project))


def get_latest_latest24h_refresh(project_id: int) -> Optional[dict]:
    d = _first(select(refreshes).where(refreshes.c.project_id == project_id).order_by(refreshes.c.id.desc()).limit(1))
    if d is None:
        return None
    for key in _REFRESH_JSON:
        d[key] = json.loads(d.pop(f"{key}_json") or "null")
    return d


def fail_interrupted_latest24h_refreshes() -> int:
    """A server restart ends any refresh mid-flight; mark it so the page never waits on it forever."""
    with sa.begin() as conn:
        return conn.execute(update(refreshes).where(refreshes.c.status == "running").values(
            status="failed", error="Interrupted by a server restart", finished_at=time.time())).rowcount


# ─── A finished deck's files (deck_store.py) ────────────────────────────────

def save_deck_files(run_id: int, project_id: int, parts) -> int:
    """Replace the run's stored files with `parts` ((name, part, gz, bytes[, s3_key]) tuples, read one at a time) and drop the
    project's other runs, in one transaction: a failed save keeps the previous run. Returns the bytes stored."""
    total = 0
    now = time.time()
    with sa.begin() as conn:
        conn.execute(delete(files).where(files.c.run_id == run_id))
        for name, part, gz, content, *rest in parts:          # one part in memory at a time; no RETURNING of the bytes
            conn.execute(insert(files).values(run_id=run_id, project_id=project_id, name=name, part=part, gz=gz,
                                              content=content, created_at=now, s3_key=rest[0] if rest else None))
            total += len(content)
        conn.execute(delete(files).where(files.c.project_id == project_id, files.c.run_id != run_id))
    return total


def deck_file_names(run_id: int) -> list[str]:
    with sa.begin() as conn:
        return list(conn.execute(select(files.c.name).distinct().where(files.c.run_id == run_id)).scalars())


def project_deck_s3_keys(project_id: int) -> list[tuple[int, str]]:
    """(run_id, S3 key) of every file of the project's stored decks that lives in S3."""
    with sa.begin() as conn:
        return [(r.run_id, r.s3_key) for r in conn.execute(
            select(files.c.run_id, files.c.s3_key).where(files.c.project_id == project_id, files.c.s3_key.is_not(None)))]


def deck_file_s3_key(run_id: int, name: str) -> Optional[str]:
    """The S3 key the file was stored under, or None when it is kept as chunks."""
    with sa.begin() as conn:
        key = conn.execute(select(files.c.s3_key).where(files.c.run_id == run_id, files.c.name == name,
                                                        files.c.part == 0)).scalar()
    return key or None


def deck_file_parts(run_id: int, name: str):
    """(gz, bytes) of each stored part in order, fetched one at a time so a large file never sits in memory whole."""
    with sa.begin() as conn:
        part_numbers = list(conn.execute(select(files.c.part).where(files.c.run_id == run_id, files.c.name == name)
                                         .order_by(files.c.part)).scalars())
        for part in part_numbers:
            row = conn.execute(select(files.c.gz, files.c.content).where(
                files.c.run_id == run_id, files.c.name == name, files.c.part == part)).one()
            yield row.gz, bytes(row.content)

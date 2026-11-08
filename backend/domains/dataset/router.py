"""Data set API: upload, tag, page/filter, select-all ids, bulk decisions with undo, article edit, per-RQ query panel."""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path as PathParam, Query, UploadFile

from ...agents import question_tag_schema as tag_schema
from ...core import store
from ...core.auth import require_project_access
from ..projects import gates
from ..deliverable import rows as engine_rows
from ..deliverable.labels import theme_key
from . import repository as repo, service
from .schemas import ArticleEdit, DecisionRequest, KeepRequest, RQQuery, UndoRequest

router = APIRouter()
logger = logging.getLogger(__name__)
ProjectId = Annotated[int, PathParam(ge=1)]
RqId = Annotated[str, PathParam(min_length=1, max_length=40)]
Access = Annotated[dict, Depends(require_project_access)]
UNDO_SECONDS = 60
_UNDO: dict[str, tuple[float, int, list[dict]]] = {}   # token -> (expires_at, project_id, snapshot)
_UNDO_LOCK = threading.Lock()


class Filters:
    """Query params shared by the page and select-all endpoints."""
    def __init__(self, channel: Literal["traditional", "social"],
                 status: Literal["all", "approved", "review", "irrelevant", "no_match"] = "all",
                 rq: str | None = Query(None, max_length=40), sentiment: str | None = Query(None, max_length=20),
                 theme: str | None = Query(None, max_length=200), brand: str | None = Query(None, max_length=200),
                 content_status: str | None = Query(None, max_length=40), q: str | None = Query(None, max_length=200),
                 pool: Literal["matched", "irrelevant", "all"] = "matched"):
        self.kw = dict(channel=channel, status=None if status == "all" else status, rq_id=rq, sentiment=sentiment,
                       theme=theme, brand=brand, content_status=content_status, q=q,
                       pool=None if pool == "all" else pool)


def _who(user: dict) -> str:
    return user.get("display_name") or user.get("email") or "analyst"


def _bad_ext(name: str) -> str | None:
    return None if name.lower().endswith(service.ALLOWED_EXT) else "Unsupported file type (use .csv, .xlsx or .xls)"


@router.post("/articles/{project_id}/upload")
def upload(project_id: ProjectId, user: Access, files: list[UploadFile] = File(...)):
    gates.require(project_id, "data_set")
    repo.set_dataset_approval(project_id, None)
    accepted, refused = [], []
    for f in files:
        name = f.filename or "upload"
        err = _bad_ext(name)
        data = b"" if err else f.file.read(service.MAX_FILE_BYTES + 1)   # never read an oversized file whole
        if not err and len(data) > service.MAX_FILE_BYTES:
            err = "File is larger than 50 MB"
        if err:
            refused.append({"file_name": name, "error": err, "rows_read": 0, "added": 0, "duplicates": 0})
        else:
            accepted.append((name, data))
    if not accepted:
        too_big = all(r["error"].startswith("File is larger") for r in refused)
        raise HTTPException(413 if too_big else 400,
                            "; ".join(f"{r['file_name']}: {r['error']}" for r in refused))
    out = service.upload(project_id, accepted, _who(user))
    out["files"] = [*out["files"], *refused]
    return out


@router.get("/articles/{project_id}/files")
def files(project_id: ProjectId, _: Access):
    return repo.list_files(project_id)


FileId = Annotated[int, PathParam(ge=1)]


def _file_of(project_id: int, file_id: int) -> dict:
    f = repo.get_file(project_id, file_id)
    if not f:
        raise HTTPException(404, "No such file in this project")
    return f


@router.get("/articles/{project_id}/files/{file_id}/impact")
def file_impact(project_id: ProjectId, file_id: FileId, _: Access):
    _file_of(project_id, file_id)
    return repo.file_impact(project_id, file_id)


@router.delete("/articles/{project_id}/files/{file_id}")
def delete_file(project_id: ProjectId, file_id: FileId, _: Access):
    f = _file_of(project_id, file_id)
    _guard(project_id)
    out = repo.delete_file(project_id, file_id)
    repo.set_dataset_approval(project_id, None)
    if f.get("s3_key"):
        try:
            from ...core import object_store
            object_store.delete(f["s3_key"])
        except Exception as e:      # the rows are gone; a stray object is only storage
            logger.warning("upload file %s: S3 delete failed (%s)", file_id, type(e).__name__)
    return {"ok": True, **out}


@router.post("/articles/{project_id}/match")
def match(project_id: ProjectId, _: Access):
    """Run each approved research question's Boolean query over the articles (free, no GPT)."""
    gates.require(project_id, "data_set")
    _guard(project_id)
    repo.set_dataset_approval(project_id, None)
    return service.match_rqs(project_id)


@router.post("/articles/{project_id}/approve")
def approve_dataset(project_id: ProjectId, user: Access):
    """The analyst's sign-off on the tagged data set; the deck is built from it straight away."""
    gates.require(project_id, "data_set")
    _guard(project_id)
    counts = repo.tagging_counts(project_id)
    if not counts["total"] or counts["tags"].get("pending", 0):
        raise HTTPException(409, "Tag the matched articles first")
    from ..deliverable import rows as deck_rows
    if not repo.approved_count(project_id, [q.id for q in deck_rows.approved_rqs(project_id)]):
        raise HTTPException(409, "Approve at least one article for a research question first")
    repo.set_dataset_approval(project_id, _who(user))
    from ..deliverable import engine
    try:
        run_id = engine.start_run(project_id)
    except engine.RunBusy as e:
        return {"approved": True, "run_id": None, "note": str(e)}
    return {"approved": True, "run_id": run_id}


@router.post("/articles/{project_id}/tag")
def tag(project_id: ProjectId, user: Access):
    gates.require(project_id, "data_set")
    repo.set_dataset_approval(project_id, None)      # new tags: the analyst approves again
    try:
        return {"job_id": service.start_tagging(project_id, _who(user))}
    except service.TaggingBusy as e:
        raise HTTPException(409, str(e))


@router.get("/articles/{project_id}/tagging")
def tagging(project_id: ProjectId, _: Access):
    return service.tagging_state(project_id)


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) and v else default
    except ValueError:
        return default


def _status(rq_rows: list[dict]) -> str:
    counted = [r for r in rq_rows if r["matched"] or r["decided_by"]]
    if not counted:
        return "No RQ match"
    states = {r["status"] for r in counted}
    return "Approved" if states == {"approved"} else "Irrelevant" if states == {"irrelevant"} else "Review"


def _row(a: dict) -> dict:
    rq_rows = a.pop("rq")
    out = {k: v for k, v in a.items() if k not in ("tags_json", "syndicated_json", "similar_json")}
    out.update(tags=_loads(a.get("tags_json"), {}), syndicated=_loads(a.get("syndicated_json"), None),
               similar=_loads(a.get("similar_json"), None))
    out["rq"] = {r["rq_id"]: {"status": r["status"], "matched": bool(r["matched"]),
                              "match_confidence": r["match_confidence"], "keywords": _loads(r["keywords_json"], []),
                              "tags": _loads(r["tags_json"], {}), "evidence": _loads(r["evidence_json"], {}),
                              "summary": r["summary"], "reason": r["reason"], "decided_by": r["decided_by"],
                              "decided_at": r["decided_at"], "query_changed": bool(r["query_changed"])}
                 for r in rq_rows}
    out["matched_rqs"] = [r["rq_id"] for r in rq_rows if r["matched"]]
    out["status"] = _status(rq_rows)
    return out


def _rq_columns(project_id: int) -> list[dict]:
    schemas = {rq: tag_schema.from_json(row["schema"]) for rq, row in store.get_question_tag_schemas(project_id).items()}
    out = []
    for q in engine_rows.approved_rqs(project_id):
        s = schemas.get(q.id)
        out.append({"id": q.id, "question": q.question,
                    "tag_columns": [{"key": t.tag_name, "type": t.tag_type, "allowed_values": list(t.allowed_values),
                                     "review_column": t.review_column} for t in s.tags] if s else []})
    return out


@router.get("/articles/{project_id}")
def page(project_id: ProjectId, _: Access, f: Annotated[Filters, Depends()],
         offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    arts, total = repo.page(project_id, **f.kw, offset=offset, limit=limit)
    titles = repo.theme_titles(project_id)
    rows = [_row(a) for a in arts]
    for r in rows:     # raw label -> the consolidated title the deck uses
        labels = [v for v in (r["tags"].get("themes") or {}).values() if v]
        r["theme_titles"] = {v: titles.get(theme_key(v), v) for v in labels}
    return {"rows": rows, "total": total, "rqs": _rq_columns(project_id)}


@router.get("/articles/{project_id}/facets")
def facets(project_id: ProjectId, _: Access, channel: Literal["traditional", "social"]):
    out = repo.facets(project_id, channel)
    titles = repo.theme_titles(project_id)
    out["themes"] = [{"label": l, "title": titles.get(theme_key(l), l)} for l in out["themes"]]
    return out


@router.get("/articles/{project_id}/by-ids")
def by_ids(project_id: ProjectId, _: Access, ids: Annotated[list[int], Query(min_length=1, max_length=200)]):
    """Articles of this project by id (Syndicated / Similar lookups across pages)."""
    arts, _n = repo.page(project_id, ids=ids, limit=len(ids))
    return {"rows": [_row(a) for a in arts]}


@router.get("/articles/{project_id}/ids")
def ids(project_id: ProjectId, _: Access, f: Annotated[Filters, Depends()]):
    return {"ids": repo.ids_matching(project_id, **f.kw)}


def _remember(project_id: int, snapshot: list[dict]) -> str:
    token, now = secrets.token_urlsafe(16), time.time()
    with _UNDO_LOCK:
        for k in [k for k, v in _UNDO.items() if v[0] < now]:
            del _UNDO[k]
        _UNDO[token] = (now + UNDO_SECONDS, project_id, snapshot)
    return token


@router.post("/articles/{project_id}/{article_id:int}/keep")      # :int so /decisions/undo never lands here
def keep_relevant(project_id: ProjectId, article_id: Annotated[int, PathParam(ge=1)], req: KeepRequest, user: Access):
    """An analyst keeps an article the organization's exclusion list blocked: their comment is stored, the org
    remembers it, and the free Boolean match runs again so the article can be tagged like any other."""
    gates.require(project_id, "data_set")
    _guard(project_id)
    result = service.keep_relevant(project_id, article_id, _who(user), req.comment.strip())
    if result is None:
        raise HTTPException(404, "Article not found")
    repo.set_dataset_approval(project_id, None)      # the data set changed: the analyst approves again
    return result


@router.post("/articles/{project_id}/decisions")
def decide(project_id: ProjectId, req: DecisionRequest, user: Access):
    by = _who(user)
    if req.rq_id and req.rq_id not in {q.id for q in engine_rows.approved_rqs(project_id)}:
        raise HTTPException(422, f"{req.rq_id} is not an approved research question of this project")
    # no rq_id: the article's matched RQ rows only; an article with none ("No RQ match") is left alone
    snapshot = repo.decide(project_id, req.article_ids, [req.rq_id] if req.rq_id else None, req.status, by, req.reason)
    return {"changed": len(snapshot), "undo_token": _remember(project_id, snapshot)}


@router.post("/articles/{project_id}/decisions/undo")
def undo(project_id: ProjectId, req: UndoRequest, _: Access):
    with _UNDO_LOCK:
        entry = _UNDO.get(req.undo_token)
        if not entry or entry[0] < time.time() or entry[1] != project_id:
            raise HTTPException(404, "Nothing to undo (the undo window has passed)")
        del _UNDO[req.undo_token]
    repo.undo(project_id, entry[2])
    return {"restored": len(entry[2])}


@router.patch("/articles/{project_id}/{article_id}")
def edit(project_id: ProjectId, article_id: Annotated[int, PathParam(ge=1)], req: ArticleEdit, user: Access):
    matched = repo.edit_article(project_id, article_id, req.sentiment, req.themes, req.brands)
    if matched is None:
        raise HTTPException(404, "Article not found")
    if matched:
        repo.decide(project_id, [article_id], matched, "approved", _who(user), "edited")
    return {"ok": True, "approved_rqs": matched}


# ---- query panel ---------------------------------------------------------------------------------------------------
def _approved_rq(project_id: int, rq_id: str):
    rq = next((q for q in engine_rows.approved_rqs(project_id) if q.id == rq_id), None)
    if rq is None:
        raise HTTPException(404, f"{rq_id} is not an approved research question of this project")
    return rq


def _guard(project_id: int) -> None:
    """Changing an RQ while its rows are being tagged or read into a deck would race them."""
    if service.is_tagging(project_id):
        raise HTTPException(409, "Tagging is running for this project; try again when it finishes")
    if repo.deck_run_active(project_id):
        raise HTTPException(409, "A deck is being built or queued for this project; try again when it finishes")


def _schema_view(schema) -> dict:
    return {"fields": [{"name": t.tag_name, "type": t.tag_type, "definition": t.definition, "values": list(t.allowed_values)}
                       for t in (schema.tags if schema else [])]}


@router.get("/articles/{project_id}/rqs")
def rqs(project_id: ProjectId, _: Access):
    schemas = service.rq_schemas(project_id)
    return [{"rq_id": q.id, "question": q.question, "query": q.query, "status": q.status,
             "counts": service.rq_counts(project_id, q, schemas), "schema": _schema_view(schemas.get(q.id))}
            for q in engine_rows.approved_rqs(project_id)]


@router.post("/articles/{project_id}/rqs/{rq_id}/preview")
def preview_rq(project_id: ProjectId, rq_id: RqId, req: RQQuery, _: Access):
    return service.preview(project_id, _approved_rq(project_id, rq_id), req.query)


def _counts(project_id: int, rq_id: str) -> dict:
    return {"counts": service.rq_counts(project_id, _approved_rq(project_id, rq_id), service.rq_schemas(project_id))}


@router.post("/articles/{project_id}/rqs/{rq_id}/save")
def save_rq(project_id: ProjectId, rq_id: RqId, req: RQQuery, _: Access):
    rq = _approved_rq(project_id, rq_id)
    _guard(project_id)
    if req.query == rq.query:          # rq.query is the effective one (match_query or query): nothing to re-match
        return _counts(project_id, rq_id)
    errors = service.query_errors(req.query)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    plan = service.plan_rematch(project_id, rq, req.query)      # before the edit: it reads the pre-edit signature
    strategy = store.get_latest_strategy(project_id)
    if not strategy or not store.update_research_question(strategy["id"], rq_id, rq.question, req.query,
                                                          drop_match_query=True):
        raise HTTPException(404, "Research question not found")
    try:
        service.apply_rematch(project_id, rq_id, plan)
    except Exception:
        logger.exception("Re-match of %s failed for project %s; the query edit is rolled back", rq_id, project_id)
        store.update_research_question(strategy["id"], rq_id, rq.question, rq.query)
        raise HTTPException(500, "The query could not be saved; it was left unchanged")
    return _counts(project_id, rq_id)


@router.get("/articles/{project_id}/rqs/{rq_id}/estimate")
def estimate_rq(project_id: ProjectId, rq_id: RqId, _: Access):
    return service.estimate(project_id, _approved_rq(project_id, rq_id))


@router.post("/articles/{project_id}/rqs/{rq_id}/retag")
def retag_rq(project_id: ProjectId, rq_id: RqId, user: Access):
    _approved_rq(project_id, rq_id)
    _guard(project_id)
    try:
        return {"job_id": service.start_tagging(project_id, _who(user), only_rq=rq_id)}
    except service.TaggingBusy as e:
        raise HTTPException(409, str(e))


@router.delete("/articles/{project_id}/rqs/{rq_id}")
def delete_rq(project_id: ProjectId, rq_id: RqId, _: Access):
    _approved_rq(project_id, rq_id)
    _guard(project_id)
    removed = repo.approved_count(project_id, [rq_id])
    strategy = store.get_latest_strategy(project_id)
    if not strategy or not store.delete_research_question(strategy["id"], rq_id):
        raise HTTPException(404, "Research question not found")
    return {"removed_approved": removed}

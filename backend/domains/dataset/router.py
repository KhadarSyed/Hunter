"""Data set API: upload, tag, page/filter, select-all ids, bulk decisions with undo, article edit."""
from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path as PathParam, Query, UploadFile

from ...agents import question_tag_schema as tag_schema
from ...core import store
from ...core.auth import require_project_access
from ..deliverable import rows as engine_rows
from . import repository as repo, service
from .schemas import ArticleEdit, DecisionRequest, UndoRequest

router = APIRouter()
ProjectId = Annotated[int, PathParam(ge=1)]
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
                 content_status: str | None = Query(None, max_length=40), q: str | None = Query(None, max_length=200)):
        self.kw = dict(channel=channel, status=None if status == "all" else status, rq_id=rq, sentiment=sentiment,
                       theme=theme, brand=brand, content_status=content_status, q=q)


def _who(user: dict) -> str:
    return user.get("display_name") or user.get("email") or "analyst"


def _bad_ext(name: str) -> str | None:
    return None if name.lower().endswith(service.ALLOWED_EXT) else "Unsupported file type (use .csv, .xlsx or .xls)"


@router.post("/articles/{project_id}/upload")
def upload(project_id: ProjectId, user: Access, files: list[UploadFile] = File(...)):
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


@router.post("/articles/{project_id}/tag")
def tag(project_id: ProjectId, user: Access):
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
                              "decided_at": r["decided_at"]} for r in rq_rows}
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
    return {"rows": [_row(a) for a in arts], "total": total, "rqs": _rq_columns(project_id),
            "theme_titles": repo.theme_titles(project_id)}


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


@router.post("/articles/{project_id}/decisions")
def decide(project_id: ProjectId, req: DecisionRequest, user: Access):
    by = _who(user)
    if req.rq_id and req.rq_id not in {q.id for q in engine_rows.approved_rqs(project_id)}:
        raise HTTPException(422, f"{req.rq_id} is not an approved research question of this project")
    if req.rq_id:
        snapshot = repo.decide(project_id, req.article_ids, [req.rq_id], req.status, by, req.reason)
    else:   # every RQ row the article has; an article with none ("No RQ match") gets rows for the approved RQs
        have = repo.articles_with_rq(project_id, req.article_ids)
        snapshot = repo.decide(project_id, [i for i in req.article_ids if i in have], None, req.status, by, req.reason)
        bare = [i for i in req.article_ids if i not in have]
        approved = [q.id for q in engine_rows.approved_rqs(project_id)]
        if bare and approved:
            snapshot += repo.decide(project_id, bare, approved, req.status, by, req.reason)
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

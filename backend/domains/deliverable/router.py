"""Deliverable engine API: start a run, read the latest/any run with its streamed sections, download outputs."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query
from fastapi.responses import FileResponse

from ...core import store
from ...core.auth import require_project_access
from ..deckstudio import data_tables, revise
from . import engine, repair_run
from . import rows as engine_rows
from .schemas import (DataCoverageResponse, DeckDesign, DeckDesignChange, DeckDesignResult, DeliverableRunPayload,
                      DeliverableRunStarted)

router = APIRouter()
_MEDIA = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "html": "text/html", "pdf": "application/pdf",
          "studio_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
ProjectId = Annotated[int, PathParam(ge=1)]
RunId = Annotated[int, PathParam(ge=1)]
Access = Annotated[dict, Depends(require_project_access)]


def _owned_run(project_id: int, run_id: int) -> dict:
    run = store.get_deliverable_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(404, "Run not found")
    return run


def _payload(run_id: int) -> dict:
    """The run with its sections, plus whether its Fix buttons can work (older runs need one regenerate first)."""
    payload = engine.run_payload(run_id)
    run = payload["run"]
    if not run:
        return payload
    return {**payload, "run": {**run, "repairable": repair_run.has_repair_context(run)}}


@router.post("/deliverable/{project_id}/run", response_model=DeliverableRunStarted)
def start(project_id: ProjectId, _: Access):
    try:
        return {"run_id": engine.start_run(project_id)}
    except engine.RunBusy as e:
        raise HTTPException(409, str(e))


@router.post("/deliverable/{project_id}/runs/{run_id}/repair", status_code=202)
def repair(project_id: ProjectId, run_id: RunId, _: Access,
           scope: Annotated[Literal["checks", "brief", "all"], Query()] = "all"):
    """The repair agent on a finished run: the open deck checks, the brief's open asks, or both."""
    _owned_run(project_id, run_id)
    try:
        repair_run.start(project_id, run_id, scope)
    except engine.RunBusy as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id, "scope": scope}


@router.get("/deliverable/{project_id}/coverage", response_model=DataCoverageResponse)
def coverage(project_id: ProjectId, _: Access):
    """Articles per question from the approved datasets, counted as the engine will: a question with no upload of its
    own is still answered by other uploads that match its query (Data Sources shows this instead of 'not approved')."""
    return engine_rows.coverage(project_id)


@router.get("/deliverable/{project_id}/latest", response_model=DeliverableRunPayload)
def latest(project_id: ProjectId, _: Access):
    run = store.get_latest_deliverable_run(project_id)
    return _payload(run["id"]) if run else {"run": None, "sections": []}


@router.get("/deliverable/{project_id}/runs/{run_id}", response_model=DeliverableRunPayload)
def get_run(project_id: ProjectId, run_id: RunId, _: Access):
    _owned_run(project_id, run_id)
    return _payload(run_id)


@router.get("/deliverable/{project_id}/runs/{run_id}/download/{kind}", response_class=FileResponse)
def download(project_id: ProjectId, run_id: RunId, kind: str, _: Access):
    run = _owned_run(project_id, run_id)
    if kind == "xlsx":                     # the data tables sit in the run's own deck folder, never a requested path
        path = next(Path(run["deck_dir"]).glob(f"*{data_tables.FILE_SUFFIX}"), None) if run.get("deck_dir") else None
    else:
        path = run.get(f"{kind}_path") if kind in _MEDIA else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "File not available")
    return FileResponse(path, media_type=_MEDIA[kind], filename=Path(path).name)


# The deck holds model-written HTML: it runs in an opaque origin with no network, so even a sanitiser miss
# cannot reach the API with the viewer's session
_DECK_HEADERS = {
    "Content-Security-Policy": ("sandbox allow-scripts; default-src 'none'; img-src data:; "
                                "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                                "script-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'; "
                                "frame-ancestors 'self'"),
    "X-Content-Type-Options": "nosniff",
}


@router.get("/deliverable/{project_id}/runs/{run_id}/deck/{asset_path:path}", response_class=FileResponse)
def deck_asset(project_id: ProjectId, run_id: RunId, asset_path: str, _: Access):
    """The studio HTML deck and its assets, only from inside this run's deck folder."""
    run = _owned_run(project_id, run_id)
    if not run.get("deck_dir"):
        raise HTTPException(404, "File not available")
    root = Path(run["deck_dir"]).resolve()
    target = (root / asset_path).resolve()
    if not target.is_file() or root not in target.parents:
        raise HTTPException(404, "File not available")
    return FileResponse(target, headers=_DECK_HEADERS if target.suffix.lower() == ".html" else {"X-Content-Type-Options": "nosniff"})


_design_lock = threading.Lock()     # one re-export at a time: it screenshots every slide


def _deck_dir(project_id: int, run_id: int, *, idle: bool = False) -> Path:
    run = _owned_run(project_id, run_id)
    if not run.get("deck_dir") or not (Path(run["deck_dir"]) / "spec.json").is_file():
        raise HTTPException(404, "This run has no deck to restyle")
    if idle and run.get("status") != "completed":
        raise HTTPException(409, "The deck is still being built or repaired")
    return Path(run["deck_dir"])


@router.get("/deliverable/{project_id}/runs/{run_id}/design", response_model=DeckDesign)
def get_design(project_id: ProjectId, run_id: RunId, _: Access):
    deck_dir = _deck_dir(project_id, run_id)
    return revise.design(deck_dir, (store.get_project(project_id) or {}).get("brand") or "")


@router.post("/deliverable/{project_id}/runs/{run_id}/design/preview", response_model=DeckDesignResult)
def preview_design(project_id: ProjectId, run_id: RunId, body: DeckDesignChange, _: Access):
    """The deck re-rendered in the chosen colours as preview.html, in seconds; nothing is saved."""
    return revise.set_design(_deck_dir(project_id, run_id), body.model_dump(exclude_none=True), preview=True)


def _locked(fn):
    if not _design_lock.acquire(blocking=False):
        raise HTTPException(409, "Another deck is being re-exported; try again in a few minutes")
    try:
        out = fn()
    finally:
        _design_lock.release()
    return {"applied": out["applied"], "rejected": out["rejected"]}


@router.post("/deliverable/{project_id}/runs/{run_id}/design", response_model=DeckDesignResult)
def apply_design(project_id: ProjectId, run_id: RunId, body: DeckDesignChange, _: Access):
    """Saves the colours and re-exports the PPTX and PDF (a few minutes for a long deck)."""
    deck_dir = _deck_dir(project_id, run_id, idle=True)
    return _locked(lambda: revise.set_design(deck_dir, body.model_dump(exclude_none=True)))


@router.post("/deliverable/{project_id}/runs/{run_id}/design/reset", response_model=DeckDesignResult)
def reset_design(project_id: ProjectId, run_id: RunId, _: Access):
    deck_dir = _deck_dir(project_id, run_id, idle=True)
    try:
        return _locked(lambda: revise.reset_design(deck_dir))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/deliverable/{project_id}/runs/{run_id}/thumbnail/{n}", response_class=FileResponse)
def thumbnail(project_id: ProjectId, run_id: RunId, n: Annotated[int, PathParam(ge=1)], _: Access):
    run = _owned_run(project_id, run_id)
    folder = Path(run.get("thumbs_dir") or "")
    pngs = sorted(folder.glob("*.png")) if folder.exists() else []
    if n > len(pngs):
        raise HTTPException(404, "Thumbnail not available")
    return FileResponse(pngs[n - 1], media_type="image/png")

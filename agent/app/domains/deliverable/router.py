"""Deliverable engine API: start a run, read the latest/any run with its streamed sections, download outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam
from fastapi.responses import FileResponse

from ...core import store
from ...core.auth import require_project_access
from . import engine
from .schemas import DeliverableRunPayload, DeliverableRunStarted

router = APIRouter()
_MEDIA = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "html": "text/html", "pdf": "application/pdf",
          "studio_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
ProjectId = Annotated[int, PathParam(ge=1)]
RunId = Annotated[int, PathParam(ge=1)]
Access = Annotated[dict, Depends(require_project_access)]


def _owned_run(project_id: int, run_id: int) -> dict:
    run = store.get_deliverable_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/deliverable/{project_id}/run", response_model=DeliverableRunStarted)
def start(project_id: ProjectId, _: Access):
    try:
        return {"run_id": engine.start_run(project_id)}
    except engine.RunBusy as e:
        raise HTTPException(409, str(e))


@router.get("/deliverable/{project_id}/latest", response_model=DeliverableRunPayload)
def latest(project_id: ProjectId, _: Access):
    run = store.get_latest_deliverable_run(project_id)
    return engine.run_payload(run["id"]) if run else {"run": None, "sections": []}


@router.get("/deliverable/{project_id}/runs/{run_id}", response_model=DeliverableRunPayload)
def get_run(project_id: ProjectId, run_id: RunId, _: Access):
    _owned_run(project_id, run_id)
    return engine.run_payload(run_id)


@router.get("/deliverable/{project_id}/runs/{run_id}/download/{kind}", response_class=FileResponse)
def download(project_id: ProjectId, run_id: RunId, kind: str, _: Access):
    run = _owned_run(project_id, run_id)
    path = run.get(f"{kind}_path") if kind in _MEDIA else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "File not available")
    return FileResponse(path, media_type=_MEDIA[kind], filename=Path(path).name)


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
    return FileResponse(target)


@router.get("/deliverable/{project_id}/runs/{run_id}/thumbnail/{n}", response_class=FileResponse)
def thumbnail(project_id: ProjectId, run_id: RunId, n: Annotated[int, PathParam(ge=1)], _: Access):
    run = _owned_run(project_id, run_id)
    folder = Path(run.get("thumbs_dir") or "")
    pngs = sorted(folder.glob("*.png")) if folder.exists() else []
    if n > len(pngs):
        raise HTTPException(404, "Thumbnail not available")
    return FileResponse(pngs[n - 1], media_type="image/png")

"""Agent routes: autopilot control, activity, memory, the copilot, and (super admin) issues and fixes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...core import store
from ...core.auth import get_current_user, require_project_access
from . import autopilot
from .api_client import ToolError
from .schemas import AutopilotStart
from .status import project_status

router = APIRouter()
ProjectId = Annotated[int, Path(ge=1)]


@router.get("/agent/{project_id}")
def agent_state(project_id: ProjectId, _u=Depends(require_project_access)):
    s = project_status(project_id)
    return {"autopilot": store.get_autopilot(project_id),
            "status": {k: s[k] for k in ("project_id", "name", "steps", "next")}}


@router.post("/agent/{project_id}/autopilot/start")
def autopilot_start(project_id: ProjectId, body: AutopilotStart, user=Depends(get_current_user),
                    _u=Depends(require_project_access)):
    try:
        return autopilot.start(project_id, user["id"], body.input_folder)
    except ToolError as e:
        raise HTTPException(400, str(e))


@router.post("/agent/{project_id}/autopilot/stop")
def autopilot_stop(project_id: ProjectId, _u=Depends(require_project_access)):
    autopilot.stop(project_id)
    return {"ok": True}


@router.get("/agent/{project_id}/events")
def agent_events(project_id: ProjectId, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                 after_id: Annotated[int, Query(ge=0)] = 0, _u=Depends(require_project_access)):
    return store.list_agent_events(project_id, limit=limit, after_id=after_id)


@router.get("/agent/{project_id}/memory")
def agent_memory(project_id: ProjectId, _u=Depends(require_project_access)):
    return [m for m in store.list_memory(project_id) if m["kind"] != "pending"]

"""Agent routes: autopilot control, activity, memory, the copilot, and (super admin) issues and fixes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...core import config, store
from ...core.auth import get_current_user, require_project_access
from . import autopilot, copilot
from .api_client import ToolError
from .schemas import AutopilotStart, CopilotMessage
from .status import project_status
from . import memory
from .repair import apply as repair_apply, worktree
from .schemas import RejectBody

router = APIRouter()
ProjectId = Annotated[int, Path(ge=1)]


def _super_admin(user=Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only a super admin can manage fixes")
    return user


@router.get("/agent/admin/issues")
def admin_issues(status: str | None = None, _a=Depends(_super_admin)):
    return store.list_issues(status)


@router.get("/agent/admin/fixes")
def admin_fixes(status: str | None = None, _a=Depends(_super_admin)):
    return store.list_fixes(status)


@router.post("/agent/admin/fixes/{fix_id}/apply")
def admin_apply(fix_id: Annotated[int, Path(ge=1)], admin=Depends(_super_admin)):
    return repair_apply.apply_fix(fix_id, admin["email"])


@router.post("/agent/admin/fixes/{fix_id}/reject")
def admin_reject(fix_id: Annotated[int, Path(ge=1)], body: RejectBody, admin=Depends(_super_admin)):
    fix = store.get_fix(fix_id)
    if not fix or fix["status"] != "proposed":
        raise HTTPException(409, "Only a proposed fix can be rejected")
    store.update_fix(fix_id, status="rejected", note=f"rejected by {admin['email']}: {body.reason}")
    store.set_issue_status(fix["issue_id"], "rejected", body.reason)
    memory.remember(0, "fix", f"fix_{fix_id}", {"outcome": "rejected", "why": body.reason})
    path = config.DATA_DIR / "autofix" / fix["branch"].replace("/", "-")
    if path.exists():
        worktree.remove(worktree.Worktree(path=path, branch=fix["branch"], base=""))
    return {"ok": True}


@router.post("/agent/admin/issues/{issue_id}/retry")
def admin_retry(issue_id: Annotated[int, Path(ge=1)], _a=Depends(_super_admin)):
    store.set_issue_status(issue_id, "open", "retry requested")
    return {"ok": True}


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


@router.post("/agent/{project_id}/copilot")
def copilot_reply(project_id: ProjectId, body: CopilotMessage, user=Depends(get_current_user),
                  _u=Depends(require_project_access)):
    return copilot.reply(project_id, user["id"], body.message, autopilot._llm(), confirm=body.confirm)

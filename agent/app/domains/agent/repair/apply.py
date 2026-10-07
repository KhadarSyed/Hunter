"""Apply a proposed fix to the running app: merge, rebuild the frontend if needed, restart under the supervisor, then
verify after startup (API health + the browser QA re-check of the affected page). A failed check reverts the merge and
restarts again. Auto-apply is rate-limited and switches itself off after repeated rollbacks."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

from ....core import config, store
from .. import memory
from . import worktree

logger = logging.getLogger(__name__)
AUTO_APPLY_PER_HOUR = 3
MAX_CONSECUTIVE_ROLLBACKS = 2
HEALTH_TIMEOUT = 90
HEALTH_DELAY = 3
_GLOBAL = 0
_SETTING = "auto_apply"
_ACTIVE = ("applying", "verifying")


def _setting() -> dict:
    return next((m["value"] for m in store.list_memory(_GLOBAL, "decision") if m["key"] == _SETTING),
                {"enabled": True, "rollbacks": 0})


def auto_apply_enabled() -> bool:
    return bool(_setting().get("enabled", True))


def _auto_applied_last_hour() -> int:
    cutoff = time.time() - 3600
    return sum(1 for f in store.list_fixes() if f["note"].startswith("auto") and f["updated_at"] >= cutoff
               and f["status"] in ("applied", "verifying", "rolled_back"))


def _restart() -> None:
    from agent.supervisor import RESTART_CODE
    threading.Timer(1.0, os._exit, args=(RESTART_CODE,)).start()


def _build_web() -> tuple[int, str]:
    r = subprocess.run(["cmd", "/c", "npm", "run", "build"], cwd=config.REPO_ROOT / "web", capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)[-4000:]


def _running_work() -> int:
    """Deliverable runs and background jobs a restart would kill."""
    return store.count_running_work()


def _refuse(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def _precheck(fix: dict | None, approved_by: str | None) -> str:
    if not fix or fix["status"] != "proposed":
        return "fix is not waiting to be applied"
    if fix["tier"] == "never":
        return "this change touches protected files and is never applied automatically or from the inbox"
    if approved_by is None and fix["tier"] != "auto":
        return "only design-only fixes apply without approval"
    if approved_by is None and not auto_apply_enabled():
        return "auto-apply is disabled after repeated rollbacks"
    if approved_by is None and _auto_applied_last_hour() >= AUTO_APPLY_PER_HOUR:
        return f"auto-apply limit of {AUTO_APPLY_PER_HOUR} per hour reached"
    if any(f["status"] in _ACTIVE for f in store.list_fixes()):
        return "another fix is being applied"
    if os.environ.get("HUNTER_SUPERVISED") != "1":
        return "the backend is not running under the supervisor, so it cannot restart itself"
    busy = _running_work()
    if busy:
        return f"{busy} deliverable run(s) or job(s) are running; the restart would interrupt them"
    if not worktree.tree_clean():
        return "the main checkout has uncommitted changes"
    return ""


def apply_fix(fix_id: int, approved_by: str | None, restart=None, build_web=None) -> dict:
    fix = store.get_fix(fix_id)
    reason = _precheck(fix, approved_by)
    if reason:
        if fix and fix["status"] == "proposed" and "uncommitted" in reason:
            store.update_fix(fix_id, note=f"waiting: {reason}")
        return _refuse(reason)
    store.update_fix(fix_id, status="applying", note="auto" if approved_by is None else f"approved by {approved_by}")
    try:
        sha = worktree.merge(fix["branch"])
    except RuntimeError as e:
        store.update_fix(fix_id, status="proposed", note=f"merge failed: {e}"[:300])
        return _refuse(f"merge failed: {e}")
    test_file = (config.AUTOFIX_DIR / fix["branch"].replace("/", "-") / "agent" / "tests"
                 / f"test_autofix_{fix['issue_id']}.py")
    if test_file.exists():
        shutil.copy2(test_file, config.REPO_ROOT / "agent" / "tests" / test_file.name)
    if "web/" in fix["diff"]:
        code, out = (build_web or _build_web)()
        if code != 0:
            worktree.revert(sha)
            store.update_fix(fix_id, status="rolled_back", note=f"frontend build failed: {out[-200:]}")
            return _refuse("frontend build failed; reverted")
    store.update_fix(fix_id, status="verifying", commit_sha=sha)
    (restart or _restart)()
    return {"status": "verifying", "reason": "merged; restarting to verify"}


def _health() -> bool:
    import requests
    url = f"http://127.0.0.1:{os.environ.get('HUNTER_PORT', '8002')}/api/health"
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=5).json().get("ok"):
                return True
        except Exception:
            time.sleep(2)
    return False


def _qa_user() -> int:
    user = next((u["id"] for u in store.list_users() if u["role"] == "super_admin"), None)
    if user is None:
        raise RuntimeError("no super admin account for the browser check")
    return user


def _qa(fix: dict) -> list[str]:
    issue = store.get_issue(fix["issue_id"]) or {}
    if issue.get("source") != "qa_browser":
        return []
    from ..qa_browser import walk
    page = (issue.get("detail") or {}).get("page") or "dashboard"
    found = walk(f"http://127.0.0.1:{os.environ.get('HUNTER_PORT', '8002')}", _qa_user(), issue.get("project_id") or 0,
                 config.DATA_DIR / "qa" / "verify", [page])
    return [f.detail for f in found if f.kind == issue["kind"]]


def _rolled_back(fix: dict, why: str, setting: dict, build_web) -> None:
    worktree.revert(fix["commit_sha"])
    if "web/" in fix["diff"]:
        (build_web or _build_web)()
    store.update_fix(fix["id"], status="rolled_back", note=f"verify failed: {why[:200]}")
    store.set_issue_status(fix["issue_id"], "open", f"fix {fix['id']} rolled back")
    rollbacks = setting.get("rollbacks", 0) + 1
    store.set_memory(_GLOBAL, "decision", _SETTING, {"enabled": rollbacks < MAX_CONSECUTIVE_ROLLBACKS,
                                                     "rollbacks": rollbacks})
    memory.remember(_GLOBAL, "fix", f"fix_{fix['id']}", {"outcome": "rolled_back", "why": why[:200]})
    if rollbacks >= MAX_CONSECUTIVE_ROLLBACKS:
        from .issues import file_issue
        file_issue("repair", "auto_apply_disabled", "Auto-apply switched off after repeated rollbacks",
                   {"last_fix": fix["id"]})


def verify_pending(health=None, qa=None, restart=None, build_web=None) -> list[int]:
    done = []
    for fix in store.list_fixes("verifying"):
        try:
            ok = (health or _health)()
            still = (qa or _qa)(fix) if ok else ["health check failed"]
        except Exception as e:      # a check that cannot run is a failed check: roll back, never leave it "verifying"
            logger.exception("verification of fix %s could not run", fix["id"])
            ok, still = False, [f"verification could not run: {type(e).__name__}: {e}"]
        setting = _setting()
        if ok and not still:
            store.update_fix(fix["id"], status="applied")
            store.set_issue_status(fix["issue_id"], "fixed", f"fix {fix['id']} applied")
            store.set_memory(_GLOBAL, "decision", _SETTING, {**setting, "rollbacks": 0})
            memory.remember(_GLOBAL, "fix", f"fix_{fix['id']}", {"outcome": "applied", "issue": fix["issue_id"]})
        else:
            _rolled_back(fix, still[0], setting, build_web)
            (restart or _restart)()
        done.append(fix["id"])
    return done


def rollback_verifying(why: str, build_web=None) -> list[int]:
    """Called by the supervisor when the backend dies on startup with a fix still being verified: revert it."""
    rolled = []
    for fix in store.list_fixes("verifying"):
        try:
            _rolled_back(fix, why, _setting(), build_web)
            rolled.append(fix["id"])
        except Exception:
            logger.exception("could not roll back fix %s", fix["id"])
    return rolled


def verify_pending_async() -> None:
    if store.list_fixes("verifying"):
        threading.Timer(HEALTH_DELAY, verify_pending).start()

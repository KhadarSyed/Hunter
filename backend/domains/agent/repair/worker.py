"""Background fix worker: one open issue at a time becomes a proposed fix; design-only fixes then apply themselves."""
from __future__ import annotations

import logging
import threading
import time

from pathlib import Path

from ....core import config, store
from . import apply as apply_mod
from . import fixer, worktree

logger = logging.getLogger(__name__)
POLL_SECONDS = 60


MIN_REPORT_WORDS = 6
_NOTICE_SOURCES = ("repair", "deck_validation")    # notices and missing content, not code defects


def _vague(issue: dict) -> str:
    """Why an issue is too thin for a fix attempt ("" when it is actionable)."""
    detail = issue.get("detail") or {}
    if issue["source"] in _NOTICE_SOURCES:
        return "a notice, not a code defect"
    if not detail:
        return "no detail recorded"
    if issue["source"] == "user":
        words = len(str(detail.get("detail") or "").split()) + len(issue["title"].split())
        if not detail.get("page") or words < MIN_REPORT_WORDS:
            return "needs more detail (which page, what was expected, what happened)"
    return ""


def tick(llm, propose=fixer.propose, apply_fix=apply_mod.apply_fix) -> dict | None:
    """The oldest actionable open issue gets one fix attempt; vague ones wait in triage for a person."""
    issue = None
    for candidate in sorted(store.list_issues("open"), key=lambda i: i["id"]):
        why = _vague(candidate)
        if not why:
            issue = candidate
            break
        store.set_issue_status(candidate["id"], "triage", f"not sent to the fixer: {why}")
    if issue is None:
        return None
    out = propose(issue["id"], llm)
    result = {"issue_id": issue["id"], **out}
    if out.get("status") == "proposed" and (store.get_fix(out["fix_id"]) or {}).get("tier") == "auto":
        result["apply"] = apply_fix(out["fix_id"], None)
    return result


def propose_in_background(issue_id: int) -> bool:
    """An admin's "Propose fix": one proposal at a time, run off the request thread. False when one is already
    running or a fix is being applied."""
    busy = store.list_issues("fixing") or any(f["status"] in ("applying", "verifying") for f in store.list_fixes())
    if busy:
        return False
    store.set_issue_status(issue_id, "fixing", "proposal requested by an admin")

    def work() -> None:
        from ..autopilot import _llm
        try:
            fixer.propose(issue_id, _llm())
        except Exception as e:      # the issue never stays "fixing" because of a crash
            logger.exception("fix proposal for issue %s failed", issue_id)
            store.set_issue_status(issue_id, "discarded", f"fixer error: {type(e).__name__}")
    threading.Thread(target=work, daemon=True, name=f"fix-proposal-{issue_id}").start()
    return True


INTERRUPTED = "proposal interrupted by a restart"


def recover_interrupted(repo: Path | None = None) -> list[int]:
    """At startup no proposal can still be running: an issue left "fixing" was cut off by a restart. It goes back
    to the queue, and any autofix worktree no fix was recorded for is removed."""
    recovered = []
    for issue in store.list_issues("fixing"):
        if INTERRUPTED in (issue.get("note") or ""):        # killed the process twice: a person looks first
            store.set_issue_status(issue["id"], "triage", "proposal interrupted by a restart twice; needs a person")
            continue
        store.set_issue_status(issue["id"], "open", f"{INTERRUPTED}; queued again")
        recovered.append(issue["id"])
    known = {f["branch"].replace("/", "-") for f in store.list_fixes()}
    if config.AUTOFIX_DIR.is_dir():
        for path in config.AUTOFIX_DIR.glob("autofix-*"):
            if path.is_dir() and path.name not in known:
                branch = "autofix/" + path.name[len("autofix-"):]
                try:
                    worktree.remove(worktree.Worktree(path=path, branch=branch, base=""), repo)
                except Exception as e:  # noqa: BLE001 -- a stale folder must never stop startup
                    logger.warning("could not remove stale worktree %s: %s", path.name, type(e).__name__)
    return recovered


def _loop() -> None:
    from ..autopilot import _llm
    while True:
        try:
            if not any(f["status"] in ("applying", "verifying") for f in store.list_fixes()):
                tick(_llm())
        except Exception:       # the worker keeps running; the failure is in the log
            logger.exception("fix worker tick failed")
        time.sleep(POLL_SECONDS)


def start() -> None:
    threading.Thread(target=_loop, daemon=True, name="fix-worker").start()

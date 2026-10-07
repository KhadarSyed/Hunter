"""Background fix worker: one open issue at a time becomes a proposed fix; design-only fixes then apply themselves."""
from __future__ import annotations

import logging
import threading
import time

from ....core import store
from . import apply as apply_mod
from . import fixer

logger = logging.getLogger(__name__)
POLL_SECONDS = 60


def tick(llm, propose=fixer.propose, apply_fix=apply_mod.apply_fix) -> dict | None:
    open_issues = sorted(store.list_issues("open"), key=lambda i: i["id"])
    if not open_issues:
        return None
    issue = open_issues[0]
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

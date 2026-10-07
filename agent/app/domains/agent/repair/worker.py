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

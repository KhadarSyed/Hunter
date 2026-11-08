"""The deck run's own log, reachable from any module the run calls: a fallback (the AI step failed and a rule-based
result stands in) is written there as well as to the server log, so the analyst sees it beside the run's progress."""
from __future__ import annotations

import contextvars
import logging

logger = logging.getLogger(__name__)
_LOG: contextvars.ContextVar = contextvars.ContextVar("deck_run_log", default=None)
_BUDGETS: contextvars.ContextVar = contextvars.ContextVar("deck_run_budgets", default=None)


def bind(log) -> contextvars.Token:
    _BUDGETS.set({})                 # a fresh set of per-run budgets with each run
    return _LOG.set(log)


def take(name: str, limit: int) -> bool:
    """One unit of a per-run budget (e.g. logo vision checks): True while under `limit`; always True outside a run."""
    budgets = _BUDGETS.get()
    if budgets is None:
        return True
    used = budgets.get(name, 0)
    if used >= limit:
        return False
    budgets[name] = used + 1
    return True


def note(message: str) -> None:
    """'Fallback: …' in the current deck run's log; nothing outside a run. Never raises."""
    log = _LOG.get()
    if log is None:
        return
    try:
        log(f"Fallback: {message}")
    except Exception as e:
        logger.debug("run log note skipped: %s", type(e).__name__)

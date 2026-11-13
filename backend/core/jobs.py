"""Managed background-job runner.

Every long-running task (research, strategy generation, execution runs, QC checks,
Brief-to-Deck runs, chat replies) is submitted here instead of spawning ad-hoc threads:
one bounded pool, started/stopped with the app lifespan, and every job failure is
logged with its name instead of dying silently inside a daemon thread.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_WORKERS = 8  # LLM calls are I/O-bound on cloud providers


class JobRunner:
    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._max_workers = max_workers
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def _ensure_pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(self._max_workers, thread_name_prefix="hunter-job")
            return self._pool

    def submit(self, fn: Callable[..., Any], *args: Any, name: str | None = None, **kwargs: Any) -> Future:
        """Run fn(*args, **kwargs) in the background. Exceptions are logged, not raised."""
        job_name = name or getattr(fn, "__name__", "job")
        ctx = contextvars.copy_context()  # the submitter's usage scope and memory flags follow the job

        def run() -> Any:
            try:
                return ctx.run(fn, *args, **kwargs)
            except Exception:
                logger.exception("Background job %r failed", job_name)
                raise

        return self._ensure_pool().submit(run)

    def shutdown(self, wait: bool = False) -> None:
        """Stop accepting jobs; queued-but-not-started jobs are cancelled."""
        with self._lock:
            pool, self._pool = self._pool, None
        if pool:
            pool.shutdown(wait=wait, cancel_futures=True)


runner = JobRunner()
submit = runner.submit

# ─── Jobs that survive a restart ─────────────────────────────────────────────
# A stage registers its job function once (fn(job_id, project_id, **params)); launch() saves the job's inputs with
# its intel_jobs row, and at startup resume_interrupted() starts every job a stopped server left running or queued
# again with the same inputs. The job itself skips what it already finished (its checkpoints, see core/store
# save_checkpoint), and the AI answers it got before the restart are replayed from memory instead of asked again.

_RESUMABLE: dict[str, Callable[..., Any]] = {}
_BOOTED_AT = time.time()
# the request's usage scope: who pays, which stage (also what decides the org's guardrails go into the prompt)
_SCOPE_FIELDS = ("org_id", "user_id", "project_id", "stage")


def resumable(job_type: str):
    """Decorator: fn(job_id, project_id, **params) is the job body for job_type, also used to resume it."""
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        _RESUMABLE[job_type] = fn
        return fn
    return register


def launch(job_type: str, job_id: str, project_id: int, **params: Any) -> str:
    """Create the job row with its inputs (JSON-able) and the caller's usage scope, then run it in the background."""
    from . import store
    from ..domains.usage import service as usage
    scope = {k: v for k, v in {**usage.current(), "project_id": project_id}.items()
             if k in _SCOPE_FIELDS and v is not None}
    store.create_job(job_id, project_id, job_type, params={"args": params, "scope": scope})
    runner.submit(_RESUMABLE[job_type], job_id, project_id, name=f"{job_type}:{project_id}", **params)
    return job_id


def _resume(fn: Callable[..., Any], job: dict) -> None:
    from ..domains.memory import service as memory
    from ..domains.usage import service as usage
    params = job["params"]
    with usage.scope(**params.get("scope", {})), memory.replay(job["created_at"]):
        fn(job["id"], job["project_id"], **params.get("args", {}))


def resume_interrupted() -> dict[str, list[str]]:
    """At startup: every job left running or queued is started again (or cancelled when it cannot be)."""
    from . import store
    out: dict[str, list[str]] = {"resumed": [], "cancelled": []}
    for job in store.claim_interrupted_jobs(_BOOTED_AT):
        fn = _RESUMABLE.get(job["job_type"])
        if fn is None or not isinstance(job["params"], dict):
            store.update_job(job["id"], status="cancelled", error="Canceled: stopped by a server restart")
            store.clear_checkpoints(f"job:{job['id']}")
            out["cancelled"].append(job["id"])
            continue
        logger.info("Resuming %s job %s for project %s after a restart", job["job_type"], job["id"], job["project_id"])
        runner.submit(_resume, fn, job, name=f"resume:{job['job_type']}:{job['project_id']}")
        out["resumed"].append(job["id"])
    return out

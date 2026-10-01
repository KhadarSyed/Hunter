"""Managed background-job runner.

Every long-running task (research, strategy generation, execution runs, QC checks,
Brief-to-Deck runs, chat replies) is submitted here instead of spawning ad-hoc threads:
one bounded pool, started/stopped with the app lifespan, and every job failure is
logged with its name instead of dying silently inside a daemon thread.
"""
from __future__ import annotations

import logging
import threading
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

        def run() -> Any:
            try:
                return fn(*args, **kwargs)
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

"""Watches the briefs inbox folder and triggers a pipeline run for each new
brief file that lands there (debounced so partially-written/copying files are
skipped until they settle)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .brief_parser import SUPPORTED_SUFFIXES

DEBOUNCE_SECONDS = 3.0
IGNORE_PREFIXES = ("~$", ".")


def _is_candidate_brief(path: Path) -> bool:
    return (
        path.suffix.lower() in SUPPORTED_SUFFIXES
        and not path.name.startswith(IGNORE_PREFIXES)
    )


class _Handler(FileSystemEventHandler):
    def __init__(self, on_new_brief: Callable[[Path], None]):
        self._on_new_brief = on_new_brief
        self._pending: dict[str, float] = {}
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _queue(self, path: Path) -> None:
        if not _is_candidate_brief(path):
            return
        with self._lock:
            self._pending[str(path)] = time.time()

    def on_created(self, event):
        if not event.is_directory:
            self._queue(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._queue(Path(event.dest_path))

    def poll_ready(self) -> None:
        now = time.time()
        ready = []
        with self._lock:
            for path_str, first_seen in list(self._pending.items()):
                if now - first_seen >= DEBOUNCE_SECONDS:
                    ready.append(path_str)
                    del self._pending[path_str]
        for path_str in ready:
            path = Path(path_str)
            if path_str in self._seen or not path.exists():
                continue
            self._seen.add(path_str)
            try:
                self._on_new_brief(path)
            except Exception:
                pass


class BriefWatcher:
    def __init__(self, briefs_dir: str, on_new_brief: Callable[[Path], None]):
        self.briefs_dir = briefs_dir
        self._handler = _Handler(on_new_brief)
        self._observer = Observer()
        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        Path(self.briefs_dir).mkdir(parents=True, exist_ok=True)
        self._observer.schedule(self._handler, self.briefs_dir, recursive=False)
        self._observer.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._handler.poll_ready()
            time.sleep(1.0)

    def stop(self) -> None:
        self._stop.set()
        self._observer.stop()
        self._observer.join(timeout=5)

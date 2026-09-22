"""FastAPI app: REST endpoints for history/settings/manual triggers + a
WebSocket that streams live pipeline events (the "live feed") to the UI.

Serves the built React frontend from agent/static/ so a single server
at http://localhost:8000 is all you need — bookmarkable, no Vite required.
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import memory
from . import intelligence_store
from .config import Settings, load_settings, save_settings, ensure_dirs
from .llm_provider import build_llm_client
from .ollama_client import OllamaClient
from .pipeline import run_pipeline, run_template_pipeline
from .watcher import BriefWatcher
from .intelligence_api import router as intel_router, set_broadcast as intel_set_broadcast

app = FastAPI(title="Hunter Brief-to-Deck Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(intel_router)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_run_lock = threading.Lock()
_run_busy = False
_loop: Optional[asyncio.AbstractEventLoop] = None
_watcher: Optional[BriefWatcher] = None


class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self.connections:
                self.connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


def _broadcast_threadsafe(message: dict) -> None:
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast(message), _loop)


def _run_in_background(brief_path: Path, template_mode: bool = False, include_research: bool = False) -> None:
    global _run_busy
    with _run_lock:
        if _run_busy:
            _broadcast_threadsafe({
                "type": "run_queued_conflict",
                "brief_filename": brief_path.name,
                "message": "Another run is already in progress; try again once it finishes.",
            })
            return
        _run_busy = True

    def worker():
        global _run_busy
        try:
            def on_event(event_type: str, payload: dict):
                _broadcast_threadsafe({"type": event_type, **payload})

            _broadcast_threadsafe({"type": "history_updated"})
            if template_mode:
                result = run_template_pipeline(brief_path, on_event=on_event, include_research=include_research)
            else:
                result = run_pipeline(brief_path, on_event=on_event)

            if result.get("status") == "completed":
                output_path = result.get("output_path", "")
                run_id = result.get("run_id")
                research_path = result.get("research_path")
                msg = f"Deck ready!\n\nSaved to: {output_path}"
                if research_path:
                    msg += f"\n\nSecondary Research Report: {research_path}"
                memory.add_chat_message(None, "assistant", msg)
                _broadcast_threadsafe({"type": "chat", "role": "assistant", "content": msg, "run_id": None})
            elif result.get("status") == "failed":
                error = result.get("error", "Unknown error")
                msg = f"Run failed: {error}"
                memory.add_chat_message(None, "assistant", msg)
                _broadcast_threadsafe({"type": "chat", "role": "assistant", "content": msg, "run_id": None})
        finally:
            with _run_lock:
                _run_busy = False
            _broadcast_threadsafe({"type": "history_updated"})

    threading.Thread(target=worker, daemon=True).start()


@app.on_event("startup")
async def on_startup():
    global _loop, _watcher
    _loop = asyncio.get_event_loop()
    memory.init_db()
    intelligence_store.init_intelligence_db()
    intelligence_store.cancel_stale_running_jobs()
    intel_set_broadcast(_broadcast_threadsafe)
    memory.mark_interrupted_runs()
    settings = load_settings()
    ensure_dirs(settings)

    def on_new_brief(path: Path):
        _run_in_background(path)

    _watcher = BriefWatcher(settings.briefs_dir, on_new_brief)
    _watcher.start()


@app.on_event("shutdown")
async def on_shutdown():
    if _watcher:
        _watcher.stop()


# ---- settings ----

class SettingsPayload(BaseModel):
    repo_dir: str
    briefs_dir: str
    output_dir: str
    ignore_patterns: list[str]
    ollama_host: str
    embed_model: str
    chat_model: str
    top_k_candidates: int
    relevance_threshold: float


@app.get("/api/settings")
def get_settings():
    return load_settings().to_dict()


@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    settings = Settings(**payload.dict())
    save_settings(settings)
    ensure_dirs(settings)
    global _watcher
    if _watcher:
        _watcher.stop()

    def on_new_brief(path: Path):
        _run_in_background(path)

    _watcher = BriefWatcher(settings.briefs_dir, on_new_brief)
    _watcher.start()
    return {"ok": True}


@app.get("/api/status")
def status():
    settings = load_settings()
    ollama = OllamaClient(settings.ollama_host, settings.embed_model, settings.chat_model)
    return {
        "ollama_reachable": ollama.is_reachable(),
        "slide_count": memory.slide_count(),
        "deck_count": memory.deck_count(),
        "run_busy": _run_busy,
    }


# ---- history ----

@app.get("/api/runs")
def list_runs():
    return memory.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = memory.get_run(run_id)
    if not run:
        return {"error": "not found"}
    return {
        "run": run,
        "events": memory.list_events(run_id),
        "chat": memory.list_chat_messages(run_id),
    }


@app.get("/api/runs/{run_id}/download")
def download_run(run_id: int):
    run = memory.get_run(run_id)
    if not run or not run.get("output_path") or not Path(run["output_path"]).exists():
        return {"error": "output not available"}
    return FileResponse(
        run["output_path"],
        filename=Path(run["output_path"]).name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: int):
    run = memory.get_run(run_id)
    if not run:
        return {"error": "not found"}
    memory.delete_run(run_id)
    _broadcast_threadsafe({"type": "history_updated"})
    return {"ok": True}


@app.post("/api/runs/reset-lock")
def reset_run_lock():
    """Force-clear the run lock when it gets stuck."""
    global _run_busy
    with _run_lock:
        was_busy = _run_busy
        _run_busy = False
    memory.mark_interrupted_runs()
    _broadcast_threadsafe({"type": "history_updated"})
    return {"ok": True, "was_busy": was_busy}


# ---- manual trigger / chat ----

class TriggerPayload(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = None


@app.post("/api/runs/trigger")
def trigger_run(payload: TriggerPayload):
    settings = load_settings()
    if payload.filename:
        brief_path = Path(settings.briefs_dir) / payload.filename
        if not brief_path.exists():
            return {"error": "file not found in briefs inbox"}
    elif payload.text:
        brief_path = Path(settings.briefs_dir) / f"pasted_brief_{uuid.uuid4().hex[:8]}.txt"
        brief_path.write_text(payload.text, encoding="utf-8")
    else:
        return {"error": "provide either 'text' or 'filename'"}

    user_message = payload.text or f"Run brief: {payload.filename}"
    memory.add_chat_message(None, "user", user_message)
    _broadcast_threadsafe({"type": "chat", "role": "user", "content": user_message, "run_id": None})
    _run_in_background(brief_path)
    return {"ok": True, "brief_filename": brief_path.name}


class TemplateTriggerPayload(BaseModel):
    text: str
    include_research: bool = False


@app.post("/api/runs/template")
def trigger_template_run(payload: TemplateTriggerPayload):
    import tempfile
    tmp_dir = Path(tempfile.gettempdir()) / "hunter_agent_templates"
    tmp_dir.mkdir(exist_ok=True)
    brief_path = tmp_dir / f"template_brief_{uuid.uuid4().hex[:8]}.txt"
    brief_path.write_text(payload.text, encoding="utf-8")

    memory.add_chat_message(None, "user", payload.text)
    _broadcast_threadsafe({"type": "chat", "role": "user", "content": payload.text, "run_id": None})
    _run_in_background(brief_path, template_mode=True, include_research=payload.include_research)
    return {"ok": True, "brief_filename": brief_path.name}


class ChatPayload(BaseModel):
    content: str
    run_id: Optional[int] = None


@app.post("/api/chat")
def post_chat(payload: ChatPayload):
    memory.add_chat_message(payload.run_id, "user", payload.content)
    _broadcast_threadsafe({"type": "chat", "role": "user", "content": payload.content, "run_id": payload.run_id})

    settings = load_settings()
    ollama = build_llm_client(settings)
    recent_runs = memory.list_runs(limit=10)
    if recent_runs:
        runs_summary = "\n".join(
            f"- {r['client_guess'] or r['brief_filename']} ({r['status']}, output: {r['output_path'] or 'n/a'})"
            for r in recent_runs
        )
    else:
        runs_summary = "(no runs recorded yet)"

    def worker():
        try:
            reply = ollama.chat([
                {
                    "role": "system",
                    "content": (
                        "You are the assistant panel of a local Hunter PR deck-building agent. "
                        "Answer briefly and helpfully about past runs, the repository, or how to use the tool. "
                        "To actually build a deck, tell the user to drop a brief file in the inbox folder or use "
                        "the 'New Run' button and paste the brief there - you cannot start a run yourself from chat.\n\n"
                        "The ONLY real run history you know about is listed below. Never invent client names, "
                        "project names, or details beyond this list and general tool usage guidance - if asked "
                        "about something not in this list, say you don't have a record of it rather than guessing.\n\n"
                        f"RECENT RUNS:\n{runs_summary}"
                    ),
                },
                {"role": "user", "content": payload.content},
            ])
        except Exception as e:  # noqa: BLE001
            reply = f"(Ollama error: {e})"
        memory.add_chat_message(payload.run_id, "assistant", reply)
        _broadcast_threadsafe({"type": "chat", "role": "assistant", "content": reply, "run_id": payload.run_id})

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True}


@app.get("/api/chat")
def get_chat(run_id: Optional[int] = None):
    return memory.list_chat_messages(run_id)


@app.delete("/api/chat")
def clear_chat():
    memory.clear_chat_messages()
    _broadcast_threadsafe({"type": "chat_cleared"})
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(ws)


# ---- static frontend (built React app) ----

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not found"}, status_code=404)
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(STATIC_DIR / "index.html"))

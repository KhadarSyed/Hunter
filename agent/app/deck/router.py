"""Brief-to-Deck product routes: settings, status, run history, manual triggers, chat.

Runs are single-flight by design (PowerPoint COM automation and the local LLM are
single-consumer on this machine): a trigger while busy broadcasts
`run_queued_conflict` instead of queuing.
"""
from __future__ import annotations

import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core.api import ApiModel, OkResponse
from ..core.config import Settings, ensure_dirs, load_settings, save_settings
from ..core.events import broadcast
from ..core.jobs import submit
from ..core.llm_provider import build_llm_client
from ..core.ollama_client import OllamaClient
from . import memory
from .pipeline import run_pipeline, run_template_pipeline
from .watcher import BriefWatcher

router = APIRouter(prefix="/api", tags=["brief-to-deck"])

PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TEMPLATE_TMP_DIR = Path(tempfile.gettempdir()) / "hunter_agent_templates"
RECENT_RUNS_FOR_CHAT = 10

_run_lock = threading.Lock()
_run_busy = False
_watcher: BriefWatcher | None = None


# ─── Schemas ─────────────────────────────────────────────────────────────────

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


class StatusResponse(ApiModel):
    ollama_reachable: bool
    slide_count: int
    deck_count: int
    run_busy: bool


class RunDetailResponse(ApiModel):
    run: dict
    events: list[dict]
    chat: list[dict]


class TriggerPayload(BaseModel):
    text: str | None = None
    filename: str | None = None


class TemplateTriggerPayload(BaseModel):
    text: str
    include_research: bool = False


class TriggerResponse(OkResponse):
    brief_filename: str


class ResetLockResponse(OkResponse):
    was_busy: bool


class ChatPayload(BaseModel):
    content: str
    run_id: int | None = None


# ─── Run execution + brief watcher ───────────────────────────────────────────

def _run_worker(brief_path: Path, template_mode: bool, include_research: bool) -> None:
    global _run_busy
    try:
        def on_event(event_type: str, payload: dict) -> None:
            broadcast({"type": event_type, **payload})

        broadcast({"type": "history_updated"})
        if template_mode:
            result = run_template_pipeline(brief_path, on_event=on_event, include_research=include_research)
        else:
            result = run_pipeline(brief_path, on_event=on_event)

        if result.get("status") == "completed":
            msg = f"Deck ready!\n\nSaved to: {result.get('output_path', '')}"
            if result.get("research_path"):
                msg += f"\n\nSecondary Research Report: {result['research_path']}"
        elif result.get("status") == "failed":
            msg = f"Run failed: {result.get('error', 'Unknown error')}"
        else:
            return
        memory.add_chat_message(None, "assistant", msg)
        broadcast({"type": "chat", "role": "assistant", "content": msg, "run_id": None})
    finally:
        with _run_lock:
            _run_busy = False
        broadcast({"type": "history_updated"})


def start_run(brief_path: Path, template_mode: bool = False, include_research: bool = False) -> None:
    global _run_busy
    with _run_lock:
        if _run_busy:
            broadcast({
                "type": "run_queued_conflict",
                "brief_filename": brief_path.name,
                "message": "Another run is already in progress; try again once it finishes.",
            })
            return
        _run_busy = True
    submit(_run_worker, brief_path, template_mode, include_research, name=f"deck-run:{brief_path.name}")


def start_watcher(settings: Settings | None = None) -> None:
    """(Re)start watching the briefs inbox; new files trigger a run."""
    global _watcher
    stop_watcher()
    settings = settings or load_settings()
    _watcher = BriefWatcher(settings.briefs_dir, lambda path: start_run(path))
    _watcher.start()


def stop_watcher() -> None:
    global _watcher
    if _watcher:
        _watcher.stop()
        _watcher = None


# ─── Settings + status ───────────────────────────────────────────────────────

@router.get("/settings", response_model=SettingsPayload)
def get_settings():
    return load_settings().to_dict()


@router.post("/settings", response_model=OkResponse)
def update_settings(payload: SettingsPayload):
    settings = Settings(**payload.model_dump())
    save_settings(settings)
    ensure_dirs(settings)
    start_watcher(settings)
    return OkResponse()


@router.get("/status", response_model=StatusResponse)
def status():
    s = load_settings()
    return StatusResponse(
        ollama_reachable=OllamaClient(s.ollama_host, s.embed_model, s.chat_model).is_reachable(),
        slide_count=memory.slide_count(),
        deck_count=memory.deck_count(),
        run_busy=_run_busy,
    )


# ─── Run history ─────────────────────────────────────────────────────────────

def _get_run_or_404(run_id: int) -> dict:
    run = memory.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/runs", response_model=list[dict])
def list_runs():
    return memory.list_runs()


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: int):
    run = _get_run_or_404(run_id)
    return RunDetailResponse(run=run, events=memory.list_events(run_id), chat=memory.list_chat_messages(run_id))


@router.get("/runs/{run_id}/download")
def download_run(run_id: int):
    output = _get_run_or_404(run_id).get("output_path")
    if not output or not Path(output).exists():
        raise HTTPException(404, "Output not available")
    return FileResponse(output, filename=Path(output).name, media_type=PPTX_MEDIA_TYPE)


@router.delete("/runs/{run_id}", response_model=OkResponse)
def delete_run(run_id: int):
    _get_run_or_404(run_id)
    memory.delete_run(run_id)
    broadcast({"type": "history_updated"})
    return OkResponse()


@router.post("/runs/reset-lock", response_model=ResetLockResponse)
def reset_run_lock():
    """Force-clear the run lock when it gets stuck."""
    global _run_busy
    with _run_lock:
        was_busy, _run_busy = _run_busy, False
    memory.mark_interrupted_runs()
    broadcast({"type": "history_updated"})
    return ResetLockResponse(was_busy=was_busy)


# ─── Manual triggers ─────────────────────────────────────────────────────────

@router.post("/runs/trigger", response_model=TriggerResponse)
def trigger_run(payload: TriggerPayload):
    briefs_dir = Path(load_settings().briefs_dir)
    if payload.filename:
        brief_path = briefs_dir / Path(payload.filename).name  # no path traversal out of the inbox
        if not brief_path.exists():
            raise HTTPException(404, "File not found in briefs inbox")
    elif payload.text:
        brief_path = briefs_dir / f"pasted_brief_{uuid.uuid4().hex[:8]}.txt"
        brief_path.write_text(payload.text, encoding="utf-8")
    else:
        raise HTTPException(400, "Provide either 'text' or 'filename'")

    user_message = payload.text or f"Run brief: {payload.filename}"
    memory.add_chat_message(None, "user", user_message)
    broadcast({"type": "chat", "role": "user", "content": user_message, "run_id": None})
    start_run(brief_path)
    return TriggerResponse(brief_filename=brief_path.name)


@router.post("/runs/template", response_model=TriggerResponse)
def trigger_template_run(payload: TemplateTriggerPayload):
    TEMPLATE_TMP_DIR.mkdir(exist_ok=True)
    brief_path = TEMPLATE_TMP_DIR / f"template_brief_{uuid.uuid4().hex[:8]}.txt"
    brief_path.write_text(payload.text, encoding="utf-8")
    memory.add_chat_message(None, "user", payload.text)
    broadcast({"type": "chat", "role": "user", "content": payload.text, "run_id": None})
    start_run(brief_path, template_mode=True, include_research=payload.include_research)
    return TriggerResponse(brief_filename=brief_path.name)


# ─── Chat ────────────────────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = (
    "You are the assistant panel of a local Hunter PR deck-building agent. "
    "Answer briefly and helpfully about past runs, the repository, or how to use the tool. "
    "To actually build a deck, tell the user to drop a brief file in the inbox folder or use "
    "the 'New Run' button and paste the brief there - you cannot start a run yourself from chat.\n\n"
    "The ONLY real run history you know about is listed below. Never invent client names, "
    "project names, or details beyond this list and general tool usage guidance - if asked "
    "about something not in this list, say you don't have a record of it rather than guessing.\n\n"
    "RECENT RUNS:\n{runs}"
)


def _chat_reply(content: str, run_id: int | None) -> None:
    recent = memory.list_runs(limit=RECENT_RUNS_FOR_CHAT)
    runs = "\n".join(
        f"- {r['client_guess'] or r['brief_filename']} ({r['status']}, output: {r['output_path'] or 'n/a'})"
        for r in recent
    ) or "(no runs recorded yet)"
    try:
        reply = build_llm_client(load_settings()).chat([
            {"role": "system", "content": _CHAT_SYSTEM_PROMPT.format(runs=runs)},
            {"role": "user", "content": content},
        ])
    except Exception as e:  # noqa: BLE001 — surfaced to the user in the chat panel
        reply = f"(LLM error: {e})"
    memory.add_chat_message(run_id, "assistant", reply)
    broadcast({"type": "chat", "role": "assistant", "content": reply, "run_id": run_id})


@router.post("/chat", response_model=OkResponse)
def post_chat(payload: ChatPayload):
    memory.add_chat_message(payload.run_id, "user", payload.content)
    broadcast({"type": "chat", "role": "user", "content": payload.content, "run_id": payload.run_id})
    submit(_chat_reply, payload.content, payload.run_id, name="deck-chat")
    return OkResponse()


@router.get("/chat", response_model=list[dict])
def get_chat(run_id: int | None = None):
    return memory.list_chat_messages(run_id)


@router.delete("/chat", response_model=OkResponse)
def clear_chat():
    memory.clear_chat_messages()
    broadcast({"type": "chat_cleared"})
    return OkResponse()

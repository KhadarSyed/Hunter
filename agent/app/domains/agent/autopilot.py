"""The autopilot: drives one project from brief to delivered deck. Each turn reads status + memory, picks the next
tool (Azure OpenAI tool calling, or the deterministic next step), runs it and records it. State lives in the database,
so a restart resumes the loop (resume_all at startup)."""
from __future__ import annotations

import logging
import threading
import time

from ...core import store
from . import memory
from .api_client import ApiClient
from .status import project_status
from .tools import TOOLS, ToolContext, list_input_files, run_tool, tool_specs

logger = logging.getLogger(__name__)
MAX_STEPS = 60
MAX_FAILURES_PER_STEP = 3
WAIT_SECONDS = 20
_worker = threading.Semaphore(1)          # one project at a time per worker (spec 3.3)
_stop: set[int] = set()
_SYSTEM = ("You are Hunter's autopilot. You move a research project from client brief to delivered deck by calling one "
           "tool per turn. Prefer the suggested next step unless memory says the user wants something else. Never "
           "approve a step whose state is not 'ready'. If a step failed, read why (read_run) before retrying.")


def _api(user_id: int):
    return ApiClient(user_id)


def _llm():
    try:
        from ...core.anthropic_client import get_llm_client
        return get_llm_client()
    except Exception as e:
        logger.warning("autopilot runs deterministically: %s", type(e).__name__)
        return None


def decide(project_id: int, llm, status: dict) -> tuple[str, dict, str]:
    fallback = status["next"] or "wait"
    if llm is None or not getattr(llm, "is_reachable", lambda: False)() or fallback == "wait":
        return fallback, {}, "deterministic next step"
    steps = "\n".join(f"- {s['label']}: {s['state']} {s['detail']}".rstrip() for s in status["steps"])
    prompt = (f"{memory.context(project_id, llm)}\n\nPipeline:\n{steps}\nSuggested next step: {fallback}\n"
              "Call exactly one tool.")
    try:
        reply = llm.chat_tools([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}], tool_specs())
        call = (reply.get("tool_calls") or [None])[0]
        if call and call["name"] in TOOLS and "_raw" not in call["arguments"]:
            return call["name"], call["arguments"], (reply.get("content") or "model choice")[:200]
    except Exception as e:      # an LLM failure never stops the project: take the deterministic step
        logger.warning("autopilot decision fell back: %s", type(e).__name__)
    return fallback, {}, "deterministic next step (model unavailable or chose an unknown tool)"


def drive(project_id: int, user_id: int, llm=None, sleep=time.sleep) -> str:
    failures: dict[str, int] = {}
    api = _api(user_id)
    ctx = ToolContext(project_id=project_id, user_id=user_id, actor="autopilot", api=api, llm=llm)
    try:
        for n in range(1, MAX_STEPS + 1):
            if project_id in _stop:
                _stop.discard(project_id)
                store.upsert_autopilot(project_id, user_id, "stopped", "stopped by user")
                return "stopped"
            status = project_status(project_id)
            if status["next"] is None:
                store.upsert_autopilot(project_id, user_id, "done", "deck delivered")
                memory.record(project_id, "autopilot", "done", {"steps": n - 1})
                return "done"
            name, args, why = decide(project_id, llm, status)
            store.upsert_autopilot(project_id, user_id, "running", f"step {n}: {name}")
            if name == "wait":
                sleep(WAIT_SECONDS)
                continue
            out = run_tool(ctx, name, args)
            if out.get("needs_human"):
                store.upsert_autopilot(project_id, user_id, "blocked", f"{name}: {out['error']}")
                return "blocked"
            if out["ok"]:
                failures.pop(name, None)
                memory.remember(project_id, "decision", f"step_{n}", {"tool": name, "why": why})
                continue
            failures[name] = failures.get(name, 0) + 1
            if failures[name] >= MAX_FAILURES_PER_STEP:
                note = f"{name} failed {failures[name]} times: {out['error']}"[:500]
                store.upsert_autopilot(project_id, user_id, "blocked", note)
                memory.remember(project_id, "fix", f"blocked_{name}", {"error": out["error"]})
                return "blocked"
        store.upsert_autopilot(project_id, user_id, "blocked", f"no delivery after {MAX_STEPS} steps")
        return "blocked"
    finally:
        if api is not None:
            api.close()


def _run(project_id: int, user_id: int) -> None:
    with _worker:
        try:
            drive(project_id, user_id, llm=_llm())
        except Exception as e:      # a crash is recorded so the UI shows it; the thread never dies silently
            logger.exception("autopilot crashed for project %s", project_id)
            store.upsert_autopilot(project_id, user_id, "blocked", f"autopilot error: {e}"[:500])


def _spawn(project_id: int, user_id: int) -> None:
    threading.Thread(target=_run, args=(project_id, user_id), daemon=True, name=f"autopilot-{project_id}").start()


def start(project_id: int, user_id: int, input_folder: str | None = None) -> dict:
    if input_folder:
        list_input_files(input_folder)               # raises ToolError outside the allowed roots
        memory.remember(project_id, "fact", "input_folder", input_folder)
    _stop.discard(project_id)
    store.upsert_autopilot(project_id, user_id, "running", "starting", attempts=0)
    memory.record(project_id, "autopilot", "start", {"input_folder": input_folder})
    _spawn(project_id, user_id)
    return store.get_autopilot(project_id)


def stop(project_id: int) -> None:
    _stop.add(project_id)


def resume_all() -> list[int]:
    resumed = []
    for ap in store.list_autopilots("running"):
        memory.record(ap["project_id"], "autopilot", "resume", {"after": ap["note"]})
        _spawn(ap["project_id"], ap["user_id"])
        resumed.append(ap["project_id"])
    return resumed

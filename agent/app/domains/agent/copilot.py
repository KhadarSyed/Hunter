"""The copilot: a project chat that answers from run data and can act with the autopilot's tools. Costly actions come
back as a pending action the user confirms; nothing destructive exists to call."""
from __future__ import annotations

import json
import threading
import secrets
import time

from ...core import store
from . import memory
from .api_client import ApiClient
from .tools import TOOLS, ToolContext, run_tool, tool_specs

MAX_TOOL_TURNS = 4
PENDING_TTL = 1800
_SYSTEM = ("You are Hunter's copilot for one research project. Answer from tool results, briefly and concretely. "
           "Use read_run to explain scorecards and failures. To change the deck, call the matching tool. You cannot "
           "delete projects or datasets; say so if asked. If the user reports a problem, file it with report_issue.")


def _action(tool: str, out: dict) -> dict:
    return {"tool": tool, "ok": out["ok"], **({"error": out.get("error")} if not out["ok"] else {})}


def _pending(project_id: int, tool: str, args: dict) -> dict:
    pid = secrets.token_hex(8)
    item = {"id": pid, "tool": tool, "args": args, "summary": f"{tool} {json.dumps(args)[:120]}", "at": time.time()}
    store.set_memory(project_id, "pending", pid, item)
    return {k: item[k] for k in ("id", "tool", "args", "summary")}


def _confirm(ctx: ToolContext, pending_id: str) -> dict:
    item = next((m["value"] for m in store.list_memory(ctx.project_id, "pending") if m["key"] == pending_id), None)
    store.delete_memory(ctx.project_id, "pending", pending_id)
    if not item or time.time() - item["at"] > PENDING_TTL:
        return {"reply": "There is no pending action with that id (it may have expired).", "actions": [], "pending": None}
    tool = TOOLS.get(item["tool"])
    if tool is not None and tool.costly:       # minutes long: start it and answer now; progress streams to the page
        _start_background(ctx.project_id, ctx.user_id, item["tool"], item["args"])
        return {"reply": f"Started {item['tool'].replace('_', ' ')}. Progress shows in Recent Activity and the run log.",
                "actions": [{"tool": item["tool"], "ok": True}], "pending": None}
    out = run_tool(ctx, item["tool"], item["args"])
    return {"reply": "Done." if out["ok"] else f"That failed: {out.get('error')}", "actions": [_action(item["tool"], out)],
            "pending": None}


def _start_background(project_id: int, user_id: int, tool: str, args: dict) -> None:
    def work() -> None:
        from .autopilot import _llm
        api = ApiClient(user_id)
        try:
            run_tool(ToolContext(project_id=project_id, user_id=user_id, actor="copilot", api=api, llm=_llm()), tool, args)
        finally:
            api.close()
    threading.Thread(target=work, daemon=True, name=f"copilot-{tool}-{project_id}").start()


def _no_llm(ctx: ToolContext) -> dict:
    result = run_tool(ctx, "project_status", {}).get("result") or {}
    steps = ", ".join(f"{x['label']}: {x['state']}" for x in result.get("steps", []))
    return {"reply": f"The model is unavailable, so I can only report status. {steps}. "
                     f"Next step: {result.get('next') or 'none'}.", "actions": [], "pending": None}


def reply(project_id: int, user_id: int, message: str, llm, confirm: str | None = None, api=None) -> dict:
    own = api is None
    ctx = ToolContext(project_id=project_id, user_id=user_id, actor="copilot", api=api or ApiClient(user_id), llm=llm)
    try:
        return _reply(ctx, message, llm, confirm)
    finally:
        if own:                 # the session this call opened is closed with it
            ctx.api.close()


def _reply(ctx: ToolContext, message: str, llm, confirm: str | None) -> dict:
    project_id = ctx.project_id
    if confirm:
        return _confirm(ctx, confirm)
    memory.record(project_id, "copilot", "copilot_message", {"chars": len(message)})
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return _no_llm(ctx)
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": memory.context(project_id, llm)},
                {"role": "user", "content": message}]
    actions: list[dict] = []
    for _ in range(MAX_TOOL_TURNS):
        out = llm.chat_tools(messages, tool_specs())
        calls = out.get("tool_calls") or []
        if not calls:
            text = (out.get("content") or "").strip() or "I have nothing to add."
            memory.record(project_id, "copilot", "copilot_reply", {"chars": len(text)})
            return {"reply": text, "actions": actions, "pending": None}
        messages.append(out["message"])
        for call in calls:
            tool = TOOLS.get(call["name"])
            if tool is None:
                actions.append({"tool": call["name"], "ok": False, "error": "no such tool"})
                result = {"ok": False, "error": "no such tool; this cannot be done"}
            elif tool.costly:
                pending = _pending(project_id, call["name"], call["arguments"])
                return {"reply": f"This will run {call['name'].replace('_', ' ')}, which takes a while. Confirm to go ahead.",
                        "actions": actions, "pending": pending}
            else:
                result = run_tool(ctx, call["name"], call["arguments"])
                actions.append(_action(call["name"], result))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)[:12000]})
    return {"reply": "I ran out of steps for this question; please narrow it.", "actions": actions, "pending": None}

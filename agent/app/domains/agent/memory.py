"""Per-project memory shared by the autopilot and the copilot, and the prompt context built from it.
The context stays under a fixed token budget: memory rows, then a rolling summary of older events, then the most
recent events."""
from __future__ import annotations

import json
import logging
from collections import Counter

from ...core import store
from ...core.events import broadcast

logger = logging.getLogger(__name__)
MEMORY_KINDS = ("preference", "decision", "fact", "fix")
PROMPT_BUDGET_TOKENS = 6000
RECENT_EVENTS = 30
SUMMARY_KEY = "events"
SUMMARY_SHARE = 0.25          # at most a quarter of the budget goes to the rolling summary
_SUMMARY_PROMPT = ("Summarise this project's agent activity log in at most 120 words: what was done, what failed and "
                   "why, what the user asked for. Plain sentences, no lists.")


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def remember(project_id: int, kind: str, key: str, value) -> None:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind {kind!r}")
    store.set_memory(project_id, kind, key, value)


def record(project_id: int, actor: str, action: str, detail: dict | None = None, run_id: int | None = None) -> int:
    event_id = store.add_agent_event(project_id, actor, action, detail, run_id)
    broadcast({"type": "agent_event", "project_id": project_id, "actor": actor, "action": action, "event_id": event_id})
    return event_id


def _line(e: dict) -> str:
    detail = json.dumps(e["detail"], default=str)[:300] if e.get("detail") else ""
    return f"[{e['id']}] {e['actor']} {e['action']} {detail}".strip()


def _clip(text: str, budget: int) -> str:
    return text if estimate_tokens(text) <= budget else text[: max(0, budget * 4 - 8)] + " …"


def _summary(project_id: int, older: list[dict], llm) -> str:
    upto = older[0]["id"]                       # older is newest-first
    saved = next((m["value"] for m in store.list_memory(project_id, "summary") if m["key"] == SUMMARY_KEY), None)
    if saved and saved.get("upto") == upto:
        return saved["text"]
    text = ""
    if llm is not None and getattr(llm, "is_reachable", lambda: False)():
        try:
            log = "\n".join(_line(e) for e in reversed(older))[-24000:]
            text = (llm.chat([{"role": "system", "content": _SUMMARY_PROMPT},
                              {"role": "user", "content": log}]) or "").strip()
        except Exception as e:      # the deterministic summary below still fits the budget
            logger.warning("memory summary skipped: %s", type(e).__name__)
    if not text:
        counts = Counter(e["action"] for e in older)
        text = f"{len(older)} earlier events: " + ", ".join(f"{a} x{n}" for a, n in counts.most_common(12))
    store.set_memory(project_id, "summary", SUMMARY_KEY, {"upto": upto, "text": text})
    return text


def context(project_id: int, llm=None, budget: int = PROMPT_BUDGET_TOKENS) -> str:
    rows = [m for m in store.list_memory(project_id) if m["kind"] in MEMORY_KINDS]
    facts = "\n".join(f"{m['kind']}: {m['key']} = {json.dumps(m['value'], default=str)[:400]}" for m in rows)
    head = _clip("Project memory:\n" + (facts or "(none)"), budget // 3)
    events = store.list_agent_events(project_id, limit=5000)
    recent, older = events[:RECENT_EVENTS], events[RECENT_EVENTS:]
    summary = _clip("Earlier activity: " + _summary(project_id, older, llm), int(budget * SUMMARY_SHARE)) if older else ""
    room = budget - estimate_tokens(head) - estimate_tokens(summary) - 8
    lines: list[str] = []
    for e in recent:                            # newest first, so the latest always fit
        line = _line(e)
        if estimate_tokens("\n".join(lines + [line])) > room:
            break
        lines.append(line)
    tail = "Recent activity (newest first):\n" + "\n".join(lines)
    return "\n\n".join(part for part in (head, summary, tail) if part)

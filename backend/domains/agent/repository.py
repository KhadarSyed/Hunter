"""The Hunter agent's per-project memory, event log, autopilot state and issues, through SQLAlchemy Core."""
from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import agent_autopilots as autopilots
from .models import agent_events as events
from .models import agent_issues as issues
from .models import agent_memory as memory

# core/store.py star-imports this module: export only the repository functions
__all__ = ["set_memory", "list_memory", "delete_memory", "add_agent_event", "list_agent_events", "upsert_autopilot",
           "get_autopilot", "list_autopilots", "file_issue_row"]

OPEN_ISSUE_STATES = ("open", "triage", "fixing", "proposed", "needs_llm")


def _row(r, json_cols: dict[str, str]) -> dict:
    d = dict(r._mapping)
    for col, name in json_cols.items():
        raw = d.pop(col)
        d[name] = json.loads(raw) if raw else None
    return d


def set_memory(project_id: int, kind: str, key: str, value) -> None:
    stmt = pg_insert(memory).values(project_id=project_id, kind=kind, key=key,
                                    value_json=json.dumps(value, default=str), updated_at=time.time())
    with sa.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=[memory.c.project_id, memory.c.kind, memory.c.key],
                                                set_={"value_json": stmt.excluded.value_json,
                                                      "updated_at": stmt.excluded.updated_at}))


def list_memory(project_id: int, kind: str | None = None) -> list[dict]:
    q = (select(memory.c.project_id, memory.c.kind, memory.c.key, memory.c.value_json, memory.c.updated_at)
         .where(memory.c.project_id == project_id).order_by(memory.c.kind, memory.c.key))
    if kind:
        q = q.where(memory.c.kind == kind)
    with sa.begin() as conn:
        return [_row(r, {"value_json": "value"}) for r in conn.execute(q)]


def delete_memory(project_id: int, kind: str, key: str) -> None:
    with sa.begin() as conn:
        conn.execute(delete(memory).where(memory.c.project_id == project_id, memory.c.kind == kind,
                                          memory.c.key == key))


def add_agent_event(project_id: int, actor: str, action: str, detail: dict | None = None,
                    run_id: int | None = None) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(events).values(
            project_id=project_id, run_id=run_id, actor=actor, action=action,
            detail_json=json.dumps(detail, default=str) if detail is not None else None, at=time.time())
            .returning(events.c.id)).scalar_one()


def list_agent_events(project_id: int, limit: int = 50, after_id: int = 0) -> list[dict]:
    q = (select(events).where(events.c.project_id == project_id, events.c.id > after_id)
         .order_by(events.c.id.desc()).limit(limit))
    with sa.begin() as conn:
        return [_row(r, {"detail_json": "detail"}) for r in conn.execute(q)]


def upsert_autopilot(project_id: int, user_id: int, status: str, note: str = "", attempts: int | None = None) -> None:
    with sa.begin() as conn:
        current = conn.execute(select(autopilots.c.attempts).where(autopilots.c.project_id == project_id)).scalar()
        tries = attempts if attempts is not None else (current if current is not None else 0)
        stmt = pg_insert(autopilots).values(project_id=project_id, user_id=user_id, status=status, note=note,
                                            attempts=tries, updated_at=time.time())
        conn.execute(stmt.on_conflict_do_update(index_elements=[autopilots.c.project_id], set_={
            c: stmt.excluded[c] for c in ("user_id", "status", "note", "attempts", "updated_at")}))


def get_autopilot(project_id: int) -> Optional[dict]:
    with sa.begin() as conn:
        row = conn.execute(select(autopilots).where(autopilots.c.project_id == project_id)).first()
    return dict(row._mapping) if row else None


def list_autopilots(status: str | None = None) -> list[dict]:
    q = select(autopilots).order_by(autopilots.c.updated_at)
    if status:
        q = q.where(autopilots.c.status == status)
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def file_issue_row(fingerprint: str, source: str, kind: str, title: str, detail: dict,
                   project_id: int | None, status: str = "open") -> tuple[int, bool]:
    """(issue id, created?): an open issue with the same fingerprint is counted again instead of duplicated."""
    now = time.time()
    with sa.begin() as conn:
        open_id = conn.execute(select(issues.c.id).where(issues.c.fingerprint == fingerprint,
                                                         issues.c.status.in_(OPEN_ISSUE_STATES))).scalar()
        if open_id is not None:
            conn.execute(update(issues).where(issues.c.id == open_id).values(seen=issues.c.seen + 1, updated_at=now))
            return open_id, False
        issue_id = conn.execute(insert(issues).values(
            project_id=project_id, source=source, kind=kind, title=title, detail_json=json.dumps(detail, default=str),
            fingerprint=fingerprint, status=status, created_at=now, updated_at=now).returning(issues.c.id)).scalar_one()
    return issue_id, True

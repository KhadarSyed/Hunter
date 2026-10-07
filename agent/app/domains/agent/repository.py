"""SQLite access for the Hunter agent: per-project memory, the event log, autopilot state, issues and fixes."""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

OPEN_ISSUE_STATES = ("open", "triage", "fixing", "proposed", "needs_llm")
_FIX_FIELDS = {"status", "note", "commit_sha", "diff", "tier", "tests"}


def _row(r, json_cols: dict[str, str]) -> dict:
    d = dict(r)
    for col, name in json_cols.items():
        raw = d.pop(col)
        d[name] = json.loads(raw) if raw else None
    return d


def set_memory(project_id: int, kind: str, key: str, value) -> None:
    conn = _conn()
    conn.execute("INSERT INTO agent_memory (project_id, kind, key, value_json, updated_at) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(project_id, kind, key) DO UPDATE SET value_json = excluded.value_json, "
                 "updated_at = excluded.updated_at", (project_id, kind, key, json.dumps(value, default=str), time.time()))
    conn.commit()
    conn.close()


def list_memory(project_id: int, kind: str | None = None) -> list[dict]:
    conn = _conn()
    sql = "SELECT project_id, kind, key, value_json, updated_at FROM agent_memory WHERE project_id = ?"
    rows = conn.execute(sql + (" AND kind = ?" if kind else "") + " ORDER BY kind, key",
                        (project_id, kind) if kind else (project_id,)).fetchall()
    conn.close()
    return [_row(r, {"value_json": "value"}) for r in rows]


def delete_memory(project_id: int, kind: str, key: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM agent_memory WHERE project_id = ? AND kind = ? AND key = ?", (project_id, kind, key))
    conn.commit()
    conn.close()


def add_agent_event(project_id: int, actor: str, action: str, detail: dict | None = None,
                    run_id: int | None = None) -> int:
    conn = _conn()
    event_id = conn.execute("INSERT INTO agent_events (project_id, run_id, actor, action, detail_json, at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (project_id, run_id, actor, action,
                             json.dumps(detail, default=str) if detail is not None else None, time.time())).lastrowid
    conn.commit()
    conn.close()
    return event_id


def list_agent_events(project_id: int, limit: int = 50, after_id: int = 0) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_events WHERE project_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
                        (project_id, after_id, limit)).fetchall()
    conn.close()
    return [_row(r, {"detail_json": "detail"}) for r in rows]


def upsert_autopilot(project_id: int, user_id: int, status: str, note: str = "", attempts: int | None = None) -> None:
    conn = _conn()
    current = conn.execute("SELECT attempts FROM agent_autopilots WHERE project_id = ?", (project_id,)).fetchone()
    tries = attempts if attempts is not None else (current["attempts"] if current else 0)
    conn.execute("INSERT INTO agent_autopilots (project_id, user_id, status, note, attempts, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET user_id = excluded.user_id, "
                 "status = excluded.status, note = excluded.note, attempts = excluded.attempts, "
                 "updated_at = excluded.updated_at", (project_id, user_id, status, note, tries, time.time()))
    conn.commit()
    conn.close()


def get_autopilot(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_autopilots WHERE project_id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_autopilots(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_autopilots" + (" WHERE status = ?" if status else "") + " ORDER BY updated_at",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def file_issue_row(fingerprint: str, source: str, kind: str, title: str, detail: dict,
                   project_id: int | None, status: str = "open") -> tuple[int, bool]:
    conn = _conn()
    marks = ",".join("?" * len(OPEN_ISSUE_STATES))
    row = conn.execute(f"SELECT id FROM agent_issues WHERE fingerprint = ? AND status IN ({marks})",
                       (fingerprint, *OPEN_ISSUE_STATES)).fetchone()
    now = time.time()
    if row:
        conn.execute("UPDATE agent_issues SET seen = seen + 1, updated_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        conn.close()
        return row["id"], False
    issue_id = conn.execute("INSERT INTO agent_issues (project_id, source, kind, title, detail_json, fingerprint, "
                            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (project_id, source, kind, title, json.dumps(detail, default=str), fingerprint, status, now,
                             now)).lastrowid
    conn.commit()
    conn.close()
    return issue_id, True


def count_running_work() -> int:
    """Running deliverable runs plus pending/running jobs: what a supervised restart would interrupt.
    (Reads two other domains' tables; it is the agent's own safety check before restarting the app.)"""
    conn = _conn()
    runs = conn.execute("SELECT COUNT(*) FROM intel_deliverable_runs WHERE status = 'running'").fetchone()[0]
    jobs = conn.execute("SELECT COUNT(*) FROM intel_jobs WHERE status IN ('pending', 'running')").fetchone()[0]
    conn.close()
    return runs + jobs


def get_issue(issue_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_issues WHERE id = ?", (issue_id,)).fetchone()
    conn.close()
    return _row(row, {"detail_json": "detail"}) if row else None


def list_issues(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_issues" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [_row(r, {"detail_json": "detail"}) for r in rows]


def set_issue_status(issue_id: int, status: str, note: str = "") -> None:
    conn = _conn()
    conn.execute("UPDATE agent_issues SET status = ?, note = ?, updated_at = ? WHERE id = ?",
                 (status, note, time.time(), issue_id))
    conn.commit()
    conn.close()


def create_fix(issue_id: int, branch: str, tier: str, diff: str, tests: dict) -> int:
    conn = _conn()
    now = time.time()
    fix_id = conn.execute("INSERT INTO agent_fixes (issue_id, branch, tier, diff, tests_json, status, created_at, "
                          "updated_at) VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)",
                          (issue_id, branch, tier, diff, json.dumps(tests), now, now)).lastrowid
    conn.commit()
    conn.close()
    return fix_id


def get_fix(fix_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_fixes WHERE id = ?", (fix_id,)).fetchone()
    conn.close()
    return _row(row, {"tests_json": "tests"}) if row else None


def list_fixes(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_fixes" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [_row(r, {"tests_json": "tests"}) for r in rows]


def update_fix(fix_id: int, **fields) -> None:
    unknown = set(fields) - _FIX_FIELDS
    if unknown:
        raise ValueError(f"unknown fix fields: {sorted(unknown)}")
    if "tests" in fields:
        fields["tests_json"] = json.dumps(fields.pop("tests"))
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = _conn()
    conn.execute(f"UPDATE agent_fixes SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), time.time(), fix_id))
    conn.commit()
    conn.close()

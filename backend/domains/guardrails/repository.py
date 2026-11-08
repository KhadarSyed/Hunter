"""SQL for org_guardrails."""
from __future__ import annotations

import time

from ...core.db import _conn


def list_guardrails(org_id: int, active_only: bool = False) -> list[dict]:
    conn = _conn()
    try:
        sql = "SELECT * FROM org_guardrails WHERE org_id = ?" + (" AND active = 1" if active_only else "")
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", (org_id,)).fetchall()]
    finally:
        conn.close()


def get_guardrail(gid: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM org_guardrails WHERE id = ?", (gid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def add_guardrail(org_id: int, title: str, body: str, active: bool, user_id: int | None) -> int:
    now = time.time()
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO org_guardrails (org_id, title, body, active, updated_by, created_at, "
                           "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (org_id, title, body, int(active), user_id, now, now))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_guardrail(gid: int, title: str, body: str, active: bool, user_id: int | None) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE org_guardrails SET title = ?, body = ?, active = ?, updated_by = ?, updated_at = ? "
                     "WHERE id = ?", (title, body, int(active), user_id, time.time(), gid))
        conn.commit()
    finally:
        conn.close()


def delete_guardrail(gid: int) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM org_guardrails WHERE id = ?", (gid,))
        conn.commit()
    finally:
        conn.close()


def org_id_by_name(name: str) -> int | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM organizations WHERE lower(trim(name)) = lower(trim(?)) ORDER BY id",
                           (name,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

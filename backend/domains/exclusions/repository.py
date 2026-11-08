"""SQL for intel_exclusions (one row per excluded domain or keyword, scoped to an organization)."""
from __future__ import annotations

import time

from ...core.db import _conn


def list_exclusions(org_id: int | None) -> list[dict]:
    conn = _conn()
    try:
        if org_id is None:
            rows = conn.execute("SELECT * FROM intel_exclusions WHERE org_id IS NULL ORDER BY kind, value").fetchall()
        else:
            rows = conn.execute("SELECT * FROM intel_exclusions WHERE org_id = ? ORDER BY kind, value",
                                (org_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def add_exclusion(org_id: int | None, kind: str, value: str, user_id: int) -> dict:
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO intel_exclusions (org_id, kind, value, created_by, created_at) "
                           "VALUES (?, ?, ?, ?, ?)", (org_id, kind, value, user_id, time.time()))
        conn.commit()
        row = conn.execute("SELECT * FROM intel_exclusions WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    return dict(row)


def add_exclusions(org_id: int | None, kind: str, values: list[str], user_id: int) -> int:
    """Many rules in one transaction (bulk import); returns how many were added."""
    if not values:
        return 0
    now = time.time()
    conn = _conn()
    try:
        for v in values:
            conn.execute("INSERT INTO intel_exclusions (org_id, kind, value, created_by, created_at) "
                         "VALUES (?, ?, ?, ?, ?)", (org_id, kind, v, user_id, now))
        conn.commit()
    finally:
        conn.close()
    return len(values)


def get_exclusion(exclusion_id: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM intel_exclusions WHERE id = ?", (exclusion_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def delete_exclusion(exclusion_id: int) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM intel_exclusions WHERE id = ?", (exclusion_id,))
        conn.commit()
    finally:
        conn.close()

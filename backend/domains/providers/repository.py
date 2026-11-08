"""SQL for an organisation's own chat LLM providers (table org_llm_providers, migration 46)."""
from __future__ import annotations

import time

from ...core.db import _conn

FIELDS = ("name", "provider_type", "base_url", "model", "api_version")


def _rows(sql: str, params: tuple) -> list[dict]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def list_for_org(org_id: int) -> list[dict]:
    """The default first, then newest first."""
    return _rows("SELECT * FROM org_llm_providers WHERE org_id = ? ORDER BY is_default DESC, id DESC", (org_id,))


def newest_for_org(org_id: int) -> dict | None:
    rows = _rows("SELECT * FROM org_llm_providers WHERE org_id = ? ORDER BY id DESC LIMIT 1", (org_id,))
    return rows[0] if rows else None


def get(provider_id: int) -> dict | None:
    rows = _rows("SELECT * FROM org_llm_providers WHERE id = ?", (provider_id,))
    return rows[0] if rows else None


def default_for_org(org_id: int) -> dict | None:
    rows = _rows("SELECT * FROM org_llm_providers WHERE org_id = ? AND is_default = 1 ORDER BY id LIMIT 1", (org_id,))
    return rows[0] if rows else None


def create(org_id: int, fields: dict, key_enc: str, key_hint: str, user_id: int) -> int:
    now = time.time()
    conn = _conn()
    try:
        row = conn.execute(
            "INSERT INTO org_llm_providers (org_id, name, provider_type, base_url, model, api_version, api_key_enc, "
            "key_hint, created_at, updated_at, updated_by_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, *(fields[f] for f in FIELDS), key_enc, key_hint, now, now, user_id)).fetchone()
        conn.commit()
        return int(row["id"])
    finally:
        conn.close()


def update(provider_id: int, fields: dict, key_enc: str | None, key_hint: str | None, user_id: int) -> None:
    """A changed connection is untested again."""
    sets = [f"{f} = ?" for f in FIELDS]
    params: list = [fields[f] for f in FIELDS]
    if key_enc is not None:
        sets += ["api_key_enc = ?", "key_hint = ?"]
        params += [key_enc, key_hint]
    sets += ["status = 'untested'", "last_error = ''", "updated_at = ?", "updated_by_user_id = ?"]
    conn = _conn()
    try:
        conn.execute(f"UPDATE org_llm_providers SET {', '.join(sets)} WHERE id = ?",
                     (*params, time.time(), user_id, provider_id))
        conn.commit()
    finally:
        conn.close()


def delete(provider_id: int) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM org_llm_providers WHERE id = ?", (provider_id,))
        conn.commit()
    finally:
        conn.close()


def set_default(org_id: int, provider_id: int | None) -> None:
    """One default per org; None clears it (the org goes back to the platform model). One transaction."""
    conn = _conn()
    try:
        conn.execute("UPDATE org_llm_providers SET is_default = 0 WHERE org_id = ?", (org_id,))
        if provider_id is not None:
            conn.execute("UPDATE org_llm_providers SET is_default = 1 WHERE id = ? AND org_id = ?",
                         (provider_id, org_id))
        conn.commit()
    finally:
        conn.close()


def record_test(provider_id: int, ok: bool, error: str, latency_ms: int) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE org_llm_providers SET status = ?, last_error = ?, last_tested_at = ?, "
                     "last_latency_ms = ? WHERE id = ?",
                     ("ok" if ok else "failed", error[:300], time.time(), latency_ms, provider_id))
        conn.commit()
    finally:
        conn.close()


def project_org(project_id: int) -> int | None:
    rows = _rows("SELECT org_id FROM intel_projects WHERE id = ?", (project_id,))
    return rows[0]["org_id"] if rows else None


_OUTAGE = ("acting_provider_id", "down_since", "failed_calls", "notified", "paused", "last_error")


def get_outage(org_id: int) -> dict | None:
    rows = _rows("SELECT * FROM org_llm_state WHERE org_id = ?", (org_id,))
    return {k: rows[0][k] for k in _OUTAGE} if rows else None


def save_outage(org_id: int, st: dict) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO org_llm_state (org_id, acting_provider_id, down_since, failed_calls, notified, paused, "
            "last_error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (org_id) DO UPDATE SET "
            "acting_provider_id = EXCLUDED.acting_provider_id, down_since = EXCLUDED.down_since, "
            "failed_calls = EXCLUDED.failed_calls, notified = EXCLUDED.notified, paused = EXCLUDED.paused, "
            "last_error = EXCLUDED.last_error, updated_at = EXCLUDED.updated_at",
            (org_id, *(st[k] for k in _OUTAGE), time.time()))
        conn.commit()
    finally:
        conn.close()


def clear_outage(org_id: int) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM org_llm_state WHERE org_id = ?", (org_id,))
        conn.commit()
    finally:
        conn.close()

"""Auth repository: organizations, users, sessions (connection helper: core/db.py)."""
from __future__ import annotations

import secrets
import time

from ...core.db import _conn
from .service import FAILED_LOGIN_LIMIT, LOCKOUT_SECONDS, SESSION_TTL_SECONDS


def create_user(org_id: int | None, email: str, password_hash: str, display_name: str,
                 role: str, must_change_password: bool = True) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO users (org_id, email, password_hash, display_name, role, "
        "must_change_password, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (org_id, email.lower().strip(), password_hash, display_name, role,
         1 if must_change_password else 0, now),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id


def get_user_by_id(user_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_session(user_id: int) -> tuple[str, float]:
    conn = _conn()
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + SESSION_TTL_SECONDS
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, expires_at))
    conn.commit()
    conn.close()
    return token, expires_at


def get_session_user(token: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ? AND u.archived_at IS NULL",
        (token, time.time())).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def record_failed_login(email: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE users SET failed_login_count = failed_login_count + 1, "
        "locked_until = CASE WHEN failed_login_count + 1 >= ? THEN ? ELSE locked_until END "
        "WHERE email = ?",
        (FAILED_LOGIN_LIMIT, time.time() + LOCKOUT_SECONDS, email.lower().strip()))
    conn.commit()
    conn.close()


def clear_failed_logins(email: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE email = ?",
        (email.lower().strip(),))
    conn.commit()
    conn.close()


def is_locked_out(email: str) -> bool:
    user = get_user_by_email(email)
    return bool(user and user["locked_until"] and user["locked_until"] > time.time())


def update_user_password(user_id: int, password_hash: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (password_hash, user_id))
    conn.commit()
    conn.close()


def create_organization(name: str, admin_email: str, admin_display_name: str,
                          admin_temp_password_hash: str) -> dict:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO organizations (name, created_at) VALUES (?, ?)", (name, now))
    org_id = cur.lastrowid
    conn.execute(
        "INSERT INTO users (org_id, email, password_hash, display_name, role, "
        "must_change_password, created_at) VALUES (?, ?, ?, ?, 'admin', 1, ?)",
        (org_id, admin_email.lower().strip(), admin_temp_password_hash, admin_display_name, now))
    conn.commit()
    conn.close()
    return {"id": org_id, "name": name}


def list_organizations() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT o.id, o.name, o.archived_at, u.display_name AS admin_name, u.email AS admin_email "
        "FROM organizations o LEFT JOIN users u ON u.org_id = o.id AND u.role = 'admin' "
        "ORDER BY o.id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def archive_organization(org_id: int) -> dict | None:
    conn = _conn()
    if not conn.execute("SELECT 1 FROM organizations WHERE id = ?", (org_id,)).fetchone():
        conn.close()
        return None
    now = time.time()
    with conn:
        conn.execute("UPDATE organizations SET archived_at = ? WHERE id = ?", (now, org_id))
        conn.execute("UPDATE users SET archived_at = ? WHERE org_id = ? AND archived_at IS NULL",
                     (now, org_id))
        conn.execute(
            "UPDATE intel_projects SET archived_at = ? WHERE org_id = ? AND archived_at IS NULL",
            (now, org_id))
    conn.close()
    return {"id": org_id}


def reactivate_organization(org_id: int) -> dict | None:
    conn = _conn()
    if not conn.execute("SELECT 1 FROM organizations WHERE id = ?", (org_id,)).fetchone():
        conn.close()
        return None
    with conn:
        conn.execute("UPDATE organizations SET archived_at = NULL WHERE id = ?", (org_id,))
    conn.close()
    return {"id": org_id}


def list_users(org_id: int | None = None) -> list[dict]:
    conn = _conn()
    if org_id is not None:
        rows = conn.execute("SELECT * FROM users WHERE org_id = ? ORDER BY id", (org_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def archive_user(user_id: int) -> dict | None:
    conn = _conn()
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        conn.close()
        return None
    conn.execute("UPDATE users SET archived_at = ? WHERE id = ?", (time.time(), user_id))
    conn.commit()
    conn.close()
    return {"id": user_id}


def reactivate_user(user_id: int) -> dict | None:
    conn = _conn()
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        conn.close()
        return None
    conn.execute("UPDATE users SET archived_at = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"id": user_id}


def reassign_projects(from_user_id: int, to_user_id: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "UPDATE intel_projects SET owner_user_id = ? WHERE owner_user_id = ?",
        (to_user_id, from_user_id))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def list_archived() -> dict:
    conn = _conn()
    orgs = [dict(r) for r in conn.execute(
        "SELECT id, name FROM organizations WHERE archived_at IS NOT NULL").fetchall()]
    users = [dict(r) for r in conn.execute(
        "SELECT id, email, display_name, org_id FROM users WHERE archived_at IS NOT NULL").fetchall()]
    projects = [dict(r) for r in conn.execute(
        "SELECT id, project_name, org_id FROM intel_projects WHERE archived_at IS NOT NULL").fetchall()]
    conn.close()
    return {"organizations": orgs, "users": users, "projects": projects}


def update_profile(user_id: int, display_name: str, avatar_url: str | None = None) -> None:
    conn = _conn()
    if avatar_url is not None:
        conn.execute("UPDATE users SET display_name = ?, avatar_url = ? WHERE id = ?",
                     (display_name, avatar_url, user_id))
    else:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
    conn.commit()
    conn.close()

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

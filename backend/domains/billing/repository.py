"""SQL for plans, org subscriptions, per-user token limits and the admin dashboards."""
from __future__ import annotations

import time

from ...core.db import _conn

ORG_PROFILE_FIELDS = ("logo_url", "procurement_name", "procurement_email", "procurement_phone", "address",
                      "country", "pin_code")
_PLAN_FIELDS = ("name", "max_users", "max_projects", "duration_months", "price", "currency", "active")


def _all(sql: str, params: tuple = ()) -> list[dict]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: tuple = ()) -> dict | None:
    rows = _all(sql, params)
    return rows[0] if rows else None


def _write(sql: str, params: tuple = ()) -> int | None:
    conn = _conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ─── plans ──────────────────────────────────────────────────────────────────────────────────────────────────

def list_plans(include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else " WHERE active = 1"
    return _all(f"SELECT * FROM subscription_plans{where} ORDER BY price, id")


def get_plan(plan_id: int) -> dict | None:
    return _one("SELECT * FROM subscription_plans WHERE id = ?", (plan_id,))


def create_plan(fields: dict) -> int:
    cols = [f for f in _PLAN_FIELDS if f in fields]
    return _write(f"INSERT INTO subscription_plans ({', '.join(cols)}, created_at) VALUES "
                  f"({', '.join('?' for _ in cols)}, ?)", (*[fields[c] for c in cols], time.time()))


def update_plan(plan_id: int, fields: dict) -> None:
    cols = [f for f in _PLAN_FIELDS if f in fields]
    if cols:
        _write(f"UPDATE subscription_plans SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
               (*[fields[c] for c in cols], plan_id))


# ─── subscriptions ──────────────────────────────────────────────────────────────────────────────────────────

def create_subscription(org_id: int, plan_id: int, status: str, created_by: int | None,
                        starts_at: float | None = None, ends_at: float | None = None,
                        payment_ref: str | None = None) -> int:
    return _write("INSERT INTO org_subscriptions (org_id, plan_id, status, starts_at, ends_at, payment_ref, "
                  "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (org_id, plan_id, status, starts_at, ends_at, payment_ref, created_by, time.time()))


def get_subscription(sub_id: int) -> dict | None:
    return _one("SELECT s.*, p.name AS plan_name, p.max_users, p.max_projects, p.duration_months, p.price, "
                "p.currency FROM org_subscriptions s JOIN subscription_plans p ON p.id = s.plan_id WHERE s.id = ?",
                (sub_id,))


def update_subscription(sub_id: int, **fields) -> None:
    cols = list(fields)
    _write(f"UPDATE org_subscriptions SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
           (*[fields[c] for c in cols], sub_id))


def org_subscriptions(org_id: int) -> list[dict]:
    """Every paid or running subscription of the org, newest first (abandoned checkouts left out)."""
    return _all("SELECT s.*, p.name AS plan_name, p.max_users, p.max_projects, p.duration_months, p.price, "
                "p.currency FROM org_subscriptions s JOIN subscription_plans p ON p.id = s.plan_id "
                "WHERE s.org_id = ? AND s.status IN ('active', 'queued', 'expired') ORDER BY s.starts_at DESC, s.id DESC",
                (org_id,))


def subscriptions_with_status(*statuses: str) -> list[dict]:
    marks = ", ".join("?" for _ in statuses)
    return _all("SELECT s.*, p.name AS plan_name FROM org_subscriptions s JOIN subscription_plans p ON p.id = s.plan_id "
                f"WHERE s.status IN ({marks})", statuses)


# ─── counts and spend ───────────────────────────────────────────────────────────────────────────────────────

def org_user_count(org_id: int) -> int:
    """Seats in use: the org's own users plus users shared into it (Super Admins never count)."""
    row = _one("SELECT COUNT(*) AS n FROM users WHERE archived_at IS NULL AND role <> 'super_admin' AND (org_id = ? "
               "OR id IN (SELECT user_id FROM user_organizations WHERE org_id = ?))", (org_id, org_id))
    return int(row["n"]) if row else 0


def org_project_count(org_id: int) -> int:
    row = _one("SELECT COUNT(*) AS n FROM intel_projects WHERE org_id = ? AND archived_at IS NULL", (org_id,))
    return int(row["n"]) if row else 0


def user_tokens_since(user_id: int, since: float) -> int:
    """A user's spend: calls they made plus calls on projects they own (the Usage page's attribution)."""
    row = _one("SELECT COALESCE(SUM(total_tokens), 0) AS n FROM llm_usage WHERE ts >= ? AND (user_id = ? OR "
               "project_id IN (SELECT id FROM intel_projects WHERE owner_user_id = ?))", (since, user_id, user_id))
    return int(row["n"]) if row else 0


def org_tokens_since(since: float) -> dict[int, int]:
    rows = _all("SELECT org_id, COALESCE(SUM(total_tokens), 0) AS n FROM llm_usage WHERE ts >= ? AND org_id IS NOT "
                "NULL GROUP BY org_id", (since,))
    return {r["org_id"]: int(r["n"]) for r in rows}


def project_tokens(org_id: int) -> dict[int, int]:
    rows = _all("SELECT project_id, COALESCE(SUM(total_tokens), 0) AS n FROM llm_usage WHERE project_id IN "
                "(SELECT id FROM intel_projects WHERE org_id = ?) GROUP BY project_id", (org_id,))
    return {r["project_id"]: int(r["n"]) for r in rows}


# ─── token limits ───────────────────────────────────────────────────────────────────────────────────────────

def get_token_limit(user_id: int) -> dict | None:
    return _one("SELECT * FROM user_token_limits WHERE user_id = ?", (user_id,))


def token_limits_for(user_ids: list[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    marks = ", ".join("?" for _ in user_ids)
    return {r["user_id"]: r for r in _all(f"SELECT * FROM user_token_limits WHERE user_id IN ({marks})",
                                          tuple(user_ids))}


def set_token_limit(user_id: int, monthly_tokens: int | None) -> None:
    _write("INSERT INTO user_token_limits (user_id, monthly_tokens, updated_at) VALUES (?, ?, ?) "
           "ON CONFLICT(user_id) DO UPDATE SET monthly_tokens = excluded.monthly_tokens, "
           "updated_at = excluded.updated_at", (user_id, monthly_tokens, time.time()))


def mark_token_notified(user_id: int, period: str) -> None:
    _write("UPDATE user_token_limits SET notified_period = ? WHERE user_id = ?", (period, user_id))


# ─── org profile + dashboard reads ──────────────────────────────────────────────────────────────────────────

def update_org_profile(org_id: int, fields: dict) -> None:
    cols = [f for f in ORG_PROFILE_FIELDS if f in fields]
    if cols:
        _write(f"UPDATE organizations SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
               (*[fields[c] for c in cols], org_id))


def org_profile(org_id: int) -> dict | None:
    return _one(f"SELECT id, name, archived_at, created_at, {', '.join(ORG_PROFILE_FIELDS)} FROM organizations "
                "WHERE id = ?", (org_id,))


def all_orgs() -> list[dict]:
    return _all(f"SELECT id, name, archived_at, created_at, {', '.join(ORG_PROFILE_FIELDS)} FROM organizations "
                "ORDER BY name")


def org_users(org_id: int) -> list[dict]:
    """The org's own users with their last sign-in (newest session)."""
    return _all("SELECT u.id, u.email, u.display_name, u.role, u.archived_at, u.created_at, "
                "(SELECT MAX(s.created_at) FROM sessions s WHERE s.user_id = u.id) AS last_login "
                "FROM users u WHERE u.org_id = ? AND u.role <> 'super_admin' ORDER BY u.display_name", (org_id,))


def org_projects(org_id: int) -> list[dict]:
    return _all("SELECT p.id, p.project_name, p.brand, p.created_at, p.updated_at, p.owner_user_id, "
                "u.display_name AS owner_name, u.email AS owner_email FROM intel_projects p "
                "LEFT JOIN users u ON u.id = p.owner_user_id WHERE p.org_id = ? AND p.archived_at IS NULL "
                "ORDER BY p.updated_at DESC", (org_id,))


def platform_counts() -> dict:
    row = _one("SELECT (SELECT COUNT(*) FROM organizations WHERE archived_at IS NULL) AS orgs, "
               "(SELECT COUNT(*) FROM users WHERE archived_at IS NULL AND role <> 'super_admin') AS users, "
               "(SELECT COUNT(*) FROM intel_projects WHERE archived_at IS NULL) AS projects")
    return {k: int(v or 0) for k, v in (row or {}).items()}

"""Plans, org subscriptions, per-user token limits and the admin dashboards, through SQLAlchemy Core (models.py)."""
from __future__ import annotations

import time

from sqlalchemy import Select, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import (ORG_PROFILE_FIELDS, intel_projects, llm_usage, org_subscriptions, organizations, sessions,
                     subscription_plans, user_organizations, user_token_limits, users)

_PLAN_FIELDS = ("name", "max_users", "max_projects", "duration_months", "price", "currency", "active")
_PAID_STATUSES = ("active", "queued", "expired")
plans, subs = subscription_plans, org_subscriptions


def _all(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


def _one(query) -> dict | None:
    rows = _all(query)
    return rows[0] if rows else None


def _scalar(query) -> int:
    with sa.begin() as conn:
        return int(conn.execute(query).scalar() or 0)


def _run(statement):
    with sa.begin() as conn:
        return conn.execute(statement)


# ─── plans ──────────────────────────────────────────────────────────────────────────────────────────────────

def list_plans(include_inactive: bool = False) -> list[dict]:
    q = select(plans).order_by(plans.c.price, plans.c.id)
    return _all(q if include_inactive else q.where(plans.c.active == 1))


def get_plan(plan_id: int) -> dict | None:
    return _one(select(plans).where(plans.c.id == plan_id))


def create_plan(fields: dict) -> int:
    values = {f: fields[f] for f in _PLAN_FIELDS if f in fields}
    with sa.begin() as conn:
        return conn.execute(insert(plans).values(**values, created_at=time.time()).returning(plans.c.id)).scalar_one()


def update_plan(plan_id: int, fields: dict) -> None:
    values = {f: fields[f] for f in _PLAN_FIELDS if f in fields}
    if values:
        _run(update(plans).where(plans.c.id == plan_id).values(**values))


# ─── subscriptions ──────────────────────────────────────────────────────────────────────────────────────────

def _with_plan() -> Select:
    return (select(subs, plans.c.name.label("plan_name"), plans.c.max_users, plans.c.max_projects,
                   plans.c.duration_months, plans.c.price, plans.c.currency)
            .join(plans, plans.c.id == subs.c.plan_id))


def create_subscription(org_id: int, plan_id: int, status: str, created_by: int | None, starts_at: float,
                        ends_at: float) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(subs).values(
            org_id=org_id, plan_id=plan_id, status=status, starts_at=starts_at, ends_at=ends_at,
            payment_ref="granted", reminders="", created_by=created_by, created_at=time.time(),
        ).returning(subs.c.id)).scalar_one()


def get_subscription(sub_id: int) -> dict | None:
    return _one(_with_plan().where(subs.c.id == sub_id))


def update_subscription(sub_id: int, **fields) -> None:
    _run(update(subs).where(subs.c.id == sub_id).values(**fields))    # an unknown column name raises


def org_subscriptions(org_id: int) -> list[dict]:
    """Every applied subscription of the org (active, queued or expired), newest first."""
    return _all(_with_plan().where(subs.c.org_id == org_id, subs.c.status.in_(_PAID_STATUSES))
                .order_by(subs.c.starts_at.desc(), subs.c.id.desc()))


def subscriptions_with_status(*statuses: str) -> list[dict]:
    return _all(select(subs, plans.c.name.label("plan_name")).join(plans, plans.c.id == subs.c.plan_id)
                .where(subs.c.status.in_(statuses)))


# ─── counts and spend ───────────────────────────────────────────────────────────────────────────────────────

def _owned_projects(user_id: int):
    return select(intel_projects.c.id).where(intel_projects.c.owner_user_id == user_id)


def org_user_count(org_id: int) -> int:
    """Seats in use: the org's own users plus users shared into it (Super Admins never count)."""
    shared = select(user_organizations.c.user_id).where(user_organizations.c.org_id == org_id)
    return _scalar(select(func.count()).select_from(users).where(
        users.c.archived_at.is_(None), users.c.role != "super_admin",
        or_(users.c.org_id == org_id, users.c.id.in_(shared))))


def org_project_count(org_id: int) -> int:
    return _scalar(select(func.count()).select_from(intel_projects).where(
        intel_projects.c.org_id == org_id, intel_projects.c.archived_at.is_(None)))


def _tokens():
    return func.coalesce(func.sum(llm_usage.c.total_tokens), 0)


def user_tokens_since(user_id: int, since: float) -> int:
    """A user's spend: calls they made plus calls on projects they own (the Usage page's attribution)."""
    return _scalar(select(_tokens()).where(
        llm_usage.c.ts >= since,
        or_(llm_usage.c.user_id == user_id, llm_usage.c.project_id.in_(_owned_projects(user_id)))))


def org_tokens_since(since: float) -> dict[int, int]:
    rows = _all(select(llm_usage.c.org_id, _tokens().label("n"))
                .where(llm_usage.c.ts >= since, llm_usage.c.org_id.is_not(None)).group_by(llm_usage.c.org_id))
    return {r["org_id"]: int(r["n"]) for r in rows}


def project_tokens(org_id: int) -> dict[int, int]:
    org_projects_q = select(intel_projects.c.id).where(intel_projects.c.org_id == org_id)
    rows = _all(select(llm_usage.c.project_id, _tokens().label("n"))
                .where(llm_usage.c.project_id.in_(org_projects_q)).group_by(llm_usage.c.project_id))
    return {r["project_id"]: int(r["n"]) for r in rows}


# ─── token limits ───────────────────────────────────────────────────────────────────────────────────────────

def get_token_limit(user_id: int) -> dict | None:
    return _one(select(user_token_limits).where(user_token_limits.c.user_id == user_id))


def token_limits_for(user_ids: list[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    rows = _all(select(user_token_limits).where(user_token_limits.c.user_id.in_(user_ids)))
    return {r["user_id"]: r for r in rows}


def set_token_limit(user_id: int, monthly_tokens: int | None) -> None:
    stmt = pg_insert(user_token_limits).values(user_id=user_id, monthly_tokens=monthly_tokens, notified_period="",
                                               updated_at=time.time())
    _run(stmt.on_conflict_do_update(index_elements=[user_token_limits.c.user_id], set_={
        "monthly_tokens": stmt.excluded.monthly_tokens, "updated_at": stmt.excluded.updated_at}))


def mark_token_notified(user_id: int, period: str) -> None:
    _run(update(user_token_limits).where(user_token_limits.c.user_id == user_id).values(notified_period=period))


# ─── org profile + dashboard reads ──────────────────────────────────────────────────────────────────────────

def _org_columns():
    return [organizations.c.id, organizations.c.name, organizations.c.archived_at, organizations.c.created_at,
            *(organizations.c[f] for f in ORG_PROFILE_FIELDS)]


def update_org_profile(org_id: int, fields: dict) -> None:
    values = {f: fields[f] for f in ORG_PROFILE_FIELDS if f in fields}
    if values:
        _run(update(organizations).where(organizations.c.id == org_id).values(**values))


def org_profile(org_id: int) -> dict | None:
    return _one(select(*_org_columns()).where(organizations.c.id == org_id))


def all_orgs() -> list[dict]:
    return _all(select(*_org_columns()).order_by(organizations.c.name))


def org_users(org_id: int) -> list[dict]:
    """The org's own users with their last sign-in (newest session)."""
    last_login = (select(func.max(sessions.c.created_at)).where(sessions.c.user_id == users.c.id)
                  .scalar_subquery().label("last_login"))
    return _all(select(users.c.id, users.c.email, users.c.display_name, users.c.role, users.c.archived_at,
                       users.c.created_at, last_login)
                .where(users.c.org_id == org_id, users.c.role != "super_admin").order_by(users.c.display_name))


def org_projects(org_id: int) -> list[dict]:
    p = intel_projects
    return _all(select(p.c.id, p.c.project_name, p.c.brand, p.c.created_at, p.c.updated_at, p.c.owner_user_id,
                       users.c.display_name.label("owner_name"), users.c.email.label("owner_email"))
                .select_from(p.outerjoin(users, users.c.id == p.c.owner_user_id))
                .where(p.c.org_id == org_id, p.c.archived_at.is_(None)).order_by(p.c.updated_at.desc()))


def platform_counts() -> dict:
    def count(table, *where):
        return select(func.count()).select_from(table).where(*where).scalar_subquery()
    row = _one(select(
        count(organizations, organizations.c.archived_at.is_(None)).label("orgs"),
        count(users, users.c.archived_at.is_(None), users.c.role != "super_admin").label("users"),
        count(intel_projects, intel_projects.c.archived_at.is_(None)).label("projects")))
    return {k: int(v or 0) for k, v in (row or {}).items()}

"""Auth repository: organizations, users, sessions, memberships and password resets, through SQLAlchemy Core
(models.py). Multi-step writes (delete user/org, archive org, complete a reset) each run in one transaction."""
from __future__ import annotations

import secrets
import time

from sqlalchemy import and_, case, delete, exists, func, insert, literal, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core import sa
from .models import intel_projects, organizations, password_resets, sessions, user_organizations, users
from .service import FAILED_LOGIN_LIMIT, LOCKOUT_SECONDS, SESSION_TTL_SECONDS

# core/store.py star-imports this module: export only the repository functions, not SQLAlchemy helpers or tables
__all__ = [
    "create_user", "get_user_by_id", "get_user_by_email", "create_session", "get_session_user", "set_session_org",
    "delete_session", "record_failed_login", "clear_failed_logins", "is_locked_out", "update_user_password",
    "reset_user_password", "create_organization_for_member", "create_organization", "get_organization_by_id",
    "list_organizations", "get_organization", "delete_user", "delete_organization", "archive_organization",
    "reactivate_organization", "list_users", "archive_user", "reactivate_user", "reassign_projects",
    "list_archived", "update_profile", "find_organization_by_name", "create_bare_organization", "has_super_admin",
    "make_super_admin", "is_member_of_org", "add_user_to_org", "list_user_organizations", "create_password_reset",
    "recent_reset_count", "open_otp_reset", "bump_reset_attempts", "verify_reset", "reset_by_token",
    "complete_reset", "set_platform_llm", "org_uses_platform_llm", "org_name_taken",
    "get_allow_editorial_images", "set_allow_editorial_images",
]

O, U, S, M, R, P = organizations, users, sessions, user_organizations, password_resets, intel_projects


def _norm(email: str) -> str:
    return email.lower().strip()


def _one(query) -> dict | None:
    with sa.begin() as conn:
        row = conn.execute(query).first()
    return dict(row._mapping) if row else None


def _all(query) -> list[dict]:
    with sa.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(query)]


def _run(statement) -> int:
    """Execute one write; the affected row count."""
    with sa.begin() as conn:
        return conn.execute(statement).rowcount


# ─── users and sessions ─────────────────────────────────────────────────────────────────────────────────────────

def create_user(org_id: int | None, email: str, password_hash: str, display_name: str,
                role: str, must_change_password: bool = True) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(U).values(
            org_id=org_id, email=_norm(email), password_hash=password_hash, display_name=display_name, role=role,
            must_change_password=1 if must_change_password else 0, created_at=time.time()).returning(U.c.id)).scalar_one()


def get_user_by_id(user_id: int) -> dict | None:
    return _one(select(U).where(U.c.id == user_id))


def get_user_by_email(email: str) -> dict | None:
    return _one(select(U).where(U.c.email == _norm(email)))


def create_session(user_id: int, ttl_seconds: int = SESSION_TTL_SECONDS) -> tuple[str, float]:
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + ttl_seconds
    _run(insert(S).values(token=token, user_id=user_id, created_at=now, expires_at=expires_at))
    return token, expires_at


def get_session_user(token: str) -> dict | None:
    """The session's user. An active org picked in the profile menu (still a membership, or any live org for a
    Super Admin) replaces org_id for this session; primary_org_id keeps the user's own."""
    with sa.begin() as conn:
        row = conn.execute(select(U, S.c.active_org_id.label("session_org_id")).join(S, U.c.id == S.c.user_id)
                           .where(S.c.token == token, S.c.expires_at > time.time(), U.c.archived_at.is_(None))).first()
        if not row:
            return None
        user = dict(row._mapping)
        active = user.pop("session_org_id", None)
        user["primary_org_id"] = user["org_id"]
        if active is not None and active != user["org_id"]:
            live_org = select(O.c.id).where(O.c.id == active, O.c.archived_at.is_(None))
            if user["role"] != "super_admin":
                live_org = live_org.where(exists().where(M.c.user_id == user["id"], M.c.org_id == O.c.id))
            if conn.execute(live_org).first():
                user["org_id"] = active
    user["active_org_id"] = user["org_id"] if active is not None else None
    return user


def set_session_org(token: str, org_id: int | None) -> None:
    _run(update(S).where(S.c.token == token).values(active_org_id=org_id))


def delete_session(token: str) -> None:
    _run(delete(S).where(S.c.token == token))


def record_failed_login(email: str) -> None:
    attempts = U.c.failed_login_count + 1                   # SET expressions read the row as it was before the update
    _run(update(U).where(U.c.email == _norm(email)).values(
        failed_login_count=attempts,
        locked_until=case((attempts >= FAILED_LOGIN_LIMIT, time.time() + LOCKOUT_SECONDS), else_=U.c.locked_until)))


def clear_failed_logins(email: str) -> None:
    _run(update(U).where(U.c.email == _norm(email)).values(failed_login_count=0, locked_until=None))


def is_locked_out(email: str) -> bool:
    user = get_user_by_email(email)
    return bool(user and user["locked_until"] and user["locked_until"] > time.time())


def update_user_password(user_id: int, password_hash: str) -> None:
    _run(update(U).where(U.c.id == user_id).values(password_hash=password_hash, must_change_password=0))


def reset_user_password(user_id: int, password_hash: str) -> None:
    """Admin-initiated reset — unlike update_user_password (self-service), this sets
    must_change_password=1 so the handed-out temp password is forced to change on next login."""
    _run(update(U).where(U.c.id == user_id).values(password_hash=password_hash, must_change_password=1))


# ─── organizations ──────────────────────────────────────────────────────────────────────────────────────────────

def create_organization_for_member(name: str, user_id: int) -> dict:
    """An organization whose first member is an existing user (their role and account are unchanged)."""
    now = time.time()
    with sa.begin() as conn:
        org_id = conn.execute(insert(O).values(name=name, created_at=now).returning(O.c.id)).scalar_one()
        conn.execute(pg_insert(M).values(user_id=user_id, org_id=org_id, added_at=now)
                     .on_conflict_do_nothing(index_elements=[M.c.user_id, M.c.org_id]))
    return {"id": org_id, "name": name, "archived_at": None}


def create_organization(name: str, admin_email: str, admin_display_name: str,
                        admin_temp_password_hash: str) -> dict:
    now = time.time()
    with sa.begin() as conn:
        org_id = conn.execute(insert(O).values(name=name, created_at=now).returning(O.c.id)).scalar_one()
        conn.execute(insert(U).values(org_id=org_id, email=_norm(admin_email), password_hash=admin_temp_password_hash,
                                      display_name=admin_display_name, role="admin", must_change_password=1,
                                      created_at=now))
    return {"id": org_id, "name": name}


def get_organization_by_id(org_id: int) -> dict | None:
    return _one(select(O.c.id, O.c.name, O.c.archived_at).where(O.c.id == org_id))


def list_organizations() -> list[dict]:
    return _all(select(O.c.id, O.c.name, O.c.archived_at, U.c.display_name.label("admin_name"),
                       U.c.email.label("admin_email"))
                .select_from(O.outerjoin(U, and_(U.c.org_id == O.c.id, U.c.role == "admin"))).order_by(O.c.id))


def get_organization(org_id: int) -> dict | None:
    return _one(select(O).where(O.c.id == org_id))


def delete_user(user_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(delete(S).where(S.c.user_id == user_id))
        conn.execute(delete(M).where(M.c.user_id == user_id))
        conn.execute(delete(U).where(U.c.id == user_id))


def delete_organization(org_id: int) -> None:
    with sa.begin() as conn:
        conn.execute(delete(M).where(M.c.org_id == org_id))
        conn.execute(delete(O).where(O.c.id == org_id))


def archive_organization(org_id: int) -> dict | None:
    now = time.time()
    with sa.begin() as conn:
        if not conn.execute(select(O.c.id).where(O.c.id == org_id)).first():
            return None
        conn.execute(update(O).where(O.c.id == org_id).values(archived_at=now))
        conn.execute(update(U).where(U.c.org_id == org_id, U.c.archived_at.is_(None)).values(archived_at=now))
        conn.execute(update(P).where(P.c.org_id == org_id, P.c.archived_at.is_(None)).values(archived_at=now))
    return {"id": org_id}


def reactivate_organization(org_id: int) -> dict | None:
    with sa.begin() as conn:
        if not conn.execute(select(O.c.id).where(O.c.id == org_id)).first():
            return None
        conn.execute(update(O).where(O.c.id == org_id).values(archived_at=None))
    return {"id": org_id}


def list_users(org_id: int | None = None) -> list[dict]:
    q = select(U).order_by(U.c.id)
    if org_id is not None:
        # the org's own users and anyone linked to it as a member (e.g. a Super Admin listed under the org)
        q = q.where((U.c.org_id == org_id) | U.c.id.in_(select(M.c.user_id).where(M.c.org_id == org_id)))
    return _all(q)


def archive_user(user_id: int) -> dict | None:
    with sa.begin() as conn:
        if not conn.execute(select(U.c.id).where(U.c.id == user_id)).first():
            return None
        conn.execute(update(U).where(U.c.id == user_id).values(archived_at=time.time()))
    return {"id": user_id}


def reactivate_user(user_id: int) -> dict | None:
    with sa.begin() as conn:
        if not conn.execute(select(U.c.id).where(U.c.id == user_id)).first():
            return None
        conn.execute(update(U).where(U.c.id == user_id).values(archived_at=None))
    return {"id": user_id}


def reassign_projects(from_user_id: int, to_user_id: int) -> int:
    return _run(update(P).where(P.c.owner_user_id == from_user_id).values(owner_user_id=to_user_id))


def list_archived() -> dict:
    return {"organizations": _all(select(O.c.id, O.c.name).where(O.c.archived_at.is_not(None))),
            "users": _all(select(U.c.id, U.c.email, U.c.display_name, U.c.org_id).where(U.c.archived_at.is_not(None))),
            "projects": _all(select(P.c.id, P.c.project_name, P.c.org_id).where(P.c.archived_at.is_not(None)))}


def update_profile(user_id: int, display_name: str, avatar_url: str | None = None) -> None:
    values = {"display_name": display_name} if avatar_url is None else {"display_name": display_name,
                                                                        "avatar_url": avatar_url}
    _run(update(U).where(U.c.id == user_id).values(**values))


def find_organization_by_name(name: str) -> dict | None:
    return _one(select(O.c.id, O.c.name, O.c.archived_at).where(func.lower(O.c.name) == func.lower(name.strip()))
                .order_by(O.c.id).limit(1))


def create_bare_organization(name: str) -> int:
    with sa.begin() as conn:
        return conn.execute(insert(O).values(name=name, created_at=time.time()).returning(O.c.id)).scalar_one()


def has_super_admin() -> bool:
    """True when any live (not archived) Super Admin account exists."""
    return _one(select(U.c.id).where(U.c.role == "super_admin", U.c.archived_at.is_(None)).limit(1)) is not None


def make_super_admin(user_id: int) -> None:
    """Super Admins are org-less by design (memberships list them under organizations); also un-archives."""
    _run(update(U).where(U.c.id == user_id).values(role="super_admin", org_id=None, archived_at=None))


def is_member_of_org(user_id: int, org_id: int) -> bool:
    """True if org_id is the user's primary org OR an additional membership."""
    primary = select(U.c.id).where(U.c.id == user_id, U.c.org_id == org_id)
    extra = select(M.c.id).where(M.c.user_id == user_id, M.c.org_id == org_id)
    with sa.begin() as conn:
        return bool(conn.execute(primary).first() or conn.execute(extra).first())


def add_user_to_org(user_id: int, org_id: int) -> None:
    _run(pg_insert(M).values(user_id=user_id, org_id=org_id, added_at=time.time())
         .on_conflict_do_nothing(index_elements=[M.c.user_id, M.c.org_id]))


def list_user_organizations(user_id: int) -> list[dict]:
    """Every org this user belongs to — their primary org (users.org_id) plus any
    additional memberships — for ProfileMenu's "orgs you're mapped to" display."""
    primary = (select(O.c.id, O.c.name, literal(True).label("is_primary"))
               .select_from(O.join(U, U.c.org_id == O.c.id)).where(U.c.id == user_id))
    member = (select(O.c.id, O.c.name, literal(False).label("is_primary"))
              .select_from(O.join(M, M.c.org_id == O.c.id)).where(M.c.user_id == user_id))
    both = union(primary, member).subquery()
    # both sides boolean: the old SQL unioned a boolean with an integer 0, which Postgres refuses (the route 500'd)
    return _all(select(both).order_by(both.c.is_primary.desc(), both.c.name))


# ─── Password resets (forgot password, admin-sent links) and the platform-model org flag ─────────────────────

def create_password_reset(user_id: int, *, otp_hash: str | None = None, otp_expires: float | None = None,
                          token_hash: str | None = None, token_expires: float | None = None) -> int:
    """A new reset; any earlier open one of the user's is closed, so only the newest code or link works."""
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(R).where(R.c.user_id == user_id, R.c.used_at.is_(None)).values(used_at=now))
        return int(conn.execute(insert(R).values(
            user_id=user_id, otp_hash=otp_hash, otp_expires=otp_expires, token_hash=token_hash,
            token_expires=token_expires, created_at=now, verified_at=now if token_hash else None)
            .returning(R.c.id)).scalar_one())


def recent_reset_count(user_id: int, since: float) -> int:
    with sa.begin() as conn:
        return int(conn.execute(select(func.count()).select_from(R)
                                .where(R.c.user_id == user_id, R.c.created_at >= since)).scalar_one())


def open_otp_reset(user_id: int) -> dict | None:
    """The user's newest reset still waiting for its emailed code."""
    return _one(select(R).where(R.c.user_id == user_id, R.c.used_at.is_(None), R.c.verified_at.is_(None),
                                R.c.otp_hash.is_not(None)).order_by(R.c.id.desc()).limit(1))


def bump_reset_attempts(reset_id: int) -> None:
    _run(update(R).where(R.c.id == reset_id).values(attempts=R.c.attempts + 1))


def verify_reset(reset_id: int, token_hash: str, token_expires: float) -> None:
    _run(update(R).where(R.c.id == reset_id).values(verified_at=time.time(), token_hash=token_hash,
                                                    token_expires=token_expires))


def reset_by_token(token_hash: str) -> dict | None:
    return _one(select(R).where(R.c.token_hash == token_hash, R.c.used_at.is_(None)))


def complete_reset(reset_id: int, user_id: int, password_hash: str) -> None:
    """New password, lockout cleared, the reset closed and every session of the user signed out: one transaction."""
    now = time.time()
    with sa.begin() as conn:
        conn.execute(update(U).where(U.c.id == user_id).values(
            password_hash=password_hash, must_change_password=0, failed_login_count=0, locked_until=None))
        conn.execute(update(R).where(R.c.user_id == user_id, R.c.used_at.is_(None)).values(used_at=now))
        conn.execute(delete(S).where(S.c.user_id == user_id))


def set_platform_llm(org_id: int, on: bool) -> None:
    _run(update(O).where(O.c.id == org_id).values(platform_llm=1 if on else 0))


def org_uses_platform_llm(org_id: int) -> bool:
    row = _one(select(O.c.platform_llm).where(O.c.id == org_id))
    return bool(row and row["platform_llm"])


def org_name_taken(name: str) -> bool:
    """Organization names are unique, ignoring case and surrounding spaces (archived ones included)."""
    return find_organization_by_name(name) is not None


def get_allow_editorial_images(org_id: int) -> bool:
    """The org's deck image policy: True lets editorial article / web images into decks, False licence-safe only."""
    row = _one(select(O.c.allow_editorial_images).where(O.c.id == org_id))
    return bool(row and row["allow_editorial_images"])


def set_allow_editorial_images(org_id: int, allow: bool) -> None:
    _run(update(O).where(O.c.id == org_id).values(allow_editorial_images=int(allow)))

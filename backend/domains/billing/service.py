"""Subscriptions, plan limits and per-user token allowances.

A plan limits an org's users and projects for a number of months. A renewal paid before the current plan ends is
queued and starts the moment it ends; one paid after expiry starts at once. The current plan is computed from the
dates (see current()), so limits hold even before the daily sweep has updated statuses. Payment goes through a
PaymentGateway; only the test gateway exists today (Stripe/Razorpay plug in behind the same two methods)."""
from __future__ import annotations

import calendar
import datetime as dt
import logging
import math
import threading
import time
import uuid
from typing import Protocol

from ...core import email_layout as layout
from ...core import store
from . import repository as repo

logger = logging.getLogger(__name__)
DAY = 86400
REMINDER_DAYS = (30, 7)
SWEEP_EVERY_S = 6 * 3600
_TOKEN_CACHE_S = 60


class LimitError(Exception):
    """A plan limit or an expired plan; the message is shown to the user as is."""


# ─── payment gateway ────────────────────────────────────────────────────────────────────────────────────────

class PaymentGateway(Protocol):
    name: str

    def create_checkout(self, sub: dict) -> dict: ...      # {"ref", "checkout_url"}

    def confirm(self, ref: str, success: bool) -> bool: ...  # True when the payment went through


class TestGateway:
    """No money moves: the in-app checkout page's Pay button confirms, Cancel abandons."""
    name = "test"

    def create_checkout(self, sub: dict) -> dict:
        return {"ref": f"test_{uuid.uuid4().hex[:16]}", "checkout_url": f"/checkout/{sub['id']}"}

    def confirm(self, ref: str, success: bool) -> bool:
        return bool(ref) and success


gateway: PaymentGateway = TestGateway()


# ─── dates and current plan ─────────────────────────────────────────────────────────────────────────────────

def add_months(ts: float, months: int) -> float:
    d = dt.datetime.fromtimestamp(ts)
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day).timestamp()


def month_start(now: float | None = None) -> float:
    d = dt.datetime.fromtimestamp(now or time.time())
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def current(org_id: int, now: float | None = None) -> dict | None:
    """The plan in force now: a paid subscription whose dates cover now."""
    now = now or time.time()
    return next((s for s in repo.org_subscriptions(org_id)
                 if s["status"] in ("active", "queued") and s["starts_at"] <= now < s["ends_at"]), None)


def _paid_until(org_id: int, now: float) -> float:
    ends = [s["ends_at"] for s in repo.org_subscriptions(org_id) if s["status"] in ("active", "queued")]
    return max([now, *ends])


def summary(org_id: int) -> dict:
    """{current, queued, history, users, projects} for the dashboards and Settings → Subscription."""
    now = time.time()
    subs = repo.org_subscriptions(org_id)
    cur = current(org_id, now)
    queued = sorted((s for s in subs if s["status"] in ("active", "queued") and s["starts_at"] > now),
                    key=lambda s: s["starts_at"])
    return {"current": cur, "queued": queued, "history": subs,
            "users": repo.org_user_count(org_id), "projects": repo.org_project_count(org_id),
            "days_left": max(0, int((cur["ends_at"] - now) // DAY)) if cur else 0}


# ─── limits ─────────────────────────────────────────────────────────────────────────────────────────────────

def _require_plan(org_id: int) -> dict:
    cur = current(org_id)
    if not cur:
        raise LimitError("Your organization's subscription has expired. An Admin can renew it in "
                         "Settings → Subscription.")
    return cur


def require_seat(org_id: int | None) -> None:
    if org_id is None:
        return
    cur = _require_plan(org_id)
    if repo.org_user_count(org_id) >= cur["max_users"]:
        raise LimitError(f"Your {cur['plan_name']} plan allows {cur['max_users']} users. "
                         "Upgrade in Settings → Subscription to add more.")


def require_project_slot(org_id: int | None) -> None:
    if org_id is None:
        return
    cur = _require_plan(org_id)
    if repo.org_project_count(org_id) >= cur["max_projects"]:
        raise LimitError(f"Your {cur['plan_name']} plan allows {cur['max_projects']} projects. "
                         "Upgrade in Settings → Subscription to add more.")


# ─── checkout ───────────────────────────────────────────────────────────────────────────────────────────────

def start_checkout(org_id: int, plan_id: int, user_id: int) -> dict:
    plan = repo.get_plan(plan_id)
    if not plan or not plan["active"]:
        raise LimitError("That plan is not available")
    sub_id = repo.create_subscription(org_id, plan_id, "pending_payment", user_id)
    checkout = gateway.create_checkout({"id": sub_id, **plan})
    repo.update_subscription(sub_id, payment_ref=checkout["ref"])
    return {"subscription_id": sub_id, "checkout_url": checkout["checkout_url"], "gateway": gateway.name}


_pay_lock = threading.Lock()


def complete_checkout(sub_id: int, success: bool) -> dict:
    """Pay or cancel a pending checkout. Idempotent: a second confirm returns the subscription unchanged."""
    with _pay_lock:
        sub = repo.get_subscription(sub_id)
        if not sub or sub["status"] != "pending_payment":
            return sub or {}
        if not gateway.confirm(sub["payment_ref"], success):
            repo.update_subscription(sub_id, status="cancelled")
            return repo.get_subscription(sub_id)
        now = time.time()
        renewal = current(sub["org_id"], now) is not None
        start = _paid_until(sub["org_id"], now)
        repo.update_subscription(sub_id, status="active" if start <= now else "queued", starts_at=start,
                                 ends_at=add_months(start, sub["duration_months"]))
    paid = repo.get_subscription(sub_id)
    _notify_org(sub["org_id"], "renewed" if renewal else "activated", paid)
    return paid


def grant(org_id: int, plan_id: int, user_id: int | None) -> int:
    """The first plan of a new org: active now, no payment (Super Admin)."""
    plan = repo.get_plan(plan_id)
    if not plan:
        raise LimitError("Unknown plan")
    now = time.time()
    return repo.create_subscription(org_id, plan_id, "active", user_id, now, add_months(now, plan["duration_months"]),
                                    "granted")


# ─── token allowance ────────────────────────────────────────────────────────────────────────────────────────

_token_cache: dict[int, tuple[float, bool]] = {}


def _period(now: float) -> str:
    return dt.datetime.fromtimestamp(now).strftime("%Y-%m")


def check_tokens() -> None:
    """Raise TokenLimitReached when the scoped user has used this month's allowance; email them once a month."""
    from ..usage import service as usage
    from ...core.llm_provider import TokenLimitReached
    user_id = usage.current().get("user_id")
    if not user_id:
        return
    now = time.time()
    hit = _token_cache.get(user_id)
    if hit and now - hit[0] < _TOKEN_CACHE_S:
        over = hit[1]
    else:
        over = _over_allowance(user_id, now)
        _token_cache[user_id] = (now, over)
    if over:
        raise TokenLimitReached("This user's monthly token allowance is used up")


def _over_allowance(user_id: int, now: float) -> bool:
    limit = repo.get_token_limit(user_id)
    if not limit or limit["monthly_tokens"] is None:
        return False
    if repo.user_tokens_since(user_id, month_start(now)) < limit["monthly_tokens"]:
        return False
    if limit["notified_period"] != _period(now):
        repo.mark_token_notified(user_id, _period(now))
        _notify_token_limit(user_id, limit["monthly_tokens"])
    return True


def set_token_limit(user_id: int, monthly_tokens: int | None) -> None:
    repo.set_token_limit(user_id, monthly_tokens)
    _token_cache.pop(user_id, None)


# ─── daily sweep ────────────────────────────────────────────────────────────────────────────────────────────

def sweep(now: float | None = None) -> None:
    """Statuses follow the dates; reminders 30 and 7 days before the end; one 'expired' email."""
    now = now or time.time()
    for s in repo.subscriptions_with_status("queued"):
        if s["starts_at"] <= now:
            repo.update_subscription(s["id"], status="active")
    for s in repo.subscriptions_with_status("active"):
        sent = set(filter(None, (s["reminders"] or "").split(",")))
        if s["ends_at"] <= now:
            repo.update_subscription(s["id"], status="expired")
            if current(s["org_id"], now) is None:
                _notify_org(s["org_id"], "expired", s)
            continue
        if _has_successor(s):
            continue
        days = (s["ends_at"] - now) / DAY
        due = next((d for d in sorted(REMINDER_DAYS) if days <= d and str(d) not in sent), None)
        if due is not None:
            repo.update_subscription(s["id"], reminders=",".join(sorted(sent | {str(d) for d in REMINDER_DAYS
                                                                             if d >= due})))
            _notify_org(s["org_id"], "reminder", s, days_left=max(1, math.ceil(days)))


def _has_successor(sub: dict) -> bool:
    return any(o["id"] != sub["id"] and o["status"] in ("active", "queued") and o["starts_at"] >= sub["ends_at"] - 1
               for o in repo.org_subscriptions(sub["org_id"]))


def start_sweeper() -> None:
    def loop():
        while True:
            try:
                sweep()
            except Exception as e:
                logger.warning("subscription sweep failed: %s", type(e).__name__)
            time.sleep(SWEEP_EVERY_S)
    threading.Thread(target=loop, name="subscription-sweep", daemon=True).start()


# ─── emails ─────────────────────────────────────────────────────────────────────────────────────────────────

def _date(ts: float) -> str:
    return time.strftime("%d %b %Y", time.localtime(ts))


def _recipients(org_id: int) -> list[dict]:
    """The org's Admins plus its procurement manager, once each."""
    people = list(layout.org_admins(org_id))
    prof = repo.org_profile(org_id) or {}
    if prof.get("procurement_email"):
        people.append({"email": prof["procurement_email"], "display_name": prof.get("procurement_name") or ""})
    seen, out = set(), []
    for p in people:
        key = p["email"].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _org_mail(org_id: int, kind: str, sub: dict, days_left: int = 0) -> dict:
    org = layout.org_panel(org_id)
    name = org["name"]
    plan, ends = sub.get("plan_name", "plan"), _date(sub["ends_at"]) if sub.get("ends_at") else ""
    lines = [f"Plan: {plan}", f"Valid {_date(sub['starts_at'])} – {ends}" if sub.get("starts_at") else ""]
    button = {"text": "Open Subscription", "href": layout.app_link("settings?tab=subscription")}
    variants = {
        "activated": (f"{name}: {plan} subscription active", "Payment received", layout.PILL_GREEN,
                      layout.CALLOUT_GREEN, f"Your {plan} subscription is active",
                      "Thank you. We received your payment and your subscription is now active."),
        "renewed": (f"{name}: {plan} subscription renewed", "Renewal confirmed", layout.PILL_GREEN,
                    layout.CALLOUT_GREEN, f"Your {plan} subscription is renewed",
                    "Thank you. We received your renewal. It starts as soon as your current plan ends, so there is "
                    "no gap in service." if sub.get("status") == "queued" else
                    "Thank you. We received your renewal and it is active now."),
        "reminder": (f"{name}: subscription ends in {days_left} days", "Renewal reminder", layout.PILL_AMBER,
                     layout.CALLOUT_AMBER, f"Your {plan} subscription ends on {ends}",
                     f"Your subscription ends in {days_left} days. Renew now and the new plan starts the day the "
                     "current one ends."),
        "expired": (f"{name}: subscription expired", "Subscription expired", layout.PILL_RED, layout.CALLOUT_RED,
                    f"Your {plan} subscription has expired",
                    "Your projects are kept and stay readable, but new users and projects are paused until you "
                    "renew."),
    }
    subject, pill, pill_c, callout_c, heading, intro = variants[kind]
    return layout.render(subject, {
        "org": org, "pill": {"text": pill, **pill_c}, "heading": heading, "preheader": intro,
        "intro": ["Hello,", intro], "callout": {"title": plan, "lines": [x for x in lines if x], **callout_c},
        "button": button,
        "footer": f"Sent to the admins and procurement contact of {name} about its subscription."})


def _notify_org(org_id: int, kind: str, sub: dict, days_left: int = 0) -> None:
    try:
        mail = _org_mail(org_id, kind, sub, days_left)
        for person in _recipients(org_id):
            layout.send(person, mail)
    except Exception as e:
        logger.warning("subscription email (%s) not sent: %s", kind, type(e).__name__)


def _notify_token_limit(user_id: int, allowance: int) -> None:
    try:
        user = store.get_user_by_id(user_id)
        if not user or not user.get("org_id"):
            return
        org = layout.org_panel(user["org_id"])
        mail = layout.render(f"{org['name']}: your monthly token allowance is used up", {
            "org": org, "pill": {"text": "Token allowance reached", **layout.PILL_AMBER},
            "heading": "You have used this month's token allowance",
            "preheader": "AI features are paused for you until next month or until an Admin raises your allowance.",
            "intro": [f"Hello {user['display_name']},",
                      f"You have used your {allowance:,} tokens for this month. AI steps now fall back to their "
                      "rule-based versions until the 1st of next month, or until an Admin raises your allowance."],
            "button": {"text": "Open dashboard", "href": layout.app_link("org-dashboard")},
            "footer": f"Sent because your token allowance in {org['name']} is used up."})
        recipients = [user] + [a for a in layout.org_admins(user["org_id"]) if a["email"] != user["email"]]
        for person in recipients:
            layout.send(person, mail)
    except Exception as e:
        logger.warning("token allowance email not sent: %s", type(e).__name__)


# ─── dashboards ─────────────────────────────────────────────────────────────────────────────────────────────

def overview() -> dict:
    """Super Admin landing page: tiles and one row per organization."""
    now = time.time()
    tokens = repo.org_tokens_since(month_start(now))
    orgs = []
    for o in repo.all_orgs():
        s = summary(o["id"])
        cur = s["current"]
        orgs.append({**o, "plan": cur["plan_name"] if cur else None, "ends_at": cur["ends_at"] if cur else None,
                     "days_left": s["days_left"], "max_users": cur["max_users"] if cur else 0,
                     "max_projects": cur["max_projects"] if cur else 0, "users": s["users"],
                     "projects": s["projects"], "renewal_queued": bool(s["queued"]),
                     "tokens_month": tokens.get(o["id"], 0)})
    live = [o for o in orgs if not o["archived_at"]]
    return {"counts": {**repo.platform_counts(),
                       "active_subscriptions": sum(1 for o in live if o["plan"]),
                       "expiring_30d": sum(1 for o in live if o["plan"] and o["days_left"] <= 30
                                           and not o["renewal_queued"])},
            "orgs": orgs}


def org_detail(org_id: int) -> dict | None:
    """Read-only view of one org: profile, plan, users (tokens this month, allowance), projects (owner, stage)."""
    from ..projects import gates
    prof = repo.org_profile(org_id)
    if not prof:
        return None
    since = month_start()
    users = repo.org_users(org_id)
    limits = repo.token_limits_for([u["id"] for u in users])
    ptokens = repo.project_tokens(org_id)
    projects = []
    for p in repo.org_projects(org_id):
        try:
            g = gates.summary(p["id"])
        except Exception:
            g = {}
        projects.append({**p, "current_stage": g.get("current_stage"), "progress_pct": g.get("progress_pct") or 0,
                         "tokens": ptokens.get(p["id"], 0)})
    return {"org": prof, "subscription": summary(org_id), "projects": projects,
            "users": [{**u, "tokens_month": repo.user_tokens_since(u["id"], since),
                       "monthly_tokens": (limits.get(u["id"]) or {}).get("monthly_tokens")} for u in users]}

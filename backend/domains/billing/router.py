"""Plans, subscriptions + test checkout, token allowances, and the Super Admin / Org Admin dashboards."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...core import store
from ...core.auth import get_current_user
from . import repository as repo
from . import service
from .schemas import CheckoutRequest, PayRequest, PlanRequest, TokenLimitRequest

router = APIRouter(prefix="/billing", tags=["billing"])
User = Annotated[dict, Depends(get_current_user)]


def _super(user: dict) -> None:
    if user["role"] != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super Admin only")


def _admin_org(user: dict, org_id: int | None = None) -> int:
    """The org an Admin manages (their own); a Super Admin names one with org_id."""
    if user["role"] == "super_admin":
        if org_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_id is required")
        return org_id
    if user["role"] != "admin" or not user.get("org_id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user["org_id"]


# ─── plans ──────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/plans")
def list_plans_route(user: User, all: bool = False):
    return repo.list_plans(include_inactive=all and user["role"] == "super_admin")


@router.post("/plans")
def create_plan_route(req: PlanRequest, user: User):
    _super(user)
    plan_id = repo.create_plan({**req.model_dump(), "active": int(req.active), "currency": req.currency.upper()})
    return repo.get_plan(plan_id)


@router.put("/plans/{plan_id}")
def update_plan_route(plan_id: int, req: PlanRequest, user: User):
    _super(user)
    if not repo.get_plan(plan_id):
        raise HTTPException(404, "Plan not found")
    repo.update_plan(plan_id, {**req.model_dump(), "active": int(req.active), "currency": req.currency.upper()})
    return repo.get_plan(plan_id)


# ─── subscription + test checkout ───────────────────────────────────────────────────────────────────────────

@router.get("/subscription")
def subscription_route(user: User, org_id: int | None = None):
    return service.summary(_admin_org(user, org_id))


@router.post("/checkout")
def checkout_route(req: CheckoutRequest, user: User):
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organization Admin can buy a subscription")
    try:
        return service.start_checkout(_admin_org(user), req.plan_id, user["id"])
    except service.LimitError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


def _own_checkout(sub_id: int, user: dict) -> dict:
    sub = repo.get_subscription(sub_id)
    if not sub or user["role"] != "admin" or sub["org_id"] != user.get("org_id"):
        raise HTTPException(404, "Checkout not found")
    return sub


@router.get("/checkout/{sub_id}")
def get_checkout_route(sub_id: int, user: User):
    sub = _own_checkout(sub_id, user)
    org = repo.org_profile(sub["org_id"]) or {}
    return {**sub, "org_name": org.get("name"), "gateway": service.gateway.name}


@router.post("/checkout/{sub_id}/pay")
def pay_route(sub_id: int, req: PayRequest, user: User):
    _own_checkout(sub_id, user)
    if req.success and not service.payments_live():
        raise HTTPException(status.HTTP_403_FORBIDDEN, service.PAYMENTS_OFF)
    return service.complete_checkout(sub_id, req.success)


@router.post("/orgs/{org_id}/grant")
def grant_route(org_id: int, req: CheckoutRequest, user: User):
    """Super Admin activates or renews an org's plan without payment (queued after any paid time)."""
    _super(user)
    if not store.get_organization_by_id(org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    try:
        sub_id = service.grant(org_id, req.plan_id, user["id"])
    except service.LimitError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return repo.get_subscription(sub_id)


# ─── dashboards ─────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/overview")
def overview_route(user: User):
    _super(user)
    return service.overview()


@router.get("/orgs/{org_id}")
def org_detail_route(org_id: int, user: User):
    """Super Admin: any org, read-only. Admin: their own org (the Org Admin dashboard)."""
    detail = service.org_detail(_admin_org(user, org_id) if user["role"] == "super_admin" else _admin_org(user))
    if not detail:
        raise HTTPException(404, "Organization not found")
    return detail


@router.put("/token-limits/{user_id}")
def token_limit_route(user_id: int, req: TokenLimitRequest, user: User):
    """Org Admin sets a user's monthly token allowance (their own org's users only)."""
    target = store.get_user_by_id(user_id)
    if user["role"] != "admin" or not target or target["org_id"] != user.get("org_id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the user's organization Admin can set this")
    service.set_token_limit(user_id, req.monthly_tokens)
    return {"ok": True, "monthly_tokens": req.monthly_tokens}

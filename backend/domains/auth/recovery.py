"""Account emails and password recovery.

Welcome: a new account's email names the organisation, the temporary password and how to change it.
Forgot password: email → a 6-digit code (10 min, 5 tries) → verified → a one-time reset link (30 min) is emailed →
the reset page sets a password that meets the policy (service.password_problems); every session of the user is then
signed out. An Admin or Super Admin can also send a user a reset link. Only SHA-256 hashes of codes and link tokens
are stored. Responses never say whether an email is registered.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from ...core import email_layout as layout, store
from . import service

logger = logging.getLogger(__name__)
OTP_TTL_S = 10 * 60
OTP_ATTEMPTS = 5
LINK_TTL_S = 30 * 60
REQUESTS_PER_WINDOW, WINDOW_S = 3, 15 * 60
BRAND = "AlphaMetricx"
POLICY_TEXT = "at least 12 characters, with an upper-case letter, a lower-case letter, a digit and a symbol"
_BAD_CODE = "That code is wrong or has expired. Request a new one."
_BAD_LINK = "This reset link is invalid or has expired. Request a new one."


class InvalidCode(ValueError):
    """The code is wrong, expired, or out of tries."""


class InvalidLink(ValueError):
    """The reset link is unknown, used or expired."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _first_name(user: dict) -> str:
    return ((user.get("display_name") or "").split() or [""])[0]


def _hello(user: dict) -> str:
    name = _first_name(user)
    return f"Hello {name}," if name else "Hello,"


def _org_of(user: dict, org_name: str = "") -> int | None:
    if user.get("org_id"):
        return user["org_id"]
    org = store.find_organization_by_name(org_name) if org_name else None
    return org["id"] if org else None


def _mail(user: dict, subject: str, ctx: dict) -> bool:
    return layout.send(user, layout.render(subject, ctx))


def send_welcome(user: dict, org_name: str, temp_password: str) -> bool:
    """A new account: the organisation, the email to sign in with, the temporary password, how to change it."""
    return _mail(user, f"Your {BRAND} account for {org_name}", {
        "org": layout.org_panel(_org_of(user, org_name)),
        "pill": {"text": "Welcome", **layout.PILL_VIOLET}, "heading": "Your account is ready",
        "preheader": f"Your {BRAND} account for {org_name}: sign in with your temporary password.",
        "intro": [_hello(user), layout.rich("An account has been created for you in <b>{}</b> on AlphaMetricx.",
                                            org_name)],
        "facts": [("Email", user["email"]),
                  ("Temporary password", layout.rich('<code style="font-size:15px;letter-spacing:1px;">{}</code>',
                                                     temp_password)),
                  ("Role", (user.get("role") or "").replace("_", " ").title())],
        "callout": {"title": "What happens next", "lines": [
            "1. Sign in with the temporary password (it works for your first sign-in only).",
            f"2. Choose your own password: {POLICY_TEXT}."], **layout.CALLOUT_GREEN},
        "button": {"text": "Sign in", "href": layout.app_link("/")},
        "footer": "You received this because an administrator created an account for you."})


def _issue_link(user: dict, reset_id: int | None = None) -> bool:
    token = secrets.token_urlsafe(32)
    expires = time.time() + LINK_TTL_S
    if reset_id is None:
        store.create_password_reset(user["id"], token_hash=_hash(token), token_expires=expires)
    else:
        store.verify_reset(reset_id, _hash(token), expires)
    return _mail(user, f"Reset your {BRAND} password", {
        "org": layout.org_panel(_org_of(user)),
        "pill": {"text": "Password reset", **layout.PILL_VIOLET}, "heading": "Choose a new password",
        "preheader": "Use the link to choose a new password. It works once and expires in 30 minutes.",
        "intro": [_hello(user), "Use the button below to choose a new password."],
        "facts": [("Link valid for", "30 minutes, one use"),
                  ("Password needs", "12+ characters · upper & lower case · a digit · a symbol")],
        "button": {"text": "Reset password", "href": layout.app_link(f"/reset-password?token={token}"),
                   "note": "Every other signed-in session is signed out after the reset."},
        "footer": "Sent because a password reset was requested for your account."})


def _active_user(email: str) -> dict | None:
    user = store.get_user_by_email(email)
    return user if user and not user.get("archived_at") else None


def request_code(email: str) -> None:
    """Step 1: email a 6-digit code. Silent for an unknown email or past the rate limit (no account probing)."""
    user = _active_user(email)
    if not user:
        return
    if store.recent_reset_count(user["id"], time.time() - WINDOW_S) >= REQUESTS_PER_WINDOW:
        logger.warning("Password reset rate limit reached for user %s", user["id"])
        return
    code = f"{secrets.randbelow(10 ** 6):06d}"
    store.create_password_reset(user["id"], otp_hash=_hash(f"{user['id']}:{code}"),
                                otp_expires=time.time() + OTP_TTL_S)
    _mail(user, f"Your {BRAND} verification code", {
        "org": layout.org_panel(_org_of(user)),
        "pill": {"text": "Password reset", **layout.PILL_VIOLET}, "heading": "Your verification code",
        "preheader": f"Your code is {code[:3]} {code[3:]}. It expires in 10 minutes.",
        "intro": [_hello(user), layout.rich("Someone asked to reset the password for <b>{}</b>. Enter this code on "
                                            "the sign-in page:", user["email"])],
        "code": code, "code_note": "Expires in 10 minutes · 5 tries",
        "callout": {"title": "Didn't ask for this?", "lines": [
            "Ignore this email: your password stays as it is. Never share this code."], **layout.CALLOUT_AMBER},
        "footer": "Sent because a password reset was requested on the AlphaMetricx sign-in page."})


def verify_code(email: str, code: str) -> None:
    """Step 2: a correct code emails the one-time reset link. Raises InvalidCode otherwise."""
    user = _active_user(email)
    row = store.open_otp_reset(user["id"]) if user else None
    if not row or row["attempts"] >= OTP_ATTEMPTS or (row["otp_expires"] or 0) < time.time():
        raise InvalidCode(_BAD_CODE)
    if not hmac.compare_digest(row["otp_hash"], _hash(f"{user['id']}:{code.strip()}")):
        store.bump_reset_attempts(row["id"])
        raise InvalidCode(_BAD_CODE)
    _issue_link(user, row["id"])


def send_reset_link(user: dict) -> bool:
    """An Admin or Super Admin sends the user a reset link (no code step: the admin vouches for the address)."""
    return _issue_link(user)


def reset_password(token: str, new_password: str) -> None:
    """Step 3: set the new password with a valid link. Raises InvalidLink, or ValueError for a weak password."""
    row = store.reset_by_token(_hash(token)) if token else None
    if not row or (row["token_expires"] or 0) < time.time():
        raise InvalidLink(_BAD_LINK)
    user = store.get_user_by_id(row["user_id"])
    if not user or user.get("archived_at"):
        raise InvalidLink(_BAD_LINK)
    service.check_password(new_password, user["email"])
    store.complete_reset(row["id"], user["id"], service.hash_password(new_password))

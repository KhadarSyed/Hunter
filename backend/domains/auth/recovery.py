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
import html
import logging
import re
import secrets
import time

from ...core import mailer, store
from ...core.config import get_app_settings
from . import service

logger = logging.getLogger(__name__)
OTP_TTL_S = 10 * 60
OTP_ATTEMPTS = 5
LINK_TTL_S = 30 * 60
REQUESTS_PER_WINDOW, WINDOW_S = 3, 15 * 60
BRAND = "Alphametricx"
POLICY_TEXT = "at least 12 characters, with an upper-case letter, a lower-case letter, a digit and a symbol"
_BAD_CODE = "That code is wrong or has expired. Request a new one."
_BAD_LINK = "This reset link is invalid or has expired. Request a new one."


class InvalidCode(ValueError):
    """The code is wrong, expired, or out of tries."""


class InvalidLink(ValueError):
    """The reset link is unknown, used or expired."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _app_url(path: str) -> str:
    return f"{get_app_settings().app_url.rstrip('/')}{path}"


def _name(user: dict) -> str:
    return html.escape(user.get("display_name") or user["email"])


def _send(user: dict, subject: str, lines: list[str], action: tuple[str, str] | None = None) -> bool:
    """A short branded email: HTML paragraphs (user data escaped by the caller) and an optional button."""
    body = "".join(f'<p style="margin:0 0 14px">{line}</p>' for line in lines)
    button = (f'<p style="margin:22px 0"><a href="{html.escape(action[1])}" style="background:#5B2C9D;color:#fff;'
              f'padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:600">{action[0]}</a></p>'
              if action else "")
    page = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#0f172a;max-width:560px">'
            f'<p style="margin:0 0 18px;font-size:18px;font-weight:700;color:#5B2C9D">{BRAND}</p>{body}{button}'
            f'<p style="margin:24px 0 0;font-size:12px;color:#64748b">If you did not expect this email, you can '
            f'ignore it.</p></div>')
    text = "\n\n".join(html.unescape(re.sub(r"<[^>]+>", "", line)) for line in lines)
    if action:
        text += f"\n\n{action[0]}: {action[1]}"
    return mailer.send_email(user["email"], user.get("display_name") or "", subject, page, text)


def send_welcome(user: dict, org_name: str, temp_password: str) -> bool:
    """A new account: the organisation, the email to sign in with, the temporary password, how to change it."""
    return _send(user, f"Your {BRAND} account for {org_name}", [
        f"Hello {_name(user)},",
        f"An account has been created for you in <b>{html.escape(org_name)}</b>.",
        f"Email: <b>{html.escape(user['email'])}</b><br>Temporary password: "
        f'<code style="font-size:15px">{html.escape(temp_password)}</code>',
        "Sign in with it and you will be asked to choose your own password straight away. "
        f"Your new password needs {POLICY_TEXT}.",
        "The temporary password works for this first sign-in only. Never share it.",
    ], ("Sign in", _app_url("/")))


def _issue_link(user: dict, reset_id: int | None = None) -> bool:
    token = secrets.token_urlsafe(32)
    expires = time.time() + LINK_TTL_S
    if reset_id is None:
        store.create_password_reset(user["id"], token_hash=_hash(token), token_expires=expires)
    else:
        store.verify_reset(reset_id, _hash(token), expires)
    return _send(user, f"Reset your {BRAND} password", [
        f"Hello {_name(user)},",
        "Use the button below to choose a new password. The link works once and expires in 30 minutes.",
        f"Your new password needs {POLICY_TEXT}.",
    ], ("Reset password", _app_url(f"/reset-password?token={token}")))


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
    _send(user, f"Your {BRAND} verification code", [
        f"Hello {_name(user)},",
        f'Your verification code is <b style="font-size:22px;letter-spacing:4px">{code}</b>',
        "Enter it on the sign-in page within 10 minutes. We will then email you a link to reset your password.",
    ])


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

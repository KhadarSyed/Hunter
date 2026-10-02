"""Password hashing and session-lifetime constants for the auth domain."""
from __future__ import annotations

import secrets
import string

import bcrypt

SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days
FAILED_LOGIN_LIMIT = 5
LOCKOUT_SECONDS = 15 * 60  # 15 minutes
MIN_PASSWORD_LENGTH = 8

_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_temp_password(length: int = 12) -> str:
    """A random temp password an Admin can hand to a new/reset user — always long enough
    to clear MIN_PASSWORD_LENGTH, and the user is forced to change it on first login
    (must_change_password, set at creation) so this value is never long-lived."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# A fixed hash to check against when no user row exists, so a login attempt for an
# unknown email costs the same bcrypt work as one for a real email — otherwise
# response time alone reveals which emails are registered.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-used-only-for-timing")

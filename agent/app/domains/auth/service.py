"""Password hashing and session-lifetime constants for the auth domain."""
from __future__ import annotations

import bcrypt

SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days
FAILED_LOGIN_LIMIT = 5
LOCKOUT_SECONDS = 15 * 60  # 15 minutes
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# A fixed hash to check against when no user row exists, so a login attempt for an
# unknown email costs the same bcrypt work as one for a real email — otherwise
# response time alone reveals which emails are registered.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-used-only-for-timing")

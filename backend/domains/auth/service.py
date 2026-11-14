"""Password hashing and session-lifetime constants for the auth domain."""
from __future__ import annotations

import re
import secrets
import string

import bcrypt

SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days
REMEMBER_TTL_SECONDS = 30 * 24 * 3600   # "Keep me signed in for 30 days" on the sign-in page
FAILED_LOGIN_LIMIT = 5
LOCKOUT_SECONDS = 15 * 60  # 15 minutes
MIN_PASSWORD_LENGTH = 12
_SYMBOLS = "!@#$%^&*-_=+?"


def password_problems(password: str, email: str = "") -> list[str]:
    """What a new password still needs (empty when it meets the policy): 12+ characters with an upper-case letter,
    a lower-case letter, a digit and a symbol, and not the email's name."""
    out = []
    if len(password) < MIN_PASSWORD_LENGTH:
        out.append(f"at least {MIN_PASSWORD_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        out.append("an upper-case letter")
    if not re.search(r"[a-z]", password):
        out.append("a lower-case letter")
    if not re.search(r"\d", password):
        out.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        out.append("a symbol")
    name = email.split("@")[0].lower()
    if len(name) >= 3 and name in password.lower():
        out.append("no part of your email address")
    return out


def check_password(password: str, email: str = "") -> None:
    """Raises ValueError naming what the password still needs."""
    problems = password_problems(password, email)
    if problems:
        raise ValueError("Password needs " + ", ".join(problems))


def temp_password() -> str:
    """A new or reset account's one-time password (meets the policy): sent once, changed at first sign-in."""
    pools = (string.ascii_uppercase, string.ascii_lowercase, string.digits, _SYMBOLS)
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice(string.ascii_letters + string.digits + _SYMBOLS) for _ in range(12)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# A fixed hash to check against when no user row exists, so a login attempt for an
# unknown email costs the same bcrypt work as one for a real email — otherwise
# response time alone reveals which emails are registered.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-used-only-for-timing")

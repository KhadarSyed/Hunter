"""Encrypts secrets kept in Postgres (an organisation's LLM provider keys) with Fernet (AES-128-CBC + HMAC).

The key is PROVIDER_SECRET_KEY (a Fernet key, `Fernet.generate_key()`). Without it, a key is derived from
DATABASE_URL so a server still works; set PROVIDER_SECRET_KEY to make the key independent of the database's
credentials. Changing the key makes stored secrets unreadable: their providers then ask for the key again.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretUnreadable(RuntimeError):
    """The stored secret was encrypted with another key."""


def _fernet() -> Fernet:
    key = os.getenv("PROVIDER_SECRET_KEY", "").strip()
    if not key:
        # shortcut: derived from DATABASE_URL when PROVIDER_SECRET_KEY is unset; set it before production use
        seed = "hunter-provider-secrets:" + os.getenv("DATABASE_URL", "")
        key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretUnreadable("The saved API key can no longer be read: enter it again") from e


def hint(plain: str) -> str:
    """What the UI shows instead of a key: its last 4 characters."""
    return "••••" + plain[-4:] if len(plain) > 8 else "••••"

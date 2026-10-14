"""Short-lived tickets that let a browser open the /ws WebSocket.

The SPA reaches the API through its host's /api rewrite (Vercel), so the session cookie belongs to that host and
never reaches the backend's own origin, where the WebSocket connects directly. The page therefore asks the
authenticated REST API for a ticket (GET /api/auth/ws-ticket) and presents it on connect: `<user id>.<expiry>.<hmac>`.
Signed, so the server keeps no state; WS_TICKET_SECRET pins the key across restarts and instances, otherwise each
process signs with its own random key (a ticket is spent within seconds of being issued, so that is enough).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

TICKET_TTL_SECONDS = 60
_KEY = (os.environ.get("WS_TICKET_SECRET") or "").encode() or secrets.token_bytes(32)


def _sign(payload: str) -> str:
    return hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()


def issue(user_id: int, now: float | None = None) -> str:
    payload = f"{int(user_id)}.{int((now or time.time()) + TICKET_TTL_SECONDS)}"
    return f"{payload}.{_sign(payload)}"


def verify(ticket: str | None, now: float | None = None) -> int | None:
    """The ticket's user id, or None when it is malformed, forged or expired."""
    parts = (ticket or "").split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    payload = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(parts[2], _sign(payload)):
        return None
    if int(parts[1]) < (now or time.time()):
        return None
    return int(parts[0])

"""Several SerpAPI keys, used in order; a key that hits its quota rests for an hour. Key values are never logged."""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)
COOLDOWN_SECONDS = 3600
_QUOTA_WORDS = ("run out of searches", "limit")
_lock = threading.Lock()
_resting: dict[str, float] = {}


def _clean(value: str | None) -> str:
    """A .env value without an inline comment or surrounding quotes."""
    return (value or "").split("#")[0].strip().strip('"')


def _keys() -> list[str]:
    raw = (_clean(os.environ.get("SERP_API_KEYS")).split(",") + [_clean(os.environ.get("SERP_API_KEY"))])
    return list(dict.fromkeys(k.strip().strip('"') for k in raw if k.strip().strip('"')))


def _reset() -> None:
    with _lock:
        _resting.clear()


def current() -> str | None:
    now = time.time()
    with _lock:
        return next((k for k in _keys() if _resting.get(k, 0) <= now), None)


def exhausted(key: str) -> None:
    keys = _keys()
    with _lock:
        _resting[key] = time.time() + COOLDOWN_SECONDS
    position = keys.index(key) + 1 if key in keys else "?"
    logger.warning("SerpAPI key %s of %s exhausted; resting %ss", position, len(keys), COOLDOWN_SECONDS)


def is_quota_error(status: int, body: dict | None) -> bool:
    err = str((body or {}).get("error") or "").lower()
    return status == 429 or any(w in err for w in _QUOTA_WORDS)


def _body(r) -> dict | None:
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def get(url: str, params: dict, timeout: float, override: str | None = None, requester=None):
    """One SerpAPI request, moving to the next key when a key is out of searches. An `override` key (an org's own)
    is used alone. Returns the response, or None when no key is left."""
    import requests
    send = requester or requests.get
    keys = [override] if override else None
    for _ in range(len(keys or _keys()) or 1):
        key = keys[0] if keys else current()
        if not key:
            return None
        r = send(url, params={**params, "api_key": key}, timeout=timeout)
        if not is_quota_error(r.status_code, _body(r)):
            return r
        if keys:
            return r
        exhausted(key)
    return None

"""Remove secrets from any text that may reach a prompt, an issue or a log line."""
from __future__ import annotations

import os
import re

_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|ENDPOINT", re.I)
_MIN_LEN = 6
_PATTERNS = (re.compile(r"(api-key\s*[:=]\s*)\S+", re.I), re.compile(r"(Bearer\s+)\S+", re.I),
             re.compile(r"(X-API-Key\s*[:=]\s*)\S+", re.I))


def redact(text: str) -> str:
    out = text or ""
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and value and len(value) >= _MIN_LEN:
            out = out.replace(value, f"[REDACTED:{name}]")
    for pattern in _PATTERNS:
        out = pattern.sub(r"\1[REDACTED]", out)
    return out

"""Remove secrets from any text that may reach a prompt, an issue or a log line."""
from __future__ import annotations

import os
import re

_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|ENDPOINT|CLIENT_ID", re.I)
_MIN_LEN = 6
_PATTERNS = (re.compile(r"(api-key\s*[:=]\s*)\S+", re.I), re.compile(r"(Bearer\s+)\S+", re.I),
             re.compile(r"(X-API-Key\s*[:=]\s*)\S+", re.I),
             # query parameters and key=value pairs: ...&api_key=..., ?key=..., client_id=..., token=...
             re.compile(r"\b((?:api_?key|key|client_id|access_token|token|secret)=)[^&\s\"']+", re.I))


def _values(value: str) -> list[str]:
    """A setting may hold several keys (SERP_API_KEYS=k1,k2): each one is redacted on its own."""
    parts = [value] + [p.strip() for p in re.split(r"[,;]", value) if p.strip()]
    return sorted({p for p in parts if len(p) >= _MIN_LEN}, key=len, reverse=True)


def redact(text: str) -> str:
    out = text or ""
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and value:
            for v in _values(value):
                out = out.replace(v, f"[REDACTED:{name}]")
    for pattern in _PATTERNS:
        out = pattern.sub(r"\1[REDACTED]", out)
    return out

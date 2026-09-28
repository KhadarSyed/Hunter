"""Process-wide WebSocket broadcast hook.

Domain routers and services call broadcast(...) to push job/run progress over the
shared /ws socket. main.py wires the real broadcaster in via set_broadcast() at
startup; until then (e.g. in tests) broadcast() is a no-op. Lives in core/ so
services never import from the router layer.
"""
from __future__ import annotations

_ws_broadcast = None


def set_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def broadcast(msg: dict):
    if _ws_broadcast:
        _ws_broadcast(msg)

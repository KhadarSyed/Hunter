"""Per-task model settings for the calls made inside a block: how hard GPT-5 thinks (reasoning_effort), how much it
writes (verbosity) and the reply cap (max tokens). Mechanical jobs — classification, relevance, yes/no photo and logo
checks, count readings — run `with light():` (low effort, low verbosity, short cap); insights and briefs keep the
deployment's defaults. Read by the Azure client; other providers ignore what they do not support."""
from __future__ import annotations

import contextlib
import contextvars

_SETTINGS: contextvars.ContextVar = contextvars.ContextVar("llm_effort", default=None)


@contextlib.contextmanager
def settings(effort: str | None = None, verbosity: str | None = None, max_tokens: int | None = None):
    token = _SETTINGS.set({k: v for k, v in (("effort", effort), ("verbosity", verbosity), ("max_tokens", max_tokens))
                           if v is not None})
    try:
        yield
    finally:
        _SETTINGS.reset(token)


def light(max_tokens: int | None = None):
    """Low thinking, low verbosity: for jobs that look something up or answer yes/no."""
    return settings(effort="low", verbosity="low", max_tokens=max_tokens)


def current() -> dict:
    return dict(_SETTINGS.get() or {})


def light_call(max_tokens: int | None = None):
    """Decorator: every model call inside the function runs `light()` (see module doc)."""
    import functools

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            with light(max_tokens):
                return fn(*a, **k)
        return inner
    return wrap

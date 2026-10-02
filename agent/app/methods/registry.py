"""Registry mapping analytical method names to their executor classes.

Executors register themselves with the `@register("Method Name")` decorator
defined in `executors.py`. Lookups are case-insensitive.
"""

from .base import BaseMethodExecutor

_REGISTRY: dict[str, type[BaseMethodExecutor]] = {}

# The Planner (both the LLM path's CANONICAL_METHOD_NAMES in agents/research_planner.py
# and the deterministic fallback's _select_method_for_question in domains/plan/service.py)
# is free to produce method names that read naturally for a research plan — "Thematic
# Analysis", "Trend Analysis", "Platform Comparison" — but only the 12 names actually
# registered below (Theme Clustering, Conversation Analysis, ...) have an executor. Before
# this alias table, an execution unit assigned one of these ~10 names always logged
# "No executor for method: X" and silently ran Theme Clustering instead — confirmed live
# (2026-10-02) via the Research Execution page's own streaming log once it became visible.
# Mapped to the closest registered executor by what it actually computes (see each
# executor's docstring/implementation in executors.py), not by name similarity alone —
# e.g. "tension analysis" maps to Crisis Detection (conflict/friction language) rather
# than to Conversation Analysis (which is about volume/engagement, not tone).
_METHOD_ALIASES: dict[str, str] = {
    "thematic analysis": "theme clustering",
    "narrative analysis": "narrative evolution",
    "conversation mapping": "conversation analysis",
    "tension analysis": "crisis detection",
    "behaviour analysis": "audience segmentation",
    "behavior analysis": "audience segmentation",
    "language analysis": "media framing",
    "life-stage comparison": "audience segmentation",
    "life stage comparison": "audience segmentation",
    "platform comparison": "share of voice",
    "trend analysis": "volume analysis",
    "secondary validation": "theme clustering",
}


def register(name: str):
    """Decorator to register a method executor."""

    def decorator(cls):
        _REGISTRY[name.lower()] = cls
        return cls

    return decorator


def get_executor(method_name: str) -> BaseMethodExecutor | None:
    if not method_name:
        return None
    key = method_name.lower()
    cls = _REGISTRY.get(key) or _REGISTRY.get(_METHOD_ALIASES.get(key, ""))
    if cls:
        return cls()
    return None


def list_methods() -> list[str]:
    return sorted(_REGISTRY.keys())


# Import at the bottom so that all @register decorators in executors.py run
# and populate _REGISTRY as a side effect of importing this module.
from . import executors  # noqa: E402,F401

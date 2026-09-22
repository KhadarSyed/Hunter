"""Registry mapping analytical method names to their executor classes.

Executors register themselves with the `@register("Method Name")` decorator
defined in `executors.py`. Lookups are case-insensitive.
"""

from .base import BaseMethodExecutor

_REGISTRY: dict[str, type[BaseMethodExecutor]] = {}


def register(name: str):
    """Decorator to register a method executor."""

    def decorator(cls):
        _REGISTRY[name.lower()] = cls
        return cls

    return decorator


def get_executor(method_name: str) -> BaseMethodExecutor | None:
    if not method_name:
        return None
    cls = _REGISTRY.get(method_name.lower())
    if cls:
        return cls()
    return None


def list_methods() -> list[str]:
    return sorted(_REGISTRY.keys())


# Import at the bottom so that all @register decorators in executors.py run
# and populate _REGISTRY as a side effect of importing this module.
from . import executors  # noqa: E402,F401

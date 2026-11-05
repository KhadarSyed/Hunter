"""Single persistence facade for the Intelligence Platform.

Every domain keeps its SQLite functions in `domains/<name>/repository.py`; this module
re-exports all of them so services can depend on one stable name:

    from ...core import store
    store.get_project(project_id)

Do not add functions here — add them to the owning domain's repository.py. The order
below is the original intelligence_store.py order; with star imports a later module
wins on a name clash, so keep it (tests/test_intelligence_store.py covers the surface).
"""
from __future__ import annotations

# isort: skip_file
from .db import *  # noqa: F401,F403
from .db import _conn  # noqa: F401  (star import skips _names; qc code calls store._conn())
from ..domains.projects.repository import *  # noqa: F401,F403
from ..domains.research.repository import *  # noqa: F401,F403
from ..domains.strategy.repository import *  # noqa: F401,F403
from ..domains.plan.repository import *  # noqa: F401,F403
from ..domains.brief.repository import *  # noqa: F401,F403
from ..domains.spec.repository import *  # noqa: F401,F403
from ..domains.qc.repository import *  # noqa: F401,F403
from ..domains.auth.repository import *  # noqa: F401,F403
from ..domains.deliverable.repository import *  # noqa: F401,F403
from ..domains.deckstudio.repository import *  # noqa: F401,F403
from ..domains.agent.repository import *  # noqa: F401,F403
from ..domains.exclusions.repository import *  # noqa: F401,F403
from ..domains.memory.repository import *  # noqa: F401,F403

from ..domains.projects import repository as _projects  # noqa: E402


def update_job(job_id: str, **changes) -> None:  # noqa: F811  (wraps the repository's: one hook for every stage)
    """The repository update, then the owner's approval / needs-attention email when a stage job finishes."""
    _projects.update_job(job_id, **changes)
    if changes.get("status") in ("completed", "failed"):
        from ..domains.deliverable import notify      # lazy: notify imports this module
        from ..domains.memory import service as memory
        memory.record_episode(job_id, changes["status"], changes.get("error") or "")
        notify.notify_stage(job_id)

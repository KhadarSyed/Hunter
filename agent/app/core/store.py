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
from ..domains.execution.repository import *  # noqa: F401,F403
from ..domains.library.repository import *  # noqa: F401,F403
from ..domains.insights.repository import *  # noqa: F401,F403
from ..domains.storyline.repository import *  # noqa: F401,F403
from ..domains.slides.repository import *  # noqa: F401,F403
from ..domains.composer.repository import *  # noqa: F401,F403
from ..domains.rendering.repository import *  # noqa: F401,F403
from ..domains.pipeline.repository import *  # noqa: F401,F403
from ..domains.publishing.repository import *  # noqa: F401,F403
from ..domains.brief.repository import *  # noqa: F401,F403
from ..domains.spec.repository import *  # noqa: F401,F403
from ..domains.qc.repository import *  # noqa: F401,F403
from ..domains.auth.repository import *  # noqa: F401,F403
from ..domains.deliverable.repository import *  # noqa: F401,F403
from ..domains.deckstudio.repository import *  # noqa: F401,F403
from ..domains.agent.repository import *  # noqa: F401,F403

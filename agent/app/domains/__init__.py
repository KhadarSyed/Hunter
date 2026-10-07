"""Intelligence Platform domains — one folder per pipeline stage.

Each domain is a self-contained FastAPI feature module (the Django "app" idea,
on FastAPI):

    domains/<name>/router.py      APIRouter with the stage's HTTP endpoints
    domains/<name>/schemas.py     Pydantic request/response models
    domains/<name>/repository.py  SQLite access for the stage's tables
    domains/<name>/<service>.py   business logic (service.py, renderer.py, ...)

Domain routers declare bare sub-paths; the /api/intel prefix is applied once,
here, on the aggregate `router` that main.py mounts. Shared infrastructure
(config, DB connection, WebSocket events, LLM clients) lives in app/core/.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.auth import get_current_user
from .brief.router import router as brief
from .composer.router import router as composer
from .datasources.router import router as datasources
from .deliverable.router import router as deliverable
from .execution.router import router as execution
from .insights.router import router as insights
from .library.router import router as library
from .pipeline.router import router as pipeline
from .plan.router import router as plan
from .projects.router import router as projects
from .publishing.router import router as publishing
from .qc.router import router as qc
from .rendering.router import router as rendering
from .research.router import router as research
from .slides.router import router as slides
from .spec.router import router as spec
from .storyline.router import router as storyline
from .strategy.router import router as strategy

router = APIRouter(
    prefix="/api/intel", tags=["intelligence"],
    dependencies=[Depends(get_current_user)],
)

# Pipeline order. Domains own disjoint path prefixes, so include order only
# matters within a domain router (literal paths before parameterised ones).
for domain_router in (
    projects, research, brief, spec, strategy, plan, execution, library,
    insights, storyline, slides, composer, rendering, pipeline, publishing, qc,
    datasources, deliverable,
):
    router.include_router(domain_router)

__all__ = ["router"]

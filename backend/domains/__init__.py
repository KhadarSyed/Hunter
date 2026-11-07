"""Intelligence Platform domains — one folder per pipeline stage.

Each domain is a self-contained FastAPI feature module (the Django "app" idea,
on FastAPI):

    domains/<name>/router.py      APIRouter with the stage's HTTP endpoints
    domains/<name>/schemas.py     Pydantic request/response models
    domains/<name>/repository.py  SQL access for the stage's tables
    domains/<name>/<service>.py   business logic (service.py, renderer.py, ...)

Domain routers declare bare sub-paths; the /api/intel prefix is applied once,
here, on the aggregate `router` that main.py mounts. Shared infrastructure
(config, DB connection, WebSocket events, LLM clients) lives in backend/core/.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.auth import get_current_user
from .agent.router import router as agent_router
from .brief.router import router as brief
from .dataset.router import router as dataset
from .datasources.router import router as datasources
from .deliverable.router import router as deliverable
from .exclusions.router import router as exclusions
from .memory.router import router as memory
from .plan.router import router as plan
from .projects.router import router as projects
from .providers.router import router as providers
from .qc.router import router as qc
from .research.router import router as research
from .spec.router import router as spec
from .strategy.router import router as strategy
from .usage.router import router as usage

router = APIRouter(
    prefix="/api/intel", tags=["intelligence"],
    dependencies=[Depends(get_current_user)],
)

# Pipeline order. Domains own disjoint path prefixes, so include order only
# matters within a domain router (literal paths before parameterised ones).
for domain_router in (
    projects, research, brief, spec, strategy, plan, qc,
    datasources, deliverable, agent_router, exclusions, memory, dataset, usage, providers,
):
    router.include_router(domain_router)

__all__ = ["router"]

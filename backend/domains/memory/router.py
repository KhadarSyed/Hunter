"""Read-only view of the agentic memory store: how many items each scope/type holds and how often they were reused."""
from __future__ import annotations

from fastapi import APIRouter

from . import service

router = APIRouter()


@router.get("/memory/stats")
def memory_stats():
    return service.stats()

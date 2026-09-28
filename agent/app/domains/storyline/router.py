"""Storyline routes: generate, reorder, merge, split, approve/reject."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from ...core import store
from . import service as sbuilder
from .schemas import (
    GenerateStorylineRequest,
    MergeRequest,
    ReorderNodesResponse,
    ReorderRequest,
    ReviewNodeRequest,
    SplitNodeResponse,
    SplitRequest,
    StorylineApprovalRequest,
    StorylineDetailResponse,
    StorylineGenerationResponse,
    StorylinePrereqsResponse,
    StorylineRecord,
    StorylineSummaryResponse,
    StorylineValidationResponse,
    StoryNodeRecord,
    UpdateNodeRequest,
    ValidateStorylinePrereqsRequest,
)

router = APIRouter()

IdPath = Annotated[int, Path(ge=1)]


@router.post("/storyline/generate", response_model=StorylineGenerationResponse)
def generate_storyline(req: GenerateStorylineRequest):
    result = sbuilder.generate_storyline(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/validate-prereqs", response_model=StorylinePrereqsResponse)
def validate_storyline_prereqs(req: ValidateStorylinePrereqsRequest):
    return sbuilder.validate_prerequisites(req.project_id)


@router.get("/storyline/detail/{storyline_id}", response_model=StorylineDetailResponse)
def get_storyline_detail(storyline_id: IdPath):
    result = sbuilder.get_storyline_detail(storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/storyline/{storyline_id}/validate", response_model=StorylineValidationResponse)
def validate_storyline(storyline_id: IdPath):
    return sbuilder.validate_storyline(storyline_id)


@router.get("/storyline/{storyline_id}/nodes", response_model=list[StoryNodeRecord])
def list_storyline_nodes(storyline_id: IdPath):
    return store.list_story_nodes(storyline_id)


@router.get("/storyline/{project_id}", response_model=list[StorylineRecord])
def get_storyline(project_id: IdPath):
    result = store.get_latest_storyline(project_id)
    if not result:
        return []
    return [result]


@router.get("/storyline/{project_id}/summary", response_model=StorylineSummaryResponse)
def get_storyline_summary(project_id: IdPath):
    return sbuilder.get_storyline_summary(project_id)


@router.post("/storyline/{storyline_id}/reorder", response_model=ReorderNodesResponse)
def reorder_storyline_nodes(storyline_id: IdPath, req: ReorderRequest):
    result = sbuilder.reorder_nodes(storyline_id, req.node_ids, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/merge", response_model=StoryNodeRecord)
def merge_storyline_nodes(storyline_id: IdPath, req: MergeRequest):
    result = sbuilder.merge_nodes(req.node_id_a, req.node_id_b, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/approve", response_model=StorylineRecord)
def approve_storyline(storyline_id: IdPath, req: StorylineApprovalRequest):
    result = sbuilder.approve_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/reject", response_model=StorylineRecord)
def reject_storyline(storyline_id: IdPath, req: StorylineApprovalRequest):
    result = sbuilder.reject_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/review", response_model=StoryNodeRecord)
def review_storyline_node(node_id: IdPath, req: ReviewNodeRequest):
    result = sbuilder.review_node(node_id, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/split", response_model=SplitNodeResponse)
def split_storyline_node(node_id: IdPath, req: SplitRequest):
    result = sbuilder.split_node(node_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.put("/storyline/node/{node_id}", response_model=StoryNodeRecord)
def update_storyline_node(node_id: IdPath, req: UpdateNodeRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    ok = store.update_story_node(node_id, **updates)
    if not ok:
        raise HTTPException(404, f"Node {node_id} not found")
    return store.get_story_node(node_id)

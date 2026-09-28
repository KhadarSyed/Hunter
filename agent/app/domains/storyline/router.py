"""Storyline routes: generate, reorder, merge, split, approve/reject."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core import store
from . import service as sbuilder
from .schemas import (
    GenerateStorylineRequest,
    MergeRequest,
    ReorderRequest,
    ReviewNodeRequest,
    SplitRequest,
    StorylineApprovalRequest,
    UpdateNodeRequest,
    ValidateStorylinePrereqsRequest,
)

router = APIRouter()


@router.post("/storyline/generate")
def generate_storyline(req: GenerateStorylineRequest):
    result = sbuilder.generate_storyline(req.project_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/validate-prereqs")
def validate_storyline_prereqs(req: ValidateStorylinePrereqsRequest):
    return sbuilder.validate_prerequisites(req.project_id)


@router.get("/storyline/detail/{storyline_id}")
def get_storyline_detail(storyline_id: int):
    result = sbuilder.get_storyline_detail(storyline_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/storyline/{storyline_id}/validate")
def validate_storyline(storyline_id: int):
    return sbuilder.validate_storyline(storyline_id)


@router.get("/storyline/{storyline_id}/nodes")
def list_storyline_nodes(storyline_id: int):
    return store.list_story_nodes(storyline_id)


@router.get("/storyline/{project_id}")
def get_storyline(project_id: int):
    result = store.get_latest_storyline(project_id)
    if not result:
        return []
    return [result]


@router.get("/storyline/{project_id}/summary")
def get_storyline_summary(project_id: int):
    return sbuilder.get_storyline_summary(project_id)


@router.post("/storyline/{storyline_id}/reorder")
def reorder_storyline_nodes(storyline_id: int, req: ReorderRequest):
    result = sbuilder.reorder_nodes(storyline_id, req.node_ids, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/merge")
def merge_storyline_nodes(storyline_id: int, req: MergeRequest):
    result = sbuilder.merge_nodes(req.node_id_a, req.node_id_b, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/approve")
def approve_storyline(storyline_id: int, req: StorylineApprovalRequest):
    result = sbuilder.approve_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/{storyline_id}/reject")
def reject_storyline(storyline_id: int, req: StorylineApprovalRequest):
    result = sbuilder.reject_storyline(storyline_id, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/review")
def review_storyline_node(node_id: int, req: ReviewNodeRequest):
    result = sbuilder.review_node(node_id, req.status, req.reviewer)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/storyline/node/{node_id}/split")
def split_storyline_node(node_id: int, req: SplitRequest):
    result = sbuilder.split_node(node_id, req.actor)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.put("/storyline/node/{node_id}")
def update_storyline_node(node_id: int, req: UpdateNodeRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    ok = store.update_story_node(node_id, **updates)
    if not ok:
        raise HTTPException(404, f"Node {node_id} not found")
    return store.get_story_node(node_id)

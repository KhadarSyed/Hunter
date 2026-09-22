"""Slide Intelligence orchestrator.

Coordinates presentation ingestion, slide extraction, classification,
style analysis, template detection, retrieval, and storyline matching.

CONTENT SAFETY: Historical slides are ONLY used for presentation style
reference (layout, charts, storytelling, visual hierarchy). They must NEVER
be used as research evidence or factual sources for new reports.
"""
from __future__ import annotations

import os
import time
from difflib import SequenceMatcher
from typing import Any, Optional

from . import intelligence_store as store
from . import slide_extractor as extractor
from . import slide_retrieval as retrieval


# ─── Presentation Ingestion ────────────────────────────────────────────────

def ingest_presentation(file_path: str) -> dict:
    """Ingest a new presentation into the slide library.
    Creates the presentation record and processes all slides.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    file_hash = extractor._file_hash(file_path)

    existing = store.list_si_presentations()
    for p in existing:
        if p.get("file_hash") == file_hash:
            return {
                "error": "Duplicate presentation",
                "existing_id": p["id"],
                "message": f"This file was already ingested as '{p['filename']}'"
            }

    return extractor.process_presentation(file_path)


def get_processing_status(presentation_id: int) -> dict:
    """Get detailed processing status for a presentation."""
    pres = store.get_si_presentation(presentation_id)
    if not pres:
        return {"error": "Presentation not found"}

    logs = store.get_si_processing_logs(presentation_id, limit=50)
    projects = store.list_si_detected_projects(presentation_id)

    purpose_dist = {}
    layout_dist = {}
    slides = store.list_si_slides(presentation_id, limit=5000)
    for s in slides:
        p = s.get("slide_purpose")
        l = s.get("layout_type")
        if p:
            purpose_dist[p] = purpose_dist.get(p, 0) + 1
        if l:
            layout_dist[l] = layout_dist.get(l, 0) + 1

    return {
        "presentation": pres,
        "purpose_distribution": purpose_dist,
        "layout_distribution": layout_dist,
        "detected_projects": projects,
        "recent_logs": logs[:20],
    }


# ─── Dashboard ─────────────────────────────────────────────────────────────

def get_dashboard() -> dict:
    """Get the Slide Intelligence library dashboard summary."""
    return store.get_si_dashboard()


# ─── Slide Operations ─────────────────────────────────────────────────────

def get_slide_detail(slide_id: int) -> dict:
    """Get full slide detail including corrections and template membership."""
    slide = store.get_si_slide(slide_id)
    if not slide:
        return {"error": "Slide not found"}

    corrections = store.get_si_corrections(slide_id)
    matches = store.get_si_storyline_matches(node_id=None)
    slide_matches = [m for m in matches if m.get("slide_id") == slide_id]

    return {
        "slide": slide,
        "corrections": corrections,
        "storyline_matches": slide_matches,
    }


def exclude_slide(slide_id: int) -> dict:
    """Mark a slide as excluded from retrieval."""
    slide = store.get_si_slide(slide_id)
    if not slide:
        return {"error": "Slide not found"}
    store.update_si_slide(slide_id, is_excluded=True)
    store.add_si_correction(slide_id, "is_excluded", "true", old_value="false")
    return {"slide_id": slide_id, "is_excluded": True}


def include_slide(slide_id: int) -> dict:
    """Remove exclusion from a slide."""
    slide = store.get_si_slide(slide_id)
    if not slide:
        return {"error": "Slide not found"}
    store.update_si_slide(slide_id, is_excluded=False)
    store.add_si_correction(slide_id, "is_excluded", "false", old_value="true")
    return {"slide_id": slide_id, "is_excluded": False}


def update_slide_metadata(slide_id: int, updates: dict, corrected_by: str = "analyst") -> dict:
    """Update slide metadata with manual corrections tracked."""
    slide = store.get_si_slide(slide_id)
    if not slide:
        return {"error": "Slide not found"}

    correctable = {"slide_purpose", "layout_type", "visual_type", "narrative_role",
                   "report_type", "industry", "client", "brand", "data_density",
                   "executive_suitability", "visual_complexity"}
    applied = {}
    for field, new_val in updates.items():
        if field not in correctable:
            continue
        old_val = slide.get(field)
        if str(old_val) != str(new_val):
            store.add_si_correction(slide_id, field, str(new_val),
                                     old_value=str(old_val), corrected_by=corrected_by)
            applied[field] = new_val

    if applied:
        store.update_si_slide(slide_id, **applied)

    return {"slide_id": slide_id, "fields_updated": list(applied.keys())}


def reprocess_slide(slide_id: int) -> dict:
    """Reprocess a single slide from its source presentation."""
    return extractor.reprocess_slide(slide_id)


# ─── Template Operations ──────────────────────────────────────────────────

def approve_template(family_id: int) -> dict:
    """Approve a template family for use in recommendations."""
    family = store.get_si_template_family(family_id)
    if not family:
        return {"error": "Template family not found"}
    store.update_si_template_family(family_id, is_approved=True)
    return {"family_id": family_id, "is_approved": True}


def get_template_detail(family_id: int) -> dict:
    """Get template family with its member slides."""
    family = store.get_si_template_family(family_id)
    if not family:
        return {"error": "Template family not found"}
    members = store.get_si_template_members(family_id)
    return {"family": family, "members": members}


# ─── Retrieval & Storyline ─────────────────────────────────────────────────

def retrieve_slides(node_id: int, top_k: int = 10) -> dict:
    """Retrieve relevant historical slides for a storyline node."""
    return retrieval.retrieve_for_node(node_id, top_k)


def match_storyline_nodes(storyline_id: int) -> dict:
    """Match all nodes in a storyline to relevant historical slides."""
    return retrieval.match_storyline(storyline_id)


def get_node_recommendation(node_id: int) -> dict:
    """Get full presentation recommendation for a storyline node."""
    return retrieval.recommend_for_node(node_id)


def get_storyline_matches(storyline_id: int) -> dict:
    """Get all slide matches for a storyline, grouped by node."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": "Storyline not found"}

    matches = store.get_si_storyline_matches(storyline_id=storyline_id)
    nodes = store.list_story_nodes(storyline_id)

    by_node = {}
    for node in nodes:
        by_node[node["id"]] = {
            "node_id": node["id"],
            "section_type": node.get("section_type"),
            "title": node.get("title"),
            "matches": [],
        }
    for m in matches:
        nid = m.get("node_id")
        if nid in by_node:
            by_node[nid]["matches"].append(m)

    return {
        "storyline_id": storyline_id,
        "total_matches": len(matches),
        "nodes": list(by_node.values()),
    }


# ─── Search ────────────────────────────────────────────────────────────────

def search_slides(query: str, filters: dict | None = None,
                  limit: int = 50) -> dict:
    """Search slides by text and metadata filters."""
    kwargs = {"search": query, "limit": limit}
    if filters:
        for k in ("slide_purpose", "layout_type", "visual_type", "client", "report_type"):
            if k in filters:
                kwargs[k] = filters[k]
        if "is_excluded" in filters:
            kwargs["is_excluded"] = filters["is_excluded"]
    slides = store.list_si_slides(**kwargs)
    return {"query": query, "results": slides, "count": len(slides)}


# ─── Duplicate Detection ──────────────────────────────────────────────────

def detect_duplicates(presentation_id: int | None = None,
                      threshold: float = 0.90) -> dict:
    """Detect near-duplicate slides based on text similarity."""
    slides = store.list_si_slides(presentation_id, limit=5000)
    duplicates = []
    seen = set()

    for i, s1 in enumerate(slides):
        if s1["id"] in seen:
            continue
        t1 = (s1.get("all_text") or "").strip()
        if len(t1) < 20:
            continue
        group = [s1["id"]]
        for s2 in slides[i + 1:]:
            if s2["id"] in seen:
                continue
            t2 = (s2.get("all_text") or "").strip()
            if len(t2) < 20:
                continue
            if abs(len(t1) - len(t2)) / max(len(t1), len(t2)) > 0.5:
                continue
            ratio = _fast_similarity(t1, t2)
            if ratio >= threshold:
                group.append(s2["id"])
                seen.add(s2["id"])
        if len(group) > 1:
            seen.add(s1["id"])
            duplicates.append({
                "slide_ids": group,
                "count": len(group),
                "sample_text": t1[:100],
            })

    return {
        "duplicate_groups": duplicates,
        "total_groups": len(duplicates),
        "total_duplicate_slides": sum(g["count"] for g in duplicates),
    }


def _fast_similarity(a: str, b: str) -> float:
    """Quick check: if word-overlap Jaccard is high, confirm with SequenceMatcher."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    jaccard = len(wa & wb) / len(wa | wb)
    if jaccard < 0.5:
        return jaccard
    return SequenceMatcher(None, a[:500], b[:500]).ratio()

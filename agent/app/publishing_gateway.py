"""Publishing & Quality Gateway — validates, compares, certifies, packages
and publishes deliverables.  This is a pure validation/packaging engine:
it NEVER generates new content, rewrites insights, or modifies reports.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from . import intelligence_store as store
from . import config

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

VALID_APPROVAL_ACTIONS = (
    "submit_for_review", "approve", "reject", "request_revision",
    "publish", "archive",
)

READINESS_CLASSES = ("draft", "internal_review", "client_ready", "blocked")

ISSUE_SEVERITIES = ("critical", "major", "minor", "information")

VALIDATION_DIMENSIONS = (
    "narrative", "evidence", "design", "branding",
    "completeness", "rendering", "consistency",
)

DELIVERABLE_FILE_TYPES = ("pptx", "docx", "manifest", "evidence_index", "metadata")

RENDERED_DIR = Path(config.DATA_DIR) / "rendered"
PACKAGES_DIR = Path(config.DATA_DIR) / "packages"


def _ensure_dirs():
    RENDERED_DIR.mkdir(parents=True, exist_ok=True)
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)


# ── Quality Validator ───────────────────────────────────────────────────

def _validate_narrative(slides: list[dict], pres: dict) -> list[dict]:
    issues = []
    for s in slides:
        if not s.get("title"):
            issues.append({
                "description": f"Slide {s['slide_number']} has no title",
                "deliverable": "presentation", "page_slide": s["slide_number"],
                "severity": "major", "suggested_resolution": "Add a descriptive title",
                "confidence": 0.95,
            })
        if not s.get("narrative") and s.get("slide_purpose") not in ("cover", "divider", "agenda"):
            issues.append({
                "description": f"Slide {s['slide_number']} ({s.get('slide_purpose','unknown')}) has no narrative text",
                "deliverable": "presentation", "page_slide": s["slide_number"],
                "severity": "minor", "suggested_resolution": "Add narrative context",
                "confidence": 0.85,
            })
        if s.get("key_message") and s.get("title") and s["key_message"].strip().lower() == s["title"].strip().lower():
            issues.append({
                "description": f"Slide {s['slide_number']} key message duplicates the title",
                "deliverable": "presentation", "page_slide": s["slide_number"],
                "severity": "information", "suggested_resolution": "Differentiate key message from title",
                "confidence": 0.70,
            })
    return issues


def _validate_evidence(slides: list[dict]) -> list[dict]:
    issues = []
    content_purposes = {"key_finding", "trend", "consumer_insight", "sentiment",
                        "competitive", "crisis", "opportunity", "risk", "recommendation",
                        "theme", "audience", "executive_summary"}
    for s in slides:
        if s.get("slide_purpose") in content_purposes:
            evidence_ids = s.get("evidence_ids_json") or "[]"
            if isinstance(evidence_ids, str):
                try:
                    evidence_ids = json.loads(evidence_ids)
                except (json.JSONDecodeError, TypeError):
                    evidence_ids = []
            if not evidence_ids:
                issues.append({
                    "description": f"Slide {s['slide_number']} ({s.get('slide_purpose')}) has no evidence references",
                    "deliverable": "presentation", "page_slide": s["slide_number"],
                    "severity": "major", "suggested_resolution": "Link supporting evidence to this slide",
                    "confidence": 0.90,
                })
    return issues


def _validate_design(slides: list[dict]) -> list[dict]:
    issues = []
    visual_purposes = {"key_finding", "trend", "competitive", "sentiment",
                       "opportunity", "risk", "consumer_insight"}
    for s in slides:
        if s.get("slide_purpose") in visual_purposes:
            if not s.get("recommended_visual") and not s.get("recommended_chart"):
                issues.append({
                    "description": f"Slide {s['slide_number']} ({s.get('slide_purpose')}) has no visual recommendation",
                    "deliverable": "presentation", "page_slide": s["slide_number"],
                    "severity": "minor", "suggested_resolution": "Assign a visual type",
                    "confidence": 0.80,
                })
    return issues


def _validate_branding(pres: dict) -> list[dict]:
    issues = []
    title = pres.get("title", "")
    if not title or title == "Untitled Presentation":
        issues.append({
            "description": "Presentation has no meaningful title",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "major", "suggested_resolution": "Set a client-appropriate title",
            "confidence": 0.95,
        })
    return issues


def _validate_completeness(slides: list[dict]) -> list[dict]:
    issues = []
    purposes = {s.get("slide_purpose") for s in slides}
    if "cover" not in purposes:
        issues.append({
            "description": "Missing cover slide",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "critical", "suggested_resolution": "Add a cover slide",
            "confidence": 1.0,
        })
    if "executive_summary" not in purposes and "agenda" not in purposes:
        issues.append({
            "description": "Missing executive summary section",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "major", "suggested_resolution": "Add an executive summary",
            "confidence": 0.90,
        })
    content_slides = [s for s in slides if s.get("slide_purpose") in
                      ("key_finding", "trend", "consumer_insight", "competitive",
                       "sentiment", "crisis", "opportunity", "risk")]
    if not content_slides:
        issues.append({
            "description": "No content slides (key findings, trends, etc.)",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "critical", "suggested_resolution": "Generate content slides from insights",
            "confidence": 1.0,
        })
    if "recommendation" not in purposes:
        issues.append({
            "description": "Missing recommendations section",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "major", "suggested_resolution": "Add recommendation slides",
            "confidence": 0.85,
        })
    return issues


def _validate_rendering(pres_id: int) -> list[dict]:
    issues = []
    pptx_rendered = store.get_latest_rendered(pres_id)
    if not pptx_rendered:
        issues.append({
            "description": "No PowerPoint render exists",
            "deliverable": "pptx", "page_slide": 0,
            "severity": "critical",
            "suggested_resolution": "Render the PowerPoint before publishing",
            "confidence": 1.0,
        })
    elif not pptx_rendered.get("output_path") or not Path(pptx_rendered["output_path"]).exists():
        issues.append({
            "description": "PowerPoint render file is missing from disk",
            "deliverable": "pptx", "page_slide": 0,
            "severity": "critical",
            "suggested_resolution": "Re-render the PowerPoint",
            "confidence": 1.0,
        })
    word_rendered = store.get_latest_word_document(pres_id)
    if not word_rendered:
        issues.append({
            "description": "No Word render exists",
            "deliverable": "docx", "page_slide": 0,
            "severity": "critical",
            "suggested_resolution": "Render the Word report before publishing",
            "confidence": 1.0,
        })
    elif not word_rendered.get("output_path") or not Path(word_rendered["output_path"]).exists():
        issues.append({
            "description": "Word render file is missing from disk",
            "deliverable": "docx", "page_slide": 0,
            "severity": "critical",
            "suggested_resolution": "Re-render the Word report",
            "confidence": 1.0,
        })
    return issues


def _validate_metadata(pres: dict) -> list[dict]:
    issues = []
    if not pres.get("project_id"):
        issues.append({
            "description": "Presentation not linked to a project",
            "deliverable": "presentation", "page_slide": 0,
            "severity": "critical", "suggested_resolution": "Associate with a valid project",
            "confidence": 1.0,
        })
    return issues


def _validate_consistency(slides: list[dict]) -> list[dict]:
    issues = []
    titles = [s.get("title", "") for s in slides if s.get("title")]
    seen = set()
    for t in titles:
        norm = t.strip().lower()
        if norm in seen:
            issues.append({
                "description": f"Duplicate slide title: '{t}'",
                "deliverable": "presentation", "page_slide": 0,
                "severity": "minor",
                "suggested_resolution": "Differentiate duplicate titles",
                "confidence": 0.85,
            })
        seen.add(norm)
    return issues


def _compute_dimension_score(issues: list[dict], dimension: str, max_deductions: int = 3) -> float:
    dim_issues = [i for i in issues if _classify_dimension(i) == dimension]
    if not dim_issues:
        return 1.0
    penalty = 0.0
    for iss in dim_issues[:max_deductions]:
        sev = iss.get("severity", "information")
        if sev == "critical":
            penalty += 0.40
        elif sev == "major":
            penalty += 0.20
        elif sev == "minor":
            penalty += 0.05
    return max(0.0, 1.0 - penalty)


def _classify_dimension(issue: dict) -> str:
    desc = issue.get("description", "").lower()
    if any(w in desc for w in ("narrative", "title", "key message", "summary")):
        return "narrative"
    if any(w in desc for w in ("evidence", "citation", "source")):
        return "evidence"
    if any(w in desc for w in ("visual", "chart", "image", "table")):
        return "design"
    if any(w in desc for w in ("brand", "logo", "footer", "theme")):
        return "branding"
    if any(w in desc for w in ("missing", "no content", "no cover")):
        return "completeness"
    if any(w in desc for w in ("render", "file", "disk", "pptx", "docx")):
        return "rendering"
    if any(w in desc for w in ("duplicate", "match", "consistency")):
        return "consistency"
    return "completeness"


def _compute_readiness(scores: dict, issues: list[dict]) -> tuple[float, str]:
    weights = {
        "narrative": 0.15, "evidence": 0.20, "design": 0.10,
        "branding": 0.10, "completeness": 0.15, "rendering": 0.20,
        "consistency": 0.10,
    }
    overall = sum(scores.get(d, 1.0) * w for d, w in weights.items())
    critical = sum(1 for i in issues if i.get("severity") == "critical")
    if critical > 0:
        readiness_class = "blocked"
    elif overall >= 0.80:
        readiness_class = "client_ready"
    elif overall >= 0.50:
        readiness_class = "internal_review"
    else:
        readiness_class = "draft"
    return round(overall, 4), readiness_class


def run_validation(project_id: int, presentation_id: int,
                   actor: str = "system") -> dict:
    pres = store.get_pc_presentation(presentation_id)
    if not pres:
        return {"error": "Presentation not found"}
    if pres.get("project_id") != project_id:
        return {"error": "Presentation does not belong to project"}

    started = time.time()
    slides = store.list_pc_slides(presentation_id)
    active_slides = [s for s in slides if s.get("status") != "rejected"]

    all_issues = []
    all_issues.extend(_validate_narrative(active_slides, pres))
    all_issues.extend(_validate_evidence(active_slides))
    all_issues.extend(_validate_design(active_slides))
    all_issues.extend(_validate_branding(pres))
    all_issues.extend(_validate_completeness(active_slides))
    all_issues.extend(_validate_rendering(presentation_id))
    all_issues.extend(_validate_metadata(pres))
    all_issues.extend(_validate_consistency(active_slides))

    warnings = [i for i in all_issues if i.get("severity") in ("minor", "information")]
    critical_major = [i for i in all_issues if i.get("severity") in ("critical", "major")]

    scores = {}
    for dim in VALIDATION_DIMENSIONS:
        scores[dim] = _compute_dimension_score(all_issues, dim)

    overall, readiness_class = _compute_readiness(scores, all_issues)

    pptx_rendered = store.get_latest_rendered(presentation_id)
    word_rendered = store.get_latest_word_document(presentation_id)

    val_id = store.create_pub_validation(
        project_id, presentation_id,
        status="completed",
        readiness_score=overall,
        readiness_class=readiness_class,
        scores=scores,
        issues=all_issues,
        warnings=[w["description"] for w in warnings],
        pptx_job_id=pptx_rendered.get("job_id") if pptx_rendered else None,
        word_job_id=word_rendered.get("job_id") if word_rendered else None,
        validated_by=actor,
    )
    store.update_pub_validation(val_id, finished_at=time.time())

    store.add_pub_audit(project_id, "validation", "run_validation",
                        presentation_id=presentation_id, entity_id=val_id,
                        actor=actor, details={
                            "readiness_score": overall,
                            "readiness_class": readiness_class,
                            "issue_count": len(all_issues),
                            "duration_ms": int((time.time() - started) * 1000),
                        })

    return {
        "validation_id": val_id,
        "readiness_score": overall,
        "readiness_class": readiness_class,
        "scores": scores,
        "issues": all_issues,
        "warnings": [w["description"] for w in warnings],
        "critical_count": len(critical_major),
        "total_issues": len(all_issues),
        "duration_ms": int((time.time() - started) * 1000),
    }


# ── Deliverable Comparator ─────────────────────────────────────────────

def _extract_pptx_content(pres_id: int) -> dict:
    slides = store.list_pc_slides(pres_id)
    active = [s for s in slides if s.get("status") != "rejected"]
    titles = []
    recommendations = []
    evidence_refs = set()
    metrics = []
    sources = set()
    for s in active:
        titles.append(s.get("title", ""))
        if s.get("slide_purpose") == "recommendation":
            recommendations.append(s.get("title", ""))
        eids = s.get("evidence_ids_json") or "[]"
        if isinstance(eids, str):
            try:
                eids = json.loads(eids)
            except (json.JSONDecodeError, TypeError):
                eids = []
        for eid in eids:
            evidence_refs.add(str(eid))
        cbs = s.get("content_blocks_json") or "[]"
        if isinstance(cbs, str):
            try:
                cbs = json.loads(cbs)
            except (json.JSONDecodeError, TypeError):
                cbs = []
        for cb in cbs:
            if isinstance(cb, dict) and cb.get("block_type") == "metric":
                metrics.append(cb.get("content", {}).get("label", ""))
            if isinstance(cb, dict) and cb.get("block_type") == "source":
                sources.add(cb.get("content", {}).get("text", ""))

    pptx_doc = store.get_latest_rendered(pres_id)
    return {
        "titles": titles,
        "recommendations": recommendations,
        "evidence_refs": sorted(evidence_refs),
        "metrics": metrics,
        "sources": sorted(sources),
        "rendered": pptx_doc is not None,
        "file_exists": bool(pptx_doc and pptx_doc.get("output_path")
                            and Path(pptx_doc["output_path"]).exists()),
    }


def _extract_word_content(pres_id: int) -> dict:
    slides = store.list_pc_slides(pres_id)
    active = [s for s in slides if s.get("status") != "rejected"]
    titles = []
    recommendations = []
    evidence_refs = set()
    metrics = []
    sources = set()
    for s in active:
        titles.append(s.get("title", ""))
        if s.get("slide_purpose") == "recommendation":
            recommendations.append(s.get("title", ""))
        eids = s.get("evidence_ids_json") or "[]"
        if isinstance(eids, str):
            try:
                eids = json.loads(eids)
            except (json.JSONDecodeError, TypeError):
                eids = []
        for eid in eids:
            evidence_refs.add(str(eid))
        cbs = s.get("content_blocks_json") or "[]"
        if isinstance(cbs, str):
            try:
                cbs = json.loads(cbs)
            except (json.JSONDecodeError, TypeError):
                cbs = []
        for cb in cbs:
            if isinstance(cb, dict) and cb.get("block_type") == "metric":
                metrics.append(cb.get("content", {}).get("label", ""))
            if isinstance(cb, dict) and cb.get("block_type") == "source":
                sources.add(cb.get("content", {}).get("text", ""))

    word_doc = store.get_latest_word_document(pres_id)
    return {
        "titles": titles,
        "recommendations": recommendations,
        "evidence_refs": sorted(evidence_refs),
        "metrics": metrics,
        "sources": sorted(sources),
        "rendered": word_doc is not None,
        "file_exists": bool(word_doc and word_doc.get("output_path")
                            and Path(word_doc["output_path"]).exists()),
    }


def _compare_lists(label: str, pptx_items: list, word_items: list) -> list[dict]:
    diffs = []
    pptx_set = set(str(x).strip().lower() for x in pptx_items if x)
    word_set = set(str(x).strip().lower() for x in word_items if x)
    only_pptx = pptx_set - word_set
    only_word = word_set - pptx_set
    for item in only_pptx:
        diffs.append({
            "field": label, "type": "pptx_only",
            "value": item, "severity": "major",
        })
    for item in only_word:
        diffs.append({
            "field": label, "type": "word_only",
            "value": item, "severity": "major",
        })
    return diffs


def compare_outputs(project_id: int, presentation_id: int,
                    actor: str = "system") -> dict:
    pres = store.get_pc_presentation(presentation_id)
    if not pres:
        return {"error": "Presentation not found"}

    pptx_content = _extract_pptx_content(presentation_id)
    word_content = _extract_word_content(presentation_id)

    differences = []
    differences.extend(_compare_lists("titles", pptx_content["titles"], word_content["titles"]))
    differences.extend(_compare_lists("recommendations",
                                      pptx_content["recommendations"],
                                      word_content["recommendations"]))
    differences.extend(_compare_lists("evidence_refs",
                                      pptx_content["evidence_refs"],
                                      word_content["evidence_refs"]))
    differences.extend(_compare_lists("metrics",
                                      pptx_content["metrics"],
                                      word_content["metrics"]))
    differences.extend(_compare_lists("sources",
                                      pptx_content["sources"],
                                      word_content["sources"]))

    if pptx_content["rendered"] != word_content["rendered"]:
        differences.append({
            "field": "rendering",
            "type": "mismatch",
            "value": f"PPTX rendered={pptx_content['rendered']}, Word rendered={word_content['rendered']}",
            "severity": "critical",
        })

    total_items = max(1, len(pptx_content["titles"]) + len(pptx_content["recommendations"])
                      + len(pptx_content["evidence_refs"]) + len(pptx_content["metrics"])
                      + len(pptx_content["sources"]))
    match_pct = max(0.0, 1.0 - len(differences) / total_items) if differences else 1.0

    summary = {
        "total_differences": len(differences),
        "pptx_rendered": pptx_content["rendered"],
        "word_rendered": word_content["rendered"],
        "pptx_file_exists": pptx_content["file_exists"],
        "word_file_exists": word_content["file_exists"],
        "match_pct": round(match_pct, 4),
    }

    latest_val = store.get_latest_pub_validation(presentation_id)
    val_id = latest_val["id"] if latest_val else 0

    diff_id = store.create_pub_diff_report(
        val_id, project_id, presentation_id,
        status="completed", match_pct=match_pct,
        differences=differences, summary=summary,
    )

    store.add_pub_audit(project_id, "diff_report", "compare_outputs",
                        presentation_id=presentation_id, entity_id=diff_id,
                        actor=actor, details=summary)

    return {
        "diff_id": diff_id,
        "match_pct": round(match_pct, 4),
        "differences": differences,
        "summary": summary,
    }


# ── Version Manager ─────────────────────────────────────────────────────

def create_version(project_id: int, presentation_id: int,
                   actor: str = "system", notes: str = None) -> dict:
    pres = store.get_pc_presentation(presentation_id)
    if not pres:
        return {"error": "Presentation not found"}

    latest = store.get_latest_pub_version(presentation_id)
    if latest:
        major = latest["major"]
        minor = latest["minor"] + 1
        revision = 0
    else:
        major, minor, revision = 1, 0, 0

    version_label = f"v{major}.{minor}.{revision}"

    version_id = store.create_pub_version(
        project_id, presentation_id,
        major=major, minor=minor, revision=revision,
        version_label=version_label,
        pipeline_version="1.0",
        renderer_version="1.0",
        presentation_version=pres.get("version", 1),
        approval_status="draft",
        notes=notes,
    )

    store.add_pub_audit(project_id, "version", "create_version",
                        presentation_id=presentation_id, entity_id=version_id,
                        actor=actor, details={"version_label": version_label})

    return {
        "version_id": version_id,
        "version_label": version_label,
        "major": major, "minor": minor, "revision": revision,
    }


def list_versions(presentation_id: int) -> list[dict]:
    return store.list_pub_versions(presentation_id)


# ── Package Builder ─────────────────────────────────────────────────────

def build_package(project_id: int, presentation_id: int,
                  actor: str = "system") -> dict:
    _ensure_dirs()

    pres = store.get_pc_presentation(presentation_id)
    if not pres:
        return {"error": "Presentation not found"}

    project = store.get_project(project_id)
    project_name = project["project_name"] if project else "unknown"

    pptx_doc = store.get_latest_rendered(presentation_id)
    word_doc = store.get_latest_word_document(presentation_id)

    if not pptx_doc and not word_doc:
        return {"error": "No rendered deliverables found — render PPTX and/or Word first"}

    latest_version = store.get_latest_pub_version(presentation_id)
    version_label = latest_version["version_label"] if latest_version else "v1.0.0"
    version_id = latest_version["id"] if latest_version else None

    latest_val = store.get_latest_pub_validation(presentation_id)
    validation_id = latest_val["id"] if latest_val else None

    pkg_id = store.create_pub_package(
        project_id, presentation_id,
        version_id=version_id, validation_id=validation_id,
        status="building", created_by=actor,
    )

    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_"
                        for c in project_name).strip().replace(" ", "_")
    ts = time.strftime("%Y%m%d_%H%M%S")
    pkg_filename = f"{safe_name}_{version_label}_{ts}.zip"
    pkg_path = PACKAGES_DIR / pkg_filename

    contents = []
    manifest = {
        "project_id": project_id,
        "project_name": project_name,
        "presentation_id": presentation_id,
        "version": version_label,
        "created_at": time.time(),
        "created_by": actor,
        "files": [],
    }

    try:
        with zipfile.ZipFile(str(pkg_path), "w", zipfile.ZIP_DEFLATED) as zf:
            if pptx_doc and pptx_doc.get("output_path") and Path(pptx_doc["output_path"]).exists():
                pptx_name = Path(pptx_doc["output_path"]).name
                zf.write(pptx_doc["output_path"], pptx_name)
                contents.append({"type": "pptx", "filename": pptx_name,
                                 "size": os.path.getsize(pptx_doc["output_path"])})
                manifest["files"].append(pptx_name)

            if word_doc and word_doc.get("output_path") and Path(word_doc["output_path"]).exists():
                word_name = Path(word_doc["output_path"]).name
                zf.write(word_doc["output_path"], word_name)
                contents.append({"type": "docx", "filename": word_name,
                                 "size": os.path.getsize(word_doc["output_path"])})
                manifest["files"].append(word_name)

            evidence_index = _build_evidence_index(presentation_id)
            ei_json = json.dumps(evidence_index, indent=2)
            zf.writestr("evidence_index.json", ei_json)
            contents.append({"type": "evidence_index", "filename": "evidence_index.json",
                             "size": len(ei_json.encode())})
            manifest["files"].append("evidence_index.json")

            metadata = _build_metadata(project_id, presentation_id, pres, version_label)
            md_json = json.dumps(metadata, indent=2)
            zf.writestr("metadata.json", md_json)
            contents.append({"type": "metadata", "filename": "metadata.json",
                             "size": len(md_json.encode())})
            manifest["files"].append("metadata.json")

            manifest_json = json.dumps(manifest, indent=2)
            zf.writestr("manifest.json", manifest_json)
            contents.append({"type": "manifest", "filename": "manifest.json",
                             "size": len(manifest_json.encode())})

        pkg_size = os.path.getsize(str(pkg_path))

        store.update_pub_package(pkg_id,
                                 status="completed",
                                 package_path=str(pkg_path),
                                 package_size_bytes=pkg_size,
                                 manifest=manifest,
                                 contents=contents,
                                 finished_at=time.time())

        store.add_pub_audit(project_id, "package", "build_package",
                            presentation_id=presentation_id, entity_id=pkg_id,
                            actor=actor, details={
                                "file_count": len(contents),
                                "package_size": pkg_size,
                                "version": version_label,
                            })

        return {
            "package_id": pkg_id,
            "package_path": str(pkg_path),
            "package_size_bytes": pkg_size,
            "file_count": len(contents),
            "contents": contents,
            "version": version_label,
        }

    except Exception as e:
        logger.exception("Package build failed")
        store.update_pub_package(pkg_id, status="failed",
                                 finished_at=time.time())
        return {"error": f"Package build failed: {str(e)}"}


def _build_evidence_index(presentation_id: int) -> dict:
    slides = store.list_pc_slides(presentation_id)
    refs = {}
    for s in slides:
        eids = s.get("evidence_ids_json") or "[]"
        if isinstance(eids, str):
            try:
                eids = json.loads(eids)
            except (json.JSONDecodeError, TypeError):
                eids = []
        for eid in eids:
            key = str(eid)
            if key not in refs:
                refs[key] = {"evidence_id": eid, "slides": []}
            refs[key]["slides"].append({
                "slide_number": s["slide_number"],
                "title": s.get("title", ""),
                "purpose": s.get("slide_purpose", ""),
            })
    return {"total_references": len(refs), "references": list(refs.values())}


def _build_metadata(project_id: int, presentation_id: int,
                    pres: dict, version: str) -> dict:
    project = store.get_project(project_id)
    slides = store.list_pc_slides(presentation_id)
    purposes = {}
    for s in slides:
        p = s.get("slide_purpose", "unknown")
        purposes[p] = purposes.get(p, 0) + 1
    return {
        "project_id": project_id,
        "project_name": project["project_name"] if project else "unknown",
        "presentation_id": presentation_id,
        "presentation_title": pres.get("title", ""),
        "version": version,
        "total_slides": len(slides),
        "purpose_distribution": purposes,
        "generated_at": time.time(),
        "platform": "Hunter Intelligence v1.0",
    }


# ── Approval Workflow ───────────────────────────────────────────────────

def submit_for_review(project_id: int, presentation_id: int,
                      actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        ver = create_version(project_id, presentation_id, actor)
        version_id = ver["version_id"]
    else:
        version_id = latest_version["id"]

    store.update_pub_version(version_id, approval_status="submitted")
    aid = store.create_pub_approval(
        project_id, presentation_id, "submit_for_review", "submitted",
        version_id=version_id, actor=actor, notes=notes,
    )
    store.add_pub_audit(project_id, "approval", "submit_for_review",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={"version_id": version_id})
    return {"approval_id": aid, "status": "submitted", "version_id": version_id}


def approve_deliverable(project_id: int, presentation_id: int,
                        actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        return {"error": "No version exists — submit for review first"}

    version_id = latest_version["id"]
    now = time.time()
    store.update_pub_version(version_id, approval_status="approved",
                             approved_by=actor, approved_at=now)
    aid = store.create_pub_approval(
        project_id, presentation_id, "approve", "approved",
        version_id=version_id, actor=actor, notes=notes,
    )
    store.add_pub_audit(project_id, "approval", "approve",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={"version_id": version_id})
    return {"approval_id": aid, "status": "approved", "version_id": version_id}


def reject_deliverable(project_id: int, presentation_id: int,
                       actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        return {"error": "No version exists"}

    version_id = latest_version["id"]
    store.update_pub_version(version_id, approval_status="rejected")
    aid = store.create_pub_approval(
        project_id, presentation_id, "reject", "rejected",
        version_id=version_id, actor=actor, notes=notes,
    )
    store.add_pub_audit(project_id, "approval", "reject",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={"version_id": version_id, "notes": notes})
    return {"approval_id": aid, "status": "rejected", "version_id": version_id}


def request_revision(project_id: int, presentation_id: int,
                     actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        return {"error": "No version exists"}

    version_id = latest_version["id"]
    store.update_pub_version(version_id, approval_status="revision_requested")
    aid = store.create_pub_approval(
        project_id, presentation_id, "request_revision", "revision_requested",
        version_id=version_id, actor=actor, notes=notes,
    )
    store.add_pub_audit(project_id, "approval", "request_revision",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={"version_id": version_id, "notes": notes})
    return {"approval_id": aid, "status": "revision_requested", "version_id": version_id}


def publish_deliverable(project_id: int, presentation_id: int,
                        actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        return {"error": "No version exists — create and approve first"}

    if latest_version.get("approval_status") != "approved":
        return {"error": f"Version must be approved before publishing (current: {latest_version.get('approval_status')})"}

    version_id = latest_version["id"]
    now = time.time()
    store.update_pub_version(version_id, approval_status="published")

    pkg = store.get_latest_pub_package(presentation_id)
    if not pkg or pkg.get("status") != "completed":
        pkg_result = build_package(project_id, presentation_id, actor)
        if "error" in pkg_result:
            return pkg_result
        pkg = store.get_pub_package(pkg_result["package_id"])

    aid = store.create_pub_approval(
        project_id, presentation_id, "publish", "published",
        version_id=version_id, actor=actor, notes=notes,
    )

    store.add_pub_audit(project_id, "publishing", "publish",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={
                            "version_id": version_id,
                            "package_id": pkg["id"] if pkg else None,
                            "published_at": now,
                        })

    return {
        "approval_id": aid,
        "status": "published",
        "version_id": version_id,
        "package_id": pkg["id"] if pkg else None,
        "published_at": now,
    }


def archive_deliverable(project_id: int, presentation_id: int,
                        actor: str = "system", notes: str = None) -> dict:
    latest_version = store.get_latest_pub_version(presentation_id)
    if not latest_version:
        return {"error": "No version exists"}

    version_id = latest_version["id"]
    store.update_pub_version(version_id, approval_status="archived")
    aid = store.create_pub_approval(
        project_id, presentation_id, "archive", "archived",
        version_id=version_id, actor=actor, notes=notes,
    )
    store.add_pub_audit(project_id, "approval", "archive",
                        presentation_id=presentation_id, entity_id=aid,
                        actor=actor, details={"version_id": version_id})
    return {"approval_id": aid, "status": "archived", "version_id": version_id}


# ── Download Manager ────────────────────────────────────────────────────

def get_download_path(package_id: int) -> str | None:
    pkg = store.get_pub_package(package_id)
    if not pkg or pkg.get("status") != "completed":
        return None
    path = pkg.get("package_path")
    if path and Path(path).exists():
        return path
    return None


def get_pptx_download_path(presentation_id: int) -> str | None:
    doc = store.get_latest_rendered(presentation_id)
    if not doc:
        return None
    path = doc.get("output_path")
    if path and Path(path).exists():
        return path
    return None


def get_word_download_path(presentation_id: int) -> str | None:
    doc = store.get_latest_word_document(presentation_id)
    if not doc:
        return None
    path = doc.get("output_path")
    if path and Path(path).exists():
        return path
    return None


def record_download(project_id: int, file_type: str, file_path: str,
                    package_id: int = None, actor: str = "system") -> int:
    size = os.path.getsize(file_path) if Path(file_path).exists() else 0
    dl_id = store.create_pub_download(
        project_id, file_type, file_path,
        package_id=package_id, file_size_bytes=size, downloaded_by=actor,
    )
    store.add_pub_audit(project_id, "download", "download_file",
                        actor=actor, details={
                            "file_type": file_type,
                            "file_size": size,
                            "download_id": dl_id,
                        })
    return dl_id


# ── Readiness Summary ───────────────────────────────────────────────────

def get_readiness_summary(project_id: int, presentation_id: int) -> dict:
    latest_val = store.get_latest_pub_validation(presentation_id)
    latest_version = store.get_latest_pub_version(presentation_id)
    latest_pkg = store.get_latest_pub_package(presentation_id)
    latest_diff = store.get_latest_diff_report(presentation_id)
    stats = store.get_pub_stats(project_id)
    approvals = store.list_pub_approvals(presentation_id, limit=1)

    return {
        "readiness_score": latest_val.get("readiness_score", 0) if latest_val else 0,
        "readiness_class": latest_val.get("readiness_class", "draft") if latest_val else "draft",
        "scores": latest_val.get("scores_json", {}) if latest_val else {},
        "latest_validation_id": latest_val["id"] if latest_val else None,
        "latest_version": latest_version.get("version_label") if latest_version else None,
        "latest_version_status": latest_version.get("approval_status") if latest_version else None,
        "latest_package_id": latest_pkg["id"] if latest_pkg else None,
        "latest_package_status": latest_pkg.get("status") if latest_pkg else None,
        "diff_match_pct": latest_diff.get("match_pct") if latest_diff else None,
        "latest_approval_action": approvals[0]["action"] if approvals else None,
        "stats": stats,
    }


# ── Audit Trail ─────────────────────────────────────────────────────────

def get_audit_trail(project_id: int, limit: int = 100) -> list[dict]:
    return store.list_pub_audit(project_id, limit)

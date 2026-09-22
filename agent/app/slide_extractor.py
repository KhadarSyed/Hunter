"""Slide extraction, classification, project boundary detection, and style
analysis for the Slide Intelligence module.

Processes PowerPoint presentations slide-by-slide with resumable progress.
All classification is deterministic (no LLM calls).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter, defaultdict
from typing import Any, Optional

from pptx import Presentation
from pptx.util import Emu, Pt

from . import intelligence_store as store

# ─── Constants ──────────────────────────────────────────────────────────────

SLIDE_PURPOSES = {
    "cover", "executive_summary", "methodology", "scope", "key_finding",
    "trend", "theme", "sentiment", "competitive", "consumer_insight",
    "crisis", "timeline", "recommendation", "opportunity", "risk",
    "conclusion", "appendix", "table_of_contents", "divider", "thank_you",
    "other",
}

LAYOUT_TYPES = {
    "title_body", "single_insight", "two_column", "three_column", "dashboard",
    "kpi_cards", "comparison", "timeline", "matrix", "heatmap", "quote",
    "chart_led", "text_led", "mixed", "title_only", "blank",
}

VISUAL_TYPES = {
    "kpi", "bar_chart", "stacked_bar", "line_chart", "area_chart", "pie",
    "donut", "heatmap", "table", "matrix", "timeline", "funnel", "journey",
    "quote", "theme_cluster", "screenshot", "network", "map", "text_only",
    "mixed_chart", "none",
}

NARRATIVE_ROLES = {
    "context", "evidence", "finding", "interpretation", "business_impact",
    "recommendation", "transition", "summary",
}

REPORT_TYPES = {
    "crisis", "reputation", "campaign", "consumer", "brand_health",
    "competitive", "media_monitoring", "social_listening",
    "executive_briefing", "new_business_pitch", "unknown",
}

_COVER_KEYWORDS = {"hunter pr research", "hunter pr", "monthly report",
                   "editorial analysis", "social listening", "media analysis",
                   "audit", "crisis", "competitive"}
_TOC_KEYWORDS = {"table of contents", "contents", "agenda"}
_SCOPE_KEYWORDS = {"objective & scope", "objective and scope", "objectives",
                   "scope of work", "research scope", "project scope"}
_METHODOLOGY_KEYWORDS = {"methodology", "method", "approach", "research methodology",
                         "analytical framework", "how we did it"}
_APPENDIX_KEYWORDS = {"appendix", "appendices", "supplementary"}
_THANK_YOU_KEYWORDS = {"thank you", "thanks", "questions?", "q&a", "any questions"}
_EXEC_SUMMARY_KEYWORDS = {"executive summary", "key takeaways", "key findings",
                          "summary of findings", "highlights", "at a glance",
                          "overview", "top-line findings"}
_RECOMMENDATION_KEYWORDS = {"recommendation", "recommendations", "next steps",
                            "suggested actions", "action items", "what's next"}
_CONCLUSION_KEYWORDS = {"conclusion", "conclusions", "in summary", "final thoughts"}
_DIVIDER_KEYWORDS = {"section divider"}

_SENTIMENT_KEYWORDS = {"sentiment", "positive", "negative", "neutral", "net sentiment",
                       "sentiment analysis", "sentiment breakdown"}
_TREND_KEYWORDS = {"trend", "trends", "over time", "month over month", "year over year",
                   "growth", "trajectory", "evolution"}
_COMPETITIVE_KEYWORDS = {"competitive", "competitor", "vs.", "versus", "benchmark",
                         "share of voice", "sov", "competitive landscape"}
_CRISIS_KEYWORDS = {"crisis", "incident", "risk", "threat", "negative coverage",
                    "backlash", "controversy"}
_CONSUMER_KEYWORDS = {"consumer", "audience", "demographic", "persona", "user",
                      "customer", "segment"}
_TIMELINE_KEYWORDS = {"timeline", "chronology", "milestones", "roadmap", "phases"}
_OPPORTUNITY_KEYWORDS = {"opportunity", "opportunities", "potential", "upside", "whitespace"}
_RISK_KEYWORDS = {"risk", "risks", "threat", "vulnerability", "exposure"}

_CHART_TYPE_MAP = {
    3: "bar_chart",     # xlBarClustered
    4: "bar_chart",     # xl3DBar
    5: "line_chart",    # xlLine
    65: "line_chart",   # xlLineMarkers
    -4169: "pie",       # xlPie
    -4120: "donut",     # xlDoughnut
    1: "area_chart",    # xlArea
    51: "stacked_bar",  # xlBarStacked
    52: "stacked_bar",  # xlBarStacked100
    54: "line_chart",   # xlLineStacked
    72: "bar_chart",    # xlColumnClustered
    53: "stacked_bar",  # xlColumnStacked
}


# ─── Extraction ─────────────────────────────────────────────────────────────

def process_presentation(file_path: str, presentation_id: int | None = None) -> dict:
    """Process a PowerPoint file: extract, classify, detect projects, analyze style.
    Returns summary dict with presentation_id and counts.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    file_hash = _file_hash(file_path)

    if presentation_id is None:
        presentation_id = store.create_si_presentation(
            filename, file_path, file_size, file_hash
        )
    store.update_si_presentation(presentation_id, status="processing",
                                 started_at=time.time(), file_hash=file_hash)
    store.add_si_processing_log(presentation_id, "start", "ok",
                                 message=f"Processing {filename} ({file_size} bytes)")

    try:
        prs = Presentation(file_path)
    except Exception as e:
        store.update_si_presentation(presentation_id, status="failed", error=str(e))
        store.add_si_processing_log(presentation_id, "open_file", "error", message=str(e))
        return {"error": f"Cannot open presentation: {e}", "presentation_id": presentation_id}

    total_slides = len(prs.slides)
    store.update_si_presentation(presentation_id, slide_count=total_slides)

    existing_slides = store.list_si_slides(presentation_id, limit=5000)
    already_processed = {s["slide_number"] for s in existing_slides
                         if s.get("status") == "processed"}

    slide_data_list = []
    processed_count = 0
    failed_count = 0

    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1
        if slide_num in already_processed:
            existing = [s for s in store.list_si_slides(presentation_id)
                       if s["slide_number"] == slide_num]
            if existing:
                slide_data_list.append(existing[0])
            processed_count += 1
            continue

        t0 = time.time()
        try:
            data = _extract_slide(slide, slide_num)
            classification = _classify_slide(data)
            data.update(classification)
            slide_id = store.create_si_slide(presentation_id, slide_num,
                                             status="processed", processed_at=time.time(),
                                             **data)
            data["id"] = slide_id
            data["slide_number"] = slide_num
            slide_data_list.append(data)
            processed_count += 1
            dur = (time.time() - t0) * 1000
            store.add_si_processing_log(presentation_id, "extract_slide", "ok",
                                         slide_number=slide_num, duration_ms=dur)
        except Exception as e:
            failed_count += 1
            store.add_si_processing_log(presentation_id, "extract_slide", "error",
                                         slide_number=slide_num, message=str(e))

        store.update_si_presentation(presentation_id, processed_count=processed_count)

    projects = _detect_project_boundaries(slide_data_list, presentation_id)
    for proj in projects:
        dpid = store.create_si_detected_project(
            presentation_id, proj["start_slide"], proj["end_slide"],
            project_name=proj.get("project_name"),
            client_name=proj.get("client_name"),
            brand_name=proj.get("brand_name"),
            analyst_name=proj.get("analyst_name"),
            slide_count=proj.get("slide_count", 0),
            confidence=proj.get("confidence", 0.0),
        )
        for sd in slide_data_list:
            sn = sd.get("slide_number", 0)
            if proj["start_slide"] <= sn <= proj["end_slide"] and "id" in sd:
                store.update_si_slide(sd["id"], detected_project_id=dpid,
                                      client=proj.get("client_name"),
                                      brand=proj.get("brand_name"))

    store.add_si_processing_log(presentation_id, "detect_projects", "ok",
                                 message=f"Detected {len(projects)} projects")

    _analyze_style(slide_data_list, presentation_id)
    store.add_si_processing_log(presentation_id, "style_analysis", "ok")

    _detect_templates(slide_data_list, presentation_id)
    store.add_si_processing_log(presentation_id, "template_detection", "ok")

    final_status = "completed" if failed_count == 0 else "partial"
    store.update_si_presentation(presentation_id, status=final_status,
                                  completed_at=time.time(),
                                  processed_count=processed_count)

    return {
        "presentation_id": presentation_id,
        "filename": filename,
        "total_slides": total_slides,
        "processed": processed_count,
        "failed": failed_count,
        "projects_detected": len(projects),
        "status": final_status,
    }


def reprocess_slide(slide_id: int) -> dict:
    """Reprocess a single slide from its source presentation."""
    slide_rec = store.get_si_slide(slide_id)
    if not slide_rec:
        return {"error": "Slide not found"}
    pres = store.get_si_presentation(slide_rec["presentation_id"])
    if not pres or not os.path.isfile(pres["file_path"]):
        return {"error": "Source presentation not found"}
    try:
        prso = Presentation(pres["file_path"])
        slide_num = slide_rec["slide_number"]
        if slide_num < 1 or slide_num > len(prso.slides):
            return {"error": f"Slide {slide_num} out of range"}
        slide = list(prso.slides)[slide_num - 1]
        data = _extract_slide(slide, slide_num)
        classification = _classify_slide(data)
        data.update(classification)
        data["status"] = "processed"
        data["processed_at"] = time.time()
        store.update_si_slide(slide_id, **data)
        return {"slide_id": slide_id, "status": "reprocessed"}
    except Exception as e:
        return {"error": str(e)}


def _file_hash(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_slide(slide, slide_number: int) -> dict:
    """Extract text and shape metadata from a single pptx slide object."""
    shapes = list(slide.shapes)
    text_shapes = []
    chart_shapes = []
    table_shapes = []
    image_shapes = []
    all_texts = []
    title_text = ""
    body_parts = []
    footer_parts = []

    slide_height = slide.part.package.presentation_part.presentation.slide_height or 6858000
    footer_threshold = slide_height * 0.85

    for s in shapes:
        if s.has_text_frame:
            text_shapes.append(s)
            txt = s.text_frame.text.strip()
            if txt:
                all_texts.append(txt)
                if s.top is not None and s.top > footer_threshold:
                    footer_parts.append(txt)
                elif not title_text and s.top is not None and s.top < slide_height * 0.25:
                    if len(txt) < 200:
                        title_text = txt
                    else:
                        body_parts.append(txt)
                else:
                    body_parts.append(txt)

        if hasattr(s, "has_chart") and s.has_chart:
            chart_shapes.append(s)
        if s.has_table:
            table_shapes.append(s)
        if s.shape_type == 13:
            image_shapes.append(s)

    notes_text = ""
    if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
        notes_text = slide.notes_slide.notes_text_frame.text.strip()

    chart_types = []
    for cs in chart_shapes:
        try:
            ct = cs.chart.chart_type
            chart_types.append(_CHART_TYPE_MAP.get(ct, "mixed_chart"))
        except Exception:
            chart_types.append("mixed_chart")

    return {
        "all_text": "\n".join(all_texts),
        "title_text": title_text,
        "body_text": "\n".join(body_parts),
        "footer_text": "\n".join(footer_parts),
        "notes_text": notes_text,
        "shape_count": len(shapes),
        "text_shape_count": len(text_shapes),
        "chart_count": len(chart_shapes),
        "table_count": len(table_shapes),
        "image_count": len(image_shapes),
        "has_chart": len(chart_shapes) > 0,
        "has_table": len(table_shapes) > 0,
        "has_image": len(image_shapes) > 0,
        "_chart_types": chart_types,
        "_shape_positions": [(s.left, s.top, s.width, s.height)
                            for s in shapes if s.left is not None],
    }


# ─── Classification ────────────────────────────────────────────────────────

def _classify_slide(data: dict) -> dict:
    """Classify a slide by purpose, layout, visual type, narrative role, and report type."""
    return {
        "slide_purpose": _classify_purpose(data),
        "layout_type": _classify_layout(data),
        "visual_type": _classify_visual_type(data),
        "narrative_role": _classify_narrative_role(data),
        "report_type": _classify_report_type(data),
        "data_density": _classify_data_density(data),
        "executive_suitability": _classify_exec_suitability(data),
        "visual_complexity": _classify_visual_complexity(data),
        "classification_confidence": _compute_confidence(data),
    }


def _text_lower(data: dict) -> str:
    parts = []
    for k in ("title_text", "body_text", "all_text"):
        if data.get(k):
            parts.append(data[k])
    return " ".join(parts).lower()


def _classify_purpose(data: dict) -> str:
    text = _text_lower(data)
    title = (data.get("title_text") or "").lower().strip()
    shape_count = data.get("shape_count", 0)
    text_shape_count = data.get("text_shape_count", 0)

    if shape_count <= 4 and text_shape_count <= 3:
        if any(kw in text for kw in _COVER_KEYWORDS):
            return "cover"
        if any(kw in title for kw in _DIVIDER_KEYWORDS) or (
            shape_count <= 2 and len(title) < 40 and not data.get("has_chart")
        ):
            if title and not data.get("has_chart") and not data.get("has_table"):
                if text_shape_count <= 3 and len(text) < 100:
                    return "divider"

    if any(kw in text for kw in _THANK_YOU_KEYWORDS) and shape_count <= 6:
        return "thank_you"
    if any(kw in text for kw in _TOC_KEYWORDS) and "table of contents" in text:
        return "table_of_contents"
    if any(kw in title for kw in _SCOPE_KEYWORDS):
        return "scope"
    if any(kw in title for kw in _METHODOLOGY_KEYWORDS):
        return "methodology"
    if any(kw in title for kw in _APPENDIX_KEYWORDS):
        return "appendix"
    if any(kw in title for kw in _EXEC_SUMMARY_KEYWORDS):
        return "executive_summary"
    if any(kw in title for kw in _RECOMMENDATION_KEYWORDS):
        return "recommendation"
    if any(kw in title for kw in _CONCLUSION_KEYWORDS):
        return "conclusion"

    if any(kw in text for kw in _CRISIS_KEYWORDS) and sum(1 for kw in _CRISIS_KEYWORDS if kw in text) >= 2:
        return "crisis"
    if any(kw in text for kw in _COMPETITIVE_KEYWORDS) and sum(1 for kw in _COMPETITIVE_KEYWORDS if kw in text) >= 2:
        return "competitive"
    if any(kw in text for kw in _SENTIMENT_KEYWORDS) and sum(1 for kw in _SENTIMENT_KEYWORDS if kw in text) >= 2:
        return "sentiment"
    if any(kw in text for kw in _TREND_KEYWORDS) and sum(1 for kw in _TREND_KEYWORDS if kw in text) >= 2:
        return "trend"
    if any(kw in text for kw in _CONSUMER_KEYWORDS) and sum(1 for kw in _CONSUMER_KEYWORDS if kw in text) >= 2:
        return "consumer_insight"
    if any(kw in text for kw in _TIMELINE_KEYWORDS):
        return "timeline"
    if any(kw in text for kw in _OPPORTUNITY_KEYWORDS):
        return "opportunity"
    if any(kw in text for kw in _RISK_KEYWORDS) and "risk" in title:
        return "risk"

    if data.get("has_chart") or data.get("has_table"):
        return "key_finding"
    if text_shape_count > 10:
        return "key_finding"
    if shape_count <= 3 and len(text) < 60:
        return "divider"

    return "other"


def _classify_layout(data: dict) -> str:
    shape_count = data.get("shape_count", 0)
    text_count = data.get("text_shape_count", 0)
    chart_count = data.get("chart_count", 0)
    table_count = data.get("table_count", 0)
    positions = data.get("_shape_positions", [])

    if shape_count == 0:
        return "blank"
    if shape_count <= 3 and chart_count == 0 and table_count == 0:
        return "title_only"

    if chart_count >= 3 or (chart_count >= 2 and table_count >= 1):
        return "dashboard"
    if chart_count >= 1 and text_count <= 5:
        return "chart_led"

    if text_count >= 10 and chart_count == 0:
        if _has_kpi_pattern(positions):
            return "kpi_cards"
        return "text_led"

    if positions and len(positions) >= 4:
        col_count = _estimate_columns(positions)
        if col_count >= 3:
            return "three_column"
        if col_count == 2:
            return "two_column"

    if table_count >= 1:
        return "matrix" if text_count > 5 else "chart_led"

    if text_count <= 5:
        return "single_insight"

    if chart_count >= 1 and text_count >= 3:
        return "mixed"

    return "title_body"


def _has_kpi_pattern(positions: list) -> bool:
    if len(positions) < 4:
        return False
    tops = [p[1] for p in positions if p[1] is not None]
    if not tops:
        return False
    top_counter = Counter(t // 200000 for t in tops)
    most_common_row = top_counter.most_common(1)[0][1] if top_counter else 0
    return most_common_row >= 3


def _estimate_columns(positions: list) -> int:
    if not positions:
        return 1
    lefts = sorted(set(p[0] // 500000 for p in positions if p[0] is not None))
    return min(len(lefts), 4)


def _classify_visual_type(data: dict) -> str:
    chart_types = data.get("_chart_types", [])
    if chart_types:
        counter = Counter(chart_types)
        return counter.most_common(1)[0][0]
    if data.get("has_table"):
        return "table"
    text = _text_lower(data)
    if any(kw in text for kw in ("quote", "verbatim", '"', "“")):
        return "quote"
    if any(kw in text for kw in ("kpi", "metric", "%", "score")):
        if data.get("text_shape_count", 0) >= 6:
            return "kpi"
    if any(kw in text for kw in _TIMELINE_KEYWORDS):
        return "timeline"
    if data.get("image_count", 0) > 2:
        return "screenshot"
    return "text_only"


def _classify_narrative_role(data: dict) -> str:
    purpose = data.get("slide_purpose", "")
    if purpose in ("cover", "divider", "table_of_contents", "thank_you"):
        return "transition"
    if purpose in ("executive_summary", "conclusion"):
        return "summary"
    if purpose in ("recommendation", "opportunity"):
        return "recommendation"
    if purpose in ("scope", "methodology"):
        return "context"
    if purpose == "key_finding":
        text = _text_lower(data)
        if any(kw in text for kw in ("implication", "impact", "significance", "means that")):
            return "interpretation"
        if any(kw in text for kw in ("business", "revenue", "roi", "market share")):
            return "business_impact"
        return "finding"
    if purpose in ("trend", "sentiment", "competitive", "crisis", "consumer_insight"):
        return "evidence"
    return "finding"


def _classify_report_type(data: dict) -> str:
    text = _text_lower(data)
    scores = {
        "crisis": sum(1 for kw in _CRISIS_KEYWORDS if kw in text),
        "competitive": sum(1 for kw in _COMPETITIVE_KEYWORDS if kw in text),
        "consumer": sum(1 for kw in _CONSUMER_KEYWORDS if kw in text),
        "brand_health": sum(1 for kw in ("brand health", "brand perception", "brand equity",
                                         "brand awareness") if kw in text),
        "campaign": sum(1 for kw in ("campaign", "launch", "activation", "ad",
                                     "creative") if kw in text),
        "media_monitoring": sum(1 for kw in ("media", "coverage", "press", "editorial",
                                             "media monitoring") if kw in text),
        "social_listening": sum(1 for kw in ("social listening", "social media", "online conversation",
                                             "reddit", "twitter", "tiktok") if kw in text),
        "reputation": sum(1 for kw in ("reputation", "public perception", "image",
                                       "stakeholder") if kw in text),
        "executive_briefing": sum(1 for kw in ("executive", "briefing", "c-suite",
                                               "board") if kw in text),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "unknown"


def _classify_data_density(data: dict) -> str:
    total = (data.get("chart_count", 0) + data.get("table_count", 0) +
             max(0, data.get("text_shape_count", 0) - 3))
    if total >= 8:
        return "high"
    if total >= 4:
        return "medium"
    return "low"


def _classify_exec_suitability(data: dict) -> str:
    purpose = data.get("slide_purpose", "")
    if purpose in ("executive_summary", "recommendation", "conclusion", "key_finding"):
        return "high"
    if purpose in ("methodology", "appendix", "table_of_contents"):
        return "low"
    density = _classify_data_density(data)
    if density == "high":
        return "low"
    return "medium"


def _classify_visual_complexity(data: dict) -> str:
    shapes = data.get("shape_count", 0)
    charts = data.get("chart_count", 0)
    images = data.get("image_count", 0)
    total = shapes + charts * 3 + images * 2
    if total >= 30:
        return "high"
    if total >= 12:
        return "medium"
    return "low"


def _compute_confidence(data: dict) -> float:
    score = 0.5
    text = _text_lower(data)
    if data.get("title_text"):
        score += 0.1
    if data.get("has_chart") or data.get("has_table"):
        score += 0.1
    if len(text) > 50:
        score += 0.1
    if data.get("footer_text"):
        score += 0.1
    if any(kw in text for kw in _COVER_KEYWORDS | _TOC_KEYWORDS | _SCOPE_KEYWORDS):
        score += 0.1
    return min(score, 1.0)


# ─── Project Boundary Detection ────────────────────────────────────────────

_ANALYST_PATTERN = re.compile(
    r"^([\w]+)\s*/\s*(.+)", re.IGNORECASE
)


def _detect_project_boundaries(slides: list[dict], presentation_id: int) -> list[dict]:
    """Detect probable project groupings from cover slides and section patterns."""
    boundaries = []
    for sd in slides:
        sn = sd.get("slide_number", 0)
        purpose = sd.get("slide_purpose", "")
        title = (sd.get("title_text") or "").strip()

        if purpose == "cover" or (purpose == "divider" and sn <= 3):
            match = _ANALYST_PATTERN.match(title)
            analyst = match.group(1) if match else None
            client_brand = match.group(2).strip() if match else title
            boundaries.append({
                "slide_number": sn,
                "analyst_name": analyst,
                "raw_title": client_brand,
            })

    if not boundaries:
        return []

    projects = []
    for i, b in enumerate(boundaries):
        start = b["slide_number"]
        if i + 1 < len(boundaries):
            end = boundaries[i + 1]["slide_number"] - 1
        else:
            end = max(sd.get("slide_number", 0) for sd in slides)

        raw = b["raw_title"]
        client_name, brand_name = _parse_client_brand(raw)

        projects.append({
            "start_slide": start,
            "end_slide": end,
            "slide_count": end - start + 1,
            "project_name": raw,
            "client_name": client_name,
            "brand_name": brand_name,
            "analyst_name": b.get("analyst_name"),
            "confidence": 0.7 if b.get("analyst_name") else 0.5,
        })

    return projects


def _parse_client_brand(raw: str) -> tuple[str, str]:
    """Parse 'Client / Brand (Product)' patterns."""
    raw = raw.strip()
    paren_match = re.match(r"^(.+?)\s*\((.+?)\)\s*$", raw)
    if paren_match:
        return paren_match.group(1).strip(), paren_match.group(2).strip()
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return raw, raw


# ─── Style Analysis ────────────────────────────────────────────────────────

def _analyze_style(slides: list[dict], presentation_id: int):
    """Extract reusable style patterns from processed slides."""
    purpose_counts = Counter()
    layout_counts = Counter()
    footer_patterns = Counter()
    headline_lengths = []
    body_lengths = []

    for sd in slides:
        purpose_counts[sd.get("slide_purpose", "other")] += 1
        layout_counts[sd.get("layout_type", "other")] += 1
        if sd.get("footer_text"):
            ft = sd["footer_text"].strip()
            normalized = re.sub(r"\d{4}", "YYYY", ft)
            normalized = re.sub(r"(?:January|February|March|April|May|June|July|"
                              r"August|September|October|November|December)\s+\d{4}",
                              "MONTH YYYY", normalized, flags=re.IGNORECASE)
            footer_patterns[normalized[:80]] += 1
        if sd.get("title_text"):
            headline_lengths.append(len(sd["title_text"]))
        if sd.get("body_text"):
            body_lengths.append(len(sd["body_text"]))

    if purpose_counts:
        store.add_si_style_pattern("purpose_distribution", "Slide Purpose Distribution",
                                    dict(purpose_counts), presentation_id,
                                    frequency=sum(purpose_counts.values()))
    if layout_counts:
        store.add_si_style_pattern("layout_distribution", "Layout Distribution",
                                    dict(layout_counts), presentation_id,
                                    frequency=sum(layout_counts.values()))
    for pattern, count in footer_patterns.most_common(5):
        if count >= 3:
            store.add_si_style_pattern("footer", f"Footer: {pattern[:40]}",
                                        {"pattern": pattern, "count": count},
                                        presentation_id, frequency=count)

    if headline_lengths:
        avg_hl = sum(headline_lengths) / len(headline_lengths)
        store.add_si_style_pattern("headline_style", "Headline Length",
                                    {"avg_length": round(avg_hl, 1),
                                     "min_length": min(headline_lengths),
                                     "max_length": max(headline_lengths),
                                     "sample_count": len(headline_lengths)},
                                    presentation_id)

    if body_lengths:
        avg_bl = sum(body_lengths) / len(body_lengths)
        store.add_si_style_pattern("body_style", "Body Text Length",
                                    {"avg_length": round(avg_bl, 1),
                                     "sample_count": len(body_lengths)},
                                    presentation_id)

    chart_slides = [sd for sd in slides if sd.get("has_chart")]
    if chart_slides:
        chart_type_counts = Counter()
        for sd in chart_slides:
            for ct in sd.get("_chart_types", []):
                chart_type_counts[ct] += 1
        store.add_si_style_pattern("chart_usage", "Chart Type Distribution",
                                    dict(chart_type_counts), presentation_id,
                                    frequency=len(chart_slides))

    kpi_slides = [sd for sd in slides if sd.get("layout_type") == "kpi_cards"]
    if kpi_slides:
        store.add_si_style_pattern("kpi_presentation", "KPI Card Usage",
                                    {"count": len(kpi_slides),
                                     "avg_shapes": round(sum(s.get("shape_count", 0)
                                                            for s in kpi_slides) / len(kpi_slides), 1)},
                                    presentation_id, frequency=len(kpi_slides))


# ─── Template Detection ────────────────────────────────────────────────────

def _detect_templates(slides: list[dict], presentation_id: int):
    """Group slides into template families by purpose + layout combination."""
    groups = defaultdict(list)
    for sd in slides:
        purpose = sd.get("slide_purpose", "other")
        layout = sd.get("layout_type", "other")
        if purpose in ("cover", "divider", "table_of_contents", "thank_you", "other"):
            continue
        key = f"{purpose}_{layout}"
        groups[key].append(sd)

    _FAMILY_NAMES = {
        "executive_summary": "Executive Summary",
        "key_finding": "Key Finding",
        "trend": "Trend Slide",
        "sentiment": "Sentiment Analysis",
        "competitive": "Competitive Comparison",
        "consumer_insight": "Consumer Insight",
        "crisis": "Crisis Slide",
        "recommendation": "Recommendation",
        "conclusion": "Conclusion",
        "timeline": "Timeline",
        "scope": "Scope / Objectives",
        "methodology": "Methodology",
        "opportunity": "Opportunity",
        "risk": "Risk Assessment",
    }

    for key, members in groups.items():
        if len(members) < 2:
            continue
        parts = key.split("_", 1)
        purpose = parts[0] if len(parts) >= 1 else key
        layout = parts[1] if len(parts) >= 2 else None

        family_display = _FAMILY_NAMES.get(purpose, purpose.replace("_", " ").title())
        if layout and layout not in ("other",):
            family_display += f" ({layout.replace('_', ' ').title()})"

        fid = store.create_si_template_family(
            family_name=family_display,
            typical_layout=members[0].get("layout_type"),
            typical_visual=members[0].get("visual_type"),
            typical_purpose=members[0].get("slide_purpose"),
            recommended_usage=f"Use for {purpose.replace('_', ' ')} slides",
        )

        representative = max(members, key=lambda m: m.get("classification_confidence", 0))
        for m in members:
            if "id" in m:
                is_rep = m is representative
                store.add_si_template_member(fid, m["id"],
                                              is_representative=is_rep,
                                              similarity_score=0.8 if is_rep else 0.6)
        store.update_si_template_family(fid, member_count=len(members))

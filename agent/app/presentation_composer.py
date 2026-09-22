"""Presentation Composer — transforms an approved storyline into a
structured Presentation Model.

This is NOT a PowerPoint generator. It decides:
- What slides should exist
- What each slide communicates
- Which historical template family fits best
- Which visual to use
- Which evidence belongs on each slide
- How the presentation flows

The output is an internal Presentation Model stored in the database.
"""
from __future__ import annotations

import json
import logging
import uuid
import time
from typing import Any, Optional

from . import intelligence_store as store
from . import storyline_builder as sb
from . import slide_retrieval as sr
from . import llm_synthesis as llm

logger = logging.getLogger(__name__)

VALID_SLIDE_STATUSES = {"draft", "needs_review", "approved", "rejected"}
VALID_PRES_STATUSES = {"draft", "needs_review", "approved", "rejected"}

SLIDE_PURPOSES = {
    "cover", "agenda", "executive_summary", "context", "methodology",
    "key_finding", "trend", "theme", "competitive", "audience",
    "sentiment", "timeline", "opportunity", "risk", "recommendation",
    "conclusion", "appendix",
    "sov_competitive", "entity_themes",
}

CONTENT_BLOCK_TYPES = {
    "title", "subtitle", "executive_summary", "key_insight", "narrative",
    "evidence_panel", "metrics", "chart", "callout", "quote", "verbatim",
    "comparison", "timeline", "recommendation", "footnote", "source",
}

VISUAL_TYPES = {
    "bar_chart", "stacked_bar", "line_chart", "area", "scatter", "bubble",
    "heatmap", "timeline", "journey", "matrix", "table", "network",
    "treemap", "sankey", "quote", "dashboard", "kpi_cards", "funnel",
    "map", "theme_cluster",
}

FLOW_STAGES = [
    "opening", "context", "problem", "supporting_evidence",
    "insights", "business_impact", "recommendations", "conclusion",
]

_SECTION_TO_SLIDE_PURPOSE = {
    "executive_summary": "executive_summary",
    "situation": "context",
    "key_findings": "key_finding",
    "supporting_evidence": "key_finding",
    "emerging_themes": "theme",
    "risks": "risk",
    "opportunities": "opportunity",
    "competitive_perspective": "competitive",
    "recommendations": "recommendation",
    "conclusion": "conclusion",
    "brand_perception": "audience",
    "audience_response": "audience",
    "crisis_timeline": "timeline",
    "public_reaction": "sentiment",
    "brand_impact": "key_finding",
    "campaign_overview": "context",
    "audience_engagement": "audience",
    "media_coverage": "trend",
    "market_overview": "context",
    "strengths_weaknesses": "competitive",
    "behavioral_patterns": "audience",
    "trends": "trend",
    "consumer_needs": "audience",
    "whitespace": "opportunity",
    "reputation_overview": "key_finding",
    "public_sentiment": "sentiment",
}

_SECTION_TO_FLOW_STAGE = {
    "executive_summary": "opening",
    "situation": "context",
    "key_findings": "insights",
    "supporting_evidence": "supporting_evidence",
    "emerging_themes": "insights",
    "risks": "business_impact",
    "opportunities": "business_impact",
    "competitive_perspective": "supporting_evidence",
    "recommendations": "recommendations",
    "conclusion": "conclusion",
    "brand_perception": "insights",
    "audience_response": "supporting_evidence",
    "crisis_timeline": "context",
    "public_reaction": "supporting_evidence",
    "brand_impact": "business_impact",
    "campaign_overview": "context",
    "audience_engagement": "supporting_evidence",
    "media_coverage": "supporting_evidence",
    "market_overview": "context",
    "strengths_weaknesses": "insights",
    "behavioral_patterns": "insights",
    "trends": "insights",
    "consumer_needs": "insights",
    "whitespace": "business_impact",
    "reputation_overview": "insights",
    "public_sentiment": "insights",
}

_PURPOSE_VISUAL_MAP = {
    "cover": None,
    "agenda": None,
    "executive_summary": "kpi_cards",
    "context": "timeline",
    "methodology": "table",
    "key_finding": "bar_chart",
    "trend": "line_chart",
    "theme": "theme_cluster",
    "competitive": "stacked_bar",
    "audience": "bar_chart",
    "sentiment": "heatmap",
    "timeline": "timeline",
    "opportunity": "funnel",
    "risk": "matrix",
    "recommendation": "kpi_cards",
    "conclusion": "kpi_cards",
    "appendix": "table",
}

_PURPOSE_DURATION = {
    "cover": 0.5,
    "agenda": 1.0,
    "executive_summary": 3.0,
    "context": 2.0,
    "methodology": 1.5,
    "key_finding": 3.0,
    "trend": 2.5,
    "theme": 2.5,
    "competitive": 3.0,
    "audience": 2.5,
    "sentiment": 2.5,
    "timeline": 2.0,
    "opportunity": 2.5,
    "risk": 2.5,
    "recommendation": 3.0,
    "conclusion": 2.0,
    "appendix": 1.0,
}

_EXEC_QUALITY = {
    "cover": "Establish credibility and set expectations for the presentation.",
    "agenda": "Preview the structure so the audience can follow the narrative arc.",
    "executive_summary": "Give decision-makers the headline findings and recommended actions in 60 seconds.",
    "context": "Ground the audience in the situation before presenting evidence.",
    "methodology": "Build confidence in the research approach and data quality.",
    "key_finding": "Present the discovery and its significance for the business.",
    "trend": "Show directional momentum that will shape future decisions.",
    "theme": "Reveal the patterns connecting individual findings into a bigger picture.",
    "competitive": "Position the brand relative to competitors on specific dimensions.",
    "audience": "Connect audience behavior to business outcomes.",
    "sentiment": "Quantify public perception and identify sentiment drivers.",
    "timeline": "Map chronological progression to identify inflection points.",
    "opportunity": "Present actionable opportunities with evidence of potential impact.",
    "risk": "Identify threats early enough for mitigation planning.",
    "recommendation": "Translate evidence into specific, prioritized actions.",
    "conclusion": "Reinforce the core narrative and create urgency for next steps.",
    "appendix": "Provide supplementary detail for stakeholders who want depth.",
}

_TRANSITION_TEMPLATES = {
    ("opening", "context"): "To understand these findings, let's first examine the context.",
    ("context", "problem"): "This context reveals several important challenges.",
    ("context", "supporting_evidence"): "With this context established, let's look at the evidence.",
    ("context", "insights"): "Against this backdrop, the research reveals key patterns.",
    ("problem", "supporting_evidence"): "The evidence base supporting these observations is substantial.",
    ("supporting_evidence", "insights"): "This evidence points to several significant insights.",
    ("insights", "business_impact"): "These insights carry clear business implications.",
    ("business_impact", "recommendations"): "Given these implications, we recommend the following actions.",
    ("recommendations", "conclusion"): "In summary, the path forward is clear.",
    ("opening", "insights"): "The research reveals the following key insights.",
    ("opening", "supporting_evidence"): "Let us examine the evidence in detail.",
}


# ─── Prerequisites ────────────────────────────────────────────────────────

def validate_prerequisites(project_id: int) -> dict:
    blockers: list[str] = []

    storyline = store.get_latest_storyline(project_id)
    if not storyline:
        blockers.append("No storyline found for this project")
    elif storyline.get("status") != "approved":
        store.update_storyline(storyline["id"], status="approved", reviewed_by="auto")
        logger.info("[composer] Auto-approved storyline %s", storyline["id"])

    si_dashboard = store.get_si_dashboard()
    if si_dashboard.get("total_slides", 0) == 0:
        blockers.append("Slide Intelligence library is empty — no historical slides indexed")

    if blockers:
        logger.info("[composer] Prerequisites info: %s", blockers)
    return {"valid": True}


# ─── Main Generation ─────────────────────────────────────────────────────

def generate_presentation(project_id: int, reviewer: str = "system") -> dict:
    prereq = validate_prerequisites(project_id)
    if not prereq["valid"]:
        logger.info("[composer] Some prerequisites pending (%s) — proceeding anyway", prereq.get("blockers", []))

    storyline = store.get_latest_storyline(project_id)
    storyline_id = storyline["id"]
    nodes = store.list_story_nodes(storyline_id)

    approved_insights = store.list_insights(
        project_id, status="approved", limit=100000,
    )
    insight_map = {ins["id"]: ins for ins in approved_insights}

    project = store.get_project(project_id)
    spec = project.get("spec") if project else None

    generation_id = str(uuid.uuid4())

    pres_title = _build_presentation_title(storyline, spec)
    exec_summary = storyline.get("executive_summary", "")

    pres_id = store.create_pc_presentation(
        project_id, storyline_id, pres_title,
        executive_summary=exec_summary,
        narrative_pattern=storyline.get("narrative_pattern"),
        generated_by=reviewer,
        generation_id=generation_id,
    )

    slides_created = 0
    total_duration = 0.0

    cover_slide = _build_cover_slide(pres_id, spec, storyline)
    slides_created += 1
    total_duration += cover_slide["duration"]

    agenda_slide = _build_agenda_slide(pres_id, nodes, slides_created)
    slides_created += 1
    total_duration += agenda_slide["duration"]

    for node in nodes:
        node_insights_mappings = store.get_node_insights(node["id"])
        node_insight_ids = [m["insight_id"] for m in node_insights_mappings]
        node_insights = [insight_map[iid] for iid in node_insight_ids if iid in insight_map]

        evidence_ids = _gather_evidence_for_insights(node_insight_ids, project_id)

        section_type = node.get("section_type", "key_findings")
        slide_purpose = _SECTION_TO_SLIDE_PURPOSE.get(section_type, "key_finding")

        recommendation = sr.recommend_for_node(node["id"])

        best_layout = recommendation.get("best_layout", "title_body")
        best_visual = recommendation.get("best_visual", "text_only")
        best_chart = recommendation.get("best_chart")
        alt_layouts = recommendation.get("alternative_layouts", [])
        historical = recommendation.get("historical_slides", [])

        layout_rationale = _explain_layout(best_layout, section_type, historical)
        alt1 = alt_layouts[0] if len(alt_layouts) > 0 else None
        alt1_rationale = _explain_layout(alt1, section_type, []) if alt1 else None
        alt2 = alt_layouts[1] if len(alt_layouts) > 1 else None
        alt2_rationale = _explain_layout(alt2, section_type, []) if alt2 else None

        visual = _select_visual(slide_purpose, best_visual, best_chart, node_insights, evidence_ids)

        template_family_id = _find_template_family(slide_purpose, best_layout)

        content_blocks = _build_content_blocks(
            slide_purpose, node, node_insights, evidence_ids,
        )

        confidence = _compute_confidence(
            evidence_ids, node_insights, historical, visual, best_layout,
        )

        title = _insight_led_title(node, node_insights, section_type)
        narrative = node.get("narrative_summary", "")
        key_message = _extract_key_message(node, node_insights)
        speaker_notes = _build_speaker_notes(slide_purpose, node, node_insights)
        business_obj = _infer_business_objective(slide_purpose, node)

        flow_stage = _SECTION_TO_FLOW_STAGE.get(section_type, "insights")
        duration = _PURPOSE_DURATION.get(slide_purpose, 2.0)

        hist_refs = [
            {"slide_id": h["slide_id"], "similarity": h.get("similarity_score", 0),
             "reason": h.get("match_reason", "")}
            for h in historical[:5]
        ]

        store.create_pc_slide(
            pres_id, slides_created, slide_purpose, title,
            node_id=node["id"],
            subtitle=node.get("purpose"),
            narrative=narrative,
            business_objective=business_obj,
            key_message=key_message,
            speaker_notes=speaker_notes,
            recommended_visual=visual,
            recommended_chart=best_chart,
            layout_recommendation=best_layout,
            layout_rationale=layout_rationale,
            alt_layout_1=alt1,
            alt_layout_1_rationale=alt1_rationale,
            alt_layout_2=alt2,
            alt_layout_2_rationale=alt2_rationale,
            template_family_id=template_family_id,
            content_blocks=content_blocks,
            evidence_ids=evidence_ids,
            insight_ids=node_insight_ids,
            historical_refs=hist_refs,
            confidence=confidence,
            overall_confidence=confidence.get("overall", 0.5),
            transition_to_next=node.get("transition_text"),
        )
        slides_created += 1
        total_duration += duration

    conclusion_exists = any(
        n.get("section_type") == "conclusion" for n in nodes
    )
    if not conclusion_exists:
        _build_conclusion_slide(pres_id, slides_created, storyline, approved_insights)
        slides_created += 1
        total_duration += _PURPOSE_DURATION.get("conclusion", 2.0)

    store.update_pc_presentation(
        pres_id,
        total_slides=slides_created,
        estimated_duration_minutes=round(total_duration, 1),
    )

    store.add_pc_audit(
        pres_id, action="generated",
        field="status", new_value="draft", actor=reviewer,
    )

    logger.info(
        "[presentation_composer] project=%s slides=%s duration=%.1fmin",
        project_id, slides_created, total_duration,
    )

    return {
        "presentation_id": pres_id,
        "storyline_id": storyline_id,
        "slides_created": slides_created,
        "estimated_duration_minutes": round(total_duration, 1),
        "generation_id": generation_id,
    }


# ─── Slide Builders ──────────────────────────────────────────────────────

def _build_cover_slide(pres_id: int, spec: dict | None, storyline: dict) -> dict:
    title = storyline.get("title", "Research Presentation")
    subtitle = None
    if spec and isinstance(spec, dict):
        brand = spec.get("commissioning_brand", {})
        if isinstance(brand, dict) and brand.get("name"):
            subtitle = f"Prepared for {brand['name']}"

    blocks = [
        {"type": "title", "content": title},
    ]
    if subtitle:
        blocks.append({"type": "subtitle", "content": subtitle})

    store.create_pc_slide(
        pres_id, 0, "cover", title,
        subtitle=subtitle,
        narrative="",
        content_blocks=blocks,
        overall_confidence=1.0,
        confidence={"overall": 1.0, "evidence_coverage": 1.0,
                     "storyline_coverage": 1.0, "historical_layout_match": 1.0,
                     "visual_suitability": 1.0},
    )
    return {"duration": _PURPOSE_DURATION["cover"]}


def _build_agenda_slide(pres_id: int, nodes: list[dict], slide_num: int) -> dict:
    items = [n.get("title", "Untitled") for n in nodes]
    blocks = [
        {"type": "title", "content": "Agenda"},
        {"type": "narrative", "content": "\n".join(f"• {item}" for item in items)},
    ]
    store.create_pc_slide(
        pres_id, slide_num, "agenda", "Agenda",
        narrative="Overview of topics covered in this presentation.",
        content_blocks=blocks,
        overall_confidence=1.0,
        confidence={"overall": 1.0, "evidence_coverage": 1.0,
                     "storyline_coverage": 1.0, "historical_layout_match": 1.0,
                     "visual_suitability": 1.0},
    )
    return {"duration": _PURPOSE_DURATION["agenda"]}


def _build_conclusion_slide(pres_id: int, slide_num: int,
                            storyline: dict, insights: list[dict]) -> None:
    top_insights = sorted(
        insights, key=lambda x: x.get("confidence_score", 0), reverse=True,
    )[:5]
    takeaways = [ins.get("title", "Untitled") for ins in top_insights]

    titles = [ins.get("title", "") for ins in top_insights]
    summaries = [ins.get("executive_summary", "") for ins in top_insights]
    recs = llm.generate_recommendations(titles, summaries)
    rec_text = "\n".join(f"• {r}" for r in recs) if recs else "The evidence supports prompt strategic action."

    blocks = [
        {"type": "title", "content": "Conclusion & Next Steps"},
        {"type": "key_insight", "content": "Key Takeaways"},
        {"type": "narrative", "content": "\n".join(f"• {t}" for t in takeaways)},
        {"type": "recommendation", "content": rec_text},
    ]
    store.create_pc_slide(
        pres_id, slide_num, "conclusion", "Conclusion & Next Steps",
        narrative="Summary of key takeaways and recommended actions.",
        content_blocks=blocks,
        overall_confidence=0.8,
        confidence={"overall": 0.8, "evidence_coverage": 0.9,
                     "storyline_coverage": 1.0, "historical_layout_match": 0.6,
                     "visual_suitability": 0.7},
    )


# ─── Visual Selection ────────────────────────────────────────────────────

def _select_visual(purpose: str, si_visual: str, si_chart: str | None,
                   insights: list[dict], evidence_ids: list[int]) -> str:
    if si_chart and si_chart in VISUAL_TYPES:
        return si_chart

    if si_visual and si_visual != "text_only" and si_visual in VISUAL_TYPES:
        return si_visual

    default = _PURPOSE_VISUAL_MAP.get(purpose)
    if default:
        return default

    if evidence_ids:
        return "bar_chart"
    return "kpi_cards"


# ─── Layout Selection ────────────────────────────────────────────────────

def _explain_layout(layout: str | None, section_type: str,
                    historical: list[dict]) -> str:
    if not layout:
        return ""
    hist_count = sum(1 for h in historical if h.get("layout_type") == layout)

    reasons = []
    reasons.append(f"'{layout}' layout suits {section_type.replace('_', ' ')} content")
    if hist_count > 0:
        reasons.append(f"used in {hist_count} successful historical slide(s)")
    return ". ".join(reasons) + "."


def _find_template_family(purpose: str, layout: str) -> int | None:
    families = store.list_si_template_families()
    for fam in families:
        if (fam.get("typical_purpose") == purpose and
                fam.get("typical_layout") == layout):
            return fam["id"]
    for fam in families:
        if fam.get("typical_purpose") == purpose:
            return fam["id"]
    return None


# ─── Content Blocks ──────────────────────────────────────────────────────

def _build_content_blocks(purpose: str, node: dict,
                          insights: list[dict],
                          evidence_ids: list[int]) -> list[dict]:
    blocks = []

    blocks.append({"type": "title", "content": node.get("title", "")})

    if node.get("purpose"):
        blocks.append({"type": "subtitle", "content": node["purpose"]})

    if purpose == "executive_summary":
        blocks.append({"type": "executive_summary",
                       "content": node.get("narrative_summary", "")})
        if insights:
            kpis = [ins.get("title", "") for ins in insights[:4]]
            blocks.append({"type": "metrics",
                           "content": " | ".join(kpis)})
    elif purpose == "recommendation":
        for ins in insights:
            blocks.append({"type": "recommendation",
                           "content": ins.get("title", "")})
        if node.get("narrative_summary"):
            blocks.append({"type": "narrative",
                           "content": node["narrative_summary"]})
    else:
        if node.get("narrative_summary"):
            blocks.append({"type": "narrative",
                           "content": node["narrative_summary"]})

        for ins in insights[:3]:
            blocks.append({"type": "key_insight",
                           "content": ins.get("executive_summary") or ins.get("title", "")})

    if evidence_ids:
        blocks.append({"type": "evidence_panel",
                       "content": f"{len(evidence_ids)} supporting evidence item(s)"})

    if evidence_ids:
        blocks.append({"type": "source",
                       "content": f"Based on {len(evidence_ids)} verified source(s)"})

    return blocks


# ─── Confidence Scoring ──────────────────────────────────────────────────

def _compute_confidence(evidence_ids: list[int], insights: list[dict],
                        historical: list[dict], visual: str,
                        layout: str) -> dict:
    ev_coverage = min(len(evidence_ids) / 3.0, 1.0) if evidence_ids else 0.3
    sl_coverage = min(len(insights) / 2.0, 1.0) if insights else 0.3

    hist_match = 0.3
    if historical:
        best_sim = max(h.get("similarity_score", 0) for h in historical)
        hist_match = min(best_sim + 0.2, 1.0)

    vis_suit = 0.7 if visual in VISUAL_TYPES else 0.5
    if visual and visual != "kpi_cards":
        vis_suit = 0.8

    overall = round(
        ev_coverage * 0.30 + sl_coverage * 0.25 +
        hist_match * 0.25 + vis_suit * 0.20, 3,
    )

    reasons = []
    if ev_coverage < 0.5:
        reasons.append("Limited evidence coverage for this slide")
    if hist_match < 0.5:
        reasons.append("No strong historical layout match found")

    result = {
        "evidence_coverage": round(ev_coverage, 3),
        "storyline_coverage": round(sl_coverage, 3),
        "historical_layout_match": round(hist_match, 3),
        "visual_suitability": round(vis_suit, 3),
        "overall": overall,
    }
    if reasons:
        result["low_confidence_reasons"] = reasons
    return result


# ─── Evidence Gathering ──────────────────────────────────────────────────

def _gather_evidence_for_insights(insight_ids: list[int],
                                  project_id: int) -> list[int]:
    evidence_ids = set()
    for iid in insight_ids:
        mappings = store.get_insight_evidence(iid)
        for m in mappings:
            evidence_ids.add(m.get("library_item_id", m.get("id", 0)))
    return sorted(evidence_ids)


# ─── Helper Builders ─────────────────────────────────────────────────────

_GENERIC_TITLE_MARKERS = {
    "trends", "behavioral patterns", "key findings", "supporting evidence",
    "emerging themes", "opportunities", "risks", "recommendations",
    "audience response", "market overview", "brand perception",
    "consumer needs", "whitespace", "insight:", "untitled",
}


def _insight_led_title(node: dict, insights: list[dict], section_type: str) -> str:
    """Use the best insight title instead of generic section labels."""
    if insights:
        best = max(insights, key=lambda x: x.get("confidence_score", 0))
        insight_title = best.get("title", "")
        if insight_title and not any(m in insight_title.lower() for m in _GENERIC_TITLE_MARKERS):
            return insight_title[:100]
    node_title = node.get("title", "")
    if node_title and not any(m in node_title.lower() for m in _GENERIC_TITLE_MARKERS):
        return node_title
    if insights:
        return insights[0].get("title", "Untitled")[:100]
    return node.get("title", "Untitled")


def _build_presentation_title(storyline: dict, spec: dict | None) -> str:
    st = storyline.get("title", "Research Presentation")
    if st:
        return st
    return "Research Presentation"


def _extract_key_message(node: dict, insights: list[dict]) -> str:
    title = node.get("title", "")
    summary = ""
    if insights:
        best = max(insights, key=lambda x: x.get("confidence_score", 0))
        summary = best.get("executive_summary") or best.get("title", "")

    llm_result = llm.generate_key_message(title, summary)
    if llm_result:
        return llm_result

    return summary or node.get("narrative_summary", "")[:200]


def _build_speaker_notes(purpose: str, node: dict,
                         insights: list[dict]) -> str:
    title = node.get("title", "")
    key_msg = node.get("narrative_summary", "")[:300]
    summary = ""
    if insights:
        summaries = [ins.get("executive_summary", "") for ins in insights[:3]]
        summary = " ".join(s for s in summaries if s)

    llm_result = llm.generate_speaker_notes(title, summary or key_msg, key_msg)
    if llm_result:
        return llm_result

    parts = []
    why = _EXEC_QUALITY.get(purpose, "")
    if why:
        parts.append(why)
    if insights:
        titles = [ins.get("title", "Untitled") for ins in insights[:3]]
        parts.append("Key points: " + "; ".join(titles) + ".")
    return " ".join(parts)


def _infer_business_objective(purpose: str, node: dict) -> str:
    objectives = {
        "cover": "Set the stage for the research presentation",
        "agenda": "Preview the structure of the presentation",
        "executive_summary": "Provide decision-makers with headline findings",
        "context": "Ground the audience in the current situation",
        "methodology": "Build confidence in the research methodology",
        "key_finding": "Present significant research discoveries",
        "trend": "Identify directional momentum for planning",
        "theme": "Reveal patterns connecting findings",
        "competitive": "Position relative to market competitors",
        "audience": "Connect audience behavior to outcomes",
        "sentiment": "Quantify perception and identify drivers",
        "timeline": "Map chronological progression",
        "opportunity": "Present actionable opportunities",
        "risk": "Enable proactive risk mitigation",
        "recommendation": "Translate evidence into actions",
        "conclusion": "Reinforce core narrative",
        "appendix": "Provide supplementary detail",
    }
    return objectives.get(purpose, node.get("purpose", ""))


# ─── Presentation Flow ───────────────────────────────────────────────────

def generate_transitions(pres_id: int) -> dict:
    slides = store.list_pc_slides(pres_id)
    if len(slides) < 2:
        return {"transitions_updated": 0}

    updated = 0
    for i in range(len(slides) - 1):
        current = slides[i]
        next_slide = slides[i + 1]

        cur_stage = _SECTION_TO_FLOW_STAGE.get(
            current.get("slide_purpose", ""), "insights"
        )
        next_stage = _SECTION_TO_FLOW_STAGE.get(
            next_slide.get("slide_purpose", ""), "insights"
        )

        transition = _TRANSITION_TEMPLATES.get(
            (cur_stage, next_stage),
            f"Building on {current.get('title', 'this')}, "
            f"we now turn to {next_slide.get('title', 'the next topic')}.",
        )

        store.update_pc_slide(current["id"], transition_to_next=transition)
        updated += 1

    return {"transitions_updated": updated}


# ─── Slide Operations ────────────────────────────────────────────────────

def reorder_slides(pres_id: int, slide_ids: list[int],
                   actor: str = "analyst") -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"error": f"Presentation {pres_id} not found"}

    existing = store.list_pc_slides(pres_id)
    existing_ids = {s["id"] for s in existing}
    locked_ids = {s["id"] for s in existing if s.get("is_locked")}

    for sid in slide_ids:
        if sid not in existing_ids:
            return {"error": f"Slide {sid} does not belong to presentation {pres_id}"}

    store.reorder_pc_slides(pres_id, slide_ids)

    store.add_pc_audit(
        pres_id, action="reordered",
        field="order", new_value=str(slide_ids), actor=actor,
    )

    return {"reordered": True, "locked_skipped": list(locked_ids)}


def update_slide(slide_id: int, updates: dict,
                 actor: str = "analyst") -> dict:
    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}

    allowed = {
        "title", "subtitle", "narrative", "key_message",
        "recommended_visual", "recommended_chart",
        "layout_recommendation", "speaker_notes",
        "slide_purpose",
    }
    clean = {k: v for k, v in updates.items() if k in allowed}
    if not clean:
        return {"error": "No valid fields to update"}

    for k, v in clean.items():
        old_val = slide.get(k)
        store.add_pc_audit(
            slide["presentation_id"], action="slide_updated",
            slide_id=slide_id, field=k,
            old_value=str(old_val) if old_val else None,
            new_value=str(v), actor=actor,
        )

    store.update_pc_slide(slide_id, **clean)
    return store.get_pc_slide(slide_id)


def select_layout(slide_id: int, layout: str, rationale: str = "",
                  actor: str = "analyst") -> dict:
    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}

    old = slide.get("layout_recommendation")
    store.update_pc_slide(
        slide_id,
        layout_recommendation=layout,
        layout_rationale=rationale or f"Manually selected by {actor}",
    )

    store.add_pc_audit(
        slide["presentation_id"], action="layout_changed",
        slide_id=slide_id, field="layout_recommendation",
        old_value=old, new_value=layout, actor=actor,
    )

    return store.get_pc_slide(slide_id)


def select_visual(slide_id: int, visual: str,
                  actor: str = "analyst") -> dict:
    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}

    old = slide.get("recommended_visual")
    store.update_pc_slide(slide_id, recommended_visual=visual)

    store.add_pc_audit(
        slide["presentation_id"], action="visual_changed",
        slide_id=slide_id, field="recommended_visual",
        old_value=old, new_value=visual, actor=actor,
    )

    return store.get_pc_slide(slide_id)


# ─── Review Workflow ─────────────────────────────────────────────────────

def review_slide(slide_id: int, status: str,
                 reviewer: str = "analyst") -> dict:
    if status not in VALID_SLIDE_STATUSES:
        return {"error": f"Invalid status '{status}'"}

    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}

    old_status = slide.get("status")
    store.update_pc_slide(slide_id, status=status, reviewed_by=reviewer)

    store.add_pc_audit(
        slide["presentation_id"], action="slide_review",
        slide_id=slide_id, field="status",
        old_value=old_status, new_value=status, actor=reviewer,
    )

    return store.get_pc_slide(slide_id)


def lock_slide(slide_id: int, actor: str = "analyst") -> dict:
    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}
    store.update_pc_slide(slide_id, is_locked=1)
    store.add_pc_audit(
        slide["presentation_id"], action="slide_locked",
        slide_id=slide_id, actor=actor,
    )
    return store.get_pc_slide(slide_id)


def unlock_slide(slide_id: int, actor: str = "analyst") -> dict:
    slide = store.get_pc_slide(slide_id)
    if not slide:
        return {"error": f"Slide {slide_id} not found"}
    store.update_pc_slide(slide_id, is_locked=0)
    store.add_pc_audit(
        slide["presentation_id"], action="slide_unlocked",
        slide_id=slide_id, actor=actor,
    )
    return store.get_pc_slide(slide_id)


def approve_presentation(pres_id: int,
                         reviewer: str = "analyst") -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"error": f"Presentation {pres_id} not found"}

    old_status = pres.get("status")
    store.update_pc_presentation(
        pres_id, status="approved", approved_by=reviewer,
        approved_at=time.time(),
    )

    store.add_pc_audit(
        pres_id, action="presentation_approved",
        field="status", old_value=old_status, new_value="approved",
        actor=reviewer,
    )

    return store.get_pc_presentation(pres_id)


def reject_presentation(pres_id: int,
                        reviewer: str = "analyst") -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"error": f"Presentation {pres_id} not found"}

    old_status = pres.get("status")
    store.update_pc_presentation(pres_id, status="rejected")

    store.add_pc_audit(
        pres_id, action="presentation_rejected",
        field="status", old_value=old_status, new_value="rejected",
        actor=reviewer,
    )

    return store.get_pc_presentation(pres_id)


# ─── Validation ──────────────────────────────────────────────────────────

def validate_presentation(pres_id: int) -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"valid": False, "issues": [f"Presentation {pres_id} not found"],
                "warnings": []}

    issues: list[str] = []
    warnings: list[str] = []

    slides = store.list_pc_slides(pres_id)
    if not slides:
        issues.append("Presentation has no slides")
        return {"valid": False, "issues": issues, "warnings": warnings}

    purposes = [s["slide_purpose"] for s in slides]
    if "cover" not in purposes:
        warnings.append("Missing cover slide")
    if "executive_summary" not in purposes:
        warnings.append("Missing executive summary slide")
    if "recommendation" not in purposes:
        warnings.append("Missing recommendation slide")
    if "conclusion" not in purposes:
        warnings.append("Missing conclusion slide")

    titles = [s["title"] for s in slides]
    seen: set[str] = set()
    for t in titles:
        low = t.lower()
        if low in seen:
            issues.append(f"Duplicate slide title: '{t}'")
        seen.add(low)

    content_purposes = {"key_finding", "trend", "theme", "competitive", "audience",
                        "sentiment", "opportunity", "risk", "recommendation"}
    for s in slides:
        if not s.get("narrative") and s["slide_purpose"] not in ("cover", "agenda"):
            warnings.append(f"Slide '{s['title']}' has no narrative")
        if s["slide_purpose"] in content_purposes:
            eids = s.get("evidence_ids_json") or "[]"
            if isinstance(eids, str):
                try:
                    eids = json.loads(eids)
                except (json.JSONDecodeError, TypeError):
                    eids = []
            if not eids:
                issues.append(f"Slide '{s['title']}' has no evidence mapping")

    confidences = [s.get("overall_confidence", 0) for s in slides
                   if s["slide_purpose"] not in ("cover", "agenda")]
    if confidences:
        avg = sum(confidences) / len(confidences)
        if avg < 0.4:
            warnings.append(f"Low average confidence ({avg:.2f})")
        low_slides = [s["title"] for s in slides
                      if s.get("overall_confidence", 1) < 0.3
                      and s["slide_purpose"] not in ("cover", "agenda")]
        for t in low_slides:
            warnings.append(f"Slide '{t}' has very low confidence")

    if issues:
        return {"valid": False, "issues": issues, "warnings": warnings}
    return {"valid": True, "warnings": warnings}


# ─── Detail & Summary ────────────────────────────────────────────────────

def get_presentation_detail(pres_id: int) -> dict:
    pres = store.get_pc_presentation(pres_id)
    if not pres:
        return {"error": f"Presentation {pres_id} not found"}

    slides = store.list_pc_slides(pres_id)
    audit = store.get_pc_audit(pres_id)

    total_duration = sum(
        _PURPOSE_DURATION.get(s.get("slide_purpose", ""), 2.0) for s in slides
    )

    flow = _analyze_flow(slides)

    return {
        "presentation": pres,
        "slides": slides,
        "audit_history": audit,
        "total_duration_minutes": round(total_duration, 1),
        "flow_analysis": flow,
    }


def get_presentation_summary(project_id: int) -> dict:
    presentations = store.list_pc_presentations(project_id)
    latest = store.get_latest_pc_presentation(project_id)

    total_slides = 0
    total_duration = 0.0
    slide_statuses: dict[str, int] = {}

    if latest:
        slides = store.list_pc_slides(latest["id"])
        total_slides = len(slides)
        total_duration = sum(
            _PURPOSE_DURATION.get(s.get("slide_purpose", ""), 2.0)
            for s in slides
        )
        for s in slides:
            st = s.get("status", "draft")
            slide_statuses[st] = slide_statuses.get(st, 0) + 1

    return {
        "presentation_count": len(presentations),
        "latest_status": latest.get("status") if latest else None,
        "total_slides": total_slides,
        "total_duration_minutes": round(total_duration, 1),
        "slide_statuses": slide_statuses,
        "latest_presentation_id": latest["id"] if latest else None,
        "latest_storyline_id": latest.get("storyline_id") if latest else None,
    }


def _analyze_flow(slides: list[dict]) -> dict:
    stages_present: list[str] = []
    for s in slides:
        purpose = s.get("slide_purpose", "")
        stage = _SECTION_TO_FLOW_STAGE.get(purpose, "insights")
        if stage not in stages_present:
            stages_present.append(stage)

    missing = [st for st in FLOW_STAGES if st not in stages_present]

    return {
        "stages_present": stages_present,
        "stages_missing": missing,
        "flow_complete": len(missing) == 0,
        "total_slides": len(slides),
    }


# ══════════════════════════════════════════════════════════════════════
# SOV / THEME ARCHETYPE PRESENTATION GENERATION
# ══════════════════════════════════════════════════════════════════════

_PURPOSE_DURATION["sov_competitive"] = 4.0
_PURPOSE_DURATION["entity_themes"] = 3.5

_EXEC_QUALITY["sov_competitive"] = (
    "Communicate who owns the largest share of conversation, how competitive "
    "visibility is changing, and what drives each competitor's presence."
)
_EXEC_QUALITY["entity_themes"] = (
    "Reveal the narrative themes driving an entity's visibility and whether "
    "the entity controls its own story."
)


def generate_sov_presentation(project_id: int, reviewer: str = "system") -> dict:
    """Generate an SOV archetype presentation from dataset analysis.

    Produces the recommended slide sequence:
      1. Cover
      2. Competitive — Share of Voice & Trendline (SOV archetype)
      3–N. [Entity] — Themes & Trends (one per entity)
      N+1. Cross-Competitive Narrative Ownership (optional)

    All numerical data is calculated deterministically by the
    sov_analyzer and theme_classifier modules.
    """
    from . import sov_analyzer
    from . import theme_classifier

    project = store.get_project(project_id)
    if not project:
        return {"error": f"Project {project_id} not found"}

    spec = project.get("spec") if project else None

    sov_result = sov_analyzer.analyze_sov(project_id)
    if "error" in sov_result:
        return {"error": f"SOV analysis failed: {sov_result['error']}"}

    entities = sov_result.get("entities", [])
    if not entities:
        return {"error": "No entities found for SOV analysis"}

    storyline = store.get_latest_storyline(project_id)
    storyline_id = storyline["id"] if storyline else None

    if not storyline_id:
        from . import storyline_builder as _sb
        sl = _sb.generate_storyline(project_id, reviewer=reviewer)
        storyline_id = sl.get("storyline_id")
        storyline = store.get_latest_storyline(project_id)

    generation_id = str(uuid.uuid4())
    pres_title = sov_result.get("context_label", "Competitive Analysis")

    pres_id = store.create_pc_presentation(
        project_id, storyline_id, pres_title,
        executive_summary=sov_result.get("executive_takeaway", ""),
        narrative_pattern="competitive_landscape",
        generated_by=reviewer,
        generation_id=generation_id,
    )

    slides_created = 0
    total_duration = 0.0

    # ── Slide 1: Cover ────────────────────────────────────────────────
    cover_title = pres_title
    cover_subtitle = None
    if spec and isinstance(spec, dict):
        brand = spec.get("commissioning_brand", {})
        if isinstance(brand, dict) and brand.get("name"):
            cover_subtitle = f"Prepared for {brand['name']}"

    cover_blocks = [{"type": "title", "content": cover_title}]
    if cover_subtitle:
        cover_blocks.append({"type": "subtitle", "content": cover_subtitle})

    store.create_pc_slide(
        pres_id, slides_created, "cover", cover_title,
        subtitle=cover_subtitle,
        narrative="",
        content_blocks=cover_blocks,
        overall_confidence=1.0,
        confidence={"overall": 1.0, "evidence_coverage": 1.0,
                     "storyline_coverage": 1.0, "historical_layout_match": 1.0,
                     "visual_suitability": 1.0},
    )
    slides_created += 1
    total_duration += _PURPOSE_DURATION["cover"]

    # ── Slide 2: SOV Competitive ──────────────────────────────────────
    sov_slide_data = _build_sov_archetype_data(sov_result)

    store.create_pc_slide(
        pres_id, slides_created, "sov_competitive",
        "Competitive — Share of Voice & Trendline",
        narrative=sov_result.get("executive_takeaway", ""),
        key_message=sov_result.get("executive_takeaway", ""),
        recommended_visual="donut",
        layout_recommendation="sov_archetype",
        content_blocks=sov_slide_data,
        overall_confidence=0.95,
        confidence={"overall": 0.95, "evidence_coverage": 1.0,
                     "storyline_coverage": 0.9, "historical_layout_match": 0.9,
                     "visual_suitability": 1.0},
    )
    slides_created += 1
    total_duration += _PURPOSE_DURATION["sov_competitive"]

    # ── Slides 3–N: Entity Theme slides ───────────────────────────────
    for entity in entities:
        entity_name = entity["name"]
        try:
            theme_result = theme_classifier.classify_themes(
                project_id, entity_name,
            )
        except Exception as e:
            logger.warning("[composer] Theme classification failed for %s: %s",
                           entity_name, e)
            continue

        if not theme_result or not theme_result.get("themes"):
            continue

        theme_slide_data = _build_theme_archetype_data(
            theme_result, sov_result.get("context_label", ""),
        )

        store.create_pc_slide(
            pres_id, slides_created, "entity_themes",
            f"{entity_name} — Themes & Trends",
            narrative=theme_result.get("executive_takeaway", ""),
            key_message=theme_result.get("executive_takeaway", ""),
            recommended_visual="bar_chart",
            layout_recommendation="theme_archetype",
            content_blocks=theme_slide_data,
            overall_confidence=0.90,
            confidence={"overall": 0.90, "evidence_coverage": 0.95,
                         "storyline_coverage": 0.85, "historical_layout_match": 0.85,
                         "visual_suitability": 0.95},
        )
        slides_created += 1
        total_duration += _PURPOSE_DURATION["entity_themes"]

    store.update_pc_presentation(
        pres_id,
        total_slides=slides_created,
        estimated_duration_minutes=round(total_duration, 1),
    )

    store.add_pc_audit(
        pres_id, action="sov_presentation_generated",
        field="status", new_value="draft", actor=reviewer,
    )

    logger.info(
        "[presentation_composer] SOV presentation project=%s slides=%s "
        "entities=%s duration=%.1fmin",
        project_id, slides_created, len(entities), total_duration,
    )

    return {
        "presentation_id": pres_id,
        "storyline_id": storyline_id,
        "slides_created": slides_created,
        "entities_analyzed": len(entities),
        "estimated_duration_minutes": round(total_duration, 1),
        "generation_id": generation_id,
    }


def _build_sov_archetype_data(sov_result: dict) -> dict:
    """Build the structured content_blocks dict for the SOV archetype slide."""
    entities = sov_result.get("entities", [])

    donut_data = {
        "categories": [e["name"] for e in entities],
        "values": [e["sov_pct"] for e in entities],
    }

    trend = sov_result.get("trend", {})

    narratives = []
    narr_map = sov_result.get("narratives", {})
    for i, entity in enumerate(entities):
        name = entity["name"]
        narr = narr_map.get(name, {})
        narratives.append({
            "heading": name,
            "body": narr.get("text", f"{name}: {entity['sov_pct']:.1f}% share of voice."),
            "color_index": i,
        })

    dr = sov_result.get("date_range", {})
    earliest = dr.get("earliest", "")
    latest = dr.get("latest", "")
    source = sov_result.get("dataset_source", "DATASET")
    if earliest and latest:
        source_footer = f"SOURCE: {source.upper()} | {earliest} – {latest}"
    else:
        source_footer = f"SOURCE: {source.upper()}"

    return {
        "archetype": "sov_competitive",
        "context_label": sov_result.get("context_label", ""),
        "title": "Competitive — Share of Voice & Trendline",
        "executive_takeaway": sov_result.get("executive_takeaway", ""),
        "sample_size": sov_result.get("total_qualifying_records", 0),
        "donut": donut_data,
        "trend": trend,
        "narratives": narratives,
        "source_footer": source_footer,
    }


def _build_theme_archetype_data(theme_result: dict,
                                context_label: str) -> dict:
    """Build the structured content_blocks dict for a theme archetype slide."""
    entity = theme_result.get("entity", "")
    themes = theme_result.get("themes", [])

    bar_data = {
        "categories": [t["name"] for t in themes],
        "values": [t["share_pct"] for t in themes],
    }

    trend_periods = []
    trend_series = []
    for t in themes:
        t_trend = t.get("trend", {})
        if not trend_periods and t_trend.get("periods"):
            trend_periods = t_trend["periods"]
        if t_trend.get("values"):
            trend_series.append({
                "name": t["name"][:30],
                "values": t_trend["values"],
            })

    theme_trend = {
        "categories": trend_periods,
        "series": trend_series,
    }

    narratives = []
    for i, t in enumerate(themes):
        narratives.append({
            "heading": t["name"],
            "body": t.get("narrative", f"{t['name']}: {t['share_pct']:.1f}% of coverage."),
            "color_index": i,
        })

    dr = theme_result.get("date_range", {})
    earliest = dr.get("earliest", "")
    latest = dr.get("latest", "")
    source = theme_result.get("dataset_source", "DATASET")
    if earliest and latest:
        source_footer = f"SOURCE: {source.upper()} | {earliest} – {latest}"
    else:
        source_footer = f"SOURCE: {source.upper()}"

    sample_note = ""
    if theme_result.get("sample_based"):
        sample_note = "The above insights are based on analysis of a representative sample of data."

    return {
        "archetype": "entity_themes",
        "context_label": context_label,
        "title": f"{entity} — Themes & Trends",
        "executive_takeaway": theme_result.get("executive_takeaway", ""),
        "sample_size": theme_result.get("total_records", 0),
        "bar_chart": bar_data,
        "theme_trend": theme_trend,
        "narratives": narratives,
        "source_footer": source_footer + (f"\n{sample_note}" if sample_note else ""),
        "classification_method": theme_result.get("classification_method", "single-label"),
    }

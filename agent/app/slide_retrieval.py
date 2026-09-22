"""Slide retrieval engine for Slide Intelligence.

Retrieves historical slides relevant to storyline nodes using text similarity,
metadata matching, and diversity-aware ranking. Also provides recommendations
for layout, visual type, and content hierarchy.

Historical slides are ONLY used for presentation style reference —
they must NEVER be used as research evidence or factual sources.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Optional

from . import intelligence_store as store

# ─── Section → Purpose mapping for retrieval ────────────────────────────────

_SECTION_TO_PURPOSE = {
    "executive_summary": ["executive_summary", "key_finding"],
    "situation": ["scope", "methodology", "key_finding"],
    "key_findings": ["key_finding", "trend", "sentiment"],
    "supporting_evidence": ["key_finding", "trend", "consumer_insight"],
    "emerging_themes": ["trend", "theme", "consumer_insight"],
    "risks": ["risk", "crisis"],
    "opportunities": ["opportunity", "trend"],
    "competitive_perspective": ["competitive"],
    "recommendations": ["recommendation"],
    "conclusion": ["conclusion", "executive_summary"],
    "additional_findings": ["key_finding", "other"],
    "sov_competitive": ["competitive", "trend", "key_finding"],
    "entity_themes": ["theme", "trend", "key_finding"],
}

# ─── Archetype definitions for template matching ──────────────────────────

ARCHETYPES = {
    "sov_competitive": {
        "name": "Competitive SOV + Trend + Competitor Narratives",
        "required_elements": [
            "title_area", "executive_takeaway", "overall_sov_visual",
            "trend_visual", "competitor_narrative_blocks", "sample_metadata",
        ],
        "preferred_layouts": ["sov_archetype", "dashboard", "two_panel"],
        "preferred_visuals": ["donut", "pie", "stacked_bar"],
        "preferred_charts": ["donut", "line_chart"],
    },
    "entity_themes": {
        "name": "Entity Themes + Theme Trend + Theme Narratives",
        "required_elements": [
            "entity_title", "executive_takeaway", "ranked_theme_visual",
            "theme_trend_visual", "theme_narrative_blocks", "sample_metadata",
        ],
        "preferred_layouts": ["theme_archetype", "dashboard", "two_panel"],
        "preferred_visuals": ["bar_chart", "horizontal_bar"],
        "preferred_charts": ["bar_chart", "line_chart"],
    },
}

_SECTION_TO_LAYOUT = {
    "executive_summary": ["dashboard", "kpi_cards", "text_led"],
    "key_findings": ["chart_led", "mixed", "two_column", "single_insight"],
    "supporting_evidence": ["chart_led", "mixed", "matrix"],
    "emerging_themes": ["text_led", "single_insight", "kpi_cards"],
    "risks": ["text_led", "two_column", "kpi_cards"],
    "opportunities": ["single_insight", "text_led"],
    "competitive_perspective": ["comparison", "chart_led", "two_column"],
    "recommendations": ["text_led", "single_insight", "kpi_cards"],
    "conclusion": ["text_led", "single_insight"],
    "situation": ["text_led", "title_body"],
}

_SECTION_TO_VISUAL = {
    "executive_summary": ["kpi", "bar_chart", "table"],
    "key_findings": ["bar_chart", "line_chart", "stacked_bar", "pie"],
    "supporting_evidence": ["bar_chart", "table", "line_chart"],
    "emerging_themes": ["theme_cluster", "bar_chart", "text_only"],
    "risks": ["kpi", "text_only", "bar_chart"],
    "opportunities": ["text_only", "bar_chart", "kpi"],
    "competitive_perspective": ["bar_chart", "stacked_bar", "table"],
    "recommendations": ["text_only", "kpi", "table"],
    "conclusion": ["text_only", "kpi"],
    "situation": ["text_only", "timeline"],
}


# ─── Retrieval ──────────────────────────────────────────────────────────────

def retrieve_for_node(node_id: int, top_k: int = 10) -> dict:
    """Retrieve the most relevant historical slides for a storyline node.
    Returns diverse results with similarity scores and recommendations.
    """
    node = store.get_story_node(node_id)
    if not node:
        return {"error": "Story node not found"}

    section_type = node.get("section_type", "key_findings")
    title = node.get("title", "")
    narrative = node.get("narrative_summary", "")
    suggested_visual = node.get("suggested_visual", "")

    preferred_purposes = _SECTION_TO_PURPOSE.get(section_type, ["key_finding"])
    preferred_layouts = _SECTION_TO_LAYOUT.get(section_type, [])
    preferred_visuals = _SECTION_TO_VISUAL.get(section_type, [])

    all_slides = store.list_si_slides(is_excluded=False, limit=5000)
    if not all_slides:
        return {"node_id": node_id, "results": [], "message": "No slides indexed"}

    scored = []
    for slide in all_slides:
        score = _compute_similarity(slide, node, preferred_purposes,
                                     preferred_layouts, preferred_visuals)
        if score > 0.1:
            scored.append((slide, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    results = _ensure_diversity(scored, top_k)

    output = []
    for slide, score in results:
        rec_elements, not_reuse = _recommend_elements(slide, section_type)
        output.append({
            "slide_id": slide["id"],
            "slide_number": slide.get("slide_number"),
            "presentation_id": slide.get("presentation_id"),
            "title_text": slide.get("title_text"),
            "slide_purpose": slide.get("slide_purpose"),
            "layout_type": slide.get("layout_type"),
            "visual_type": slide.get("visual_type"),
            "client": slide.get("client"),
            "similarity_score": round(score, 3),
            "match_reason": _explain_match(slide, node, preferred_purposes),
            "recommended_elements": rec_elements,
            "elements_not_to_reuse": not_reuse,
            "confidence": round(min(score + 0.2, 1.0), 2),
        })

    store.add_si_retrieval_history(
        query_text=f"node:{node_id} section:{section_type} title:{title[:50]}",
        results=[{"slide_id": r["slide_id"], "score": r["similarity_score"]} for r in output],
        node_id=node_id,
        storyline_id=node.get("storyline_id"),
    )

    return {"node_id": node_id, "section_type": section_type, "results": output}


def _compute_similarity(slide: dict, node: dict, preferred_purposes: list,
                        preferred_layouts: list, preferred_visuals: list) -> float:
    """Multi-dimensional similarity score between a slide and a storyline node."""
    score = 0.0

    purpose = slide.get("slide_purpose", "")
    if purpose in preferred_purposes:
        idx = preferred_purposes.index(purpose)
        score += 0.30 * (1.0 - idx * 0.15)

    layout = slide.get("layout_type", "")
    if layout in preferred_layouts:
        score += 0.15

    visual = slide.get("visual_type", "")
    if visual in preferred_visuals:
        score += 0.10
    node_visual = node.get("suggested_visual", "")
    if node_visual and visual == node_visual:
        score += 0.10

    slide_text = (slide.get("all_text") or "").lower()
    node_text = f"{node.get('title', '')} {node.get('narrative_summary', '')}".lower()
    if slide_text and node_text:
        text_sim = _text_similarity(slide_text, node_text)
        score += text_sim * 0.25

    if slide.get("executive_suitability") == "high":
        score += 0.05
    if slide.get("classification_confidence", 0) > 0.7:
        score += 0.05

    return min(score, 1.0)


def _text_similarity(a: str, b: str) -> float:
    """Fast keyword-overlap similarity (cheaper than SequenceMatcher for large texts)."""
    words_a = set(re.findall(r"\w{3,}", a.lower()))
    words_b = set(re.findall(r"\w{3,}", b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


def _ensure_diversity(scored: list[tuple], top_k: int) -> list[tuple]:
    """Select top_k results ensuring diversity across purpose, layout, and client."""
    if len(scored) <= top_k:
        return scored

    selected = []
    seen_purposes = Counter()
    seen_layouts = Counter()
    seen_clients = Counter()

    for slide, score in scored:
        if len(selected) >= top_k:
            break
        purpose = slide.get("slide_purpose", "other")
        layout = slide.get("layout_type", "other")
        client = slide.get("client", "unknown")

        penalty = 0.0
        if seen_purposes[purpose] >= 2:
            penalty += 0.15
        if seen_layouts[layout] >= 3:
            penalty += 0.10
        if seen_clients[client] >= 3:
            penalty += 0.10

        adjusted = score - penalty
        if adjusted > 0.1 or len(selected) < 3:
            selected.append((slide, score))
            seen_purposes[purpose] += 1
            seen_layouts[layout] += 1
            seen_clients[client] += 1

    return selected


def _explain_match(slide: dict, node: dict, preferred_purposes: list) -> str:
    """Generate a human-readable explanation of why this slide was selected."""
    reasons = []
    purpose = slide.get("slide_purpose", "")
    if purpose in preferred_purposes:
        reasons.append(f"Purpose '{purpose}' matches section type")
    if slide.get("layout_type") in _SECTION_TO_LAYOUT.get(node.get("section_type", ""), []):
        reasons.append(f"Layout '{slide['layout_type']}' is recommended for this section")
    if slide.get("visual_type") == node.get("suggested_visual"):
        reasons.append(f"Visual type matches storyline recommendation")
    if slide.get("has_chart"):
        reasons.append("Contains chart for data presentation")
    if slide.get("executive_suitability") == "high":
        reasons.append("High executive suitability")
    return "; ".join(reasons) if reasons else "General content relevance"


def _recommend_elements(slide: dict, section_type: str) -> tuple[list, list]:
    """Recommend which elements from this slide to reuse and which to avoid."""
    reuse = []
    avoid = []

    layout = slide.get("layout_type", "")
    visual = slide.get("visual_type", "")

    reuse.append(f"Layout structure: {layout.replace('_', ' ')}")
    if visual and visual != "text_only":
        reuse.append(f"Chart/visual type: {visual.replace('_', ' ')}")
    if slide.get("has_chart"):
        reuse.append("Chart placement and sizing")
    reuse.append("Visual hierarchy and spacing")
    reuse.append("Title and headline style")

    avoid.append("Historical data points and statistics")
    avoid.append("Client-specific content and branding")
    avoid.append("Source citations from past research")
    if slide.get("footer_text"):
        avoid.append("Footer text (use current project sources)")

    return reuse, avoid


# ─── Storyline Matching ────────────────────────────────────────────────────

def match_storyline(storyline_id: int) -> dict:
    """Match all nodes in a storyline to relevant historical slides."""
    storyline = store.get_storyline(storyline_id)
    if not storyline:
        return {"error": "Storyline not found"}

    nodes = store.list_story_nodes(storyline_id)
    if not nodes:
        return {"error": "No nodes in storyline"}

    store.delete_si_storyline_matches(storyline_id=storyline_id)

    total_matches = 0
    node_results = []

    for node in nodes:
        result = retrieve_for_node(node["id"], top_k=5)
        if "error" in result:
            node_results.append({"node_id": node["id"], "error": result["error"]})
            continue

        for r in result.get("results", []):
            store.create_si_storyline_match(
                storyline_id=storyline_id,
                node_id=node["id"],
                slide_id=r["slide_id"],
                similarity_score=r["similarity_score"],
                match_reason=r.get("match_reason"),
                recommended_elements=r.get("recommended_elements"),
                elements_not_to_reuse=r.get("elements_not_to_reuse"),
                recommended_layout=r.get("layout_type"),
                recommended_visual=r.get("visual_type"),
                confidence=r.get("confidence", 0.0),
            )
            total_matches += 1

        node_results.append({
            "node_id": node["id"],
            "section_type": node.get("section_type"),
            "matches": len(result.get("results", [])),
        })

    return {
        "storyline_id": storyline_id,
        "total_nodes": len(nodes),
        "total_matches": total_matches,
        "node_results": node_results,
    }


# ─── Recommendation Engine ─────────────────────────────────────────────────

def recommend_for_node(node_id: int) -> dict:
    """Full recommendation for a storyline node: layout, visual, chart,
    content hierarchy, callout style, evidence placement, title style,
    relevant historical slides, and alternative layouts.
    """
    node = store.get_story_node(node_id)
    if not node:
        return {"error": "Story node not found"}

    section_type = node.get("section_type", "key_findings")

    retrieval = retrieve_for_node(node_id, top_k=5)
    historical_slides = retrieval.get("results", [])

    preferred_layouts = _SECTION_TO_LAYOUT.get(section_type, ["title_body"])
    preferred_visuals = _SECTION_TO_VISUAL.get(section_type, ["text_only"])

    best_layout = preferred_layouts[0] if preferred_layouts else "title_body"
    best_visual = preferred_visuals[0] if preferred_visuals else "text_only"
    best_chart = None

    if historical_slides:
        layout_votes = Counter(s.get("layout_type") for s in historical_slides
                              if s.get("layout_type"))
        visual_votes = Counter(s.get("visual_type") for s in historical_slides
                              if s.get("visual_type") and s.get("visual_type") != "text_only")
        if layout_votes:
            best_layout = layout_votes.most_common(1)[0][0]
        if visual_votes:
            best_chart = visual_votes.most_common(1)[0][0]

    alternatives = [l for l in preferred_layouts if l != best_layout][:3]

    content_hierarchy = _get_content_hierarchy(section_type)
    callout_style = _get_callout_style(section_type)
    evidence_placement = _get_evidence_placement(section_type)
    title_style = _get_title_style(section_type)

    return {
        "node_id": node_id,
        "section_type": section_type,
        "best_layout": best_layout,
        "best_visual": best_visual,
        "best_chart": best_chart,
        "best_content_hierarchy": content_hierarchy,
        "best_callout_style": callout_style,
        "best_evidence_placement": evidence_placement,
        "best_title_style": title_style,
        "historical_slides": historical_slides,
        "alternative_layouts": alternatives,
    }


def _get_content_hierarchy(section_type: str) -> list[str]:
    hierarchies = {
        "executive_summary": ["Headline insight", "3-5 KPI cards", "Supporting narrative"],
        "key_findings": ["Finding headline", "Data visualization", "Interpretation", "Source"],
        "supporting_evidence": ["Evidence headline", "Chart/table", "Context note"],
        "emerging_themes": ["Theme title", "Theme description", "Supporting data points"],
        "risks": ["Risk headline", "Severity indicator", "Details", "Mitigation"],
        "opportunities": ["Opportunity title", "Business case", "Evidence", "Next steps"],
        "competitive_perspective": ["Comparison headline", "Side-by-side data", "Takeaway"],
        "recommendations": ["Recommendation title", "Rationale", "Expected impact", "Priority"],
        "conclusion": ["Summary headline", "Key takeaways (3-5)", "Next steps"],
        "situation": ["Context headline", "Background narrative", "Key parameters"],
    }
    return hierarchies.get(section_type, ["Title", "Body content", "Supporting details"])


def _get_callout_style(section_type: str) -> str:
    styles = {
        "executive_summary": "Bold KPI callout with percentage or metric highlight",
        "key_findings": "Insight callout box with key statistic highlighted",
        "recommendation": "Action-oriented callout with priority indicator",
        "risks": "Warning callout with severity badge",
        "opportunities": "Opportunity callout with potential impact metric",
    }
    return styles.get(section_type, "Standard callout with supporting data point")


def _get_evidence_placement(section_type: str) -> str:
    placements = {
        "executive_summary": "Integrated as KPIs above narrative",
        "key_findings": "Central chart/table with narrative below",
        "supporting_evidence": "Primary position — chart fills main area",
        "competitive_perspective": "Side-by-side comparison layout",
        "recommendations": "Supporting evidence below recommendation text",
    }
    return placements.get(section_type, "Below main narrative as supporting context")


def _get_title_style(section_type: str) -> str:
    styles = {
        "executive_summary": "Insight-led: state the conclusion, not the topic",
        "key_findings": "Finding-led: lead with the discovery",
        "recommendation": "Action-led: lead with what to do",
        "conclusion": "Summary-led: lead with the takeaway",
    }
    return styles.get(section_type, "Topic-led: descriptive section title")

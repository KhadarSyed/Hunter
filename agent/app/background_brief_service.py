"""Background Brief Service — transforms raw web research into a structured
Competitive News Brief matching the analyst briefing format.

Uses the Anthropic Claude API to synthesize raw search results into
analytical paragraphs with strategic context, matching the quality of
a senior analyst's competitive intelligence brief.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from . import intelligence_store as store

logger = logging.getLogger(__name__)

SECTION_ORDER = [
    "company_introduction",
    "executive_summary",
    "brand_developments",
    "brand_narrative",
    "competitor_developments",
    "industry_context",
    "key_issues",
    "source_register",
    "methodology",
]

SECTION_TITLES = {
    "company_introduction": "Company Introduction",
    "executive_summary": "Executive Summary",
    "brand_developments": "Brand Material Developments",
    "brand_narrative": "Brand Narrative Assessment",
    "competitor_developments": "Competitor Developments",
    "industry_context": "Industry and Policy Context",
    "key_issues": "Key Issues to Monitor",
    "source_register": "Source Register",
    "methodology": "Methodology and Limitations",
}


def compose_brief(project_id: int, research_id: int, spec: dict, research_data: dict,
                   llm_output: Optional[dict] = None) -> dict:
    source_spec = spec.get("source_spec", {})
    brand_name = (spec.get("commissioning_brand") or source_spec.get("commissioning_brand") or {}).get("name", "")
    rs = spec.get("research_subject") or source_spec.get("research_subject") or {}
    research_subject = rs.get("name", "")
    if not research_subject:
        desc = rs.get("description", "")
        research_subject = desc if len(desc) <= 80 else brand_name
    category = (spec.get("commissioning_brand") or source_spec.get("commissioning_brand") or {}).get("category", "")
    if not category:
        for s in (spec, source_spec):
            subj = s.get("research_subject", {})
            if isinstance(subj, dict):
                desc = subj.get("description", "").lower()
                for kw, cat in [("snack", "snack food"), ("food", "food & beverage"),
                                ("beverage", "food & beverage"), ("jerky", "meat snacks"),
                                ("meat", "meat snacks"), ("beauty", "beauty & personal care"),
                                ("tech", "technology"), ("fashion", "fashion & apparel")]:
                    if kw in desc:
                        category = cat
                        break
            if category:
                break
    if not brand_name and spec.get("project_name"):
        brand_name = spec["project_name"].split()[0]
    if not research_subject:
        research_subject = brand_name
    competitors = _extract_competitors(spec)
    if not competitors:
        competitors = _extract_competitors(source_spec)

    news_items = research_data.get("news_items", [])
    background_items = research_data.get("background_context", [])
    all_sources = news_items + background_items
    research_gaps = research_data.get("research_gaps", [])
    metadata = research_data.get("metadata", {})

    source_register = _build_source_register_list(all_sources)
    source_lookup = {s["url"]: s["ref"] for s in source_register if s.get("url")}

    brand_items, competitor_items, industry_items = _classify_items(
        news_items, research_subject, brand_name, competitors
    )

    llm_client = _get_llm()
    sections = {}
    llm_succeeded = False

    if llm_client:
        logger.info("Using LLM to synthesize analytical brief content")
        sections, llm_succeeded = _compose_with_llm(
            llm_client, brand_name, research_subject, category, competitors,
            brand_items, competitor_items, industry_items, research_gaps,
            metadata, source_register, source_lookup, spec
        )
    if not sections:
        logger.warning("No LLM available — falling back to rule-based brief")
        sections = _compose_rule_based(
            brand_name, research_subject, category, competitors,
            brand_items, competitor_items, industry_items, research_gaps,
            metadata, source_register, source_lookup
        )

    date_start = metadata.get("date_range_start", "")
    date_end = metadata.get("date_range_end", "")
    title_period = ""
    if date_start and date_end:
        try:
            ds = datetime.fromisoformat(date_start).strftime("%b %Y")
            de = datetime.fromisoformat(date_end).strftime("%b %Y")
            title_period = f" ({ds}–{de})"
        except (ValueError, TypeError):
            pass

    brief = {
        "title": f"{brand_name} U.S. Competitive News Brief{title_period}",
        "subtitle": "ANALYST BRIEFING",
        "purpose": f"Purpose: Provide analysts with a concise starting point before deeper media, consumer or competitive analysis. This is a curated brief of material developments, not an exhaustive clipping report.",
        "research_subject": research_subject,
        "brand_name": brand_name,
        "category": category,
        "competitors": competitors,
        "generated_at": datetime.now().strftime("%B %d, %Y"),
        "section_order": SECTION_ORDER,
        "section_titles": SECTION_TITLES,
        "sections": sections,
        "source_register": source_register,
        "research_gaps": research_gaps,
        "source_count": len(all_sources),
        "enrichment_status": "llm_synthesized" if llm_succeeded else "rule_based",
        "metadata": {
            "sources_reviewed": metadata.get("sources_reviewed", 0),
            "sources_retained": metadata.get("sources_retained", 0),
            "tier_1_count": metadata.get("tier_1_count", 0),
            "tier_2_count": metadata.get("tier_2_count", 0),
            "date_range_start": date_start,
            "date_range_end": date_end,
        },
    }

    brief_id = store.save_background_brief(project_id, research_id, brief)
    logger.info("Analyst brief composed: brief_id=%s, sections=%d, sources=%d",
                brief_id, len(sections), len(all_sources))

    return {"brief_id": brief_id, "brief": brief}


def _get_llm():
    try:
        from .anthropic_client import get_llm_client
        client = get_llm_client()
        if client and client.is_reachable():
            return client
    except Exception as e:
        logger.warning("Could not initialize Anthropic client: %s", e)
    try:
        from .ollama_client import OllamaClient
        ollama = OllamaClient()
        if ollama.is_reachable():
            logger.info("Using Ollama as fallback LLM for brief synthesis")
            return ollama
    except Exception as e:
        logger.warning("Could not initialize Ollama client: %s", e)
    return None


def _compose_with_llm(llm, brand_name, research_subject, category, competitors,
                       brand_items, competitor_items, industry_items, research_gaps,
                       metadata, source_register, source_lookup, spec):
    source_ref_block = _format_source_refs_for_prompt(source_register[:30])

    brand_data = _format_items_for_prompt(brand_items[:20], source_lookup)
    comp_data = _format_grouped_items_for_prompt(competitor_items, competitors, source_lookup)
    industry_data = _format_items_for_prompt(industry_items[:15], source_lookup)

    comp_list = ", ".join(competitors) if competitors else "not specified"
    date_start = metadata.get("date_range_start", "")
    date_end = metadata.get("date_range_end", "")

    prompt = f"""You are a senior competitive intelligence analyst writing a Competitive News Brief for {brand_name}.

CONTEXT:
- Brand: {brand_name}
- Category: {category or "financial services / retirement / wealth management"}
- Competitors: {comp_list}
- Time window: {date_start} to {date_end}
- Geography: U.S.

SOURCE DATA (raw search results with [S#] citation references):

=== {brand_name} DEVELOPMENTS ===
{brand_data}

=== COMPETITOR DEVELOPMENTS ===
{comp_data}

=== INDUSTRY / POLICY DEVELOPMENTS ===
{industry_data}

=== SOURCE REGISTER ===
{source_ref_block}

TASK: Write the following sections as a JSON object. Each section value is a string with markdown-like formatting. Write in the analytical style of a senior intelligence analyst — synthesize and interpret, don't just repeat headlines. Every factual claim MUST include a [S#] citation.

SECTIONS TO WRITE:

1. "company_introduction": Write a concise 2-3 paragraph overview of {brand_name} as a company. Cover: what the company does, its core business lines and products/services, its market position, approximate scale (assets under management, number of clients/participants, employee count if known), and key differentiators. This should read as a briefing primer for an analyst who is unfamiliar with the company. Use [S#] citations where possible but general well-known facts about the company can be stated without citation. End with a brief note on the company's competitive positioning within the {category or "financial services"} landscape.

2. "executive_summary": Write 3-5 analytical paragraphs synthesizing the key themes across {brand_name}, competitors, and industry. Then add a "## What this means for {brand_name}" sub-heading followed by 4-6 strategic recommendation bullets starting with action verbs. No bullet should just restate a headline — each should be an analytical insight about strategic implications.

3. "brand_developments": For each material {brand_name} development, write:
   "## Date | Short analytical headline"
   Then 2-4 sentences of analytical description explaining what happened, why it matters strategically, and how it connects to the broader competitive landscape. End with:
   "Strategic tags: tag1; tag2; tag3"
   Select from the MOST significant 8-12 developments only. Skip minor items.

4. "brand_narrative": Write 4-6 bullet points assessing {brand_name}'s overall narrative positioning:
   - Primary corporate narrative
   - Strongest proof points
   - Most exposed issue
   - Most underdeveloped storyline relative to competitors
   - Communication opportunities

5. "competitor_developments": Group by competitor. For each competitor write:
   "## CompetitorName"
   Then for each development:
   "### Date | Analytical headline"
   2-3 sentences of analytical description with [S#] citation.
   Only include the most strategically significant developments per competitor.

6. "industry_context": Write analytically about 3-6 industry/policy themes (not individual news items). Each as:
   "## Date range or theme | Headline"
   2-4 analytical sentences with [S#] citations explaining the theme and its implications.
   End with "## Key issues to monitor over the next 6-12 months" followed by 5-8 forward-looking bullet points.

7. "methodology": Write 5-7 bullet points covering:
   - Time window
   - Geography scope
   - Competitor set
   - Selection rule (strategic significance criteria)
   - What the brief excludes
   - Source quality notes

CRITICAL RULES:
- Write analytically. Do NOT just repeat search snippets. Synthesize, interpret, connect themes.
- Every factual claim must have a [S#] citation from the source register.
- If data is thin for a section, write a shorter but still analytical version — never pad with generic statements.
- Do NOT invent facts. Only use information from the source data provided.
- Use "##" for Heading 2 and "###" for Heading 3.
- Strategic tags should use semicolons as separators.
- Keep the tone professional, concise, analytical — like a consulting firm's briefing note.

Return ONLY valid JSON with keys: company_introduction, executive_summary, brand_developments, brand_narrative, competitor_developments, industry_context, methodology
"""

    try:
        response = llm.chat([
            {"role": "system", "content": "You are a senior competitive intelligence analyst. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ])

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        parsed = json.loads(cleaned)

        sections = {}
        for key in ["company_introduction", "executive_summary", "brand_developments",
                     "brand_narrative", "competitor_developments", "industry_context"]:
            content = parsed.get(key, "")
            title = SECTION_TITLES.get(key, key.replace("_", " ").title())
            if key == "brand_developments":
                title = f"{brand_name}: Material Developments"
            sections[key] = {"title": title, "content": content, "edited": False}

        sections["key_issues"] = {"title": SECTION_TITLES["key_issues"], "content": "", "edited": False}

        industry_content = sections.get("industry_context", {}).get("content", "")
        if "## Key issues to monitor" in industry_content:
            parts = industry_content.split("## Key issues to monitor", 1)
            sections["industry_context"]["content"] = parts[0].rstrip()
            sections["key_issues"]["content"] = parts[1].lstrip().lstrip("#").lstrip()

        sections["methodology"] = {
            "title": SECTION_TITLES["methodology"],
            "content": parsed.get("methodology", ""),
            "edited": False,
        }

        sections["source_register"] = _build_source_register_section(source_register)

        return sections, True

    except Exception as e:
        logger.error("LLM brief synthesis failed: %s", e, exc_info=True)
        fallback = _compose_rule_based(
            brand_name, research_subject, category, competitors,
            brand_items, competitor_items, industry_items, research_gaps,
            metadata, source_register, source_lookup
        )
        return fallback, False


def _format_items_for_prompt(items: list, source_lookup: dict) -> str:
    if not items:
        return "(No items found)"
    lines = []
    for item in items:
        headline = item.get("headline", "")
        date_str = item.get("date", "")
        summary = item.get("summary", "")
        publisher = item.get("publisher", "")
        cite = _cite(item, source_lookup)
        lines.append(f"- [{date_str}] {headline} ({publisher}){cite}")
        if summary:
            lines.append(f"  {summary[:300]}")
    return "\n".join(lines)


def _format_grouped_items_for_prompt(items: list, competitors: list, source_lookup: dict) -> str:
    if not items and not competitors:
        return "(No competitor data found)"

    grouped: dict[str, list] = {}
    for item in items:
        comp = item.get("_competitor", "Other")
        grouped.setdefault(comp, []).append(item)

    lines = []
    all_comps = list(dict.fromkeys(competitors + list(grouped.keys())))
    for comp in all_comps:
        lines.append(f"\n{comp}:")
        comp_items = grouped.get(comp, [])
        if not comp_items:
            lines.append("  (No developments found)")
            continue
        for item in comp_items[:8]:
            headline = item.get("headline", "")
            date_str = item.get("date", "")
            summary = item.get("summary", "")
            publisher = item.get("publisher", "")
            cite = _cite(item, source_lookup)
            lines.append(f"  - [{date_str}] {headline} ({publisher}){cite}")
            if summary:
                lines.append(f"    {summary[:300]}")

    return "\n".join(lines)


def _format_source_refs_for_prompt(register: list) -> str:
    lines = []
    for entry in register:
        ref = entry["ref"]
        publisher = entry.get("publisher", "")
        date_str = entry.get("date", "")
        headline = entry.get("headline", "")
        lines.append(f"[{ref}] {publisher} | {date_str} | {headline}")
    return "\n".join(lines)


def _compose_rule_based(brand_name, research_subject, category, competitors,
                         brand_items, competitor_items, industry_items, research_gaps,
                         metadata, source_register, source_lookup):
    sections = {}

    sections["executive_summary"] = _build_executive_summary_basic(
        research_subject, brand_name, category, brand_items, competitor_items,
        industry_items, research_gaps, metadata, source_lookup
    )
    sections["brand_developments"] = _build_brand_developments_basic(
        brand_items, brand_name, source_lookup
    )
    sections["brand_narrative"] = _build_brand_narrative_basic(
        brand_items, brand_name, source_lookup
    )
    sections["competitor_developments"] = _build_competitor_developments_basic(
        competitor_items, competitors, source_lookup
    )
    sections["industry_context"] = _build_industry_context_basic(
        industry_items, category, source_lookup
    )
    sections["key_issues"] = _build_key_issues_basic(
        brand_items, competitor_items, industry_items, research_gaps, research_subject
    )
    sections["source_register"] = _build_source_register_section(source_register)
    sections["methodology"] = _build_methodology_basic(metadata, research_gaps, competitors)

    return sections


def _build_executive_summary_basic(subject, brand_name, category, brand_items,
                                    competitor_items, industry_items, gaps,
                                    metadata, source_lookup):
    lines = []
    display_name = brand_name or subject
    date_start = metadata.get("date_range_start", "")
    date_end = metadata.get("date_range_end", "")

    # Opening overview paragraph
    period = ""
    if date_start and date_end:
        try:
            from datetime import datetime as _dt
            ds = _dt.fromisoformat(date_start).strftime("%B %Y")
            de = _dt.fromisoformat(date_end).strftime("%B %Y")
            period = f" from {ds} to {de}"
        except (ValueError, TypeError):
            period = f" from {date_start} to {date_end}"

    lines.append(
        f"This briefing synthesizes {len(brand_items)} {display_name} developments, "
        f"{len(competitor_items)} competitor signals, and {len(industry_items)} industry items"
        f"{period}. The research draws on {len(brand_items) + len(competitor_items) + len(industry_items)} "
        f"validated sources to provide an at-a-glance view of the competitive landscape."
    )
    lines.append("")

    # Brand activity themes
    brand_themes: dict[str, int] = {}
    for item in brand_items:
        family = item.get("family", "general")
        brand_themes[family] = brand_themes.get(family, 0) + 1
    if brand_themes:
        top_families = sorted(brand_themes.items(), key=lambda x: -x[1])[:4]
        family_labels = {
            "announcements": "product announcements and news",
            "campaigns": "marketing and campaign activity",
            "partnerships": "partnership and sponsorship deals",
            "leadership": "leadership and corporate moves",
            "controversies": "risk and reputational signals",
            "brand_identity": "brand positioning and identity",
            "products": "product launches and updates",
            "research_question": "strategic research areas",
            "consumer_trends": "consumer and market trends",
        }
        theme_parts = []
        for fam, count in top_families:
            label = family_labels.get(fam, fam.replace("_", " "))
            theme_parts.append(f"{label} ({count})")
        lines.append(
            f"**{display_name} activity** is concentrated in {', '.join(theme_parts[:-1])}"
            f"{' and ' + theme_parts[-1] if len(theme_parts) > 1 else theme_parts[0] if theme_parts else ''}. "
            f"The most recent developments signal active brand investment across multiple fronts."
        )
        # Cite top 2 most recent brand items
        recent = sorted(brand_items, key=lambda x: x.get("date", "") or "", reverse=True)[:2]
        for item in recent:
            cite = _cite(item, source_lookup)
            lines.append(f"Notable: {item.get('headline', '')}{cite}")
        lines.append("")

    # Competitor landscape
    if competitor_items:
        comp_groups: dict[str, int] = {}
        for ci in competitor_items:
            comp = ci.get("_competitor", "Other")
            comp_groups[comp] = comp_groups.get(comp, 0) + 1
        active_comps = sorted(comp_groups.items(), key=lambda x: -x[1])[:5]
        comp_summary = ", ".join(f"{name} ({count})" for name, count in active_comps)
        lines.append(
            f"**Competitive landscape**: The most active competitors in the review period are "
            f"{comp_summary}. "
        )
        # Cite top named competitor item
        named_comp_items = [ci for ci in competitor_items if ci.get("_competitor", "Other") != "Other"]
        if named_comp_items:
            top_comp_item = sorted(named_comp_items, key=lambda x: x.get("date", "") or "", reverse=True)[0]
            cite = _cite(top_comp_item, source_lookup)
            comp_name = top_comp_item.get("_competitor", "A competitor")
            lines.append(f"Key signal: {comp_name} — {top_comp_item.get('headline', '')}{cite}")
        lines.append("")

    # Industry context
    if industry_items:
        lines.append(
            f"**Industry context**: {len(industry_items)} macro-level developments were identified, "
            f"including regulatory, market, and consumer trend signals that may affect {display_name}'s "
            f"strategic positioning."
        )
        lines.append("")

    # Strategic implications
    lines.append(f"## What this means for {display_name}")
    implications = []
    if brand_themes.get("partnerships", 0) > 2:
        implications.append(f"- **Partnership momentum**: {display_name} has an active partnership pipeline — evaluate whether current deals are building the right brand associations and reaching priority audiences")
    if brand_themes.get("campaigns", 0) > 2:
        implications.append(f"- **Marketing investment**: Significant campaign activity suggests {display_name} is investing in brand visibility — assess whether messaging is differentiated vs. competitors")
    if brand_themes.get("announcements", 0) > 2:
        implications.append(f"- **Product news cycle**: Multiple product announcements indicate an active innovation pipeline — monitor competitor responses and market reception")
    if competitor_items:
        comp_names = list({ci.get("_competitor", "") for ci in competitor_items if ci.get("_competitor")})[:5]
        implications.append(f"- **Competitive pressure**: Monitor moves from {', '.join(comp_names)} — their activity levels suggest they are actively investing in the same space")
    if brand_themes.get("controversies", 0) > 0:
        implications.append(f"- **Reputation watch**: Risk signals detected — review controversy items for potential brand impact and prepare response strategies")
    if gaps:
        gap_list = ", ".join(str(g) for g in gaps[:3])
        implications.append(f"- **Research gaps**: Analyst follow-up needed on: {gap_list}")
    if not implications:
        implications.append(f"- Continue monitoring {display_name} and competitor developments for emerging strategic signals")
    lines.extend(implications)

    return {"title": SECTION_TITLES["executive_summary"], "content": "\n".join(lines), "edited": False}


def _build_brand_developments_basic(brand_items, brand_name, source_lookup):
    lines = []
    if not brand_items:
        lines.append(f"No material developments detected for {brand_name} during the review period.")
        return {"title": f"{brand_name}: Material Developments", "content": "\n".join(lines), "edited": False}
    sorted_items = sorted(brand_items, key=lambda x: x.get("date", "") or "", reverse=True)
    for item in sorted_items[:15]:
        headline = item.get("headline", "")
        date_str = item.get("date", "")
        summary = item.get("summary", "")
        cite = _cite(item, source_lookup)
        date_display = _format_date_heading(date_str)
        lines.append(f"## {date_display} | {headline}")
        if summary:
            lines.append(f"{summary}{cite}")
        tags = _get_strategic_tags(item)
        if tags:
            lines.append(f"Strategic tags: {'; '.join(tags)}")
        lines.append("")
    return {"title": f"{brand_name}: Material Developments", "content": "\n".join(lines), "edited": False}


def _build_brand_narrative_basic(brand_items, brand_name, source_lookup):
    if not brand_items:
        return {
            "title": "Brand Narrative Assessment",
            "content": f"Insufficient data to assess {brand_name}'s narrative positioning during the review period.",
            "edited": False,
        }

    themes: dict[str, list] = {}
    for item in brand_items:
        headline = (item.get("headline") or "").lower()
        summary = (item.get("summary") or "").lower()
        text = headline + " " + summary
        family = item.get("family", "")
        if any(w in text for w in ["launch", "new product", "release", "unveil", "introduce", "debut"]):
            themes.setdefault("Product & Innovation", []).append(item)
        elif any(w in text for w in ["partner", "collaborat", "sponsor", "endorse", "ambassador"]):
            themes.setdefault("Partnerships & Sponsorships", []).append(item)
        elif any(w in text for w in ["campaign", "marketing", "advertis", "promo", "brand"]):
            themes.setdefault("Marketing & Campaigns", []).append(item)
        elif any(w in text for w in ["financ", "revenue", "sales", "growth", "market share", "earning", "profit"]):
            themes.setdefault("Financial & Market Position", []).append(item)
        elif any(w in text for w in ["recall", "lawsuit", "controversi", "complaint", "issue", "problem", "crisis"]):
            themes.setdefault("Risk & Reputation", []).append(item)
        elif any(w in text for w in ["sustain", "esg", "environment", "social", "community", "diversity"]):
            themes.setdefault("ESG & Corporate Responsibility", []).append(item)
        else:
            themes.setdefault("General Coverage", []).append(item)

    lines = []
    lines.append(f"Analysis of {len(brand_items)} items mentioning {brand_name} reveals the following narrative themes:\n")

    for theme_name, items in sorted(themes.items(), key=lambda x: -len(x[1])):
        lines.append(f"## {theme_name} ({len(items)} mentions)")
        for item in sorted(items, key=lambda x: x.get("date", "") or "", reverse=True)[:4]:
            headline = item.get("headline", "")
            cite = _cite(item, source_lookup)
            date_display = _format_date_heading(item.get("date", ""))
            lines.append(f"- **{date_display}**: {headline}{cite}")
        lines.append("")

    top_themes = sorted(themes.items(), key=lambda x: -len(x[1]))[:3]
    if top_themes:
        dominant = ", ".join(f"{t[0]} ({len(t[1])})" for t in top_themes)
        lines.append(f"**Dominant narratives**: {dominant}")

    return {"title": "Brand Narrative Assessment", "content": "\n".join(lines), "edited": False}


def _build_competitor_developments_basic(competitor_items, competitors, source_lookup):
    lines = []
    if not competitor_items and not competitors:
        return {"title": SECTION_TITLES["competitor_developments"], "content": "No competitor developments identified.", "edited": False}
    grouped: dict[str, list] = {}
    for item in competitor_items:
        grouped.setdefault(item.get("_competitor", "Other"), []).append(item)
    for comp in competitors:
        if comp not in grouped:
            grouped[comp] = []
    for comp_name, items in grouped.items():
        lines.append(f"## {comp_name}")
        if not items:
            lines.append("No developments detected during the review period.")
            lines.append("")
            continue
        for item in sorted(items, key=lambda x: x.get("date", "") or "", reverse=True)[:6]:
            cite = _cite(item, source_lookup)
            date_display = _format_date_heading(item.get("date", ""))
            lines.append(f"### {date_display} | {item.get('headline', '')}")
            if item.get("summary"):
                lines.append(f"{item['summary']}{cite}")
            lines.append("")
    return {"title": SECTION_TITLES["competitor_developments"], "content": "\n".join(lines), "edited": False}


def _build_industry_context_basic(industry_items, category, source_lookup):
    lines = []
    if not industry_items:
        return {"title": SECTION_TITLES["industry_context"],
                "content": f"No industry or policy developments identified for the {category or 'target'} sector.",
                "edited": False}
    for item in sorted(industry_items, key=lambda x: x.get("date", "") or "", reverse=True)[:10]:
        cite = _cite(item, source_lookup)
        date_display = _format_date_heading(item.get("date", ""))
        lines.append(f"## {date_display} | {item.get('headline', '')}")
        if item.get("summary"):
            lines.append(f"{item['summary']}{cite}")
        lines.append("")
    return {"title": SECTION_TITLES["industry_context"], "content": "\n".join(lines), "edited": False}


def _build_key_issues_basic(brand_items, competitor_items, industry_items, gaps, subject):
    lines = []
    lines.append("The following issues warrant monitoring over the next 6–12 months:\n")

    controversy_items = [i for i in brand_items if i.get("family") == "controversies"]
    if controversy_items:
        lines.append(f"## Reputation & Risk ({len(controversy_items)} signals)")
        for item in controversy_items[:4]:
            lines.append(f"- {item.get('headline', 'Risk item detected')}")
        lines.append("")

    if competitor_items:
        comp_counts: dict[str, int] = {}
        for ci in competitor_items:
            comp = ci.get("_competitor", "Other")
            comp_counts[comp] = comp_counts.get(comp, 0) + 1
        active = sorted(comp_counts.items(), key=lambda x: -x[1])[:5]
        lines.append("## Competitive Moves to Watch")
        for comp_name, count in active:
            lines.append(f"- **{comp_name}**: {count} development(s) detected — assess impact on {subject}'s positioning")
        lines.append("")

    if industry_items:
        lines.append("## Industry & Regulatory Signals")
        for item in sorted(industry_items, key=lambda x: x.get("date", "") or "", reverse=True)[:3]:
            lines.append(f"- {item.get('headline', 'Industry development')}")
        lines.append("")

    if gaps:
        lines.append("## Research Gaps Requiring Follow-Up")
        for gap in gaps[:5]:
            lines.append(f"- {gap}")
        lines.append("")

    if not lines or len(lines) <= 1:
        lines.append(f"- Continue monitoring {subject} developments for emerging issues")

    return {"title": SECTION_TITLES["key_issues"], "content": "\n".join(lines), "edited": False}


def _build_methodology_basic(metadata, gaps, competitors):
    date_start = metadata.get("date_range_start", "")
    date_end = metadata.get("date_range_end", "")
    comp_list = ", ".join(competitors) if competitors else "not specified"
    lines = [
        f"- Time window: {date_start} through {date_end}.",
        "- Geography: developments material to U.S. markets.",
        f"- Competitor set: {comp_list}.",
        "- Selection rule: strategic significance to market position, product direction, regulation, financial performance, M&A, client acquisition or consumer behavior.",
        "- The brief excludes routine commentary, minor product updates, local sponsorships and non-U.S. developments.",
        "- Results limited to publicly available web content indexed by DuckDuckGo.",
        "- Source dates may reflect indexing rather than publication.",
    ]
    return {"title": SECTION_TITLES["methodology"], "content": "\n".join(lines), "edited": False}


def _build_source_register_list(all_sources: list) -> list[dict]:
    seen_urls: set[str] = set()
    register = []
    idx = 1
    sorted_sources = sorted(all_sources, key=lambda s: (_get_tier(s), s.get("headline", "")))
    for s in sorted_sources:
        url = s.get("url", "")
        if url in seen_urls or url.startswith("[mock]"):
            continue
        if url:
            seen_urls.add(url)
        register.append({
            "ref": f"S{idx}",
            "publisher": s.get("publisher", "") or _extract_domain(s.get("url", "")),
            "date": s.get("date", ""),
            "headline": s.get("headline", "Untitled"),
            "url": url,
            "tier": _get_tier(s),
        })
        idx += 1
    return register


def _build_source_register_section(register: list[dict]) -> dict:
    lines = [
        "All URLs were accessed or verified for this brief. Independent reporting is prioritized for interpretation; company releases are used for transaction terms, financial results and corporate milestones.",
        "",
    ]
    for entry in register:
        ref = entry["ref"]
        publisher = entry.get("publisher", "")
        date_str = entry.get("date", "")
        headline = entry.get("headline", "")
        meta_parts = [f"[{ref}]", publisher]
        if date_str:
            meta_parts.append(date_str)
        lines.append(" | ".join(meta_parts))
        lines.append(headline)
        lines.append("")
    return {"title": SECTION_TITLES["source_register"], "content": "\n".join(lines) if lines else "No sources.", "edited": False}


def _extract_competitors(spec: dict) -> list[str]:
    competitors = spec.get("competitors", [])
    names = []
    for c in competitors:
        if isinstance(c, dict):
            name = c.get("name", "")
            if name:
                names.append(name)
        elif isinstance(c, str) and c:
            names.append(c)
    if not names:
        sections = spec.get("sections", {})
        entities = sections.get("entities", {})
        entity_list = entities.get("content", []) if isinstance(entities, dict) else []
        if isinstance(entity_list, list):
            for e in entity_list:
                if isinstance(e, dict) and e.get("type") == "competitor":
                    name = e.get("name", "")
                    if name:
                        names.append(name)
    if not names:
        for ve_path in [
            spec.get("validated_entities", []),
            spec.get("source_spec", {}).get("validated_entities", []),
        ]:
            if isinstance(ve_path, list):
                for e in ve_path:
                    if isinstance(e, dict) and e.get("type") == "competitor":
                        name = e.get("name", "")
                        if name:
                            names.append(name)
            if names:
                break
    if not names:
        raw = spec.get("raw_brief", "")
        rs_desc = ""
        rs = spec.get("research_subject")
        if isinstance(rs, dict):
            rs_desc = rs.get("description", "")
        text_to_search = f"{raw}\n{rs_desc}"
        if text_to_search.strip():
            patterns = [
                r'competitive set includes?\s+(.+?)(?:\.|,\s*while)',
                r'competitors?\s+(?:are|include|includes)\s+(.+?)(?:\.|$)',
                r'[Cc]ompetitors?\s*\n+(.+?)(?:\n\n|\n[A-Z]|$)',
                r'[Cc]ompetitors?:\s*(.+?)(?:\n\n|\n[A-Z]|$)',
            ]
            for pat in patterns:
                match = re.search(pat, text_to_search, re.DOTALL)
                if match:
                    comp_str = match.group(1)
                    comp_str = re.sub(r'\band\b', ',', comp_str)
                    comp_str = re.sub(r'\bwhile\b.*', '', comp_str)
                    for part in comp_str.split(','):
                        part = part.strip().rstrip('.')
                        if part and len(part) > 1 and len(part) < 40:
                            names.append(part)
                    if names:
                        break
    return names


def _classify_items(news_items, subject, brand_name, competitors):
    brand_items, competitor_items, industry_items = [], [], []
    brand_terms = {t.lower() for t in [subject, brand_name] if t}
    comp_terms = {c.lower(): c for c in competitors if c}
    for item in news_items:
        text = f"{item.get('headline', '')} {item.get('summary', '')}".lower()
        family = item.get("family", "")

        matched_competitor = None
        for comp_lower, comp_original in comp_terms.items():
            if comp_lower in text:
                matched_competitor = comp_original
                break

        if family == "competitor" and not matched_competitor:
            query = item.get("_query", "").lower()
            for comp_lower, comp_original in comp_terms.items():
                if comp_lower in query:
                    matched_competitor = comp_original
                    break

        if any(bt in text for bt in brand_terms) and family != "competitor":
            brand_items.append(item)
        elif matched_competitor:
            item["_competitor"] = matched_competitor
            competitor_items.append(item)
        elif family == "competitor":
            item["_competitor"] = "Other"
            competitor_items.append(item)
        else:
            industry_items.append(item)
    return brand_items, competitor_items, industry_items


def _format_date_heading(date_str):
    if not date_str:
        return "Date unavailable"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return str(date_str)


STRATEGIC_TAG_FAMILIES = {
    "brand_identity": "Brand positioning",
    "products": "Product strategy",
    "announcements": "Corporate announcements",
    "campaigns": "Marketing & campaigns",
    "partnerships": "Strategic partnerships",
    "leadership": "Leadership & governance",
    "controversies": "Risk & controversy",
    "category": "Market trends",
    "consumer_trends": "Consumer insights",
    "research_question": "Research-relevant",
}


def _get_strategic_tags(item):
    family = item.get("family", "")
    tags = []
    if family and family in STRATEGIC_TAG_FAMILIES:
        tags.append(STRATEGIC_TAG_FAMILIES[family])
    if _get_tier(item) <= 1:
        tags.append("High-credibility source")
    return tags


def _cite(item, source_lookup):
    url = item.get("url", "")
    ref = source_lookup.get(url)
    return f" [{ref}]" if ref else ""


def _get_tier(item):
    tier = item.get("tier", 3)
    if isinstance(tier, str):
        if tier.startswith("tier_"):
            try:
                return int(tier.replace("tier_", ""))
            except ValueError:
                return 3
        try:
            return int(tier)
        except ValueError:
            return 3
    return int(tier) if isinstance(tier, (int, float)) else 3


def _extract_domain(url):
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""

"""Orchestrates one end-to-end run: brief -> retrieval -> LLM reasoning ->
deck assembly -> save -> memory, emitting a structured event at every step so
the UI can render a live "what is it doing right now" feed.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from . import deck_builder, deck_index, memory, retrieval
from .brief_parser import guess_client_name, parse_brief
from .config import Settings, load_settings
from .llm_provider import build_llm_client

EventFn = Callable[[str, dict], None]

MAX_BRIEF_CHARS = 6000
MAX_CANDIDATE_BODY_CHARS = 320


_PLACEHOLDER_PATTERNS = re.compile(
    r"^\[.*\]$|^client\s*name$|^unknown|^n/?a$|^insert|^your\s",
    re.IGNORECASE,
)


def _is_placeholder(name: str) -> bool:
    return not name or bool(_PLACEHOLDER_PATTERNS.search(name.strip()))


def _extract_client_from_brief(text: str) -> str:
    """Pull the most prominent capitalized brand/company name from the brief."""
    words = re.findall(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b", text)
    skip = {
        "Can", "What", "The", "How", "Are", "Is", "Do", "We", "Our",
        "This", "That", "January", "February", "March", "April", "May",
        "June", "July", "August", "September", "October", "November",
        "December", "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday", "Conversation", "Themes",
        "Sentiment",
    }
    candidates = [w for w in words if w not in skip and len(w) > 2]
    if not candidates:
        return ""
    from collections import Counter
    counts = Counter(candidates)
    return counts.most_common(1)[0][0]


def _noop(event_type: str, payload: dict) -> None:
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("Model did not return parseable JSON")


def _llm_json(ollama: OllamaClient, system: str, user: str, retries: int = 2) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error = None
    for attempt in range(retries + 1):
        try:
            raw = ollama.chat(messages, format_json=True)
            return _extract_json(raw)
        except Exception as e:  # noqa: BLE001 - want to retry on any parse/model failure
            last_error = e
            messages.append({"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON object, no commentary."})
    raise RuntimeError(f"LLM did not produce valid JSON after {retries + 1} attempts: {last_error}")


ANALYSIS_SYSTEM_PROMPT = """You are a PR / social-intelligence research analyst helping assemble a client \
report deck by reusing relevant slides from past projects and identifying gaps that need new analysis.

You will be given a new client brief and a numbered list of candidate slides pulled from past project \
decks (each with its title, a text excerpt, the client it came from, and a similarity score).

Return ONLY a JSON object with this exact shape:
{
  "client": "the actual brand or company name from the brief (e.g. Intuit, Wells Fargo) - NEVER use a placeholder like [Client Name]",
  "category": "product/industry category",
  "competitors": "comma-separated competitor names, or [INSERT COMPETITORS] if unknown",
  "geography": "e.g. US only",
  "time_period": "e.g. 12 Months (Month Year - Month Year)",
  "sources_tools": "e.g. Meltwater, Quid Discover",
  "research_objective": "1-2 sentence objective paraphrased from the brief",
  "focus_bullets": ["focus area 1", "focus area 2", "focus area 3"],
  "target_audience": "primary audience description",
  "report_type": "short report type label, e.g. Social Listening Report",
  "subject": "short subject line for the cover, e.g. '<Client> Topic Map'",
  "sections": [
    {
      "title": "section title",
      "parenthetical": "e.g. (EDITORIAL + SOCIAL)",
      "reused_slide_ids": [candidate index numbers that are genuinely relevant to this section],
      "gaps": ["short description of a content gap needing a freshly drafted slide, if any"]
    }
  ]
}

Rules:
- Group candidates into 2-5 thematic sections that make sense for THIS brief. Do not force in irrelevant candidates - it's fine to leave a candidate out of every section.
- A candidate's index may only be used in ONE section.
- Only add a "gaps" entry when the brief asks for something no candidate slide covers.
- Never invent statistics, percentages, or survey numbers anywhere in this JSON - use [INSERT ...] placeholders for anything you don't have real data for.
- The "client" field MUST be the brand or company the BRIEF is asking about (e.g. Intuit, Wells Fargo, Amazon), NOT the client from any candidate slide's source deck. Read the brief carefully.
- Reply with ONLY the JSON object, no markdown fences, no commentary.
"""

DRAFT_SYSTEM_PROMPT = """You are drafting ONE new analysis slide for a PR / social-intelligence report, in the \
same voice as past InfoVision Hunter reports: a short eyebrow label, a clear title, and 2-3 concise analytical \
prose paragraphs.

Return ONLY a JSON object:
{"eyebrow": "SHORT LABEL", "title": "Slide title", "paragraphs": ["paragraph 1", "paragraph 2"]}

Rules:
- Write qualitative framing and analysis only. Never invent statistics, percentages, dates, or survey figures - \
if a number would normally appear, write "[INSERT DATA]" instead.
- Keep paragraphs concise (2-4 sentences each).
- Reply with ONLY the JSON object, no markdown fences, no commentary.
"""

TEMPLATE_DESIGN_PROMPT = """You are a PR / social-intelligence research analyst designing the full slide deck \
structure for a new client report. You will receive a client brief describing what analysis is needed.

Design a complete deck with REALISTIC DUMMY DATA — fake but plausible numbers, percentages, themes, sentiment \
splits, and sample findings. The purpose is to show the client how the final report will flow and look, so the \
content must feel like a finished report with believable placeholder data they can later replace with real research.

Return ONLY a JSON object with this exact shape:
{
  "client": "the actual brand/company name from the brief",
  "category": "product/industry category",
  "competitors": "comma-separated competitor names",
  "geography": "e.g. US, Global",
  "time_period": "e.g. 12 Months (January 2025 - January 2026)",
  "sources_tools": "e.g. Meltwater, Quid Discover, Social Listening Platforms",
  "research_objective": "1-2 sentence objective paraphrased from the brief",
  "focus_bullets": ["focus area 1", "focus area 2", "focus area 3"],
  "target_audience": "primary audience description",
  "report_type": "short report type label, e.g. Social Listening Report",
  "subject": "short subject line for the cover",
  "share_of_voice": "e.g. Brand A: 45%, Brand B: 30%, Brand C: 25%",
  "sentiment_split": "e.g. Positive 34%, Neutral 28%, Negative 38%",
  "key_themes": "e.g. Product Quality, Customer Service, Pricing, Innovation",
  "top_hashtags": "e.g. #BrandName, #Industry, #CustomerExperience",
  "seasonal_peaks": "e.g. Q4 Holiday Season, Product Launch (March 2025)",
  "consumer_profile_bullets": [
    "Sample insight about the primary consumer demographic",
    "Sample insight about purchasing behavior or preferences",
    "Sample insight about brand loyalty or switching patterns"
  ],
  "sections": [
    {
      "title": "section title",
      "parenthetical": "e.g. (EDITORIAL + SOCIAL)",
      "slides": [
        {
          "eyebrow": "SHORT LABEL IN CAPS",
          "title": "Descriptive slide title",
          "paragraphs": [
            "First analytical paragraph with realistic dummy data — use specific fake numbers like 67% or 2.3M mentions to show what the final slide will look like.",
            "Second paragraph continuing the analysis with sample findings and trends."
          ]
        }
      ]
    }
  ]
}

Rules:
- Design 3-5 thematic sections that address every aspect of the brief.
- Each section should have 2-4 slides.
- USE REALISTIC FAKE DATA everywhere — specific percentages (67%, 23%), mention counts (2.3M, 450K), sentiment ratios, named themes, sample quotes. This is a TEMPLATE with dummy data, not a placeholder skeleton.
- Write in the same analytical voice as a professional PR research report.
- The "client" field MUST be the actual brand from the brief, never a placeholder.
- Reply with ONLY the JSON object, no markdown fences, no commentary.
"""

TEMPLATE_SLIDE_PROMPT = """You are drafting ONE analysis slide for a PR / social-intelligence report template. \
The slide should contain REALISTIC DUMMY DATA — fake but believable numbers, percentages, and findings that show \
what the final populated slide will look like.

Return ONLY a JSON object:
{"eyebrow": "SHORT LABEL IN CAPS", "title": "Slide title", "paragraphs": ["paragraph 1 with dummy stats", "paragraph 2 with sample findings"]}

Rules:
- Use specific fake numbers: percentages (67%), mention counts (2.3M), sentiment splits, named themes.
- Write in a professional analytical voice as if this is a real finished report.
- Keep paragraphs concise (2-4 sentences each).
- Reply with ONLY the JSON object, no markdown fences, no commentary.
"""


def _candidates_block(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        excerpt = (c["body_text"] or "")[:MAX_CANDIDATE_BODY_CHARS].replace("\n", " ")
        lines.append(
            f"[{i}] client={c['client_guess']!r} title={c['title']!r} score={c['score']:.2f}\n"
            f"    excerpt: {excerpt}"
        )
    return "\n".join(lines) if lines else "(no candidates found)"


def run_pipeline(
    brief_path: Path,
    settings: Optional[Settings] = None,
    on_event: Optional[EventFn] = None,
) -> dict:
    """Runs the full pipeline for one brief file. Returns the finished run's summary dict."""
    settings = settings or load_settings()
    emit = on_event or _noop
    memory.init_db()

    client_hint = guess_client_name("", brief_path.name)
    run_id = memory.create_run(brief_path.name, client_hint)
    emit("run_started", {"run_id": run_id, "brief_filename": brief_path.name})
    memory.add_event(run_id, "run_started", {"brief_filename": brief_path.name})

    try:
        ollama = build_llm_client(settings)
        if not ollama.is_reachable():
            raise RuntimeError(f"No LLM provider reachable (checked Azure OpenAI, Anthropic, Ollama at {settings.ollama_host}).")

        def step(event_type: str, payload: dict) -> None:
            record = memory.add_event(run_id, event_type, payload)
            emit(event_type, {**payload, "run_id": run_id, "ts": record["ts"]})

        step("brief_parsing", {"filename": brief_path.name})
        brief_text = parse_brief(brief_path)
        if not brief_text.strip():
            raise RuntimeError("Brief file appears to be empty or unreadable.")
        step("brief_parsed", {"char_count": len(brief_text)})

        step("indexing_check", {})
        index_stats = deck_index.index_repository(
            settings, ollama, on_event=lambda et, p: step(f"index_{et}", p)
        )
        step("indexing_done", index_stats)

        step("embedding_brief", {})
        step("retrieving_slides", {})
        candidates = retrieval.search(
            brief_text[:MAX_BRIEF_CHARS], ollama, top_k=max(settings.top_k_candidates * 3, 20)
        )
        candidates = [c for c in candidates if c["score"] >= settings.relevance_threshold] or candidates[:settings.top_k_candidates]
        step("slides_retrieved", {
            "count": len(candidates),
            "top_titles": [c["title"] for c in candidates[:5]],
        })

        step("reasoning_start", {"candidate_count": len(candidates)})
        analysis = _llm_json(
            ollama,
            ANALYSIS_SYSTEM_PROMPT,
            f"CLIENT BRIEF:\n{brief_text[:MAX_BRIEF_CHARS]}\n\nCANDIDATE SLIDES:\n{_candidates_block(candidates)}",
        )
        step("reasoning_complete", {"section_titles": [s.get("title") for s in analysis.get("sections", [])]})
        if analysis.get("client"):
            memory.update_run_client(run_id, analysis["client"])

        plan = _build_deck_plan(analysis, candidates, brief_text, step)

        today_str = date.today().strftime("%B %Y")
        client_name = analysis.get("client") or client_hint
        if _is_placeholder(client_name):
            client_name = _extract_client_from_brief(brief_text) or client_hint
            if analysis.get("client"):
                analysis["client"] = client_name
            memory.update_run_client(run_id, client_name)
        safe_client = re.sub(r'[<>:"/\\|?*]', '_', client_name).strip('. ')
        output_name = f"{safe_client}_{date.today().isoformat()}_Hunter Deck.pptx"
        output_path = str(Path(settings.output_dir) / output_name)

        step("assembling_deck", {"output_name": output_name})
        deck_builder.build_deck(str(_template_path()), output_path, plan)
        step("deck_saved", {"output_path": output_path})

        memory.finish_run(run_id, "completed", output_path)
        step("run_complete", {"output_path": output_path})

        return {
            "run_id": run_id,
            "status": "completed",
            "output_path": output_path,
            "sections": [s["title"] for s in plan["sections"]],
        }
    except Exception as e:  # noqa: BLE001 - surface any failure into memory + live feed
        memory.add_event(run_id, "run_failed", {"error": str(e)})
        memory.finish_run(run_id, "failed", None)
        emit("run_failed", {"run_id": run_id, "error": str(e)})
        return {"run_id": run_id, "status": "failed", "error": str(e)}


def _template_path() -> Path:
    from .config import TEMPLATE_PATH
    return TEMPLATE_PATH


def _parse_brief_fields(brief_text: str) -> dict:
    """Extract client, competitors, category, time period, and topics from
    the brief using simple heuristics — no LLM needed."""
    text = brief_text

    brands = []
    hyphenated = re.findall(r"\b[A-Z][A-Za-z]+-[A-Z][A-Za-z]+\b", text)
    for h in hyphenated:
        brands.append(h)
    raw_phrases = re.findall(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b", text)
    skip = {
        "Can", "What", "The", "How", "Are", "Is", "Do", "We", "Our",
        "This", "That", "January", "February", "March", "April", "May",
        "June", "July", "August", "September", "October", "November",
        "December", "Research", "Report", "Analysis", "Social", "Media",
        "Conversation", "Themes", "Sentiment", "Focus", "Analyze",
        "Hunter", "InfoVision", "Brief", "Objective", "Please",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday", "Positive", "Negative", "Neutral",
        "Share", "Voice", "Key", "Consumer", "Demographics",
        "Give", "Template", "Create", "Break", "Apart",
        "Conversations", "Topics", "Brands", "Category",
        "Landscape", "Overview", "Competitive", "Set",
        "Time", "Period", "Duration", "Date", "Range",
        "Market", "Industry", "Sector", "Segment",
        "Platform", "Channel", "Digital", "Online",
        "Performance", "Metrics", "Engagement", "Volume",
        "Global", "International", "Regional", "National",
        "About", "With", "From", "Into", "Over", "Between",
    }
    for phrase in raw_phrases:
        words_in_phrase = phrase.split()
        filtered = [w for w in words_in_phrase if w not in skip and len(w) > 2]
        if filtered:
            brands.append(" ".join(filtered))

    from collections import Counter
    brand_counts = Counter(brands)
    top_brands = [b for b, _ in brand_counts.most_common(6)]

    client = top_brands[0] if top_brands else "Brand"
    competitors = top_brands[1:4] if len(top_brands) > 1 else ["Competitor A", "Competitor B"]

    vs_match = re.search(
        r"(\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(?:vs\.?|versus|compared to)\s+(\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)",
        text,
    )
    if vs_match:
        c1 = " ".join(w for w in vs_match.group(1).split() if w not in skip)
        c2 = " ".join(w for w in vs_match.group(2).split() if w not in skip)
        if c1:
            client = c1
        if c2:
            competitors = [c2] + [c for c in competitors if c != c2][:2]

    and_the_match = re.search(
        r"(\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(?:and the|and)\s+(\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(?:Conversation|conversation|brand)",
        text,
    )
    if and_the_match and not vs_match:
        c1 = " ".join(w for w in and_the_match.group(1).split() if w not in skip)
        c2 = " ".join(w for w in and_the_match.group(2).split() if w not in skip)
        if c1:
            client = c1
        if c2:
            competitors = [c2] + [c for c in competitors if c != c2][:2]

    time_match = re.search(r"Q[1-4]\s*\d{4}", text)
    time_period = time_match.group(0) if time_match else "12 Months"
    if not time_match:
        month_range = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*[-–to]+\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}", text, re.IGNORECASE)
        if month_range:
            time_period = month_range.group(0)

    geo_match = re.search(r"\b(US|United States|Global|North America|Europe|UK|APAC|LATAM|EMEA)\b", text, re.IGNORECASE)
    geography = geo_match.group(0) if geo_match else "US"

    lower = text.lower()
    topics = []
    topic_keywords = {
        "sentiment": "Sentiment Analysis",
        "share of voice": "Share of Voice",
        "themes": "Key Themes & Topics",
        "hashtag": "Hashtag & Social Trends",
        "demographic": "Consumer Demographics",
        "consumer": "Consumer Insights",
        "competitor": "Competitive Landscape",
        "occasion": "Key Occasions & Moments",
        "celebrity": "Celebrity & Influencer Impact",
        "trend": "Trendlines & Volume",
        "platform": "Platform Breakdown",
        "editorial": "Editorial Coverage",
    }
    for keyword, topic_name in topic_keywords.items():
        if keyword in lower:
            topics.append(topic_name)
    if not topics:
        topics = ["Share of Voice", "Sentiment Analysis", "Key Themes & Topics", "Consumer Insights"]

    category_keywords = {
        "beauty": "Beauty & Personal Care", "fashion": "Fashion & Apparel",
        "tech": "Technology", "food": "Food & Beverage", "auto": "Automotive",
        "finance": "Financial Services", "health": "Healthcare",
        "sport": "Sports & Athletics", "retail": "Retail",
        "entertainment": "Entertainment", "travel": "Travel & Hospitality",
        "tax": "Financial Services / Tax", "shoe": "Footwear & Apparel",
        "sneaker": "Footwear & Apparel", "athlet": "Sports & Athletics",
        "coffee": "Coffee & Beverages", "beverage": "Food & Beverage",
        "drink": "Food & Beverage", "pharma": "Pharmaceuticals",
        "insurance": "Insurance & Financial Services",
        "telecom": "Telecommunications", "energy": "Energy & Utilities",
        "luxury": "Luxury & Premium Goods", "gaming": "Gaming & Interactive",
        "media": "Media & Publishing", "education": "Education & EdTech",
        "real estate": "Real Estate", "ecommerce": "E-Commerce & Retail",
    }
    category = ""
    for kw, cat in category_keywords.items():
        if kw in lower:
            category = cat
            break
    if not category:
        category = "Consumer Brand"

    return {
        "client": client,
        "competitors": competitors,
        "category": category,
        "time_period": time_period,
        "geography": geography,
        "topics": topics,
        "brief_text": brief_text,
    }


def _month_labels(n: int = 8) -> list[str]:
    """Generate month labels going backwards from today."""
    import calendar
    today = date.today()
    labels = []
    for i in range(n - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        labels.append(f"{calendar.month_abbr[m]}'{str(y)[-2:]}")
    return labels


def _generate_template_plan(fields: dict) -> dict:
    """Build a complete deck plan with visual slides — charts, tables, and
    infographic layouts matching real Hunter PR deliverables. No LLM calls."""
    client = fields["client"]
    comps = fields["competitors"]
    category = fields["category"]
    time_period = fields["time_period"]
    geography = fields["geography"]

    comp1 = comps[0] if comps else "Competitor A"
    comp2 = comps[1] if len(comps) > 1 else "Competitor B"
    comp_str = ", ".join(comps)
    today = date.today()
    date_str = today.strftime("%B %Y")
    months = _month_labels(8)
    source = f"SOURCE: MELTWATER | {months[0].replace(chr(39), ' 20')} – {months[-1].replace(chr(39), ' 20')}"

    research_obj = (
        f"Understand the social media and editorial conversation landscape surrounding "
        f"{client} relative to key competitors ({comp_str}). Identify dominant themes, "
        f"sentiment drivers, consumer demographics, and cultural moments shaping brand "
        f"perception across digital channels."
    )
    focus_bullets = [
        f"Map the share of voice and competitive positioning of {client} vs. {comp_str}",
        f"Analyze sentiment drivers — what fuels positive and negative conversation",
        f"Identify key themes, cultural moments, and content trends in the {category} space",
    ]

    sections = []

    # ── Section 1: Category Landscape ──────────────────────────────────
    sections.append({
        "title": f"{category} Landscape",
        "parenthetical": "(Editorial & Social)",
        "reused": [],
        "drafted": [
            {
                "visual_type": "kpi_tiles",
                "eyebrow": f"{category.upper()} OVERVIEW",
                "title": "Key Performance Metrics",
                "key_takeaway": f"{client} leads with 61% SOV and highest positive sentiment across the category.",
                "source": source,
                "tiles": [
                    {"value": "2.4M", "label": "Total Mentions", "subtitle": "+18% vs. prior period", "trend_up": True},
                    {"value": "61%", "label": f"{client} SOV", "subtitle": "Leads category", "trend_up": True},
                    {"value": "+36", "label": "Net Sentiment", "subtitle": "Positive 54% | Negative 18%", "trend_up": True},
                    {"value": "4.2/5", "label": "Avg. Rating", "subtitle": f"vs. {comp1} 3.8/5", "trend_up": True},
                ],
            },
            {
                "visual_type": "line_trend",
                "eyebrow": f"{category.upper()} LANDSCAPE",
                "title": f"Conversation Volume Trendline",
                "key_takeaway": f"{client} maintains the highest sustained baseline; volumes spike during campaigns.",
                "source": source,
                "n_count": "N = 2,424,000",
                "categories": months,
                "series": [
                    {"name": client, "values": [180, 210, 340, 290, 250, 195, 310, 280]},
                    {"name": comp1, "values": [95, 88, 120, 180, 105, 92, 110, 130]},
                    {"name": comp2, "values": [40, 45, 55, 48, 52, 38, 60, 50]},
                ],
                "bullets": [
                    f"{client} saw a 3.2x spike during its spring campaign window",
                    f"Sustained elevated volume through the holiday season",
                    f"{comp1} shows a sharper but narrower peak tied to product launch",
                ],
            },
            {
                "visual_type": "column_chart",
                "eyebrow": f"{category.upper()} LANDSCAPE",
                "title": "Volume by Platform",
                "key_takeaway": f"Instagram leads volume; TikTok is the fastest-growing platform (+47%).",
                "source": source,
                "categories": ["Instagram", "X / Twitter", "TikTok", "Reddit", "YouTube", "News / Editorial"],
                "values": [820, 650, 510, 265, 170, 390],
                "bullets": [
                    f"TikTok share grew from 14% to 21%; fastest-growing platform",
                    f"X/Twitter declined 8% in share of conversation",
                    f"Reddit over-indexes for product comparisons and reviews",
                ],
            },
        ],
    })

    # ── Section 2: Share of Voice & Sentiment ──────────────────────────
    sections.append({
        "title": "Share of Voice & Sentiment",
        "parenthetical": "(Brand Analysis)",
        "reused": [],
        "drafted": [
            {
                "visual_type": "doughnut_gauge",
                "eyebrow": "SHARE OF VOICE",
                "title": f"Share of Voice: {client} vs. Competitors",
                "key_takeaway": f"{client} dominates with 61% SOV; {comp1} gains in influencer content (35% SOV).",
                "source": source,
                "gauges": [
                    {"name": client, "value": 61, "label": "~1.47M mentions"},
                    {"name": comp1, "value": 28, "label": "~680K mentions"},
                    {"name": comp2, "value": 11, "label": "~264K mentions"},
                ],
                "bullets": [
                    f"{client} SOV stable at 59-63% throughout the period",
                    f"{comp1} spiked to 34% during major campaign activation",
                    f"Owned-media and earned media from launches drive {client}'s lead",
                ],
            },
            {
                "visual_type": "doughnut_sentiment",
                "eyebrow": "BRAND ANALYSIS",
                "title": "Sentiment Analysis: Cross-Brand Comparison",
                "key_takeaway": f"{client} leads positive sentiment at 54%; {comp2} lowest negative (16%).",
                "source": source,
                "n_count": "N = 2,424,000",
                "brands": [
                    {"name": client, "positive": 54, "negative": 18, "neutral": 28},
                    {"name": comp1, "positive": 47, "negative": 22, "neutral": 31},
                    {"name": comp2, "positive": 51, "negative": 16, "neutral": 33},
                ],
                "bullets": [
                    f"Net sentiment: {client} +36 | {comp1} +25 | {comp2} +35",
                    f"{comp1} negatives driven by quality complaints and shipping delays",
                    f"{comp2} perceived as safe but unremarkable",
                ],
            },
            {
                "visual_type": "bar_callout",
                "eyebrow": "BRAND ANALYSIS",
                "title": f"{client} Sentiment Drivers: Positive vs. Negative",
                "key_takeaway": f"Pricing negativity is 2.1x higher on X/Twitter and Reddit vs. Instagram/TikTok.",
                "source": source,
                "categories": [
                    "Product Innovation & Quality",
                    "Brand Values & Purpose",
                    "Customer Experience",
                    "Pricing & Value Perception",
                    "Customer Service",
                ],
                "values": [38, 24, 19, 42, 31],
                "callouts": [
                    f"38% positive. Consumers praise launches and wins vs. {comp1}: 'game changer,' 'best in class.'",
                    f"24% positive. Purpose-driven messaging resonates; sustainability +34% growth.",
                    f"19% positive. {client} 4.2/5 stars vs. {comp1} 3.8/5. Loyalty programs drive advocacy.",
                    f"42% negative. Price sensitivity is #1 detractor on X/Twitter and Reddit.",
                    f"31% negative. Returns and response times are top pain points; fix shifts ~13% to neutral.",
                ],
            },
        ],
    })

    # ── Section 3: Key Themes & Topics ─────────────────────────────────
    themes = [
        "Product Innovation & Quality",
        "Brand Campaigns & Marketing",
        "Customer Experience & Service",
        "Sustainability & Responsibility",
        "Cultural Relevance & Influencer",
    ]
    sections.append({
        "title": "Key Themes & Topics",
        "parenthetical": "(Editorial + Social)",
        "reused": [],
        "drafted": [
            {
                "visual_type": "bar_callout",
                "eyebrow": f"{category.upper()} THEMES",
                "title": "Top Conversation Themes",
                "key_takeaway": f"Product Innovation dominates at 38%; {client} leads with 2.3x {comp1}'s volume.",
                "source": source,
                "categories": themes,
                "values": [38, 24, 19, 12, 7],
                "callouts": [
                    f"38% of conversation. {client} leads 2.3x over {comp1}; 'game changer,' 'worth the price.'",
                    f"24%. Spring campaign: 340K mentions in week 1, 72% positive sentiment.",
                    f"19%. {client} 4.2/5 stars vs. {comp1} 3.8/5. Pain points: delivery, returns, sizing.",
                    f"12%. Up 34% vs. prior. {client} 2.1x more associated with sustainability than {comp1}.",
                    f"7%. TikTok creators drive 63%. Top format: organic 'day in my life' features.",
                ],
            },
            {
                "visual_type": "stacked_bar",
                "eyebrow": f"{category.upper()} THEMES",
                "title": "Sentiment by Theme",
                "key_takeaway": f"Sustainability has highest positive sentiment (68%); Customer Experience needs work.",
                "source": source,
                "categories": themes,
                "positive": [52, 62, 41, 68, 58],
                "negative": [22, 12, 34, 8, 14],
                "neutral": [26, 26, 25, 24, 28],
                "bullets": [
                    f"Customer Experience is the only theme where negative exceeds one-third",
                    f"Sustainability leads positive sentiment at 68%",
                    f"Improving service response and returns would shift sentiment for {client}",
                ],
            },
            {
                "visual_type": "line_trend",
                "eyebrow": f"{category.upper()} THEMES",
                "title": "Theme Trendlines Over Time",
                "key_takeaway": f"Sustainability grew 34% QoQ; Product Innovation peaks align with launches.",
                "source": source,
                "categories": months,
                "series": [
                    {"name": "Product Innovation", "values": [120, 130, 210, 160, 140, 125, 190, 170]},
                    {"name": "Brand Campaigns", "values": [60, 55, 180, 70, 65, 58, 90, 75]},
                    {"name": "Customer Experience", "values": [70, 75, 80, 85, 78, 72, 95, 82]},
                    {"name": "Sustainability", "values": [30, 35, 42, 48, 55, 52, 65, 60]},
                    {"name": "Cultural / Influencer", "values": [20, 22, 35, 28, 25, 30, 42, 38]},
                ],
            },
        ],
    })

    # ── Section 4: Social Conversation Analysis ────────────────────────
    sections.append({
        "title": "Social Conversation Analysis",
        "parenthetical": "(Social Listening)",
        "reused": [],
        "drafted": [
            {
                "visual_type": "column_chart",
                "eyebrow": "SOCIAL CONVERSATION",
                "title": "Top Hashtags by Volume",
                "key_takeaway": f"#{client} leads with 892K uses; community hashtags growing +67%.",
                "source": source,
                "categories": [
                    f"#{client}", f"#{comp1}",
                    f"#{category.split()[0]}", "#NewRelease",
                    f"#{client}Life", "#Sustainable",
                    f"#{comp1}Fan", "#Unboxing",
                ],
                "values": [892, 412, 287, 156, 178, 98, 134, 87],
                "bullets": [
                    f"#{client}Community growing +67%; #Sustainable{category.split()[0]} +89%",
                    f"Deal-seeking tags declining: #Fast{category.split()[0]} down 23%",
                    f"Volumes in thousands",
                ],
            },
            {
                "visual_type": "pie_chart",
                "eyebrow": "SOCIAL CONVERSATION",
                "title": "Consumer Emotion Distribution",
                "key_takeaway": f"{client} leads in Trust and Admiration; {comp1} leads in Excitement.",
                "source": source,
                "categories": ["Love", "Excitement", "Trust", "Joy", "Frustration", "Disappointment"],
                "values": [28, 22, 18, 15, 11, 6],
                "bullets": [
                    f"Positive emotions dominate overall conversation (83%)",
                    f"Frustration linked to pricing and availability",
                    f"Disappointment tied to product quality vs. marketing expectations",
                    f"Top terms: 'love' (234K), 'best' (178K), 'quality' (156K), 'overpriced' (64K)",
                ],
            },
            {
                "visual_type": "comparison_table",
                "eyebrow": "CONSUMER INSIGHTS",
                "title": "Consumer Demographics & Platform Behavior",
                "source": source,
                "headers": ["Dimension", client, comp1, comp2],
                "rows": [
                    ["Peak Age Group", "25–34 (34%)", "18–24 (31%)", "25–34 (29%)"],
                    ["Gender Skew", "Female 61%", "Balanced 52/48", "Female 55%"],
                    ["Top Platform", "Instagram (38%)", "TikTok (34%)", "Instagram (31%)"],
                    ["Growth Platform", "TikTok (+47%)", "YouTube (+32%)", "Reddit (+28%)"],
                    [f"Top Metro ({geography})", "New York (14%)", "Los Angeles (12%)", "Chicago (9%)"],
                    ["Engagement Style", "Aspirational & Loyalty", "Discovery & Trends", "Practical & Reviews"],
                ],
            },
            {
                "visual_type": "two_by_two",
                "eyebrow": "STRATEGIC FRAMEWORK",
                "title": f"{client} Strategic Positioning Matrix",
                "key_takeaway": f"{client} occupies the high-quality/high-engagement quadrant — protect and extend.",
                "source": source,
                "x_label": "ENGAGEMENT LEVEL →",
                "y_label": "↑ QUALITY PERCEPTION",
                "quadrants": [
                    {"title": "Premium Leaders", "items": [f"{client} (primary position)", "Strong brand loyalty", "High repeat purchase", "Innovation driver"]},
                    {"title": "Aspirational Challengers", "items": [f"{comp1}", "Growing social presence", "Trend-driven audience", "Influencer strength"]},
                    {"title": "Value Players", "items": ["Private label brands", "Price-focused messaging", "Deal-seeking audience", "Limited brand equity"]},
                    {"title": "Niche Specialists", "items": [f"{comp2}", "Targeted segments", "Community-driven", "Moderate growth"]},
                ],
            },
            {
                "visual_type": "theme_matrix",
                "eyebrow": "STRATEGIC IMPLICATIONS",
                "title": "Key Tensions & Opportunities",
                "key_takeaway": f"Four strategic themes emerge, each a challenge and opportunity for {client}.",
                "source": source,
                "left_header": "KEY TENSIONS",
                "right_header": "OPPORTUNITIES",
                "items": [
                    {
                        "pct": 42,
                        "left_title": "Price Perception vs. Quality",
                        "left_desc": f"42% of negative mentions cite pricing. {client} is seen as premium but 'overpriced' by price-sensitive segments on X/Twitter and Reddit.",
                        "right_title": "Value Storytelling",
                        "right_desc": f"Platform-specific value messaging on X/Twitter and Reddit, where price sensitivity is 2.1x higher. Highlight durability, longevity, and cost-per-use framing.",
                    },
                    {
                        "pct": 34,
                        "left_title": "Service Experience Gaps",
                        "left_desc": f"Returns process and response times drive 31% of negative sentiment. {comp1} scores higher on issue resolution speed.",
                        "right_title": "Service Recovery Program",
                        "right_desc": f"Improving service touchpoints could shift ~13% of negative to neutral. Focus on response time SLAs and proactive issue resolution.",
                    },
                    {
                        "pct": 68,
                        "left_title": "Sustainability Expectations",
                        "left_desc": f"Growing consumer demand (+34% QoQ) for transparent supply chains. {client} leads here but competitors are investing.",
                        "right_title": "ESG Leadership Positioning",
                        "right_desc": f"Double down on sustainability narrative. {client} is 2.1x more associated with sustainability than {comp1} — maintain and amplify this advantage.",
                    },
                    {
                        "pct": 47,
                        "left_title": "Platform Shift to TikTok",
                        "left_desc": f"TikTok grew +47% while X/Twitter declined 8%. {comp1} currently outperforms {client} in short-form creator content.",
                        "right_title": "Creator Partnership Strategy",
                        "right_desc": f"Invest in organic TikTok creator partnerships. 'Day in my life' format drives 63% of influencer-themed conversation with highest engagement.",
                    },
                ],
            },
        ],
    })

    plan = {
        "cover": {
            "report_type": "Social Listening & Topic Analysis Report",
            "subject": f"{client} Topic Map",
            "date": date_str,
        },
        "objective": {
            "geography": geography,
            "time_period": time_period,
            "sources_tools": "Meltwater, Quid Discover, Quid Monitor",
            "research_objective": research_obj,
            "focus_bullets": focus_bullets,
            "competitive_research": comp_str,
            "target_audience": f"{category} consumers, brand advocates, and social media-active audiences ages 18-54",
        },
        "summary": {
            "client": client,
            "category": category,
            "competitors": comp_str,
            "share_of_voice": f"{client}: 61% (~1.47M mentions) | {comp1}: 28% (~680K) | {comp2}: 11% (~264K)",
            "sentiment_split": f"Positive 54% | Neutral 28% | Negative 18% (Net Sentiment: +36)",
            "key_themes": "Product Innovation, Brand Campaigns, Customer Experience, Sustainability, Cultural Relevance",
            "top_hashtags": f"#{client}, #{comp1}, #{category.replace(' ', '').replace('&', '')}, #NewRelease, #Sustainable",
            "seasonal_peaks": "Holiday Season (Nov-Dec), Spring Launch Window, Back-to-School (Aug-Sep)",
            "consumer_profile_bullets": [
                f"Core audience: 25-34 year olds (34%), digitally native, brand-conscious consumers",
                f"56% female skew; highest engagement on Instagram (34%) and TikTok (21%)",
                f"Values-driven: sustainability and brand purpose mentioned in 12% of positive conversation",
                f"Price-sensitive segment vocal on X/Twitter and Reddit; loyalty-driven segment on Instagram",
                f"Top metro markets: New York, Los Angeles, Chicago — suburban growth +28% vs. prior",
            ],
        },
        "sections": sections,
    }
    return plan


def run_template_pipeline(
    brief_path: Path,
    settings: Optional[Settings] = None,
    on_event: Optional[EventFn] = None,
    include_research: bool = False,
) -> dict:
    """Generates a fresh template deck with realistic dummy data — NO LLM calls.
    Parses the brief with simple heuristics and generates all content
    programmatically for instant output (<2 seconds).

    If include_research=True, also runs secondary web research and produces
    a Word document alongside the presentation."""
    settings = settings or load_settings()
    emit = on_event or _noop
    memory.init_db()

    client_hint = guess_client_name("", brief_path.name)
    run_id = memory.create_run(brief_path.name, client_hint)
    emit("run_started", {"run_id": run_id, "brief_filename": brief_path.name})
    memory.add_event(run_id, "run_started", {"brief_filename": brief_path.name})

    try:
        def step(event_type: str, payload: dict) -> None:
            record = memory.add_event(run_id, event_type, payload)
            emit(event_type, {**payload, "run_id": run_id, "ts": record["ts"]})

        step("brief_parsing", {"filename": brief_path.name})
        brief_text = parse_brief(brief_path)
        if not brief_text.strip():
            raise RuntimeError("Brief file appears to be empty or unreadable.")
        step("brief_parsed", {"char_count": len(brief_text)})

        step("reasoning_start", {"candidate_count": 0})
        fields = _parse_brief_fields(brief_text)
        client_name = fields["client"]
        if _is_placeholder(client_name):
            client_name = _extract_client_from_brief(brief_text) or client_hint
            fields["client"] = client_name
        memory.update_run_client(run_id, client_name)

        plan = _generate_template_plan(fields)
        step("reasoning_complete", {
            "section_titles": [s["title"] for s in plan["sections"]],
        })

        for section in plan["sections"]:
            for drafted in section.get("drafted", []):
                step("drafted_slide", {
                    "section": section["title"],
                    "title": drafted["title"],
                })

        safe_client = re.sub(r'[<>:"/\\|?*]', '_', client_name).strip('. ')
        output_name = f"{safe_client}_{date.today().isoformat()}_Hunter Template.pptx"
        output_path = str(Path(settings.output_dir) / output_name)

        step("assembling_deck", {"output_name": output_name})
        deck_builder.build_template_deck(str(_template_path()), output_path, plan)
        step("deck_saved", {"output_path": output_path})

        research_path = None
        if include_research:
            from .research import run_research
            research_name = f"{safe_client}_{date.today().isoformat()}_Secondary Research.docx"
            research_path = str(Path(settings.output_dir) / research_name)

            def research_event(et: str, payload: dict) -> None:
                step(f"research_{et}" if not et.startswith("research_") else et, payload)

            research_result = run_research(
                client=client_name,
                competitors=fields["competitors"],
                category=fields["category"],
                topics=fields.get("topics", []),
                output_path=research_path,
                on_event=research_event,
                geography=fields.get("geography", "US"),
                time_period=fields.get("time_period", ""),
            )
            step("research_saved", {
                "output_path": research_path,
                "source_count": research_result.get("source_count", 0),
            })

        memory.finish_run(run_id, "completed", output_path)
        step("run_complete", {
            "output_path": output_path,
            "research_path": research_path,
        })

        result = {
            "run_id": run_id,
            "status": "completed",
            "output_path": output_path,
            "sections": [s["title"] for s in plan["sections"]],
        }
        if research_path:
            result["research_path"] = research_path
        return result
    except Exception as e:
        memory.add_event(run_id, "run_failed", {"error": str(e)})
        memory.finish_run(run_id, "failed", None)
        emit("run_failed", {"run_id": run_id, "error": str(e)})
        return {"run_id": run_id, "status": "failed", "error": str(e)}


def _build_deck_plan(analysis: dict, candidates: list[dict], brief_text: str, step: EventFn) -> dict:
    ollama_settings = load_settings()
    ollama = build_llm_client(ollama_settings)

    sections_out = []
    used_indices: set[int] = set()
    for section in analysis.get("sections", []):
        reused_refs = []
        for idx in section.get("reused_slide_ids", []):
            if not isinstance(idx, int) or idx < 0 or idx >= len(candidates) or idx in used_indices:
                continue
            used_indices.add(idx)
            c = candidates[idx]
            reused_refs.append({
                "deck_path": c["deck_path"],
                "slide_no": c["slide_no"],
                "source_client": c["client_guess"],
                "source_date": deck_index.guess_date_from_filename(Path(c["deck_path"]).name),
            })
            step("slide_selected", {
                "section": section.get("title"),
                "title": c["title"],
                "source_client": c["client_guess"],
                "deck": Path(c["deck_path"]).name,
                "slide_no": c["slide_no"],
            })

        drafted = []
        for gap in section.get("gaps", []):
            step("drafting_slide", {"section": section.get("title"), "gap": gap})
            try:
                draft = _llm_json(
                    ollama,
                    DRAFT_SYSTEM_PROMPT,
                    f"BRIEF EXCERPT:\n{brief_text[:2000]}\n\nSECTION: {section.get('title')}\nCONTENT GAP TO ADDRESS: {gap}",
                )
                drafted.append(draft)
                step("drafted_slide", {"section": section.get("title"), "title": draft.get("title")})
            except Exception as e:  # noqa: BLE001 - one failed draft shouldn't kill the run
                step("draft_failed", {"section": section.get("title"), "gap": gap, "error": str(e)})

        sections_out.append({
            "title": section.get("title", "Untitled Section"),
            "parenthetical": section.get("parenthetical", ""),
            "reused": reused_refs,
            "drafted": drafted,
        })

    if not sections_out:
        sections_out.append({"title": "Findings", "parenthetical": "", "reused": [], "drafted": []})

    return {
        "cover": {
            "report_type": analysis.get("report_type", "Research Report"),
            "subject": analysis.get("subject", analysis.get("client", "")),
            "date": date.today().strftime("%B %Y"),
        },
        "objective": {
            "geography": analysis.get("geography", "[INSERT GEOGRAPHY]"),
            "time_period": analysis.get("time_period", "[INSERT TIME PERIOD]"),
            "sources_tools": analysis.get("sources_tools", "[INSERT SOURCES / TOOLS]"),
            "research_objective": analysis.get("research_objective", ""),
            "focus_bullets": analysis.get("focus_bullets", []),
            "competitive_research": analysis.get("competitors", "[INSERT COMPETITIVE SET]"),
            "target_audience": analysis.get("target_audience", "[INSERT TARGET AUDIENCE]"),
        },
        "summary": {
            "client": analysis.get("client", ""),
            "category": analysis.get("category", ""),
            "competitors": analysis.get("competitors", "[INSERT COMPETITORS]"),
            "consumer_profile_bullets": [],
        },
        "sections": sections_out,
    }

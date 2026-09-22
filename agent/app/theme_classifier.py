"""Theme Classifier — identifies and quantifies editorial themes per entity.

For each entity in the competitive set, classifies qualifying records
into 3-6 analytical themes using a two-pass approach:
1. LLM-assisted theme discovery from a sample of records
2. Deterministic keyword-based classification of ALL records

ALL percentages and counts are calculated deterministically.
The LLM is used ONLY for theme discovery and narrative generation.
"""
from __future__ import annotations

import csv
import json
import logging
import random
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import intelligence_store as store
from . import llm_synthesis as llm

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

DISCOVERY_SAMPLE_SIZE = 200
MAX_RECORDS_FOR_FULL_CLASSIFICATION = 5000
MIN_THEMES = 3
MAX_THEMES = 6
UNCLASSIFIED_LABEL = "Other / Unclassified Mentions"
NARRATIVE_MAX_WORDS = 160
TAKEAWAY_MAX_WORDS = 90

TEXT_FIELDS = ["headline", "snippet", "key_phrases"]

_llm_available = True

# Generic, deterministic themes used only when LLM discovery is unavailable
# or fails to return a usable response. Kept broad since the platform covers
# many industries, not just fashion/retail.
_FALLBACK_THEME_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "Product & Editorial Features",
        "keywords": [
            "feature", "review", "showcase", "spotlight", "style", "styled",
            "wear", "wears", "design", "collection", "launch", "unveil", "look",
        ],
        "description": "Editorial coverage featuring or showcasing the entity's products.",
    },
    {
        "name": "Corporate Leadership & Ownership",
        "keywords": [
            "ceo", "appoint", "appointed", "executive", "acquisition", "acquire",
            "merger", "ownership", "ipo", "stake", "board", "chairman", "hire",
            "resign", "leadership",
        ],
        "description": "Coverage of executive moves, ownership changes, and corporate structure.",
    },
    {
        "name": "Retail, Pricing & Promotions",
        "keywords": [
            "sale", "discount", "price", "promo", "promotion", "deal", "store",
            "shop", "retailer", "ecommerce", "e-commerce", "clearance", "markdown",
        ],
        "description": "Coverage of pricing actions, sales events, and retail distribution.",
    },
    {
        "name": "Partnerships & Collaborations",
        "keywords": [
            "partner", "partnership", "collaboration", "collab", "alliance",
            "sponsor", "sponsorship", "licensing", "joint venture", "team up",
        ],
        "description": "Coverage of announced partnerships, collaborations, or sponsorships.",
    },
    {
        "name": "Reputation, Controversy & Legal",
        "keywords": [
            "lawsuit", "controversy", "backlash", "criticism", "scandal",
            "boycott", "investigation", "recall", "fined", "sued", "complaint",
        ],
        "description": "Coverage involving legal action, controversy, or reputational risk.",
    },
]


# ─── Main Entry Point ────────────────────────────────────────────────────────

def classify_themes(project_id: int, entity_name: str) -> dict:
    """Classify all dataset records mentioning `entity_name` into analytical themes.

    Two-pass approach:
      Pass 1 (LLM): discover 3-6 candidate themes with keyword patterns from a
        representative sample of the entity's records.
      Pass 2 (deterministic): classify every qualifying record into exactly one
        theme via keyword matching, then compute counts/shares/trends purely
        from the classified records.

    Returns a dict shaped as documented in the module — see README-level
    requirements. Never raises for missing/empty data; returns a graceful
    fallback result with an "error" key describing the reason instead.
    """
    entity_name = (entity_name or "").strip()
    if not entity_name:
        raise ValueError("entity_name is required")

    project = store.get_project(project_id)
    if not project:
        return _empty_result(entity_name, f"Project {project_id} not found")
    spec = project.get("spec") or {}

    dataset = _select_dataset(project_id)
    if not dataset:
        return _empty_result(entity_name, "No processed dataset is available for this project")

    file_path = dataset.get("file_path") or ""
    if not file_path or not Path(file_path).exists():
        return _empty_result(entity_name, "Dataset file could not be located on disk")

    column_mapping = dataset.get("column_mapping") or {}
    mapped = _get_mapped_columns(column_mapping)
    if not mapped:
        return _empty_result(entity_name, "Dataset has no recognized column mapping")

    try:
        records = _get_entity_records(file_path, column_mapping, entity_name)
    except Exception as e:  # pragma: no cover - defensive top-level guard
        logger.error("[theme_classifier] Failed to read dataset for entity %s: %s", entity_name, e)
        return _empty_result(entity_name, f"Failed to read dataset: {e}")

    total_records = len(records)
    if total_records == 0:
        return _empty_result(entity_name, f"No records mentioning '{entity_name}' were found in the dataset")

    # Guard against pathological dataset sizes — classification itself is cheap
    # (keyword matching), but keep a hard ceiling for safety/predictable latency.
    sample_based = False
    records_to_classify = records
    if total_records > MAX_RECORDS_FOR_FULL_CLASSIFICATION:
        sample_based = True
        records_to_classify = random.sample(records, MAX_RECORDS_FOR_FULL_CLASSIFICATION)
        logger.warning(
            "[theme_classifier] %s has %d records; classifying a sample of %d",
            entity_name, total_records, MAX_RECORDS_FOR_FULL_CLASSIFICATION,
        )

    # Pass 1: theme discovery from a representative sample.
    if len(records) <= DISCOVERY_SAMPLE_SIZE:
        discovery_sample = records
    else:
        discovery_sample = random.sample(records, DISCOVERY_SAMPLE_SIZE)

    theme_definitions = _discover_themes(discovery_sample, entity_name, spec)
    if not theme_definitions:
        logger.info("[theme_classifier] LLM discovery unavailable/failed for %s — using fallback themes", entity_name)
        theme_definitions = _FALLBACK_THEME_DEFINITIONS

    # Pass 2: deterministic classification of every record.
    assignments: dict[str, list[dict]] = defaultdict(list)
    for rec in records_to_classify:
        label = _classify_record(rec, theme_definitions, TEXT_FIELDS)
        assignments[label].append(rec)

    classified_total = sum(len(v) for v in assignments.values())
    ranked = sorted(assignments.items(), key=lambda kv: -len(kv[1]))

    themes_out: list[dict] = []
    rank = 0
    for name, recs in ranked:
        if not recs:
            continue
        rank += 1
        share_pct = round(len(recs) / classified_total * 100, 1) if classified_total else 0.0
        theme_def = next((t for t in theme_definitions if t["name"] == name), None)
        narrative = _generate_theme_narrative(
            {"name": name, "record_count": len(recs), "share_pct": share_pct, "definition": theme_def},
            recs,
            entity_name,
        )
        if not narrative:
            narrative = _fallback_narrative(name, recs, entity_name)

        themes_out.append({
            "name": name,
            "record_count": len(recs),
            "share_pct": share_pct,
            "rank": rank,
            "trend": _compute_trend(recs),
            "narrative": narrative,
            "key_publications": _top_values(recs, "source_name", limit=5),
            "key_topics": list((theme_def or {}).get("keywords", []))[:8],
            "is_active": _is_active_driver(recs, entity_name),
        })

    executive_takeaway = _generate_executive_takeaway(entity_name, themes_out, total_records)
    if not executive_takeaway:
        executive_takeaway = _fallback_takeaway(entity_name, themes_out, total_records)

    return {
        "entity": entity_name,
        "total_records": total_records,
        "classification_method": "single-label",
        "themes": themes_out,
        "executive_takeaway": executive_takeaway,
        "date_range": _compute_date_range(records),
        "dataset_source": _infer_dataset_source(dataset),
        "context_label": _build_context_label(spec, entity_name),
        "sample_based": sample_based,
    }


# ─── Dataset Selection & Reading ─────────────────────────────────────────────

def _select_dataset(project_id: int) -> dict | None:
    """Pick the best available dataset for this project: prefer approved,
    fall back to the most recently processed one."""
    datasets = store.get_datasets_by_project(project_id)
    usable = [d for d in datasets if d.get("processing_status", "done") == "done" and d.get("file_path")]
    if not usable:
        return None
    approved = next((d for d in usable if d.get("approval_status") == "approved"), None)
    return approved or usable[0]


def _get_mapped_columns(column_mapping: dict) -> dict:
    """Column mapping is stored as {"mapped": {field: actual_column}, "unmapped": [...]}
    by the dataset ingestion pipeline. Tolerate a flat dict too, for robustness."""
    if not isinstance(column_mapping, dict):
        return {}
    if "mapped" in column_mapping and isinstance(column_mapping["mapped"], dict):
        return column_mapping["mapped"]
    return column_mapping


def _entity_pattern(entity_name: str) -> re.Pattern:
    escaped = re.escape(entity_name.strip())
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def _iter_dataset_rows(file_path: str, expected_columns: set[str]):
    """Yield row dicts (keyed by the file's actual column headers) for CSV or
    Excel datasets. For Excel, scans each sheet for a header row that matches
    at least two of the expected (mapped) column names, tolerating title rows
    or blank rows above the real header (common in Meltwater-style exports)."""
    ext = Path(file_path).suffix.lower()

    if ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                headers: list[str] | None = None
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if headers is None:
                        non_empty = {c for c in cells if c}
                        if len(non_empty & expected_columns) >= 2:
                            headers = cells
                        continue
                    if all(not c for c in cells):
                        continue
                    yield dict(zip(headers, row))
        finally:
            wb.close()
    elif ext == ".csv":
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield row
    else:
        raise ValueError(f"Unsupported dataset file type: {ext}")


def _normalize_record(row: dict, mapped: dict) -> dict:
    def get(field: str, default: Any = "") -> Any:
        col = mapped.get(field)
        if not col:
            return default
        val = row.get(col, default)
        return val if val is not None else default

    return {
        "headline": str(get("headline")),
        "snippet": str(get("snippet")),
        "date": str(get("date")),
        "source_name": str(get("source_name")),
        "media_type": str(get("media_type")),
        "sentiment": str(get("sentiment")),
        "reach": get("reach", 0),
        "key_phrases": str(get("key_phrases")),
        "url": str(get("url")),
        "author": str(get("author")),
    }


def _get_entity_records(file_path: str, column_mapping: dict, entity_name: str) -> list[dict]:
    """Read the dataset and return normalized records whose headline, snippet,
    or key phrases mention `entity_name` (case-insensitive, word-boundary match)."""
    mapped = _get_mapped_columns(column_mapping)
    text_cols = [mapped[f] for f in TEXT_FIELDS if mapped.get(f)]
    if not text_cols:
        logger.warning("[theme_classifier] No text columns (headline/snippet/key_phrases) mapped — cannot match entity")
        return []

    expected_columns = set(mapped.values())
    pattern = _entity_pattern(entity_name)
    records: list[dict] = []

    try:
        for row in _iter_dataset_rows(file_path, expected_columns):
            haystack = " ".join(str(row.get(c) or "") for c in text_cols)
            if haystack.strip() and pattern.search(haystack):
                records.append(_normalize_record(row, mapped))
    except FileNotFoundError:
        logger.error("[theme_classifier] Dataset file not found: %s", file_path)
        return []
    except Exception as e:
        logger.error("[theme_classifier] Failed to parse dataset %s: %s", file_path, e)
        return []

    return records


# ─── Theme Discovery (Pass 1 — LLM) ──────────────────────────────────────────

def _entity_type(project_spec: dict, entity_name: str) -> str:
    entities = project_spec.get("validated_entities", []) if isinstance(project_spec, dict) else []
    name_lower = entity_name.lower()
    for e in entities:
        if isinstance(e, dict) and str(e.get("name", "")).strip().lower() == name_lower:
            return e.get("type", "brand")
    return "brand"


def _discover_themes(sample_records: list[dict], entity_name: str, project_spec: dict) -> list[dict]:
    """LLM-based theme discovery. Returns a list of {"name", "keywords", "description"}
    dicts, or [] if the LLM is unavailable or its response can't be parsed."""
    if not sample_records:
        return []

    excerpts = []
    for r in sample_records:
        text = (r.get("headline") or "").strip() or (r.get("snippet") or "").strip()[:180]
        if text:
            excerpts.append(text)
    if not excerpts:
        return []

    excerpt_block = "\n".join(f"- {e[:180]}" for e in excerpts[:150])
    entity_type = _entity_type(project_spec, entity_name)

    system = (
        "You are a senior media analyst identifying editorial themes in news/social coverage. "
        "Themes must be SPECIFIC and ANALYTICAL, describing the type of story, not generic topic labels. "
        "Good: 'Editorial Styling & Fashion Credits', 'Corporate Ownership, Leadership & Partnerships'. "
        "Bad: 'Fashion', 'Business', 'Shopping'. "
        "Each theme needs distinguishing keyword patterns that would actually appear in headlines/snippets "
        "belonging to that theme, and themes should not overlap heavily with each other."
    )
    user = f"""Below are headlines/snippets mentioning "{entity_name}" ({entity_type}) from a media coverage dataset.

{excerpt_block}

Identify between 3 and 6 distinct analytical themes that organize this coverage. For each theme, provide:
- "name": a specific, analytical theme label (never a single generic word)
- "keywords": 6-12 lowercase keywords/phrases that would appear in text belonging to this theme
- "description": one sentence describing what kind of story this theme covers

Respond in JSON with exactly this shape:
{{"themes": [{{"name": "...", "keywords": ["...", "..."], "description": "..."}}, ...]}}"""

    global _llm_available
    if not _llm_available:
        logger.info("[theme_classifier] LLM circuit-breaker tripped, using fallback themes")
        return []

    raw = llm._llm_call(system, user, format_json=True)
    if not raw:
        _llm_available = False
        logger.warning("[theme_classifier] LLM returned None — disabling LLM for remaining entities")
        return []

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[theme_classifier] Could not parse theme discovery JSON: %s", e)
        return []

    themes = parsed.get("themes") if isinstance(parsed, dict) else parsed
    if not isinstance(themes, list):
        return []

    result: list[dict] = []
    for t in themes:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        keywords = t.get("keywords", [])
        if not name or not isinstance(keywords, list) or not keywords:
            continue
        clean_keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]
        if not clean_keywords:
            continue
        result.append({
            "name": name,
            "keywords": clean_keywords,
            "description": str(t.get("description", "")).strip(),
        })

    return result[:MAX_THEMES]


# ─── Theme Classification (Pass 2 — deterministic) ──────────────────────────

def _classify_record(record: dict, theme_definitions: list[dict], text_columns: list[str]) -> str:
    """Assign a single record to the best-matching theme via keyword overlap
    count. Purely deterministic — no LLM involvement. Records that match no
    theme's keywords fall into UNCLASSIFIED_LABEL."""
    haystack = " ".join(str(record.get(c) or "") for c in text_columns).lower()
    if not haystack.strip():
        return UNCLASSIFIED_LABEL

    best_name = UNCLASSIFIED_LABEL
    best_score = 0
    for theme in theme_definitions:
        score = 0
        for kw in theme.get("keywords", []):
            kw = kw.lower().strip()
            if kw and kw in haystack:
                score += 1
        if score > best_score:
            best_score = score
            best_name = theme["name"]
    return best_name


# ─── Trend, Ranking & Descriptive Helpers ────────────────────────────────────

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y", "%Y%m%d",
)


def _period_key(raw_date: Any) -> str | None:
    """Best-effort parse of a date value into a "YYYY-MM" period bucket.
    Tolerant of ISO strings, Excel datetime str() output, and common
    US/EU date formats. Returns None (skipped from trend) if unparseable."""
    if raw_date is None:
        return None
    if isinstance(raw_date, datetime):
        return raw_date.strftime("%Y-%m")

    s = str(raw_date).strip()
    if not s:
        return None

    m = re.match(r"^(\d{4})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    date_part = s.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_part, fmt)
            return dt.strftime("%Y-%m")
        except ValueError:
            continue
    return None


def _compute_trend(records: list[dict]) -> dict:
    """Count records per YYYY-MM period, purely deterministic."""
    period_counts: dict[str, int] = defaultdict(int)
    for r in records:
        period = _period_key(r.get("date"))
        if period:
            period_counts[period] += 1
    periods = sorted(period_counts.keys())
    return {"periods": periods, "values": [period_counts[p] for p in periods]}


def _compute_date_range(records: list[dict]) -> dict:
    dates = sorted(d for d in (str(r.get("date") or "").strip() for r in records) if d)
    if not dates:
        return {"earliest": None, "latest": None}
    return {"earliest": dates[0], "latest": dates[-1]}


def _top_values(records: list[dict], field: str, limit: int = 5) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        v = str(r.get(field) or "").strip()
        if v:
            counts[v] += 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [name for name, _ in ranked[:limit]]


def _is_active_driver(records: list[dict], entity_name: str) -> bool:
    """Heuristic: an entity is an "active" narrative driver of a theme when it
    tends to appear near the start of the headline (i.e. is the subject of the
    story) rather than a passing mention deep in the text."""
    if not records:
        return False
    name_lower = entity_name.lower()
    hits = 0
    considered = 0
    for r in records:
        headline = (r.get("headline") or "").lower()
        if not headline:
            continue
        considered += 1
        idx = headline.find(name_lower)
        if 0 <= idx <= 40:
            hits += 1
    if considered == 0:
        return False
    return (hits / considered) >= 0.35


def _infer_dataset_source(dataset: dict) -> str:
    file_name = (dataset.get("file_name") or "").lower()
    for token, label in (
        ("meltwater", "Meltwater"),
        ("brandwatch", "Brandwatch"),
        ("cision", "Cision"),
        ("talkwalker", "Talkwalker"),
        ("critical mention", "CriticalMention"),
        ("criticalmention", "CriticalMention"),
    ):
        if token in file_name:
            return label
    return "Uploaded Dataset"


def _build_context_label(spec: dict, entity_name: str) -> str:
    cb = spec.get("commissioning_brand") if isinstance(spec, dict) else None
    brand_name = cb.get("name") if isinstance(cb, dict) else None
    if not brand_name:
        brand_name = spec.get("project_name") if isinstance(spec, dict) else None
    if not brand_name:
        brand_name = entity_name
    return f"{brand_name} & Competitors — Editorial Themes".upper()


def _possessive(name: str) -> str:
    """Grammatically correct possessive form — brand names frequently end in
    's' (e.g. "Brooks Brothers", "Levi's"), where trailing "'s" reads oddly."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _clamp_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:") + "…"


# ─── Narrative Generation (LLM) ──────────────────────────────────────────────

def _generate_theme_narrative(theme: dict, theme_records: list[dict], entity_name: str) -> str:
    """Per-theme 80-140 word analytical narrative. Returns "" if the LLM is
    unavailable — caller falls back to a deterministic templated narrative."""
    if not theme_records:
        return ""

    sample = theme_records[:15]
    headline_lines = [
        (r.get("headline") or r.get("snippet") or "")[:160]
        for r in sample
        if (r.get("headline") or r.get("snippet"))
    ]
    if not headline_lines:
        return ""
    headline_block = "\n".join(f"- {h}" for h in headline_lines)

    pubs = _top_values(theme_records, "source_name", limit=6)
    pub_str = ", ".join(pubs) if pubs else "a mix of unnamed outlets"
    description = (theme.get("definition") or {}).get("description", "")

    system = (
        "You are a senior media/competitive intelligence analyst writing theme interpretations "
        "for an executive briefing. Be specific and analytical — reference story types, publications, "
        "and whether coverage is recurring/sustained versus a one-off/episodic spike. "
        "Write 80-140 words, no bullet points, no headers, third person, professional consulting tone."
    )
    user = f"""Theme: "{theme['name']}" ({theme.get('record_count')} records, {theme.get('share_pct')}% of {entity_name}'s coverage in this dataset)
{"Theme definition: " + description if description else ""}
Top contributing publications: {pub_str}

Representative headlines/snippets:
{headline_block}

Write an 80-140 word analytical interpretation of this theme for {entity_name}: what the theme represents, \
what kinds of stories drive it, which publications contribute most, and whether the coverage appears \
recurring/sustained or a one-off/episodic spike."""

    if not _llm_available:
        return ""
    narrative = llm._llm_call(system, user, format_json=False)
    if not narrative:
        return ""
    return _clamp_words(narrative, NARRATIVE_MAX_WORDS)


def _fallback_narrative(theme_name: str, records: list[dict], entity_name: str) -> str:
    """Deterministic narrative used when the LLM is unavailable."""
    pubs = _top_values(records, "source_name", limit=3)
    pub_str = ", ".join(pubs) if pubs else "a mix of trade and consumer publications"
    count = len(records)
    trend = _compute_trend(records)
    span = len(trend["periods"])
    cadence = "sustained across multiple periods" if span > 1 else "concentrated within a single period"
    pattern = "a recurring editorial pattern" if span > 1 else "an episodic burst of attention"
    poss = _possessive(entity_name)
    return (
        f'"{theme_name}" accounts for {count} record{"s" if count != 1 else ""} of {poss} coverage '
        f"in this dataset, driven primarily by outlets such as {pub_str}. Coverage under this theme is "
        f"{cadence}, suggesting {pattern} rather than isolated one-off mentions. Given the volume and "
        f"consistency of the sourcing observed, this theme should be treated as a meaningful component of "
        f"{poss} overall narrative footprint in the period covered by this dataset."
    )


def _generate_executive_takeaway(entity_name: str, themes: list[dict], total_records: int) -> str:
    """2-4 sentence LLM interpretation of the entity's overall narrative pattern.
    Returns "" if the LLM is unavailable — caller falls back to a template."""
    if not themes:
        return ""

    theme_block = "\n".join(
        f"- {t['name']}: {t['record_count']} records ({t['share_pct']}%), "
        f"{'active driver' if t.get('is_active') else 'passive/contextual mention'}"
        for t in themes
    )
    system = (
        "You are a senior competitive intelligence director. Write a sharp 2-4 sentence executive "
        "takeaway interpreting an entity's overall media narrative pattern based on its theme mix. "
        "Lead with the dominant pattern, note any secondary pattern worth flagging, and note whether "
        "the coverage positions the entity as an active newsmaker or a passive/context mention."
    )
    user = f"""Entity: {entity_name}
Total records analyzed: {total_records}

Theme breakdown:
{theme_block}

Write a 2-4 sentence executive takeaway on {entity_name}'s overall narrative pattern across this coverage."""

    if not _llm_available:
        return ""
    takeaway = llm._llm_call(system, user, format_json=False)
    if not takeaway:
        return ""
    return _clamp_words(takeaway, TAKEAWAY_MAX_WORDS)


def _fallback_takeaway(entity_name: str, themes: list[dict], total_records: int) -> str:
    """Deterministic executive takeaway used when the LLM is unavailable."""
    if not themes:
        return f"No qualifying coverage was found for {entity_name} in this dataset."

    top = themes[0]
    active_note = (
        "positions it as an active newsmaker in this coverage set"
        if top.get("is_active")
        else "reflects largely passive or contextual mentions rather than entity-led stories"
    )
    parts = [
        f'{_possessive(entity_name)} coverage is dominated by "{top["name"]}" '
        f'({top["share_pct"]}% of {total_records} records), which {active_note}.'
    ]
    if len(themes) > 1:
        second = themes[1]
        parts.append(
            f'A secondary pattern around "{second["name"]}" ({second["share_pct"]}%) adds further '
            f"texture to its overall narrative footprint."
        )
    parts.append(
        "Analysts should monitor this theme mix for shifts in emphasis over subsequent reporting periods."
    )
    return " ".join(parts)


# ─── Empty / Error Fallback ──────────────────────────────────────────────────

def _empty_result(entity_name: str, reason: str) -> dict:
    logger.warning("[theme_classifier] %s (entity=%s)", reason, entity_name)
    return {
        "entity": entity_name,
        "total_records": 0,
        "classification_method": "single-label",
        "themes": [],
        "executive_takeaway": reason,
        "date_range": {"earliest": None, "latest": None},
        "dataset_source": None,
        "context_label": "",
        "sample_based": False,
        "error": reason,
    }

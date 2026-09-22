"""SOV Analyzer — deterministic Share of Voice calculations from dataset records.

Reads the actual uploaded dataset file, counts entity mentions per record,
and produces:
1. Overall SOV percentages per entity
2. Trend data (monthly aggregation) per entity
3. Active vs passive visibility classification per entity
4. Competitor narrative summaries (via LLM)

ALL numerical calculations are deterministic — the LLM is ONLY used
for narrative generation, never for percentages or counts.
"""
from __future__ import annotations

import csv
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import intelligence_store as store
from . import llm_synthesis as llm

logger = logging.getLogger(__name__)

# ─── Heuristic keyword lists ─────────────────────────────────────────────────

ACTIVE_KEYWORDS = [
    "launch", "launches", "launched", "launching",
    "announce", "announces", "announced", "announcing",
    "partner", "partners", "partnered", "partnership",
    "campaign",
    "unveil", "unveils", "unveiled", "unveiling",
    "introduce", "introduces", "introduced", "introducing",
    "debut", "debuts", "debuted", "debuting",
    "open", "opens", "opened", "opening",
    "expand", "expands", "expanded", "expansion",
    "collaborate", "collaborates", "collaborated", "collaboration",
    "sponsor", "sponsors", "sponsored", "sponsorship",
]

PASSIVE_KEYWORDS = [
    "roundup", "guide", "gift", "gifts", "gift guide",
    "list", "best of", "top 10", "top ten", "top 5", "top five",
    "where to", "style", "styling", "credit", "credits",
    "spotted", "wore", "wearing", "worn",
]

# Text columns (by canonical mapped field name) to scan for entity mentions
# and visibility classification, in priority order.
_DEFAULT_TEXT_FIELDS = ["headline", "title", "snippet", "summary", "content", "body"]

# Candidate raw column-header aliases used when column_mapping is missing or
# incomplete — matched case-insensitively against the actual file headers.
_TEXT_HEADER_ALIASES = [
    "headline", "title", "article title", "story title",
    "hit sentence", "opening text", "snippet", "extract",
    "summary", "description", "content", "content snippet", "body", "text",
]

_DATE_HEADER_ALIASES = [
    "date", "publish date", "published date", "pub date",
    "timestamp", "date/time", "publication date", "created date",
]

_SOURCE_HEADER_ALIASES = [
    "source name", "source", "publication", "outlet", "media outlet",
]

_MEDIA_TYPE_HEADER_ALIASES = [
    "information type", "media type", "type", "content type", "source type", "channel",
]

_MAX_RECORDS_SCANNED = 200_000


# ─── Public entry point ──────────────────────────────────────────────────────

def analyze_sov(project_id: int) -> dict[str, Any]:
    """Run a full, deterministic Share of Voice analysis for a project's latest dataset.

    Returns a dict shaped as described in the module docstring. Never raises —
    on any failure it returns a well-formed empty-ish result with an "error" key.
    """
    result: dict[str, Any] = {
        "entities": [],
        "total_qualifying_records": 0,
        "trend": {"periods": [], "series": []},
        "date_range": {"earliest": None, "latest": None},
        "dataset_source": "Unknown",
        "context_label": "",
        "narratives": {},
    }

    project = store.get_project(project_id)
    if not project:
        logger.error("[sov_analyzer] project %s not found", project_id)
        result["error"] = f"Project {project_id} not found"
        return result
    spec = project.get("spec") or {}

    entities_spec = _resolve_entities(spec)
    if not entities_spec:
        logger.warning("[sov_analyzer] project %s has no validated_entities of type brand/competitor", project_id)
        result["error"] = "No brand/competitor entities defined in project spec"
        result["context_label"] = _build_context_label(spec)
        return result

    dataset = store.get_latest_dataset(project_id)
    if not dataset:
        logger.warning("[sov_analyzer] project %s has no uploaded dataset", project_id)
        result["error"] = "No dataset uploaded for this project"
        result["context_label"] = _build_context_label(spec)
        return result

    file_path = dataset.get("file_path", "")
    column_mapping = dataset.get("column_mapping") or {}

    try:
        records = _read_dataset_records(file_path, column_mapping)
    except Exception as e:
        logger.error("[sov_analyzer] failed to read dataset file %s: %s", file_path, e)
        result["error"] = f"Failed to read dataset file: {e}"
        result["context_label"] = _build_context_label(spec)
        result["dataset_source"] = _infer_dataset_source(dataset.get("file_name", ""), column_mapping)
        return result

    if not records:
        logger.warning("[sov_analyzer] dataset for project %s parsed to 0 records", project_id)
        result["error"] = "Dataset contains no records"
        result["context_label"] = _build_context_label(spec)
        result["dataset_source"] = _infer_dataset_source(dataset.get("file_name", ""), column_mapping)
        return result

    text_columns = _resolve_text_columns(records, column_mapping)
    date_column = _resolve_field_column(records, column_mapping, "date", _DATE_HEADER_ALIASES)

    if not text_columns:
        logger.warning("[sov_analyzer] could not identify any text columns in dataset for project %s", project_id)
        result["error"] = "Could not identify headline/content columns in dataset"
        result["context_label"] = _build_context_label(spec)
        result["dataset_source"] = _infer_dataset_source(dataset.get("file_name", ""), column_mapping)
        return result

    entity_names = [e["name"] for e in entities_spec]

    # ── Per-record entity detection + visibility classification ─────────────
    mention_counts: Counter[str] = Counter()
    visibility_counts: dict[str, Counter[str]] = {name: Counter() for name in entity_names}
    entity_records: dict[str, list[dict]] = {name: [] for name in entity_names}
    period_entity_counts: dict[str, Counter[str]] = defaultdict(Counter)

    earliest_date: str | None = None
    latest_date: str | None = None
    qualifying_records = 0

    for record in records[:_MAX_RECORDS_SCANNED]:
        matched = _detect_entity_mentions(record, entities_spec, text_columns)
        if not matched:
            continue

        qualifying_records += 1
        visibility = _classify_visibility(record, text_columns)

        record_date = _extract_date(record, date_column)
        if record_date:
            if earliest_date is None or record_date < earliest_date:
                earliest_date = record_date
            if latest_date is None or record_date > latest_date:
                latest_date = record_date

        for name in matched:
            mention_counts[name] += 1
            visibility_counts[name][visibility] += 1
            if len(entity_records[name]) < 500:
                entity_records[name].append(record)
            period = _period_key(record_date) if record_date else None
            if period:
                period_entity_counts[period][name] += 1

    total_mentions = sum(mention_counts.values())

    # ── SOV percentages ──────────────────────────────────────────────────────
    entities_out = []
    for idx, ent in enumerate(entities_spec):
        name = ent["name"]
        mentions = mention_counts.get(name, 0)
        pct = round((mentions / total_mentions * 100), 1) if total_mentions else 0.0
        entities_out.append({
            "name": name,
            "type": ent.get("type", "brand"),
            "mentions": mentions,
            "sov_pct": pct,
            "color_index": idx,
        })
    # Highest SOV first, but keep the brand (if any) pinned to color_index 0 order is fine as-is;
    # sort output by mentions descending for readability while retaining stable color_index.
    entities_out.sort(key=lambda e: e["mentions"], reverse=True)

    # ── Trend (monthly or weekly aggregation) ────────────────────────────────
    trend = _aggregate_by_period(period_entity_counts, entity_names)

    # ── Active/passive visibility + narratives ───────────────────────────────
    narratives: dict[str, dict] = {}
    for name in entity_names:
        vis = visibility_counts.get(name, Counter())
        vis_total = vis["active"] + vis["passive"]
        active_pct = round(vis["active"] / vis_total * 100) if vis_total else 0
        passive_pct = 100 - active_pct if vis_total else 0

        narrative = _generate_entity_narrative(
            entity_name=name,
            entity_records=entity_records.get(name, []),
            total_records=qualifying_records,
            project_spec=spec,
        )
        narrative["active_pct"] = active_pct
        narrative["passive_pct"] = passive_pct
        narratives[name] = narrative

    result["entities"] = entities_out
    result["total_qualifying_records"] = qualifying_records
    result["trend"] = trend
    result["date_range"] = {"earliest": earliest_date, "latest": latest_date}
    result["dataset_source"] = _infer_dataset_source(dataset.get("file_name", ""), column_mapping)
    result["context_label"] = _build_context_label(spec)
    result["narratives"] = narratives
    result["executive_takeaway"] = _build_executive_takeaway(entities_out, narratives, qualifying_records)

    logger.info(
        "[sov_analyzer] project %s: %d qualifying records, %d entities, %d total mentions",
        project_id, qualifying_records, len(entity_names), total_mentions,
    )
    return result


# ─── Entity resolution ────────────────────────────────────────────────────────

def _resolve_entities(spec: dict) -> list[dict]:
    """Pull brand/competitor entities from the project spec's validated_entities."""
    raw = spec.get("validated_entities") or spec.get("source_spec", {}).get("validated_entities") or []
    out = []
    seen = set()
    for ent in raw:
        if not isinstance(ent, dict):
            continue
        etype = str(ent.get("type", "")).lower()
        name = str(ent.get("name", "")).strip()
        if not name or etype not in ("brand", "competitor"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "type": etype})
    return out


# ─── File reading ─────────────────────────────────────────────────────────────

def _read_dataset_records(file_path: str, column_mapping: dict) -> list[dict]:
    """Read an Excel or CSV dataset file into a list of row dicts.

    Keys are the original file column headers (not canonical field names).
    Robust to missing files, unreadable sheets, and inconsistent row lengths.
    """
    if not file_path:
        logger.warning("[sov_analyzer] empty file_path passed to _read_dataset_records")
        return []

    path = Path(file_path)
    if not path.exists():
        logger.error("[sov_analyzer] dataset file does not exist: %s", file_path)
        return []

    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return _read_excel_records(path)
    elif ext == ".csv":
        return _read_csv_records(path)
    else:
        logger.error("[sov_analyzer] unsupported dataset file extension: %s", ext)
        return []


def _read_excel_records(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        logger.error("[sov_analyzer] openpyxl not installed; cannot read Excel dataset")
        return []

    records: list[dict] = []
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        for ws in wb.worksheets:
            headers: list[str] = []
            for row in ws.iter_rows(values_only=True):
                if not headers:
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if any(cells):
                        headers = [c if c else f"Column_{i+1}" for i, c in enumerate(cells)]
                    continue
                if all(v is None for v in row):
                    continue
                row_dict = {}
                for i, header in enumerate(headers):
                    val = row[i] if i < len(row) else None
                    row_dict[header] = _cell_to_str(val)
                records.append(row_dict)
                if len(records) >= _MAX_RECORDS_SCANNED:
                    break
            if len(records) >= _MAX_RECORDS_SCANNED:
                break
        wb.close()
    except Exception as e:
        logger.error("[sov_analyzer] error reading Excel file %s: %s", path, e)
    return records


def _read_csv_records(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        raw = path.read_bytes()
        text = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")

        import io
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            records.append({k: ("" if v is None else v) for k, v in row.items()})
            if len(records) >= _MAX_RECORDS_SCANNED:
                break
    except Exception as e:
        logger.error("[sov_analyzer] error reading CSV file %s: %s", path, e)
    return records


def _cell_to_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return str(val)


# ─── Column resolution ────────────────────────────────────────────────────────

def _mapped_header(column_mapping: dict, canonical_field: str) -> str | None:
    """Look up the actual file header for a canonical field name in a
    {"mapped": {...}, "unmapped": [...]} column_mapping dict."""
    if not column_mapping:
        return None
    mapped = column_mapping.get("mapped", column_mapping)
    if isinstance(mapped, dict):
        val = mapped.get(canonical_field)
        if val:
            return val
    return None


def _resolve_text_columns(records: list[dict], column_mapping: dict) -> list[str]:
    """Determine which actual file columns hold headline/title/content text."""
    if not records:
        return []
    available = set(records[0].keys())
    resolved: list[str] = []

    for field in ("headline", "title", "snippet", "summary"):
        col = _mapped_header(column_mapping, field)
        if col and col in available and col not in resolved:
            resolved.append(col)

    if resolved:
        return resolved

    # Fall back to fuzzy header matching against known aliases.
    lower_map = {c.strip().lower(): c for c in available}
    for alias in _TEXT_HEADER_ALIASES:
        if alias in lower_map and lower_map[alias] not in resolved:
            resolved.append(lower_map[alias])

    return resolved


def _resolve_field_column(records: list[dict], column_mapping: dict, canonical_field: str,
                           aliases: list[str]) -> str | None:
    if not records:
        return None
    available = set(records[0].keys())

    col = _mapped_header(column_mapping, canonical_field)
    if col and col in available:
        return col

    lower_map = {c.strip().lower(): c for c in available}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


# ─── Entity mention detection ─────────────────────────────────────────────────

def _detect_entity_mentions(record: dict, entities: list[dict], text_columns: list[str]) -> list[str]:
    """Return the list of entity names mentioned anywhere in a record's text columns.

    Case-insensitive whole-word (or whole-phrase for multi-word names) matching.
    """
    if not text_columns:
        return []

    combined = " ".join(str(record.get(col, "") or "") for col in text_columns).lower()
    if not combined.strip():
        return []

    matched = []
    for ent in entities:
        name = ent["name"]
        if _name_matches_text(name, combined):
            matched.append(name)
    return matched


_NAME_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _name_matches_text(name: str, lower_text: str) -> bool:
    if not name:
        return False
    pattern = _NAME_PATTERN_CACHE.get(name)
    if pattern is None:
        escaped = re.escape(name.lower())
        # Allow possessive/apostrophe forms and pluralization to still match
        # via a loose word boundary rather than a strict \b, since brand
        # names frequently contain apostrophes and ampersands.
        pattern = re.compile(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])")
        _NAME_PATTERN_CACHE[name] = pattern
    return bool(pattern.search(lower_text))


# ─── Visibility classification ────────────────────────────────────────────────

def _classify_visibility(record: dict, text_columns: list[str]) -> str:
    """Classify a record as 'active' (brand-driven news) or 'passive'
    (incidental mention, e.g. gift guides, style roundups)."""
    combined = " ".join(str(record.get(col, "") or "") for col in text_columns).lower()
    if not combined.strip():
        return "passive"

    for kw in ACTIVE_KEYWORDS:
        if kw in combined:
            return "active"
    for kw in PASSIVE_KEYWORDS:
        if kw in combined:
            return "passive"
    # Default: unclassified mentions lean passive since they are typically
    # incidental references rather than brand-initiated news.
    return "passive"


# ─── Date + period aggregation ────────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
    "%m/%d/%Y", "%m/%d/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%Y/%m/%d", "%m-%d-%Y",
]


def _extract_date(record: dict, date_column: str | None) -> str | None:
    """Parse the record's date column into a normalized YYYY-MM-DD string."""
    if not date_column:
        return None
    raw = str(record.get(date_column, "") or "").strip()
    if not raw:
        return None

    # Already ISO-like (YYYY-MM-DD...) — take the date portion directly.
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if iso_match:
        return iso_match.group(1)

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def _period_key(date_str: str | None) -> str | None:
    """Convert a YYYY-MM-DD date string into a YYYY-MM month bucket."""
    if not date_str or len(date_str) < 7:
        return None
    return date_str[:7]


def _aggregate_by_period(period_entity_counts: dict[str, Counter], entity_names: list[str]) -> dict[str, Any]:
    """Group mentions by month and produce ordered trend series per entity.

    For datasets spanning fewer than ~2 distinct months, still returns
    whatever periods are present (single-point trend); the frontend can
    decide how to render a degenerate trend.
    """
    periods = sorted(period_entity_counts.keys())
    series = []
    for name in entity_names:
        values = [period_entity_counts[p].get(name, 0) for p in periods]
        series.append({"name": name, "values": values})
    return {"periods": periods, "series": series}


# ─── Dataset source + context label ───────────────────────────────────────────

def _infer_dataset_source(file_name: str, column_mapping: dict) -> str:
    """Best-effort guess at the monitoring tool the dataset came from."""
    lower_name = (file_name or "").lower()
    if "meltwater" in lower_name:
        return "Meltwater"
    if "brandwatch" in lower_name:
        return "Brandwatch"
    if "cision" in lower_name:
        return "Cision"
    if "talkwalker" in lower_name:
        return "Talkwalker"
    if "quid" in lower_name:
        return "Quid"

    mapped = (column_mapping or {}).get("mapped", {}) if isinstance(column_mapping, dict) else {}
    # Meltwater exports are recognizable by their distinctive column set.
    if "source_domain" in mapped or "key_phrases" in mapped:
        return "Meltwater"

    return "Uploaded Dataset"


def _build_context_label(spec: dict) -> str:
    """Build a '{BRAND} & COMPETITORS — {MEDIA_TYPE}' style label from the project spec."""
    cb = spec.get("commissioning_brand", {})
    brand_name = ""
    if isinstance(cb, dict):
        brand_name = str(cb.get("name", "")).strip()
    if not brand_name:
        for ent in spec.get("validated_entities", []) or []:
            if isinstance(ent, dict) and str(ent.get("type", "")).lower() == "brand":
                brand_name = str(ent.get("name", "")).strip()
                break
    if not brand_name:
        brand_name = "BRAND"

    media_type = _infer_media_type_label(spec)

    label = f"{brand_name} & COMPETITORS"
    if media_type:
        label = f"{label} — {media_type}"
    return label.upper()


def _infer_media_type_label(spec: dict) -> str:
    scope = spec.get("included_scope", {}) or {}
    content_types = scope.get("content_types") or []
    if isinstance(content_types, list) and content_types:
        return " + ".join(str(c) for c in content_types[:3])
    if isinstance(content_types, str) and content_types.strip():
        return content_types.strip()
    return ""


# ─── LLM narrative generation ─────────────────────────────────────────────────

def _generate_entity_narrative(entity_name: str, entity_records: list[dict], total_records: int,
                                project_spec: dict) -> dict:
    """Generate an analytical narrative for a single entity's coverage.

    Deterministic inputs (topic/publication/driver extraction) are computed
    here; only the prose synthesis is delegated to the LLM. Falls back to a
    template-based summary if the LLM is unavailable.
    """
    mention_count = len(entity_records)
    if mention_count == 0:
        return {
            "text": f"{entity_name} recorded no qualifying mentions in the analyzed dataset.",
            "key_drivers": [],
        }

    key_drivers = _extract_key_drivers(entity_records)
    top_publications = _extract_top_publications(entity_records)

    evidence_lines = []
    for rec in entity_records[:15]:
        text_val = _first_nonempty(rec, ["Headline", "headline", "Title", "title", "Hit Sentence",
                                          "hit sentence", "Snippet", "snippet", "Summary", "summary"])
        if text_val:
            evidence_lines.append(text_val[:200])

    narrative_text = None
    if evidence_lines:
        try:
            narrative_text = _llm_entity_narrative(
                entity_name=entity_name,
                mention_count=mention_count,
                total_records=total_records,
                key_drivers=key_drivers,
                top_publications=top_publications,
                evidence_lines=evidence_lines,
                project_spec=project_spec,
            )
        except Exception as e:
            logger.warning("[sov_analyzer] narrative LLM call failed for %s: %s", entity_name, e)
            narrative_text = None

    if not narrative_text:
        narrative_text = _fallback_narrative(entity_name, mention_count, total_records, key_drivers, top_publications)

    return {
        "text": narrative_text,
        "key_drivers": key_drivers,
    }


def _llm_entity_narrative(entity_name: str, mention_count: int, total_records: int,
                           key_drivers: list[str], top_publications: list[str],
                           evidence_lines: list[str], project_spec: dict) -> str | None:
    """Use llm_synthesis.synthesize_insight() to draft the narrative, then
    extract just the prose. Falls back gracefully if the LLM output doesn't
    parse as expected."""
    cb = project_spec.get("commissioning_brand", {}) if isinstance(project_spec, dict) else {}
    brand_name = cb.get("name", "") if isinstance(cb, dict) else ""

    objective_text = (
        f"What drove media coverage of {entity_name} in this Share of Voice dataset"
        + (f" relative to {brand_name}" if brand_name and brand_name != entity_name else "")
        + f"? ({mention_count} of {total_records} qualifying records mention {entity_name}.)"
    )

    parsed = llm.synthesize_insight(
        objective_text=objective_text,
        insight_type="share_of_voice",
        evidence_excerpts=evidence_lines,
        platforms=top_publications or ["various publications"],
    )
    if not parsed:
        return None

    parts = [parsed.get("executive_summary", ""), parsed.get("observation", "")]
    text = " ".join(p.strip() for p in parts if p and p.strip())
    if not text:
        return None

    word_count = len(text.split())
    if word_count < 40:
        # Too thin — pad with interpretation to get closer to the 70-130 word target.
        interp = parsed.get("interpretation", "")
        if interp:
            text = f"{text} {interp.strip()}"

    return text.strip()


def _fallback_narrative(entity_name: str, mention_count: int, total_records: int,
                         key_drivers: list[str], top_publications: list[str]) -> str:
    """Deterministic template narrative used when the LLM is unavailable."""
    share = round((mention_count / total_records * 100), 1) if total_records else 0.0
    drivers_str = ", ".join(key_drivers[:3]) if key_drivers else "general brand and product coverage"
    pubs_str = ", ".join(top_publications[:3]) if top_publications else "a range of outlets"

    return (
        f"{entity_name} appeared in {mention_count} of {total_records} qualifying records "
        f"({share}% of the analyzed coverage). Coverage was concentrated around {drivers_str}, "
        f"with the most frequent placements in {pubs_str}. This pattern reflects the volume "
        f"and framing of {entity_name} mentions captured in the current dataset window, rather "
        f"than a qualitative assessment of message favorability."
    )


def _build_executive_takeaway(entities: list[dict], narratives: dict,
                              total_records: int) -> str:
    """Build a 2-4 sentence executive takeaway interpreting the competitive SOV picture."""
    if not entities:
        return ""

    sorted_ents = sorted(entities, key=lambda e: e["sov_pct"], reverse=True)
    leader = sorted_ents[0]
    runner_up = sorted_ents[1] if len(sorted_ents) > 1 else None

    parts = []
    if runner_up:
        gap = leader["sov_pct"] - runner_up["sov_pct"]
        if gap > 15:
            parts.append(
                f"{leader['name']} commands the largest share of editorial attention "
                f"at {leader['sov_pct']:.1f}%, significantly ahead of "
                f"{runner_up['name']} ({runner_up['sov_pct']:.1f}%)."
            )
        elif gap > 5:
            parts.append(
                f"{leader['name']} leads share of voice at {leader['sov_pct']:.1f}%, "
                f"with {runner_up['name']} close behind at {runner_up['sov_pct']:.1f}%."
            )
        else:
            parts.append(
                f"{leader['name']} and {runner_up['name']} effectively share the top "
                f"position at {leader['sov_pct']:.1f}% and {runner_up['sov_pct']:.1f}% "
                f"respectively."
            )
    else:
        parts.append(f"{leader['name']} accounts for {leader['sov_pct']:.1f}% of coverage.")

    trailer_names = [e["name"] for e in sorted_ents if e["sov_pct"] < 10]
    if trailer_names:
        parts.append(
            f"{', '.join(trailer_names)} remain{'s' if len(trailer_names)==1 else ''} "
            f"comparatively absent from active earned-media conversation."
        )

    # Add a note about active vs passive if available
    active_leaders = []
    for e in sorted_ents[:2]:
        narr = narratives.get(e["name"], {})
        if narr.get("active_pct", 0) > 60:
            active_leaders.append(e["name"])
    if active_leaders:
        parts.append(
            f"{' and '.join(active_leaders)} {'drives' if len(active_leaders)==1 else 'drive'} "
            f"coverage through active brand-initiated narratives rather than passive mentions."
        )

    return " ".join(parts)


def _extract_key_drivers(entity_records: list[dict]) -> list[str]:
    """Extract the most frequent active-visibility keyword themes across a
    set of entity records, to use as deterministic 'key drivers' bullets."""
    driver_counts: Counter[str] = Counter()
    text_fields = ["Headline", "headline", "Title", "title", "Hit Sentence", "hit sentence",
                   "Snippet", "snippet", "Summary", "summary"]

    for rec in entity_records:
        text_val = _first_nonempty(rec, text_fields)
        if not text_val:
            continue
        lower = text_val.lower()
        for kw in ACTIVE_KEYWORDS:
            if kw in lower:
                driver_counts[kw.rstrip("s")] += 1
                break  # count each record once per driver pass

    # Normalize near-duplicate stems (launch/launches/launched -> launch)
    normalized: Counter[str] = Counter()
    for kw, count in driver_counts.items():
        stem = re.sub(r"(ed|ing|es|s)$", "", kw)
        normalized[stem] += count

    return [stem.capitalize() for stem, _ in normalized.most_common(5)]


def _extract_top_publications(entity_records: list[dict]) -> list[str]:
    """Extract the most frequent source/publication names across entity records."""
    source_fields = ["Source Name", "source name", "Source", "source", "Publication", "publication", "Outlet", "outlet"]
    pub_counts: Counter[str] = Counter()
    for rec in entity_records:
        val = _first_nonempty(rec, source_fields)
        if val:
            pub_counts[val.strip()] += 1
    return [name for name, _ in pub_counts.most_common(5)]


def _first_nonempty(record: dict, candidate_keys: list[str]) -> str | None:
    for key in candidate_keys:
        val = record.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None

"""Query Evaluator Agent -- evaluates Meltwater sample CSV/XLSX exports
against an approved project spec and search strategy.

This agent reads a Meltwater export file, detects its structure, deduplicates
records, classifies each record against the approved spec's research questions
and brand terms, identifies false-positive patterns, and calculates quality
metrics including precision, coverage, and recommended query refinements.

It does NOT call an LLM -- all classification is rule-based keyword matching
so results are deterministic and auditable.

v1.0.0 -- Initial implementation.
"""
from __future__ import annotations

import csv
import os
import re
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Callable

EventFn = Callable[[str, dict], None]

# ---------------------------------------------------------------------------
# Pandas availability
# ---------------------------------------------------------------------------

try:
    import pandas as pd  # type: ignore[import-untyped]
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False


# ---------------------------------------------------------------------------
# Meltwater column name variants
# ---------------------------------------------------------------------------

# Each logical field maps to a list of known column name variants that
# Meltwater exports may use depending on version, locale, or custom config.

COLUMN_VARIANTS: dict[str, list[str]] = {
    "headline": [
        "Headline", "headline", "Title", "title",
        "Article Title", "article_title", "HEADLINE",
    ],
    "hit_sentence": [
        "Hit Sentence", "hit_sentence", "Hit sentence",
        "Snippet", "snippet", "Key Sentence", "key_sentence",
        "HIT_SENTENCE", "Matched Text",
    ],
    "url": [
        "URL", "url", "Url", "Link", "link",
        "Article URL", "article_url", "Source URL", "source_url",
    ],
    "media_type": [
        "Media Type", "media_type", "MediaType", "mediatype",
        "Source Type", "source_type", "Type", "type",
        "MEDIA_TYPE", "Channel",
    ],
    "date": [
        "Date", "date", "Published Date", "published_date",
        "Publish Date", "publish_date", "Publication Date",
        "publication_date", "DATE", "Timestamp", "timestamp",
    ],
    "country": [
        "Country", "country", "Geography", "geography",
        "Location", "location", "Region", "region", "COUNTRY",
    ],
    "reach": [
        "Reach", "reach", "Audience", "audience",
        "Impressions", "impressions", "REACH",
        "Desktop Reach", "Mobile Reach",
    ],
    "source_name": [
        "Source Name", "source_name", "Source", "source",
        "Publication", "publication", "Publisher", "publisher",
        "SOURCE_NAME", "Media Outlet",
    ],
    "content": [
        "Content", "content", "Full Text", "full_text",
        "Body", "body", "Article Content", "article_content",
        "Text", "text", "CONTENT", "Full Content",
    ],
    "sentiment": [
        "Sentiment", "sentiment", "Tone", "tone", "SENTIMENT",
    ],
    "language": [
        "Language", "language", "Lang", "lang", "LANGUAGE",
    ],
    "author": [
        "Author", "author", "Author Name", "author_name",
        "By", "by", "AUTHOR",
    ],
}


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(file_path: str) -> dict:
    """Detect CSV vs XLSX and map key columns in a Meltwater export.

    Parameters
    ----------
    file_path : str
        Path to the sample export file.

    Returns
    -------
    dict
        Keys:
          file_type : "csv" | "xlsx" | "unknown"
          detected_columns : list of column names found in the file
          column_mapping : dict mapping logical field names to actual column names
          unmapped_columns : list of columns that do not match known variants
          record_count : number of data rows
          is_meltwater : bool -- whether this looks like a Meltwater export
          errors : list of error strings (empty on success)
    """
    result: dict[str, Any] = {
        "file_type": "unknown",
        "detected_columns": [],
        "column_mapping": {},
        "unmapped_columns": [],
        "record_count": 0,
        "is_meltwater": False,
        "errors": [],
    }

    if not os.path.isfile(file_path):
        result["errors"].append(f"File not found: {file_path}")
        return result

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".xlsx":
        result["file_type"] = "xlsx"
        if not HAS_PANDAS:
            result["errors"].append(
                "pandas is required to read .xlsx files but is not installed")
            return result
        try:
            df = pd.read_excel(file_path, nrows=0)
            columns = list(df.columns)
            df_full = pd.read_excel(file_path)
            result["record_count"] = len(df_full)
        except Exception as exc:
            result["errors"].append(f"Failed to read XLSX: {exc}")
            return result
    elif ext == ".csv":
        result["file_type"] = "csv"
        columns, record_count = _read_csv_columns(file_path)
        if columns is None:
            result["errors"].append("Failed to read CSV file")
            return result
        result["record_count"] = record_count
    else:
        result["errors"].append(
            f"Unsupported file extension '{ext}' -- expected .csv or .xlsx")
        return result

    result["detected_columns"] = columns
    mapping = _map_columns(columns)
    result["column_mapping"] = mapping
    result["unmapped_columns"] = [
        c for c in columns if c not in mapping.values()
    ]

    # Heuristic: if we mapped at least 3 key Meltwater fields, treat as
    # a Meltwater export.
    meltwater_indicators = {"headline", "url", "hit_sentence", "media_type",
                            "date", "source_name", "content"}
    matched_fields = set(mapping.keys()) & meltwater_indicators
    result["is_meltwater"] = len(matched_fields) >= 3

    return result


def _read_csv_columns(file_path: str) -> tuple[list[str] | None, int]:
    """Read column headers and count rows from a CSV file."""
    columns: list[str] | None = None
    row_count = 0
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if header is None:
                    return None, 0
                columns = header
                for _ in reader:
                    row_count += 1
            break
        except (UnicodeDecodeError, csv.Error):
            continue
    return columns, row_count


def _map_columns(columns: list[str]) -> dict[str, str]:
    """Map logical field names to actual column names found in the file."""
    mapping: dict[str, str] = {}
    col_set = {c: c for c in columns}
    col_lower = {c.lower().strip(): c for c in columns}

    for logical_name, variants in COLUMN_VARIANTS.items():
        for variant in variants:
            if variant in col_set:
                mapping[logical_name] = variant
                break
            if variant.lower().strip() in col_lower:
                mapping[logical_name] = col_lower[variant.lower().strip()]
                break
    return mapping


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_records(file_path: str, column_mapping: dict[str, str]) -> list[dict]:
    """Load records from a CSV or XLSX file, normalising column names to
    logical field names."""
    ext = os.path.splitext(file_path)[1].lower()
    raw_records: list[dict[str, Any]] = []

    if ext == ".xlsx" and HAS_PANDAS:
        df = pd.read_excel(file_path)
        raw_records = df.fillna("").to_dict(orient="records")
    elif ext == ".csv":
        raw_records = _load_csv_records(file_path)
    else:
        return []

    # Build reverse mapping: actual_column -> logical_name
    reverse = {actual: logical for logical, actual in column_mapping.items()}

    normalised: list[dict[str, Any]] = []
    for raw in raw_records:
        record: dict[str, Any] = {}
        for col_name, value in raw.items():
            logical = reverse.get(col_name, col_name)
            record[logical] = str(value).strip() if value is not None else ""
        normalised.append(record)

    return normalised


def _load_csv_records(file_path: str) -> list[dict[str, Any]]:
    """Load all rows from a CSV into a list of dicts."""
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as fh:
                reader = csv.DictReader(fh)
                return list(reader)
        except (UnicodeDecodeError, csv.Error):
            continue
    return []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(
    records: list[dict],
    similarity_threshold: float = 0.85,
) -> tuple[list[dict], list[dict]]:
    """Deduplicate records by exact URL match and headline similarity.

    Returns (unique_records, duplicate_records).
    """
    seen_urls: set[str] = set()
    seen_headlines: list[str] = []
    unique: list[dict] = []
    duplicates: list[dict] = []

    for record in records:
        url = record.get("url", "").strip().lower()
        headline = record.get("headline", "").strip().lower()

        # Exact URL match.
        if url and url in seen_urls:
            duplicates.append(record)
            continue

        # Headline similarity check.
        is_dup = False
        if headline:
            for seen_hl in seen_headlines:
                ratio = SequenceMatcher(None, headline, seen_hl).ratio()
                if ratio >= similarity_threshold:
                    is_dup = True
                    break

        if is_dup:
            duplicates.append(record)
            continue

        if url:
            seen_urls.add(url)
        if headline:
            seen_headlines.append(headline)
        unique.append(record)

    return unique, duplicates


# ---------------------------------------------------------------------------
# Keyword extraction from spec and strategy
# ---------------------------------------------------------------------------

def _extract_spec_keywords(spec: dict) -> dict[str, list[str]]:
    """Extract keyword sets from the project spec for matching.

    Returns a dict with keys:
      brand_terms : brand names, aliases, products
      research_question_terms : dict mapping question_id -> keyword list
      audience_terms : audience segment keywords
      exclusion_terms : terms that should NOT appear
    """
    result: dict[str, Any] = {
        "brand_terms": [],
        "research_question_terms": {},
        "audience_terms": [],
        "exclusion_terms": [],
    }

    # Brand terms from commissioning_brand and validated_entities.
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict) and cb.get("name"):
        result["brand_terms"].append(cb["name"])

    for ent in spec.get("validated_entities", []):
        if isinstance(ent, dict) and ent.get("name"):
            result["brand_terms"].append(ent["name"])
            for alias in ent.get("aliases", []):
                result["brand_terms"].append(alias)

    # Products and competitors from scope.
    scope = spec.get("included_scope", {})
    if isinstance(scope, dict):
        for product in scope.get("products", []):
            result["brand_terms"].append(product)
        for competitor in scope.get("competitors", []):
            result["brand_terms"].append(competitor)
        for brand in scope.get("brands", []):
            result["brand_terms"].append(brand)

    # Research question keywords.
    for rq in spec.get("research_questions", []):
        if isinstance(rq, dict):
            qid = rq.get("question_id", "")
            question_text = rq.get("question", "")
            keywords = _extract_content_words(question_text)
            # Also pull sub_questions if present.
            for sub in rq.get("sub_questions", []):
                if isinstance(sub, str):
                    keywords.extend(_extract_content_words(sub))
                elif isinstance(sub, dict) and sub.get("question"):
                    keywords.extend(_extract_content_words(sub["question"]))
            result["research_question_terms"][qid] = keywords

    # Audience terms.
    ra = spec.get("research_audience", {})
    if isinstance(ra, dict) and ra.get("description"):
        result["audience_terms"] = _extract_content_words(ra["description"])
    for seg in spec.get("audience_segments", []):
        if isinstance(seg, dict) and seg.get("name"):
            result["audience_terms"].append(seg["name"].lower())
        elif isinstance(seg, str):
            result["audience_terms"].append(seg.lower())

    # Exclusion terms from excluded_scope.
    for excl in spec.get("excluded_scope", []):
        if isinstance(excl, dict) and excl.get("item"):
            result["exclusion_terms"].append(excl["item"].lower())
        elif isinstance(excl, str):
            result["exclusion_terms"].append(excl.lower())

    # Deduplicate and normalise.
    result["brand_terms"] = list({t.lower() for t in result["brand_terms"] if t})
    result["audience_terms"] = list({t.lower() for t in result["audience_terms"] if t})
    result["exclusion_terms"] = list(
        {t.lower() for t in result["exclusion_terms"] if t})

    return result


def _extract_strategy_terms(strategy: dict) -> dict[str, list[str]]:
    """Extract keyword sets from the approved search strategy.

    Returns a dict with keys:
      include_terms : all terms from query modules and versions
      exclude_terms : exclusion terms from the strategy
    """
    include_terms: list[str] = []
    exclude_terms: list[str] = []

    # Query modules.
    for mod in strategy.get("query_modules", []):
        if not isinstance(mod, dict):
            continue
        terms = mod.get("terms", {})
        if isinstance(terms, dict):
            for term_list_key in ("primary", "synonyms"):
                for t in terms.get(term_list_key, []):
                    include_terms.append(t.lower())
            for t in terms.get("exclusions", []):
                exclude_terms.append(t.lower())

    # Exclusion strategy.
    excl_strat = strategy.get("exclusion_strategy", {})
    if isinstance(excl_strat, dict):
        global_excl = excl_strat.get("global_exclusions", "")
        if global_excl:
            # Parse NOT terms from boolean string.
            not_terms = re.findall(r'NOT\s+"([^"]+)"', global_excl, re.IGNORECASE)
            not_terms += re.findall(r'NOT\s+(\S+)', global_excl, re.IGNORECASE)
            exclude_terms.extend(t.lower() for t in not_terms)

        for cat in excl_strat.get("exclusion_categories", []):
            if isinstance(cat, dict):
                for t in cat.get("terms", []):
                    exclude_terms.append(t.lower())

    return {
        "include_terms": list(set(include_terms)),
        "exclude_terms": list(set(exclude_terms)),
    }


# Stop words to ignore when extracting content words from questions.
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out",
    "about", "up", "down", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "and", "but", "or", "if", "while", "what",
    "which", "who", "whom", "this", "that", "these", "those", "it",
    "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their",
})


def _extract_content_words(text: str) -> list[str]:
    """Extract meaningful words from text, filtering out stop words."""
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]


# ---------------------------------------------------------------------------
# Record classification
# ---------------------------------------------------------------------------

def classify_record(record: dict, spec: dict, strategy: dict) -> dict:
    """Classify a single record against the spec and strategy.

    Parameters
    ----------
    record : dict
        A normalised record with logical field names.
    spec : dict
        The approved project specification.
    strategy : dict
        The approved search strategy (from meltwater_query_builder).

    Returns
    -------
    dict
        Keys:
          classification : "relevant" | "partially_relevant" | "irrelevant" | "uncertain"
          confidence : "high" | "medium" | "low"
          matched_brand_terms : list of matched brand terms
          matched_rq_ids : list of research question IDs with matches
          matched_strategy_terms : list of strategy include terms found
          matched_exclusion_terms : list of exclusion terms found
          reasons : list of human-readable classification reasons
    """
    spec_keywords = _extract_spec_keywords(spec)
    strategy_terms = _extract_strategy_terms(strategy)

    return _classify_record_impl(record, spec_keywords, strategy_terms)


def _classify_record_impl(
    record: dict,
    spec_keywords: dict,
    strategy_terms: dict,
) -> dict:
    """Internal classification implementation using pre-extracted keywords."""
    result: dict[str, Any] = {
        "classification": "uncertain",
        "confidence": "low",
        "matched_brand_terms": [],
        "matched_rq_ids": [],
        "matched_strategy_terms": [],
        "matched_exclusion_terms": [],
        "reasons": [],
    }

    # Build a single searchable text blob from the record.
    text_parts = []
    for field in ("headline", "hit_sentence", "content", "url", "source_name"):
        val = record.get(field, "")
        if val:
            text_parts.append(val)
    search_text = " ".join(text_parts).lower()

    if not search_text.strip():
        result["classification"] = "uncertain"
        result["confidence"] = "low"
        result["reasons"].append("No searchable text content in record")
        return result

    # Match brand terms.
    for term in spec_keywords.get("brand_terms", []):
        if term in search_text:
            result["matched_brand_terms"].append(term)

    # Match research question terms.
    for qid, rq_terms in spec_keywords.get("research_question_terms", {}).items():
        match_count = sum(1 for t in rq_terms if t in search_text)
        # Require at least 2 matching terms or 50% of terms for short lists.
        threshold = max(2, len(rq_terms) // 2) if rq_terms else 1
        if match_count >= threshold:
            result["matched_rq_ids"].append(qid)

    # Match strategy include terms.
    for term in strategy_terms.get("include_terms", []):
        if term in search_text:
            result["matched_strategy_terms"].append(term)

    # Match exclusion terms.
    for term in strategy_terms.get("exclude_terms", []):
        if term in search_text:
            result["matched_exclusion_terms"].append(term)
    for term in spec_keywords.get("exclusion_terms", []):
        if term in search_text:
            if term not in result["matched_exclusion_terms"]:
                result["matched_exclusion_terms"].append(term)

    # --- Classification logic ---

    has_brand = len(result["matched_brand_terms"]) > 0
    has_rq = len(result["matched_rq_ids"]) > 0
    has_strategy = len(result["matched_strategy_terms"]) > 0
    has_exclusion = len(result["matched_exclusion_terms"]) > 0

    if has_exclusion and not has_brand and not has_rq:
        result["classification"] = "irrelevant"
        result["confidence"] = "high"
        result["reasons"].append(
            f"Contains exclusion terms ({', '.join(result['matched_exclusion_terms'])}) "
            f"without any brand or research question matches")
    elif has_brand and has_rq:
        result["classification"] = "relevant"
        result["confidence"] = "high"
        result["reasons"].append(
            f"Matches brand terms ({', '.join(result['matched_brand_terms'])}) "
            f"and research questions ({', '.join(result['matched_rq_ids'])})")
    elif has_brand and has_strategy and not has_rq:
        result["classification"] = "relevant"
        result["confidence"] = "medium"
        result["reasons"].append(
            f"Matches brand terms and strategy terms but no specific "
            f"research question")
    elif has_brand and not has_strategy and not has_rq:
        result["classification"] = "partially_relevant"
        result["confidence"] = "medium"
        result["reasons"].append(
            f"Matches brand terms ({', '.join(result['matched_brand_terms'])}) "
            f"but no strategy or research question terms")
    elif has_rq and not has_brand:
        result["classification"] = "partially_relevant"
        result["confidence"] = "medium"
        result["reasons"].append(
            f"Matches research questions ({', '.join(result['matched_rq_ids'])}) "
            f"but no brand terms")
    elif has_strategy and not has_brand and not has_rq:
        result["classification"] = "partially_relevant"
        result["confidence"] = "low"
        result["reasons"].append(
            "Matches strategy terms only -- may be topically related "
            "but not brand-specific")
    else:
        result["classification"] = "irrelevant"
        result["confidence"] = "medium"
        result["reasons"].append(
            "No matches for brand terms, research questions, or "
            "strategy terms")

    # Downgrade confidence if exclusion terms are also present.
    if has_exclusion and result["classification"] in ("relevant", "partially_relevant"):
        result["confidence"] = "low"
        result["reasons"].append(
            f"WARNING: also matches exclusion terms "
            f"({', '.join(result['matched_exclusion_terms'])})")

    return result


# ---------------------------------------------------------------------------
# False-positive pattern detection
# ---------------------------------------------------------------------------

def _detect_false_positive_patterns(
    records: list[dict],
    classifications: list[dict],
) -> list[dict]:
    """Identify recurring patterns in irrelevant records.

    Returns a list of pattern dicts describing common noise sources.
    """
    patterns: list[dict] = []

    irrelevant_records = [
        rec for rec, cls in zip(records, classifications)
        if cls["classification"] == "irrelevant"
    ]

    if not irrelevant_records:
        return patterns

    # Count domains from irrelevant URLs.
    domain_counter: Counter[str] = Counter()
    for rec in irrelevant_records:
        url = rec.get("url", "")
        domain = _extract_domain(url)
        if domain:
            domain_counter[domain] += 1

    for domain, count in domain_counter.most_common(10):
        if count >= 2:
            patterns.append({
                "pattern_type": "noisy_domain",
                "value": domain,
                "occurrences": count,
                "recommendation": f"Consider excluding domain '{domain}' "
                                  f"from searches",
            })

    # Count recurring words in irrelevant headlines.
    word_counter: Counter[str] = Counter()
    for rec in irrelevant_records:
        headline = rec.get("headline", "")
        words = _extract_content_words(headline)
        word_counter.update(words)

    # Remove very common words and find high-frequency noise terms.
    for word, count in word_counter.most_common(20):
        if count >= 3:
            patterns.append({
                "pattern_type": "noisy_term",
                "value": word,
                "occurrences": count,
                "recommendation": f"Consider adding NOT \"{word}\" to "
                                  f"exclusion strategy",
            })

    # Check for repeated source names in irrelevant records.
    source_counter: Counter[str] = Counter()
    for rec in irrelevant_records:
        source = rec.get("source_name", "").strip()
        if source:
            source_counter[source] += 1

    for source, count in source_counter.most_common(10):
        if count >= 2:
            patterns.append({
                "pattern_type": "noisy_source",
                "value": source,
                "occurrences": count,
                "recommendation": f"Consider filtering out source "
                                  f"'{source}' if consistently irrelevant",
            })

    return patterns


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL string."""
    url = url.strip().lower()
    if not url:
        return ""
    # Remove protocol.
    for prefix in ("https://", "http://", "//"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    # Remove path and query.
    url = url.split("/")[0].split("?")[0].split("#")[0]
    # Remove www prefix.
    if url.startswith("www."):
        url = url[4:]
    return url


# ---------------------------------------------------------------------------
# Coverage calculations
# ---------------------------------------------------------------------------

def _calculate_rq_coverage(
    classifications: list[dict],
    spec: dict,
) -> dict[str, dict]:
    """Calculate coverage by research question.

    Returns a dict mapping question_id -> { question, record_count, status }.
    """
    rq_coverage: dict[str, dict] = {}

    for rq in spec.get("research_questions", []):
        if not isinstance(rq, dict):
            continue
        qid = rq.get("question_id", "")
        rq_coverage[qid] = {
            "question": rq.get("question", ""),
            "record_count": 0,
            "status": "no_coverage",
        }

    for cls in classifications:
        for qid in cls.get("matched_rq_ids", []):
            if qid in rq_coverage:
                rq_coverage[qid]["record_count"] += 1

    for qid, info in rq_coverage.items():
        count = info["record_count"]
        if count == 0:
            info["status"] = "no_coverage"
        elif count < 5:
            info["status"] = "low_coverage"
        elif count < 20:
            info["status"] = "moderate_coverage"
        else:
            info["status"] = "good_coverage"

    return rq_coverage


def _calculate_platform_coverage(records: list[dict]) -> dict[str, int]:
    """Count records by media type / platform."""
    counter: Counter[str] = Counter()
    for rec in records:
        media_type = rec.get("media_type", "").strip()
        if media_type:
            counter[media_type] += 1
        else:
            counter["unknown"] += 1
    return dict(counter.most_common())


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _generate_recommendations(
    spec_keywords: dict,
    strategy_terms: dict,
    classifications: list[dict],
    false_positive_patterns: list[dict],
    rq_coverage: dict,
) -> dict:
    """Generate recommended additions and exclusions.

    Returns a dict with:
      recommended_additions : list of dicts with term and reason
      recommended_exclusions : list of dicts with term and reason
    """
    additions: list[dict] = []
    exclusions: list[dict] = []

    # Identify uncovered research questions -- recommend adding terms.
    for qid, info in rq_coverage.items():
        if info["status"] == "no_coverage":
            additions.append({
                "type": "research_question_gap",
                "research_question_id": qid,
                "question": info.get("question", ""),
                "reason": f"Research question {qid} has no matching records "
                          f"-- consider broadening search terms or adding "
                          f"synonyms for this topic",
            })

    # Check if brand terms are underrepresented.
    brand_match_counts: Counter[str] = Counter()
    for cls in classifications:
        for term in cls.get("matched_brand_terms", []):
            brand_match_counts[term] += 1
    for term in spec_keywords.get("brand_terms", []):
        if term not in brand_match_counts:
            additions.append({
                "type": "missing_brand_term",
                "term": term,
                "reason": f"Brand term '{term}' found no matches in the "
                          f"sample -- verify it appears in query strategy",
            })

    # Recommend exclusions from false-positive patterns.
    for pattern in false_positive_patterns:
        if pattern["pattern_type"] == "noisy_term":
            exclusions.append({
                "type": "frequent_noise_term",
                "term": pattern["value"],
                "occurrences": pattern["occurrences"],
                "reason": pattern["recommendation"],
            })
        elif pattern["pattern_type"] == "noisy_domain":
            exclusions.append({
                "type": "noisy_domain",
                "domain": pattern["value"],
                "occurrences": pattern["occurrences"],
                "reason": pattern["recommendation"],
            })

    return {
        "recommended_additions": additions,
        "recommended_exclusions": exclusions,
    }


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_sample(
    file_path: str,
    spec: dict,
    strategy: dict,
    *,
    emit: EventFn | None = None,
) -> dict:
    """Evaluate a Meltwater sample export against an approved spec and strategy.

    Parameters
    ----------
    file_path : str
        Path to the Meltwater CSV or XLSX export.
    spec : dict
        The approved project specification (output of Brief & Scope).
    strategy : dict
        The approved search strategy (output of Meltwater Query Builder).
    emit : EventFn, optional
        Callback for progress events.

    Returns
    -------
    dict
        Keys:
          format_info : output of detect_format()
          total_records : total rows in the file
          valid_records : records after dedup
          duplicate_records : number of duplicates removed
          relevant_count : records classified as relevant
          partially_relevant_count : records classified as partially_relevant
          irrelevant_count : records classified as irrelevant
          uncertain_count : records classified as uncertain
          precision_estimate : relevant / (relevant + partially + irrelevant + uncertain)
          false_positive_rate : irrelevant / total non-duplicate records
          estimated_recall_risk : qualitative risk assessment (not measured recall)
          coverage_by_research_question : dict of RQ coverage
          coverage_by_platform : dict of platform counts
          false_positive_patterns : list of detected noise patterns
          recommended_additions : list of recommended search additions
          recommended_exclusions : list of recommended search exclusions
          classifications : list of per-record classification dicts
          validation_errors : list of errors
          validation_warnings : list of warnings
          elapsed_seconds : wall-clock time
          _meta : agent metadata
    """
    if emit is None:
        emit = lambda event_type, payload: None

    start = time.time()

    emit("query_evaluator_started", {
        "file_path": file_path,
    })

    # --- Step 1: Detect format ---
    format_info = detect_format(file_path)

    if format_info["errors"]:
        elapsed = round(time.time() - start, 1)
        emit("query_evaluator_failed", {
            "errors": format_info["errors"],
            "elapsed": elapsed,
        })
        return {
            "format_info": format_info,
            "total_records": 0,
            "valid_records": 0,
            "duplicate_records": 0,
            "relevant_count": 0,
            "partially_relevant_count": 0,
            "irrelevant_count": 0,
            "uncertain_count": 0,
            "precision_estimate": 0.0,
            "false_positive_rate": 0.0,
            "estimated_recall_risk": "unknown",
            "coverage_by_research_question": {},
            "coverage_by_platform": {},
            "false_positive_patterns": [],
            "recommended_additions": [],
            "recommended_exclusions": [],
            "classifications": [],
            "validation_errors": format_info["errors"],
            "validation_warnings": [],
            "elapsed_seconds": elapsed,
            "_meta": _build_meta(elapsed, 0),
        }

    emit("query_evaluator_format_detected", {
        "file_type": format_info["file_type"],
        "is_meltwater": format_info["is_meltwater"],
        "columns_mapped": len(format_info["column_mapping"]),
        "record_count": format_info["record_count"],
    })

    warnings: list[str] = []
    if not format_info["is_meltwater"]:
        warnings.append(
            "File does not appear to be a standard Meltwater export -- "
            "column mapping may be incomplete")

    # --- Step 2: Load records ---
    records = _load_records(file_path, format_info["column_mapping"])
    total_records = len(records)

    emit("query_evaluator_records_loaded", {"count": total_records})

    # --- Step 3: Deduplicate ---
    unique_records, dup_records = _deduplicate(records)
    duplicate_count = len(dup_records)

    emit("query_evaluator_deduplicated", {
        "unique": len(unique_records),
        "duplicates": duplicate_count,
    })

    # --- Step 4: Extract keywords ---
    spec_keywords = _extract_spec_keywords(spec)
    strategy_terms = _extract_strategy_terms(strategy)

    # --- Step 5: Classify each record ---
    classifications: list[dict] = []
    for record in unique_records:
        cls = _classify_record_impl(record, spec_keywords, strategy_terms)
        classifications.append(cls)

    # Count classifications.
    class_counts: Counter[str] = Counter()
    for cls in classifications:
        class_counts[cls["classification"]] += 1

    relevant_count = class_counts.get("relevant", 0)
    partially_relevant_count = class_counts.get("partially_relevant", 0)
    irrelevant_count = class_counts.get("irrelevant", 0)
    uncertain_count = class_counts.get("uncertain", 0)

    valid_records = len(unique_records)

    emit("query_evaluator_classified", {
        "relevant": relevant_count,
        "partially_relevant": partially_relevant_count,
        "irrelevant": irrelevant_count,
        "uncertain": uncertain_count,
    })

    # --- Step 6: Calculate metrics ---
    if valid_records > 0:
        precision_estimate = round(
            (relevant_count + partially_relevant_count) / valid_records, 4)
        false_positive_rate = round(irrelevant_count / valid_records, 4)
    else:
        precision_estimate = 0.0
        false_positive_rate = 0.0

    # Estimated recall risk -- qualitative assessment based on coverage gaps.
    rq_coverage = _calculate_rq_coverage(classifications, spec)
    uncovered_rqs = sum(
        1 for info in rq_coverage.values()
        if info["status"] == "no_coverage"
    )
    total_rqs = len(rq_coverage)

    if total_rqs == 0:
        estimated_recall_risk = "unknown"
    elif uncovered_rqs == 0:
        estimated_recall_risk = "low"
    elif uncovered_rqs <= total_rqs * 0.3:
        estimated_recall_risk = "moderate"
    elif uncovered_rqs <= total_rqs * 0.6:
        estimated_recall_risk = "high"
    else:
        estimated_recall_risk = "very_high"

    # --- Step 7: Platform coverage ---
    platform_coverage = _calculate_platform_coverage(unique_records)

    # --- Step 8: False-positive patterns ---
    fp_patterns = _detect_false_positive_patterns(unique_records, classifications)

    # --- Step 9: Recommendations ---
    recommendations = _generate_recommendations(
        spec_keywords, strategy_terms, classifications,
        fp_patterns, rq_coverage,
    )

    elapsed = round(time.time() - start, 1)

    emit("query_evaluator_complete", {
        "total_records": total_records,
        "valid_records": valid_records,
        "precision_estimate": precision_estimate,
        "false_positive_rate": false_positive_rate,
        "estimated_recall_risk": estimated_recall_risk,
        "elapsed": elapsed,
    })

    return {
        "format_info": format_info,
        "total_records": total_records,
        "valid_records": valid_records,
        "duplicate_records": duplicate_count,
        "relevant_count": relevant_count,
        "partially_relevant_count": partially_relevant_count,
        "irrelevant_count": irrelevant_count,
        "uncertain_count": uncertain_count,
        "precision_estimate": precision_estimate,
        "false_positive_rate": false_positive_rate,
        "estimated_recall_risk": estimated_recall_risk,
        "coverage_by_research_question": rq_coverage,
        "coverage_by_platform": platform_coverage,
        "false_positive_patterns": fp_patterns,
        "recommended_additions": recommendations["recommended_additions"],
        "recommended_exclusions": recommendations["recommended_exclusions"],
        "classifications": classifications,
        "validation_errors": [],
        "validation_warnings": warnings,
        "elapsed_seconds": elapsed,
        "_meta": _build_meta(elapsed, valid_records),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_meta(elapsed: float, record_count: int) -> dict:
    """Build the _meta block attached to every agent output."""
    return {
        "agent": "query_evaluator",
        "version": "1.0.0",
        "elapsed_seconds": elapsed,
        "records_evaluated": record_count,
    }

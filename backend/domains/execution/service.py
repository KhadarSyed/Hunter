"""Dataset loaders: read an uploaded Meltwater/Empower CSV or XLSX export into normalised
row dicts (used by deliverable/rows.py)."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from ...core.tabular import read_csv_dicts

logger = logging.getLogger(__name__)

# ─── Dataset loading ───────────────────────────────────────────────────────

MELTWATER_COLUMN_MAP = {
    # "Article" is the headline column of a bare link-list export (Article / Link / Date)
    "headline": ["headline", "title", "hit headline", "hit_headline", "article title", "article"],
    "url": ["url", "hit url", "hit_url", "link"],
    "source": ["source_name", "source name", "source", "outlet", "media_outlet", "media outlet"],
    "date": ["date", "hit date", "hit_date", "publish date", "publish_date", "publication_date"],
    "author": ["author", "by", "byline", "journalist"],
    "content": ["snippet", "content", "hit sentence", "hit_sentence", "opening text", "opening_text", "summary", "body", "text"],
    "reach": ["reach", "potential_reach", "potential reach", "circulation"],
    "engagement": ["engagement", "social_engagement", "social echo", "social_echo"],
    "sentiment": ["sentiment", "tone", "polarity"],
    "language": ["language", "lang"],
    "country": ["country", "geography", "region", "location"],
    # Meltwater exports say news/social in "Information Type"; "Source Type" (online news, twitter...) is next best
    "media_type": ["media_type", "media type", "type", "medium", "document_type", "information type", "source type"],
}


def _load_dataset(file_path: str) -> list[dict]:
    """Load CSV/XLSX dataset and normalize column names."""
    path = Path(file_path)
    if not path.exists():
        logger.error("Dataset file not found: %s", file_path)
        return []

    if path.suffix.lower() in (".xlsx", ".xls"):
        return _load_xlsx(file_path)

    try:
        return _normalize_columns(read_csv_dicts(file_path))
    except (OSError, csv.Error) as e:
        logger.error("Could not read dataset %s: %s", file_path, e)
        return []


def _load_xlsx(file_path: str) -> list[dict]:
    """Load XLSX using openpyxl if available, else skip."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True)
        records: list[dict] = []
        # Every sheet: an export can hold a Meltwater sheet plus a manually extracted one. Each sheet is
        # normalized on its own because their column names differ.
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2:
                continue
            header_idx = _find_header_row(rows)
            headers = [str(h or "").strip() for h in rows[header_idx]]
            sheet_records = []
            for row in rows[header_idx + 1:]:
                if all(v is None for v in row):
                    continue
                record = {}
                for i, h in enumerate(headers):
                    if h and i < len(row):
                        record[h] = str(row[i]) if row[i] is not None else ""
                sheet_records.append(record)
            records.extend(_normalize_columns(sheet_records))
        wb.close()
        return records
    except ImportError:
        logger.warning("openpyxl not installed — cannot load XLSX")
        return []


def _find_header_row(rows: list[tuple], max_scan: int = 10) -> int:
    """Find the header row in a Meltwater export (may have metadata rows above)."""
    known_headers = {"date", "url", "headline", "title", "source name", "hit sentence",
                     "sentiment", "reach", "keywords", "author name", "content"}
    best_idx, best_score = 0, 0
    for idx in range(min(max_scan, len(rows))):
        cells = [str(c or "").strip().lower() for c in rows[idx] if c is not None]
        score = sum(1 for c in cells if c in known_headers)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _normalize_columns(records: list[dict]) -> list[dict]:
    """Map Meltwater column names to standard field names."""
    if not records:
        return []

    raw_columns = [c for c in records[0].keys() if isinstance(c, str)]
    col_map = {}
    # Every column that could fill a field, in file order: Meltwater leaves "Opening Text" blank on many rows
    # while "Hit Sentence" holds the text, so an empty first match falls through to the next one
    candidates: dict[str, list[str]] = {}
    for standard, variants in MELTWATER_COLUMN_MAP.items():
        matching = [col for col in raw_columns if col.lower().strip() in variants]
        if matching:
            col_map[matching[0]] = standard
            candidates[standard] = matching

    normalized = []
    for r in records:
        row = {}
        for raw_col, value in r.items():
            if not isinstance(raw_col, str):      # csv extra fields arrive under the key None
                continue
            mapped = col_map.get(raw_col, raw_col.lower().strip().replace(" ", "_"))
            row[mapped] = value
        for standard, cols in candidates.items():
            if row.get(standard) in (None, ""):
                row[standard] = next((r[c] for c in cols if r.get(c) not in (None, "")), row.get(standard))
        normalized.append(row)
    return normalized


def _is_excluded(record: dict) -> bool:
    """Rows the analyst removed in the Data Sources Review tab. Needs-review rows still count."""
    return record.get("approval_status") == "disapproved" or record.get("review_status") == "irrelevant"


# ─── Execution orchestration ──────────────────────────────────────────────


# ─── Run control ───────────────────────────────────────────────────────────


# ─── Query helpers ─────────────────────────────────────────────────────────


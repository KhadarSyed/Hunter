"""Parse uploaded monitoring reports (Excel / CSV / DOCX / PPTX) and detect column mappings."""
from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_FIELDS = {
    "headline": ["headline", "title", "article title", "story title", "subject", "article headline"],
    "url": ["url", "link", "article url", "source url", "article link", "web link"],
    "date": ["date", "publication date", "pub date", "published", "publish date", "article date", "created date", "timestamp"],
    "source": ["source", "publisher", "publication", "outlet", "media outlet", "source name", "media source"],
    "summary": ["summary", "snippet", "description", "abstract", "article summary", "blurb", "content", "body", "text"],
    "sentiment": ["sentiment", "tone", "sentiment score", "sentiment label"],
    "reach": ["reach", "impressions", "circulation", "audience", "potential reach", "estimated reach"],
    "author": ["author", "journalist", "byline", "writer", "reporter"],
    "media_type": ["media type", "type", "channel", "medium", "source type"],
    "engagement": ["engagement", "interactions", "shares", "social engagement"],
    "geography": ["geography", "country", "region", "location", "geo"],
    "language": ["language", "lang"],
}


def parse_file(file_path: str) -> dict[str, Any]:
    """Parse an uploaded file and return column info + preview rows."""
    p = Path(file_path)
    ext = p.suffix.lower()

    if ext == ".csv":
        return _parse_csv(p)
    elif ext in (".xlsx", ".xls"):
        return _parse_excel(p)
    elif ext == ".docx":
        return _parse_docx(p)
    elif ext == ".pptx":
        return _parse_pptx(p)
    else:
        return {"error": f"Unsupported file format: {ext}"}


def _parse_csv(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        columns = reader.fieldnames or []
        rows = []
        for i, row in enumerate(reader):
            rows.append(row)
            if i >= 999:
                break

        return {
            "columns": list(columns),
            "row_count": len(rows),
            "column_count": len(columns),
            "preview": rows[:20],
            "field_mapping": _auto_detect_mapping(columns),
        }
    except Exception as e:
        logger.error("CSV parse error: %s", e)
        return {"error": str(e)}


def _parse_excel(path: Path) -> dict[str, Any]:
    try:
        import openpyxl

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return {"error": "No active sheet in workbook"}

        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            wb.close()
            return {"error": "Empty spreadsheet - no header row found"}

        columns = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(header_row)]

        rows = []
        for i, row_vals in enumerate(rows_iter):
            row_dict = {}
            for j, val in enumerate(row_vals):
                if j < len(columns):
                    row_dict[columns[j]] = _cell_to_str(val)
            rows.append(row_dict)
            if i >= 999:
                break

        wb.close()
        return {
            "columns": columns,
            "row_count": len(rows),
            "column_count": len(columns),
            "preview": rows[:20],
            "field_mapping": _auto_detect_mapping(columns),
        }
    except ImportError:
        return {"error": "openpyxl not installed -- run: pip install openpyxl"}
    except Exception as e:
        logger.error("Excel parse error: %s", e)
        return {"error": str(e)}


def _extract_docx_hyperlink(paragraph) -> str:
    """Extract the first hyperlink URL from a Word paragraph's runs."""
    for run in paragraph.runs:
        if run.font and run.font.color and run.font.underline:
            pass
    # python-docx doesn't expose hyperlinks on runs directly; parse the XML
    import xml.etree.ElementTree as ET
    nsmap = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
             "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    for hl in paragraph._element.findall(".//w:hyperlink", nsmap):
        r_id = hl.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if r_id and hasattr(paragraph, "part") and hasattr(paragraph.part, "rels"):
            rel = paragraph.part.rels.get(r_id)
            if rel and rel.target_ref:
                return str(rel.target_ref)
    return ""


def _extract_docx_articles(path: Path) -> list[dict[str, str]]:
    """Extract article cards from a Word doc using text paragraphs + hyperlinks."""
    from docx import Document

    doc = Document(str(path))
    articles: list[dict[str, str]] = []
    entries: list[tuple[str, str]] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text or len(text) < 8:
            continue
        lower = text.lower()
        if any(skip in lower for skip in _SKIP_PHRASES):
            continue
        url = _extract_docx_hyperlink(para)
        entries.append((text, url))

    i = 0
    while i < len(entries):
        text, _ = entries[i]
        if _is_source_line(text):
            source, date, author = _parse_source_line(text)
            headline = ""
            url = ""
            if i > 0:
                headline = entries[i - 1][0]
                url = entries[i - 1][1]
            summary = ""
            if i + 1 < len(entries) and not _is_source_line(entries[i + 1][0]):
                summary = entries[i + 1][0]
                i += 2
            else:
                i += 1
            articles.append({
                "Headline": headline,
                "URL": url,
                "Source": source,
                "Date": date,
                "Author": author,
                "Summary": summary,
            })
        else:
            i += 1

    return articles


def _parse_docx(path: Path) -> dict[str, Any]:
    """Extract data from a Word document — tables first, then article cards."""
    try:
        from docx import Document

        doc = Document(str(path))

        if doc.tables:
            tbl = max(doc.tables, key=lambda t: len(t.rows))
            if len(tbl.rows) >= 2:
                columns = [cell.text.strip() or f"Column_{i+1}" for i, cell in enumerate(tbl.rows[0].cells)]
                rows = []
                for row in tbl.rows[1:]:
                    row_dict = {columns[j]: row.cells[j].text.strip() if j < len(row.cells) else "" for j in range(len(columns))}
                    rows.append(row_dict)
                    if len(rows) >= 1000:
                        break
                return {
                    "columns": columns,
                    "row_count": len(rows),
                    "column_count": len(columns),
                    "preview": rows[:20],
                    "field_mapping": _auto_detect_mapping(columns),
                }

        articles = _extract_docx_articles(path)
        if not articles:
            return {"error": "No article data or tables found in Word document"}

        columns = ["Headline", "URL", "Source", "Date", "Author", "Summary"]
        mapping = {"Headline": "headline", "URL": "url", "Source": "source", "Date": "date", "Author": "author", "Summary": "summary"}
        return {
            "columns": columns,
            "row_count": len(articles),
            "column_count": len(columns),
            "preview": articles[:20],
            "field_mapping": mapping,
        }
    except ImportError:
        return {"error": "python-docx not installed -- run: pip install python-docx"}
    except Exception as e:
        logger.error("DOCX parse error: %s", e)
        return {"error": str(e)}


_DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)

_SHORT_DATE_RE = re.compile(
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}",
    re.IGNORECASE,
)

_SKIP_PHRASES = {
    "subscription required", "sbscription required", "subcription required",
    "similar coverage", "confidential",
}


def _is_source_line(text: str) -> bool:
    """Detect source/date/author lines like 'Forbes  August 9, 2026  By Mark'."""
    if not _DATE_RE.search(text):
        return False
    stripped = text.strip()
    if stripped.startswith(('"', '“', '‘', "'")):
        return False
    if len(stripped) > 200:
        return False
    date_match = _DATE_RE.search(text)
    before = text[:date_match.start()].strip()
    if not before:
        return False
    return True


def _parse_source_line(text: str) -> tuple[str, str, str]:
    """Split a source line into (source, date, author)."""
    date_match = _DATE_RE.search(text)
    if not date_match:
        return text, "", ""
    date_str = date_match.group(0)
    before = text[:date_match.start()]
    after = text[date_match.end():]
    source = re.sub(r"[\s·–—|,]+$", "", before).strip()
    author = ""
    by_match = re.search(r"\bBy\b\s*(.+)", after, re.IGNORECASE)
    if by_match:
        author = by_match.group(1).strip().rstrip(".,;")
    return source, date_str, author


def _extract_hyperlink(shape) -> str:
    """Extract the first hyperlink URL from a shape's text runs."""
    if not shape.has_text_frame:
        return ""
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            if run.hyperlink and run.hyperlink.address:
                return run.hyperlink.address
    return ""


def _extract_key_headlines(all_shapes: list[tuple[str, object]], slide_idx: int) -> list[dict[str, str]]:
    """Extract articles from 'Key headlines of the day' slides where source, date,
    and headline are in separate text shapes."""
    texts = [t for t, _ in all_shapes]
    has_key_headlines = any("key headlines" in t.lower() for t in texts)
    if not has_key_headlines:
        return []

    articles = []
    for i, (text, shape) in enumerate(all_shapes):
        if not _SHORT_DATE_RE.match(text.strip()):
            continue
        date_str = text.strip()
        source = ""
        if i >= 1:
            candidate = all_shapes[i - 1][0].strip()
            if len(candidate) < 60 and candidate.isupper():
                source = candidate
        headline = ""
        url = ""
        for offset in range(1, 4):
            if i + offset >= len(all_shapes):
                break
            candidate_text = all_shapes[i + offset][0].strip()
            if candidate_text.isupper() and len(candidate_text) < 30:
                continue
            if "estimated reach" in candidate_text.lower():
                break
            if len(candidate_text) > 30:
                headline = candidate_text
                url = _extract_hyperlink(all_shapes[i + offset][1])
                break
        if headline and source:
            articles.append({
                "Headline": headline,
                "URL": url,
                "Source": source,
                "Date": date_str,
                "Author": "",
                "Summary": "",
                "Slide": str(slide_idx + 1),
            })
    return articles


def _extract_pptx_articles(path: Path) -> list[dict[str, str]]:
    """Extract article cards from a PPTX that uses text-box layouts (not tables)."""
    from pptx import Presentation

    prs = Presentation(str(path))
    articles: list[dict[str, str]] = []
    seen_headlines: set[str] = set()
    deferred_key_headlines: list[dict[str, str]] = []

    _non_skip = {"similar coverage"}

    for slide_idx, slide in enumerate(prs.slides):
        if slide_idx == 0:
            continue
        all_shapes: list[tuple[str, object]] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            full = shape.text_frame.text.strip()
            if not full or len(full) < 4:
                continue
            all_shapes.append((full, shape))

        deferred_key_headlines.extend(_extract_key_headlines(all_shapes, slide_idx))

        entries: list[tuple[str, object]] = []
        similar_labels: set[int] = set()
        for idx, (full, shape) in enumerate(all_shapes):
            lower = full.lower().strip()
            if lower == "similar coverage":
                similar_labels.add(idx)
                continue
            if any(skip in lower for skip in _SKIP_PHRASES - _non_skip):
                continue
            if len(full) < 8:
                continue
            entries.append((full, shape))

        similar_link_shapes: set[int] = set()
        for label_idx in similar_labels:
            next_idx = label_idx + 1
            if next_idx < len(all_shapes):
                text, shape = all_shapes[next_idx]
                lower = text.lower().strip()
                if lower not in ("similar coverage", "subscription required", "sbscription required", "subcription required", "confidential"):
                    link = _extract_hyperlink(shape)
                    if link:
                        articles.append({
                            "Headline": f"[Similar Coverage] {text[:120]}",
                            "URL": link,
                            "Source": text.split(",")[0].strip() if "," in text else text[:60],
                            "Date": "",
                            "Author": "",
                            "Summary": "",
                            "Slide": str(slide_idx + 1),
                        })
                        similar_link_shapes.add(id(shape))

        i = 0
        while i < len(entries):
            text, shape = entries[i]
            if id(shape) in similar_link_shapes:
                i += 1
                continue
            if _is_source_line(text):
                source, date, author = _parse_source_line(text)
                headline = ""
                url = ""
                if i > 0:
                    headline = entries[i - 1][0]
                    url = _extract_hyperlink(entries[i - 1][1])
                summary = ""
                if i + 1 < len(entries) and not _is_source_line(entries[i + 1][0]):
                    summary = entries[i + 1][0]
                    i += 2
                else:
                    i += 1
                if headline and any(skip in headline.lower() for skip in _SKIP_PHRASES - _non_skip):
                    headline = ""
                norm = headline[:80].lower()
                if norm and norm in seen_headlines:
                    pass
                else:
                    if norm:
                        seen_headlines.add(norm)
                    articles.append({
                        "Headline": headline,
                        "URL": url,
                        "Source": source,
                        "Date": date,
                        "Author": author,
                        "Summary": summary,
                        "Slide": str(slide_idx + 1),
                    })
            else:
                i += 1

    for ka in deferred_key_headlines:
        norm = ka["Headline"][:80].lower()
        if norm not in seen_headlines:
            seen_headlines.add(norm)
            articles.append(ka)

    return articles


def _parse_pptx(path: Path) -> dict[str, Any]:
    """Extract article cards from a PowerPoint presentation."""
    try:
        from pptx import Presentation
        from pptx.table import Table as PptxTable

        prs = Presentation(str(path))
        has_tables = False
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_table:
                    has_tables = True
                    break
            if has_tables:
                break

        if has_tables:
            tables: list[PptxTable] = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_table:
                        tables.append(shape.table)
            tbl = max(tables, key=lambda t: len(t.rows))
            if len(tbl.rows) >= 2:
                columns = [tbl.cell(0, j).text.strip() or f"Column_{j+1}" for j in range(len(tbl.columns))]
                rows = []
                for ri in range(1, len(tbl.rows)):
                    row_dict = {columns[j]: tbl.cell(ri, j).text.strip() for j in range(len(tbl.columns))}
                    rows.append(row_dict)
                    if len(rows) >= 1000:
                        break
                return {
                    "columns": columns,
                    "row_count": len(rows),
                    "column_count": len(columns),
                    "preview": rows[:20],
                    "field_mapping": _auto_detect_mapping(columns),
                }

        articles = _extract_pptx_articles(path)
        if not articles:
            return {"error": "No article data found in PowerPoint presentation"}

        columns = ["Headline", "URL", "Source", "Date", "Author", "Summary", "Slide"]
        mapping = {"Headline": "headline", "URL": "url", "Source": "source", "Date": "date", "Author": "author", "Summary": "summary"}
        return {
            "columns": columns,
            "row_count": len(articles),
            "column_count": len(columns),
            "preview": articles[:20],
            "field_mapping": mapping,
        }
    except ImportError:
        return {"error": "python-pptx not installed -- run: pip install python-pptx"}
    except Exception as e:
        logger.error("PPTX parse error: %s", e)
        return {"error": str(e)}


def _cell_to_str(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _auto_detect_mapping(columns: list[str]) -> dict[str, str]:
    """Map report columns to known QC fields using fuzzy name matching."""
    mapping = {}
    col_lower = {c: c.strip().lower().replace("_", " ").replace("-", " ") for c in columns}

    for field, aliases in KNOWN_FIELDS.items():
        for col, normalized in col_lower.items():
            if normalized in aliases:
                mapping[col] = field
                break

    return mapping


def get_rows_from_file(file_path: str, field_mapping: dict[str, str]) -> list[dict[str, str]]:
    """Read full file and return rows with mapped field names."""
    parsed = parse_file(file_path)
    if "error" in parsed:
        return []

    p = Path(file_path)
    ext = p.suffix.lower()

    if ext == ".csv":
        all_rows = _read_all_csv(p)
    elif ext in (".xlsx", ".xls"):
        all_rows = _read_all_excel(p)
    elif ext == ".docx":
        all_rows = _read_all_docx(p)
    elif ext == ".pptx":
        all_rows = _read_all_pptx(p)
    else:
        return []

    reverse_mapping = {v: k for k, v in field_mapping.items()}
    mapped_rows = []
    for row in all_rows:
        mapped = {}
        for field_name, col_name in reverse_mapping.items():
            mapped[field_name] = row.get(col_name, "")
        mapped_rows.append(mapped)

    return mapped_rows


def _read_all_csv(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _read_all_excel(path: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        return []

    rows_iter = ws.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        wb.close()
        return []

    columns = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(header_row)]
    rows = []
    for row_vals in rows_iter:
        row_dict = {}
        for j, val in enumerate(row_vals):
            if j < len(columns):
                row_dict[columns[j]] = _cell_to_str(val)
        rows.append(row_dict)
    wb.close()
    return rows


def _read_all_docx(path: Path) -> list[dict]:
    from docx import Document

    doc = Document(str(path))
    if doc.tables:
        tbl = max(doc.tables, key=lambda t: len(t.rows))
        if len(tbl.rows) >= 2:
            columns = [cell.text.strip() or f"Column_{i+1}" for i, cell in enumerate(tbl.rows[0].cells)]
            rows = []
            for row in tbl.rows[1:]:
                row_dict = {columns[j]: row.cells[j].text.strip() if j < len(row.cells) else "" for j in range(len(columns))}
                rows.append(row_dict)
            return rows

    return _extract_docx_articles(path)


def _read_all_pptx(path: Path) -> list[dict]:
    from pptx import Presentation
    from pptx.table import Table as PptxTable

    prs = Presentation(str(path))
    has_tables = False
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_table:
                has_tables = True
                break
        if has_tables:
            break

    if has_tables:
        tables: list[PptxTable] = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_table:
                    tables.append(shape.table)
        tbl = max(tables, key=lambda t: len(t.rows))
        if len(tbl.rows) >= 2:
            columns = [tbl.cell(0, j).text.strip() or f"Column_{j+1}" for j in range(len(tbl.columns))]
            rows = []
            for i in range(1, len(tbl.rows)):
                row_dict = {columns[j]: tbl.cell(i, j).text.strip() for j in range(len(tbl.columns))}
                rows.append(row_dict)
            return rows

    return _extract_pptx_articles(path)

"""Load theme coverage files into de-duplicated Article records."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

_TEXT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b. %d, %Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y")


@dataclass
class Article:
    url: str
    norm_url: str
    title: str
    date: date | None
    outlet: str
    text: str
    sentiment: str | None
    reach: float
    themes: set[str] = field(default_factory=set)
    source_file: str = ""
    row_index: int = 0
    image: str = ""            # the post's or article's own picture (Meltwater's Image column), when the export has one
    country: str = ""          # where the export says it is from: Country, State, Region (a county: "New York County")
    state: str = ""
    region: str = ""
    author: str = ""           # the journalist, or the social account (@handle) that posted it
    hour: int | None = None    # the hour it was published (Meltwater's Time column), for an hourly trend


_CLOCK = re.compile(r"^\s*(\d{1,2}):\d{2}")
_STAMP_HOUR = re.compile(r"T(\d{1,2}):\d{2}")


def parse_hour(time_value, date_value=None) -> int | None:
    """The publishing hour from a Time column ("13:30", or a time cell) or a timestamp date ("2026-03-05T10:00:00Z").
    A bare date, or a datetime at exactly midnight (Excel's date-only cell), has no hour."""
    if hasattr(time_value, "hour"):
        return int(time_value.hour)
    m = _CLOCK.match(str(time_value or ""))
    if m and int(m.group(1)) < 24:
        return int(m.group(1))
    if isinstance(date_value, datetime) and (date_value.hour or date_value.minute):
        return date_value.hour
    m = _STAMP_HOUR.search(str(date_value or ""))
    return int(m.group(1)) if m and int(m.group(1)) < 24 else None


def normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


_DASH_DATE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")


def infer_date_order(values) -> str:
    """A file's dash dates are day-first ('dmy') when any of them starts with a number over 12 (25-09-2026);
    otherwise the month-first default. Decided per file, so 12-09-2026 in a day-first export reads 12 September."""
    for v in values:
        m = _DASH_DATE.fullmatch(str(v or "").strip())
        if m and int(m.group(1)) > 12:
            return "dmy"
    return "ymd"


def parse_date(value, order: str = "ymd") -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (a, b) if order == "dmy" else (b, a)
        try:
            return date(y, month, day)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()   # ISO incl. "2026-03-05T10:00:00Z"
    except ValueError:
        pass
    text = re.sub(r"^Sept\b", "Sep", text)                                   # "Sept. 5, 2026" → "Sep. 5, 2026"
    for fmt in _TEXT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _read_rows(spec: dict) -> list[dict]:
    path = Path(spec["path"])
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        return list(csv.DictReader(text.lstrip("﻿").splitlines()))
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[spec["sheet"]] if spec.get("sheet") else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = ["" if h is None else str(h) for h in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:] if any(v is not None for v in r)]


def _to_float(v) -> float:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0



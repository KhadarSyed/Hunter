"""Load theme coverage files into de-duplicated Article records."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

DEFAULT_COLUMNS = {"title": "Title", "url": "URL", "date": "Date", "outlet": "Source Name",
                   "sentiment": "Sentiment", "reach": "Reach"}
TEXT_COLUMNS = ("Opening Text", "Hit Sentence", "Full Article Text (Important)", "Full Content")
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


def normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


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


def load_articles(config: dict) -> tuple[list[Article], dict]:
    merged: dict[str, Article] = {}
    stats = {"rows_read": 0, "unparsed_dates": 0, "duplicates_merged": 0}
    for theme in config["themes"]:
        for spec in theme["files"]:
            cols = {**DEFAULT_COLUMNS, **spec.get("columns", {})}
            for idx, row in enumerate(_read_rows(spec), start=2):
                url = str(row.get(cols["url"]) or "").strip()
                if not url:
                    continue
                stats["rows_read"] += 1
                norm = normalize_url(url)
                d = parse_date(row.get(cols["date"]), spec.get("date_order", "ymd"))
                if d is None:
                    stats["unparsed_dates"] += 1
                if norm in merged:
                    merged[norm].themes.add(theme["key"])
                    stats["duplicates_merged"] += 1
                    continue
                sentiment = row.get(cols["sentiment"])
                merged[norm] = Article(
                    url=url, norm_url=norm, title=str(row.get(cols["title"]) or "").strip(), date=d,
                    outlet=str(row.get(cols["outlet"]) or "").strip(),
                    text=" ".join(str(row[c]) for c in TEXT_COLUMNS if row.get(c)),
                    sentiment=str(sentiment).strip().lower() if sentiment else None,
                    reach=_to_float(row.get(cols["reach"])), themes={theme["key"]},
                    source_file=Path(spec["path"]).name, row_index=idx)
    return list(merged.values()), stats

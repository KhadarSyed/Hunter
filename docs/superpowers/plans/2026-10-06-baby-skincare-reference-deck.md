# Baby Skincare Reference Deck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 17-slide, cited, light-themed Hunter-style PPTX answering the Baby Skincare brief from the four uploaded coverage files.

**Architecture:** A new `agent/app/domains/deliverable/` package of small pure-Python modules (ingest → metrics → LLM classification → cited insights → python-pptx deck blocks → QC), driven by a per-project JSON config and a CLI. Every number is computed deterministically; the LLM only labels articles and drafts prose that a validator checks against computed facts and citation ids. The modules are written to be absorbed later by the Streaming Deliverable engine.

**Tech Stack:** Python 3.12, openpyxl, csv, python-pptx 1.0.2, Azure OpenAI via `agent.app.core.anthropic_client.get_llm_client()`, Brandfetch via `agent.app.domains.research.brandfetch.resolve_logo`, Playwright + amCharts 5 (gauge only), PowerPoint COM (QC export), pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-baby-skincare-reference-deck-design.md`

## Global Constraints

- Base N = union of the four theme files de-duplicated by normalised URL (expected 778; celebrity 468, deal 225, expert 69, parenting 18; 2 multi-theme).
- Share base line on every share slide: "Share of collected category coverage (N=778 unique articles, Meltwater + manual extraction, Oct 2025–Oct 2026)." — N is inserted from the computed value, never hard-coded.
- Numbers on slides come only from the metrics JSON; LLM output containing a number not in the allowed facts is rejected.
- Every insight carries ≥1 citation `[n]`; numbering is global across the deck and resolves to the appendix list.
- Unclassifiable → `unknown`, never guessed. If Azure chat is unreachable, the build stops with a clear error (no rule-based labels substituted).
- Light backgrounds only: slide background `FFFFFF`; header band `FFF6F1`; footer band `F3EEF9`. No dark or grey fills.
- Colours: title/kicker `5B2C9D`; body `404040`; chart palette lavender `8F74CC`, peach `C8643F`, powder blue `3E86B8`, mint `2E8B74`; peak highlight `5B2C9D`; footer source text `8866AA`. All ≥3:1 on white.
- Slide size 13.333 × 7.5 in (12192000 × 6858000 EMU); base deck `PPT Templates/Hunter PR Research_Johnson’s (Baby) Editorial _May 2026.pptx`.
- Output: `Baby-Skincare_Category/output/Hunter PR Research_Baby Skincare Category_Editorial_Oct 2026.pptx` plus `metrics.json`, `classifications.json`, `insights.json` beside it. Do not commit `Baby-Skincare_Category/` or `PPT Templates/` (large, client data).
- Deviation from spec §6.5, noted: the base deck is opened with python-pptx `Presentation(path)` — the same operation the PPT MCP's `create_presentation_from_template` performs — so the build is a reproducible script; the PPT MCP remains available for interactive inspection.

## Review Focus

1. Same article URL in two theme files (2 cases) — counted once in base N, counted in both themes; shares therefore sum >100% and the coverage-mix slide says so.
2. Mixed/foreign date formats (`DD-MM-YYYY` in the CSV, `Mar. 5, 2026` in the parenting file, Excel datetimes) — must parse, never silently drop; unparseable dates are counted and reported in `metrics.json`.
3. CP1252 bytes in the deal CSV (`0x92` apostrophe) — must load without crash and keep the apostrophe.
4. LLM returns an out-of-schema label (e.g. expert_type `"nurse"`) or a citation id outside the candidate set — coerced to `unknown` / insight rejected, never shown.
5. Long insight text or 40+ citation rows overflowing a slide — QC flags text-overflow; the citation appendix paginates.

Pinning tests: 1–3 in Task 1, 4 in Tasks 3 and 4, 5 in Tasks 7 and 8.

## File Structure

```
agent/app/domains/deliverable/
  __init__.py
  config.py          load + validate project JSON config
  ingest.py          Article dataclass, file loaders, date/url normalisation, de-dup
  metrics.py         deterministic metrics (shares, monthly, peaks, outlets, sentiment) + classified metrics
  classify.py        LLM article classification with schema validation + URL cache
  citations.py       global CitationRegistry
  insights.py        LLM insight drafting + validator + deterministic fallback
  style.py           measured Hunter geometry, colours, fonts
  blocks.py          python-pptx slide building blocks (header, footer, charts, cards, tables, KPI tiles)
  gauge.py           amCharts 5 gauge → PNG via Playwright
  deck.py            assemble the 17-slide deck from base template
  qc.py              geometry QC + PowerPoint PNG export
  cli.py             `python -m agent.app.domains.deliverable.cli <config.json>`
  projects/baby_skincare.json
agent/tests/test_deliverable_ingest.py
agent/tests/test_deliverable_metrics.py
agent/tests/test_deliverable_classify.py
agent/tests/test_deliverable_insights.py
agent/tests/test_deliverable_blocks.py
agent/tests/test_deliverable_deck.py
agent/tests/test_deliverable_qc.py
```

Run tests from `D:\HunterAgent` with `C:/Users/khadar.syed/AppData/Local/Programs/Python/Python312/python.exe -m pytest <file> -v` (abbreviated `PY -m pytest` below).

---

### Task 1: Config + ingest (load, normalise, de-dup)

**Files:**
- Create: `agent/app/domains/deliverable/__init__.py` (empty), `config.py`, `ingest.py`, `projects/baby_skincare.json`
- Test: `agent/tests/test_deliverable_ingest.py`

**Interfaces:**
- Produces:
  - `config.load_config(path: str | Path) -> dict` (relative paths resolved against repo root `Path(__file__).resolve().parents[4]`)
  - `ingest.Article` dataclass: `url: str, norm_url: str, title: str, date: datetime.date | None, outlet: str, text: str, sentiment: str | None, reach: float, themes: set[str], source_file: str, row_index: int`
  - `ingest.load_articles(config: dict) -> tuple[list[Article], dict]` → (deduplicated articles, `{"rows_read": int, "unparsed_dates": int, "duplicates_merged": int}`)
  - `ingest.parse_date(value, order: str = "ymd") -> date | None`, `ingest.normalize_url(url: str) -> str`

- [ ] **Step 1: Write the config file**

`agent/app/domains/deliverable/projects/baby_skincare.json`:
```json
{
  "title": "Baby Skincare Category",
  "subtitle": "Earned Editorial Analysis",
  "period_label": "Oct 2025 – Oct 2026",
  "date_label": "October 2026",
  "geography": "US",
  "brief_questions": [
    "How much of the category coverage is deal/sale-led?",
    "How much is focused on parenting advice?",
    "How much cites experts? Which expert types are cited most? What % of experts are brand-affiliated?",
    "How much of category coverage is celebrity-led or features celebrities?"
  ],
  "reference_deck": "PPT Templates/Hunter PR Research_Johnson’s (Baby) Editorial _May 2026.pptx",
  "output_dir": "Baby-Skincare_Category/output",
  "output_name": "Hunter PR Research_Baby Skincare Category_Editorial_Oct 2026.pptx",
  "themes": [
    {"key": "deal", "label": "Deal / sale-led",
     "files": [{"path": "Baby-Skincare_Category/Baby-Skin_Category_Deal_Led_Coverage.csv", "date_order": "dmy"}]},
    {"key": "parenting", "label": "Parenting advice",
     "files": [{"path": "Baby-Skincare_Category/Baby-Skin_Category_Parental Advice_Led_Coverage.xlsx",
                "columns": {"title": "Article", "url": "Link", "date": "Date", "outlet": ""}}]},
    {"key": "expert", "label": "Expert-citing",
     "files": [{"path": "Baby-Skincare_Category/Baby-Skin_Category_Experts_Citations_Led_Coverage.xlsx", "sheet": "MW_Extracted_Data"},
               {"path": "Baby-Skincare_Category/Baby-Skin_Category_Experts_Citations_Led_Coverage.xlsx", "sheet": "Manual_Extracted_Data"}]},
    {"key": "celebrity", "label": "Celebrity-led",
     "files": [{"path": "Baby-Skincare_Category/Baby-Skin_Category_Celebrity_Led_Coverage.xlsx"}]}
  ]
}
```
(`"outlet": ""` means the outlet sits in the column whose header is empty.)

- [ ] **Step 2: Write the failing tests**

`agent/tests/test_deliverable_ingest.py`:
```python
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from agent.app.domains.deliverable import ingest


def _xlsx(path: Path, header: list, rows: list, sheet: str = "Sheet1") -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


@pytest.mark.parametrize("value,expected", [
    ("2025-10-01", date(2025, 10, 1)),
    ("2026-06-03 00:00:00", date(2026, 6, 3)),
    ("Mar. 5, 2026", date(2026, 3, 5)),
    ("March 5, 2026", date(2026, 3, 5)),
    ("not a date", None),
    (None, None),
])
def test_parse_date_formats(value, expected):
    assert ingest.parse_date(value) == expected


def test_parse_date_dmy_order():
    assert ingest.parse_date("01-08-2026", order="dmy") == date(2026, 8, 1)


def test_normalize_url():
    assert ingest.normalize_url(" HTTPS://Example.com/a/ ") == "https://example.com/a"


def test_load_articles_dedups_across_themes_and_handles_cp1252(tmp_path):
    csv_path = tmp_path / "deal.csv"
    csv_path.write_bytes(
        "URL,Title,Date,Source Name,Sentiment,Reach\r\n"
        "https://a.com/1,Mom\x92s deal,01-08-2026,DealSite,positive,100\r\n".encode("latin-1")
    )
    x_path = tmp_path / "celeb.xlsx"
    _xlsx(x_path, ["URL", "Title", "Date", "Source Name", "Sentiment", "Reach"], [
        ["https://a.com/1/", "Mom's deal", "2026-08-01", "DealSite", "positive", 100],
        ["https://b.com/2", "Star bath", "2026-02-10", "Yahoo", "neutral", 50],
    ])
    p_path = tmp_path / "parent.xlsx"
    _xlsx(p_path, ["Article", "Link", "Date", ""], [["Sun tips", "https://c.com/3", "Mar. 5, 2026", "NewsBreak"],
                                                     ["Bad date", "https://d.com/4", "soon", "X"]])
    config = {"themes": [
        {"key": "deal", "label": "Deal", "files": [{"path": str(csv_path), "date_order": "dmy"}]},
        {"key": "celebrity", "label": "Celeb", "files": [{"path": str(x_path)}]},
        {"key": "parenting", "label": "Parent", "files": [{"path": str(p_path),
            "columns": {"title": "Article", "url": "Link", "date": "Date", "outlet": ""}}]},
    ]}
    articles, stats = ingest.load_articles(config)
    by_url = {a.norm_url: a for a in articles}
    assert len(articles) == 4
    assert by_url["https://a.com/1"].themes == {"deal", "celebrity"}
    assert by_url["https://a.com/1"].title == "Mom’s deal"
    assert by_url["https://c.com/3"].outlet == "NewsBreak"
    assert by_url["https://c.com/3"].date == date(2026, 3, 5)
    assert stats == {"rows_read": 5, "unparsed_dates": 1, "duplicates_merged": 1}
```
(`"\x92".encode("latin-1")` writes the single byte `0x92`, which is `’` in CP1252 and invalid UTF-8 — exactly the real file's case.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `PY -m pytest agent/tests/test_deliverable_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.app.domains.deliverable'`

- [ ] **Step 4: Implement `config.py` and `ingest.py`**

`config.py`:
```python
"""Load a per-project deliverable config; resolve paths against the repo root."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _resolve(p: str) -> str:
    path = Path(p)
    return str(path if path.is_absolute() else REPO_ROOT / path)


def load_config(path: str | Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("title", "themes", "reference_deck", "output_dir", "output_name"):
        if key not in cfg:
            raise ValueError(f"deliverable config missing '{key}'")
    cfg["reference_deck"] = _resolve(cfg["reference_deck"])
    cfg["output_dir"] = _resolve(cfg["output_dir"])
    for theme in cfg["themes"]:
        for f in theme["files"]:
            f["path"] = _resolve(f["path"])
    return cfg
```

`ingest.py`:
```python
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
        return list(csv.DictReader(text.lstrip("\ufeff").splitlines()))
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PY -m pytest agent/tests/test_deliverable_ingest.py -v` → all PASS.

- [ ] **Step 6: Verify against the real files**

```bash
PY -c "from agent.app.domains.deliverable import config, ingest; c=config.load_config('agent/app/domains/deliverable/projects/baby_skincare.json'); a,s=ingest.load_articles(c); print(len(a), s, {t: sum(t in x.themes for x in a) for t in ['celebrity','deal','expert','parenting']})"
```
Expected: `778 {...} {'celebrity': 468, 'deal': 225, 'expert': 69, 'parenting': 18}`. If not, fix the loader (not the expected numbers).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/deliverable/__init__.py agent/app/domains/deliverable/config.py agent/app/domains/deliverable/ingest.py agent/app/domains/deliverable/projects/baby_skincare.json agent/tests/test_deliverable_ingest.py
git commit -m "feat(deliverable): config loader and coverage-file ingest with URL de-dup"
```

---

### Task 2: Deterministic metrics

**Files:**
- Create: `agent/app/domains/deliverable/metrics.py`
- Test: `agent/tests/test_deliverable_metrics.py`

**Interfaces:**
- Consumes: `ingest.Article`
- Produces:
  - `metrics.compute_metrics(articles: list[Article], theme_keys: list[str]) -> dict` with keys `base_n: int`, `multi_theme: int`, `themes: {key: {"count", "share" (1 dp), "date_min", "date_max" ("YYYY-MM-DD"|None), "monthly": [{"month": "YYYY-MM", "count"}], "peaks": [{"month", "count", "rank", "top_urls": [≤3 norm_url]}], "outlets": [{"outlet", "count"}] (≤10), "sentiment": {label: count}}}`
  - `metrics.month_label(m: str) -> str` ("2026-03" → "Mar-26")

- [ ] **Step 1: Write the failing test**

`agent/tests/test_deliverable_metrics.py`:
```python
from datetime import date

from agent.app.domains.deliverable import metrics
from agent.app.domains.deliverable.ingest import Article


def _a(url, theme, d, outlet="O", sentiment=None, reach=0.0, themes=None):
    return Article(url=url, norm_url=url, title=url, date=d, outlet=outlet, text="",
                   sentiment=sentiment, reach=reach, themes=themes or {theme})


def test_shares_monthly_and_peaks():
    arts = [
        _a("u1", "deal", date(2026, 1, 5), "A", "positive", 10),
        _a("u2", "deal", date(2026, 1, 9), "A", "positive", 50),
        _a("u3", "deal", date(2026, 3, 1), "B", "neutral"),
        _a("u4", "celebrity", date(2026, 2, 1), "C", "negative", themes={"celebrity", "deal"}),
    ]
    m = metrics.compute_metrics(arts, ["deal", "celebrity"])
    assert m["base_n"] == 4
    assert m["multi_theme"] == 1
    deal = m["themes"]["deal"]
    assert deal["count"] == 4 and deal["share"] == 100.0
    assert [x["month"] for x in deal["monthly"]] == ["2026-01", "2026-02", "2026-03"]
    assert [x["count"] for x in deal["monthly"]] == [2, 1, 1]
    assert deal["peaks"][0] == {"month": "2026-01", "count": 2, "rank": 1, "top_urls": ["u2", "u1"]}
    assert deal["outlets"][0] == {"outlet": "A", "count": 2}
    assert deal["sentiment"] == {"positive": 2, "neutral": 1, "negative": 1}
    assert m["themes"]["celebrity"]["share"] == 25.0


def test_month_gap_filled_with_zero_and_undated_excluded_from_monthly():
    arts = [_a("u1", "x", date(2026, 1, 1)), _a("u2", "x", date(2026, 3, 1)), _a("u3", "x", None)]
    m = metrics.compute_metrics(arts, ["x"])
    assert [x["count"] for x in m["themes"]["x"]["monthly"]] == [1, 0, 1]
    assert m["themes"]["x"]["count"] == 3


def test_month_label():
    assert metrics.month_label("2026-03") == "Mar-26"
```

- [ ] **Step 2: Run to verify fail** — `PY -m pytest agent/tests/test_deliverable_metrics.py -v` → FAIL (`ImportError: cannot import name 'metrics'`).

- [ ] **Step 3: Implement**

`agent/app/domains/deliverable/metrics.py`:
```python
"""Deterministic coverage metrics. No LLM, no guessing."""
from __future__ import annotations

from collections import Counter
from datetime import date

from .ingest import Article

TOP_PEAKS = 5
TOP_OUTLETS = 10


def month_label(month: str) -> str:
    y, m = month.split("-")
    return date(int(y), int(m), 1).strftime("%b-%y")


def _month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _theme_metrics(arts: list[Article], base_n: int) -> dict:
    dated = [a for a in arts if a.date]
    by_month = Counter(a.date.strftime("%Y-%m") for a in dated)
    months = _month_range(min(by_month), max(by_month)) if by_month else []
    monthly = [{"month": mo, "count": by_month.get(mo, 0)} for mo in months]
    ranked = sorted((x for x in monthly if x["count"] > 0), key=lambda x: (-x["count"], x["month"]))
    peaks = []
    for rank, x in enumerate(ranked[:TOP_PEAKS], start=1):
        in_month = [a for a in dated if a.date.strftime("%Y-%m") == x["month"]]
        in_month.sort(key=lambda a: (-a.reach, a.date, a.norm_url))
        peaks.append({"month": x["month"], "count": x["count"], "rank": rank,
                      "top_urls": [a.norm_url for a in in_month[:3]]})
    outlets = Counter(a.outlet for a in arts if a.outlet)
    sentiment = Counter(a.sentiment for a in arts if a.sentiment)
    return {
        "count": len(arts),
        "share": round(100 * len(arts) / base_n, 1) if base_n else 0.0,
        "date_min": min(a.date for a in dated).isoformat() if dated else None,
        "date_max": max(a.date for a in dated).isoformat() if dated else None,
        "monthly": monthly,
        "peaks": peaks,
        "outlets": [{"outlet": o, "count": c} for o, c in outlets.most_common(TOP_OUTLETS)],
        "sentiment": dict(sentiment),
    }


def compute_metrics(articles: list[Article], theme_keys: list[str]) -> dict:
    base_n = len(articles)
    return {
        "base_n": base_n,
        "multi_theme": sum(1 for a in articles if len(a.themes) > 1),
        "themes": {k: _theme_metrics([a for a in articles if k in a.themes], base_n) for k in theme_keys},
    }
```

- [ ] **Step 4: Run to verify pass** — all PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/metrics.py agent/tests/test_deliverable_metrics.py
git commit -m "feat(deliverable): deterministic shares, monthly trend, top-5 peaks, outlets, sentiment"
```

---

### Task 3: LLM article classification (schema-validated, cached)

**Files:**
- Create: `agent/app/domains/deliverable/classify.py`
- Modify: `agent/app/domains/deliverable/metrics.py` (append `compute_classified_metrics`)
- Test: `agent/tests/test_deliverable_classify.py`

**Interfaces:**
- Consumes: `Article`; an LLM object with `chat(messages: list[dict], on_token=None, format_json: bool = False) -> str` (the `HybridLLMClient` from `get_llm_client()`), or `None`.
- Produces:
  - `classify.SCHEMAS: dict[str, dict]` — per theme `{"list_field": str, "item": {field: list[str] | None}}`
  - `classify.classify_theme(articles: list[Article], theme: str, llm, cache: dict) -> dict[str, dict]` keyed by `norm_url`; extends `cache` (`{theme: {norm_url: record}}`) in place
  - `classify.ClassificationUnavailable(RuntimeError)`
  - `metrics.compute_classified_metrics(classifications: dict[str, dict[str, dict]]) -> dict` with keys `expert` (`articles_with_expert, experts_total, type_counts, type_unknown, affiliated_pct, affiliated_n, affiliation_known_n, affiliation_unknown, affiliated_brands`), `celebrity` (`top, roles`), `deal` (`retailers, deal_types`), `parenting` (`topics`), `brands` (list of `{"brand", "count"}`)

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_deliverable_classify.py`:
```python
import json

import pytest

from agent.app.domains.deliverable import classify, metrics
from agent.app.domains.deliverable.ingest import Article


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, on_token=None, format_json=False):
        self.calls += 1
        return self.replies.pop(0)


def _art(u):
    return Article(url=u, norm_url=u, title="t " + u, date=None, outlet="O", text="body", sentiment=None,
                   reach=0, themes={"expert"})


def test_expert_classification_validates_enums_and_caches():
    reply = json.dumps({"items": [
        {"url": "u1", "experts": [
            {"name": "Dr. A", "expert_type": "dermatologist", "affiliation": "affiliated", "brand": "Aveeno",
             "evidence": "Dr. A, Aveeno consultant"},
            {"name": "B", "expert_type": "nurse", "affiliation": "maybe", "brand": "", "evidence": "B said"}],
         "brands": ["Aveeno"]},
        {"url": "zzz-not-in-batch", "experts": [], "brands": []},
    ]})
    llm = FakeLLM([reply])
    cache: dict = {}
    out = classify.classify_theme([_art("u1"), _art("u2")], "expert", llm, cache)
    e = out["u1"]["experts"]
    assert e[0]["expert_type"] == "dermatologist" and e[0]["affiliation"] == "affiliated"
    assert e[1]["expert_type"] == "unknown" and e[1]["affiliation"] == "unknown"
    assert out["u2"] == {"experts": [], "brands": [], "status": "unknown"}
    assert "zzz-not-in-batch" not in out
    classify.classify_theme([_art("u1"), _art("u2")], "expert", llm, cache)
    assert llm.calls == 1  # second call served from cache


def test_invalid_json_marks_unknown_not_crash():
    out = classify.classify_theme([_art("u1")], "expert", FakeLLM(["not json"]), {})
    assert out["u1"]["status"] == "unknown"


def test_unreachable_llm_raises():
    with pytest.raises(classify.ClassificationUnavailable):
        classify.classify_theme([_art("u1")], "expert", None, {})


def test_classified_metrics_expert_affiliation_pct():
    cls = {"expert": {
        "u1": {"experts": [{"name": "A", "expert_type": "dermatologist", "affiliation": "affiliated", "brand": "X"},
                           {"name": "B", "expert_type": "pediatrician", "affiliation": "independent", "brand": ""}],
               "brands": ["X"]},
        "u2": {"experts": [{"name": "C", "expert_type": "dermatologist", "affiliation": "unknown", "brand": ""}],
               "brands": []}}}
    m = metrics.compute_classified_metrics(cls)
    assert m["expert"]["type_counts"] == {"dermatologist": 2, "pediatrician": 1}
    assert m["expert"]["experts_total"] == 3
    assert m["expert"]["affiliated_pct"] == 50.0          # 1 of 2 with known affiliation
    assert m["expert"]["affiliation_unknown"] == 1
    assert m["brands"][0] == {"brand": "X", "count": 1}
```

- [ ] **Step 2: Run to verify fail** — `PY -m pytest agent/tests/test_deliverable_classify.py -v` → FAIL (import error).

- [ ] **Step 3: Implement `classify.py`**

```python
"""Per-article LLM labelling. Labels outside the schema become 'unknown'; nothing is invented."""
from __future__ import annotations

import json
import logging

from .ingest import Article

logger = logging.getLogger(__name__)
BATCH = 8
MAX_TEXT = 4000

SCHEMAS: dict[str, dict] = {
    "expert": {"list_field": "experts", "item": {
        "name": None, "expert_type": ["dermatologist", "pediatrician", "other_hcp", "non_hcp_expert"],
        "affiliation": ["affiliated", "independent"], "brand": None, "evidence": None}},
    "celebrity": {"list_field": "celebrities", "item": {
        "name": None, "role": ["spokesperson", "product_mention", "lifestyle"]}},
    "deal": {"list_field": "deals", "item": {
        "product": None, "retailer": None, "deal_type": ["discount", "freebie", "bundle"]}},
    "parenting": {"list_field": "topics", "item": {
        "topic": ["sun_safety", "eczema_dryness", "bathing", "diapering", "ingredients", "sleep_routine", "other"]}},
}

_INSTRUCTIONS = {
    "expert": "List every expert quoted or cited. expert_type: dermatologist, pediatrician, other_hcp "
              "(nurse, pharmacist, other clinician) or non_hcp_expert. affiliation: 'affiliated' only if the "
              "text states a tie to a brand (employee, consultant, paid partner, spokesperson) and name it in "
              "brand; 'independent' only if the text makes clear there is no brand tie; otherwise omit it. "
              "evidence: the exact short phrase that supports the label.",
    "celebrity": "List every celebrity named. role: spokesperson (paid/brand partner), product_mention, or lifestyle.",
    "deal": "List each promoted product with its retailer and deal_type (discount, freebie, bundle).",
    "parenting": "List the parenting-advice topics covered.",
}


class ClassificationUnavailable(RuntimeError):
    pass


def _clean_item(item: dict, spec: dict) -> dict:
    out = {}
    for field, allowed in spec.items():
        value = item.get(field)
        if allowed is None:
            out[field] = str(value or "").strip()
        else:
            out[field] = value if value in allowed else "unknown"
    return out


def _prompt(theme: str, batch: list[Article]) -> list[dict]:
    schema = SCHEMAS[theme]
    docs = [{"url": a.norm_url, "title": a.title, "text": a.text[:MAX_TEXT]} for a in batch]
    system = ("You label news articles for a media-research report. Use only what the article text says. "
              "If something is not stated, omit it. Return JSON only.")
    user = (f"{_INSTRUCTIONS[theme]}\nAlso list 'brands': baby/skincare brand names mentioned.\n"
            f"Return {{\"items\": [{{\"url\": <url>, \"{schema['list_field']}\": [objects with fields "
            f"{json.dumps(list(schema['item']))}], \"brands\": [..]}}]}} with one item per article.\n"
            f"Articles:\n{json.dumps(docs, ensure_ascii=False)}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def classify_theme(articles: list[Article], theme: str, llm, cache: dict) -> dict[str, dict]:
    if llm is None:
        raise ClassificationUnavailable("Azure OpenAI chat is not configured/reachable — cannot classify articles")
    schema = SCHEMAS[theme]
    store = cache.setdefault(theme, {})
    todo = [a for a in articles if a.norm_url not in store]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        wanted = {a.norm_url for a in batch}
        try:
            parsed = json.loads(llm.chat(_prompt(theme, batch), format_json=True))
        except json.JSONDecodeError:
            logger.warning("classification batch for %s returned invalid JSON; marking unknown", theme)
            parsed = {"items": []}
        for item in parsed.get("items", []):
            url = str(item.get("url", "")).strip().rstrip("/").lower()
            if url not in wanted:
                continue
            store[url] = {schema["list_field"]: [_clean_item(x, schema["item"])
                                                 for x in item.get(schema["list_field"], []) if isinstance(x, dict)],
                          "brands": [str(b).strip() for b in item.get("brands", []) if str(b).strip()]}
        for url in wanted - store.keys():
            store[url] = {schema["list_field"]: [], "brands": [], "status": "unknown"}
    return {a.norm_url: store[a.norm_url] for a in articles}
```

- [ ] **Step 4: Append `compute_classified_metrics` to `metrics.py`**

```python
def _top(counter: Counter, key: str, n: int = 10) -> list[dict]:
    return [{key: k, "count": c} for k, c in counter.most_common(n)]


def compute_classified_metrics(classifications: dict[str, dict[str, dict]]) -> dict:
    out: dict = {}
    expert_recs = classifications.get("expert", {})
    experts = [e for rec in expert_recs.values() for e in rec.get("experts", [])]
    known = [e for e in experts if e["affiliation"] in ("affiliated", "independent")]
    affiliated = sum(1 for e in known if e["affiliation"] == "affiliated")
    out["expert"] = {
        "articles_with_expert": sum(1 for r in expert_recs.values() if r.get("experts")),
        "experts_total": len(experts),
        "type_counts": dict(Counter(e["expert_type"] for e in experts if e["expert_type"] != "unknown")),
        "type_unknown": sum(1 for e in experts if e["expert_type"] == "unknown"),
        "affiliated_pct": round(100 * affiliated / len(known), 1) if known else None,
        "affiliated_n": affiliated,
        "affiliation_known_n": len(known),
        "affiliation_unknown": len(experts) - len(known),
        "affiliated_brands": _top(Counter(e["brand"] for e in experts
                                          if e["affiliation"] == "affiliated" and e["brand"]), "brand"),
    }
    celebs = classifications.get("celebrity", {})
    out["celebrity"] = {
        "top": _top(Counter(n for r in celebs.values()
                            for n in {c["name"] for c in r.get("celebrities", []) if c["name"]}), "name"),
        "roles": dict(Counter(c["role"] for r in celebs.values() for c in r.get("celebrities", []))),
    }
    deals = classifications.get("deal", {})
    out["deal"] = {
        "retailers": _top(Counter(d["retailer"] for r in deals.values() for d in r.get("deals", [])
                                  if d["retailer"]), "retailer"),
        "deal_types": dict(Counter(d["deal_type"] for r in deals.values() for d in r.get("deals", []))),
    }
    out["parenting"] = {"topics": dict(Counter(t["topic"] for r in classifications.get("parenting", {}).values()
                                               for t in r.get("topics", [])))}
    brand_articles: Counter = Counter()
    for theme_recs in classifications.values():
        for rec in theme_recs.values():
            brand_articles.update(set(rec.get("brands", [])))
    out["brands"] = _top(brand_articles, "brand", 12)
    return out
```

- [ ] **Step 5: Run to verify pass.** `PY -m pytest agent/tests/test_deliverable_classify.py agent/tests/test_deliverable_metrics.py -v`

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/deliverable/classify.py agent/app/domains/deliverable/metrics.py agent/tests/test_deliverable_classify.py
git commit -m "feat(deliverable): schema-validated LLM article classification with cache and classified metrics"
```

---

### Task 4: Citation registry + validated insights

**Files:**
- Create: `agent/app/domains/deliverable/citations.py`, `agent/app/domains/deliverable/insights.py`
- Test: `agent/tests/test_deliverable_insights.py`

**Interfaces:**
- Consumes: `Article`; LLM `chat` as in Task 3.
- Produces:
  - `citations.CitationRegistry` with `cite(article: Article) -> int` and `entries() -> list[dict]` (`{"n", "outlet", "date", "title", "url"}` ordered by n)
  - `insights.allowed_numbers(facts: list[str]) -> set[str]`
  - `insights.validate_insight(text: str, cites: list[int], allowed: set[str], candidate_ids: set[int]) -> str | None` (rejection reason, or None if valid)
  - `insights.draft_section(section: str, facts: list[str], candidates: list[Article], registry: CitationRegistry, llm, n_insights: int = 3) -> list[dict]` → `[{"headline", "text", "citations": list[int]}]`; deterministic fallback when the LLM is None or every LLM insight is rejected.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_deliverable_insights.py`:
```python
import json
from datetime import date

from agent.app.domains.deliverable import insights
from agent.app.domains.deliverable.citations import CitationRegistry
from agent.app.domains.deliverable.ingest import Article


def _art(u, outlet="Outlet"):
    return Article(url="https://" + u, norm_url="https://" + u, title="T " + u, date=date(2026, 1, 2),
                   outlet=outlet, text="", sentiment=None, reach=0, themes={"deal"})


def test_registry_is_global_and_stable():
    r = CitationRegistry()
    a, b = _art("a"), _art("b")
    assert r.cite(a) == 1 and r.cite(b) == 2 and r.cite(a) == 1
    assert r.entries()[1]["url"] == "https://b"


def test_validator_rejects_unknown_numbers_and_citations():
    allowed = insights.allowed_numbers(["Deal-led share is 28.9% (225 of 778)"])
    assert insights.validate_insight("Deals are 28.9% of coverage", [1], allowed, {1}) is None
    assert "number" in insights.validate_insight("Deals are 40% of coverage", [1], allowed, {1})
    assert "citation" in insights.validate_insight("Deals dominate", [7], allowed, {1})
    assert "citation" in insights.validate_insight("Deals dominate", [], allowed, {1})
    assert insights.validate_insight("In 2026 deals rose", [1], allowed, {1}) is None  # years allowed


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, on_token=None, format_json=False):
        return self.reply


def test_draft_section_drops_invalid_and_falls_back_when_empty():
    reg = CitationRegistry()
    cands = [_art("a"), _art("b")]
    reply = json.dumps({"insights": [
        {"headline": "Deals lead", "text": "Deal-led share is 28.9%.", "citations": [1]},
        {"headline": "Made up", "text": "Share is 55%.", "citations": [1]},
    ]})
    out = insights.draft_section("deal", ["Deal-led share is 28.9% (225 of 778)"], cands, reg, FakeLLM(reply))
    assert [i["headline"] for i in out] == ["Deals lead"]
    assert [e["url"] for e in reg.entries()] == ["https://a"]      # uncited candidate b is not registered
    fb = insights.draft_section("deal", ["Deal-led share is 28.9% (225 of 778)"], cands, CitationRegistry(), None)
    assert fb and fb[0]["citations"] and "28.9%" in fb[0]["text"]


def test_numbers_in_headline_are_checked_too():
    reply = json.dumps({"insights": [{"headline": "Deals hit 60%", "text": "Deal-led share is 28.9%.",
                                      "citations": [1]}]})
    out = insights.draft_section("deal", ["Deal-led share is 28.9% (225 of 778)"], [_art("a")],
                                 CitationRegistry(), FakeLLM(reply))
    assert out[0]["headline"] == "Key finding"                     # rejected → fallback
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `citations.py`**

```python
"""Global, stable citation numbering across the whole deck."""
from __future__ import annotations

from .ingest import Article


class CitationRegistry:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._entries: list[dict] = []

    def cite(self, article: Article) -> int:
        if article.norm_url not in self._ids:
            n = len(self._entries) + 1
            self._ids[article.norm_url] = n
            self._entries.append({"n": n, "outlet": article.outlet, "title": article.title, "url": article.url,
                                  "date": article.date.isoformat() if article.date else ""})
        return self._ids[article.norm_url]

    def entries(self) -> list[dict]:
        return list(self._entries)
```

- [ ] **Step 4: Implement `insights.py`**

```python
"""LLM-drafted insights, accepted only if every number and citation checks out."""
from __future__ import annotations

import json
import logging
import re

from .citations import CitationRegistry
from .ingest import Article

logger = logging.getLogger(__name__)
_NUM = re.compile(r"\d+(?:\.\d+)?")
_YEARS = {"2024", "2025", "2026"}


def allowed_numbers(facts: list[str]) -> set[str]:
    return {n for f in facts for n in _NUM.findall(f)} | _YEARS


def validate_insight(text: str, cites: list[int], allowed: set[str], candidate_ids: set[int]) -> str | None:
    if not cites or not set(cites) <= candidate_ids:
        return "citation missing or outside candidate set"
    bad = [n for n in _NUM.findall(text) if n not in allowed]
    if bad:
        return f"number(s) not in facts: {bad}"
    return None


def _fallback(facts: list[str], candidates: list[Article], registry: CitationRegistry) -> list[dict]:
    if not facts or not candidates:
        return []
    return [{"headline": "Key finding", "text": facts[0], "citations": [registry.cite(a) for a in candidates[:2]]}]


def draft_section(section: str, facts: list[str], candidates: list[Article], registry: CitationRegistry,
                  llm, n_insights: int = 3) -> list[dict]:
    """Candidates get local ids 1..k in the prompt; only articles an accepted insight actually cites are
    registered, so the appendix lists cited articles only."""
    if llm is None:
        return _fallback(facts, candidates, registry)
    allowed = allowed_numbers(facts)
    local = {i: a for i, a in enumerate(candidates, start=1)}
    arts = [{"id": i, "outlet": a.outlet, "date": a.date.isoformat() if a.date else "", "title": a.title,
             "excerpt": a.text[:400]} for i, a in local.items()]
    messages = [
        {"role": "system", "content": "You write insights for a media-research deck. Use ONLY numbers that appear "
         "in FACTS. Every insight must cite article ids from ARTICLES that support it. Return JSON only."},
        {"role": "user", "content": f"Section: {section}\nFACTS:\n" + "\n".join(f"- {f}" for f in facts) +
         f"\nARTICLES:\n{json.dumps(arts, ensure_ascii=False)}\nWrite {n_insights} insights as "
         '{"insights":[{"headline":"<=8 words","text":"<=45 words","citations":[ids]}]}'},
    ]
    try:
        parsed = json.loads(llm.chat(messages, format_json=True))
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("insight drafting for %s failed (%s); using fallback", section, e)
        return _fallback(facts, candidates, registry)
    kept = []
    for ins in parsed.get("insights", []):
        headline, text = str(ins.get("headline", "")).strip(), str(ins.get("text", "")).strip()
        cites = [int(c) for c in ins.get("citations", []) if str(c).isdigit()]
        reason = validate_insight(f"{headline} {text}", cites, allowed, set(local))
        if reason:
            logger.info("dropped insight in %s: %s", section, reason)
            continue
        kept.append({"headline": headline, "text": text,
                     "citations": sorted({registry.cite(local[c]) for c in cites})})
    return kept or _fallback(facts, candidates, registry)
```

- [ ] **Step 5: Run to verify pass.**

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/deliverable/citations.py agent/app/domains/deliverable/insights.py agent/tests/test_deliverable_insights.py
git commit -m "feat(deliverable): global citation registry and fact-checked insight drafting"
```

---

### Task 5: Style + slide building blocks

**Files:**
- Create: `agent/app/domains/deliverable/style.py`, `agent/app/domains/deliverable/blocks.py`
- Test: `agent/tests/test_deliverable_blocks.py`

**Interfaces:**
- Produces (`blocks`, all positions/sizes in inches as floats):
  - `new_content_slide(prs) -> Slide` (Blank layout, explicit white background)
  - `add_text(slide, x, y, w, h, text, size, bold=False, color=style.BODY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)`
  - `add_header(slide, kicker: str, title: str, summary: str)`
  - `add_footer(slide, source: str, base_n: int)`
  - `add_column_chart(slide, x, y, w, h, categories, values, highlight_idx: set[int], number_format="0") -> Chart`
  - `add_bar_chart(slide, x, y, w, h, categories, values, color=style.LAVENDER, number_format="0") -> Chart` (largest on top)
  - `add_line_chart_with_peaks(slide, x, y, w, h, categories, values, peak_idx: set[int]) -> Chart`
  - `add_doughnut(slide, x, y, w, h, categories, values, number_format='0.0"%"') -> Chart`
  - `add_insight_cards(slide, x, y, w, h, insights: list[dict], cols: int)`
  - `add_kpi_tiles(slide, x, y, w, h, tiles: list[dict])` — tile `{"value", "label", "note"}`
  - `add_table(slide, x, y, w, h, header: list[str], rows: list[list[str]], col_widths: list[float])`
  - `citation_suffix(cites: list[int]) -> str` → `" [3][7]"`

- [ ] **Step 1: Write `style.py`** (geometry measured from `Johnson’s (Baby) _May 2026.pptx` slides 6/7/16)

```python
"""Hunter house style, measured from the Johnson's (Baby) reference deck. Light backgrounds only."""
SLIDE_W, SLIDE_H = 13.333, 7.5
VIOLET = "5B2C9D"        # titles, kicker, peak highlight
BODY = "404040"
WHITE = "FFFFFF"
HEADER_BAND = "FFF6F1"   # replaces the reference deck's grey F2F2F2 (spec §5)
FOOTER_BAND = "F3EEF9"
FOOTER_TEXT = "8866AA"
CARD_FILL = "FBF8FE"
CARD_LINE = "E4DAF3"
LAVENDER, PEACH, POWDER_BLUE, MINT = "8F74CC", "C8643F", "3E86B8", "2E8B74"
PALETTE = [LAVENDER, PEACH, POWDER_BLUE, MINT]
FONT = "Arial"
HEADER_H = 1.35
KICKER_PT, TITLE_PT, SUMMARY_PT, BODY_PT, CARD_HEAD_PT, FOOTER_PT = 12, 24, 10.5, 9, 11, 7
FOOTER_Y, FOOTER_H = 7.26, 0.24
MARGIN = 0.45
```

- [ ] **Step 2: Write the failing tests**

`agent/tests/test_deliverable_blocks.py`:
```python
from pptx import Presentation
from pptx.util import Inches

from agent.app.domains.deliverable import blocks, style


def _prs():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(style.SLIDE_W), Inches(style.SLIDE_H)
    return prs


def test_header_footer_use_light_fills_and_text():
    s = blocks.new_content_slide(_prs())
    blocks.add_header(s, "Category - Editorial", "Coverage Mix", "Summary text")
    blocks.add_footer(s, "SOURCE: MELTWATER | OCT 2025 – OCT 2026", 778)
    fills = {str(sh.fill.fore_color.rgb) for sh in s.shapes if sh.shape_type == 1 and sh.fill.type == 1}
    assert {style.HEADER_BAND, style.FOOTER_BAND} <= fills
    text = " ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame)
    assert "Coverage Mix" in text and "N=778" in text
    assert str(s.background.fill.fore_color.rgb) == style.WHITE


def test_column_chart_highlights_peaks():
    s = blocks.new_content_slide(_prs())
    chart = blocks.add_column_chart(s, 0.5, 1.5, 6, 3, ["a", "b", "c"], [1, 5, 2], {1})
    pts = chart.plots[0].series[0].points
    assert str(pts[1].format.fill.fore_color.rgb) == style.VIOLET
    assert str(pts[0].format.fill.fore_color.rgb) == style.LAVENDER
    assert chart.plots[0].has_data_labels


def test_line_chart_marks_peaks_in_violet():
    s = blocks.new_content_slide(_prs())
    chart = blocks.add_line_chart_with_peaks(s, 0.5, 1.5, 12, 3, ["m1", "m2", "m3"], [3, 9, 4], {1})
    pt = chart.plots[0].series[0].points[1]
    assert str(pt.marker.format.fill.fore_color.rgb) == style.VIOLET
    assert pt.data_label.show_value is True


def test_citation_suffix_and_cards():
    assert blocks.citation_suffix([3, 7]) == " [3][7]"
    s = blocks.new_content_slide(_prs())
    blocks.add_insight_cards(s, 0.5, 4.3, 12, 2.8, [{"headline": "H", "text": "T", "citations": [2]}], cols=1)
    assert any("T [2]" in sh.text_frame.text for sh in s.shapes if sh.has_text_frame)
```

- [ ] **Step 3: Run to verify fail.**

- [ ] **Step 4: Implement `blocks.py`**

```python
"""python-pptx building blocks in the Hunter style (light backgrounds only)."""
from __future__ import annotations

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from . import style


def _rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


def citation_suffix(cites: list[int]) -> str:
    return " " + "".join(f"[{c}]" for c in cites) if cites else ""


def new_content_slide(prs):
    layout = next(l for l in prs.slide_layouts if l.name == "Blank")
    slide = prs.slides.add_slide(layout)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(style.WHITE)
    return slide


def _rect(slide, x, y, w, h, fill: str, line: str | None = None, shape=MSO_SHAPE.RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = _rgb(fill)
    if line:
        sh.line.color.rgb = _rgb(line)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def add_text(slide, x, y, w, h, text: str, size: float, bold=False, color=style.BODY,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name, r.font.size, r.font.bold = style.FONT, Pt(size), bold
        r.font.color.rgb = _rgb(color)
    return tb


def add_header(slide, kicker: str, title: str, summary: str):
    _rect(slide, 0, 0, style.SLIDE_W, style.HEADER_H, style.HEADER_BAND)
    add_text(slide, style.MARGIN, 0.15, 5.7, 0.35, kicker, style.KICKER_PT, True, style.VIOLET)
    add_text(slide, style.MARGIN, 0.5, 5.7, 0.8, title, style.TITLE_PT, True, "1F1F1F")
    add_text(slide, 6.35, 0.18, 6.55, 1.05, summary, style.SUMMARY_PT, True, style.BODY, anchor=MSO_ANCHOR.MIDDLE)


def add_footer(slide, source: str, base_n: int):
    _rect(slide, 0, style.FOOTER_Y, style.SLIDE_W, style.FOOTER_H, style.FOOTER_BAND)
    add_text(slide, 0.27, style.FOOTER_Y + 0.01, 6.5, 0.22, source.upper(), style.FOOTER_PT, False, style.FOOTER_TEXT)
    add_text(slide, 7.0, style.FOOTER_Y + 0.01, 6.1, 0.22,
             f"Base: N={base_n} unique articles collected (Meltwater + manual extraction)",
             style.FOOTER_PT, False, style.FOOTER_TEXT, align=PP_ALIGN.RIGHT)


def _chart(slide, kind, x, y, w, h, categories, values, number_format):
    data = CategoryChartData(number_format=number_format)
    data.categories = categories
    data.add_series("Articles", values)
    chart = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
    chart.has_legend = False
    chart.font.name, chart.font.size = style.FONT, Pt(9)
    chart.font.color.rgb = _rgb(style.BODY)
    return chart


def _style_axes(chart):
    chart.value_axis.visible = False
    chart.value_axis.has_major_gridlines = False
    chart.category_axis.format.line.color.rgb = _rgb(style.CARD_LINE)
    chart.category_axis.tick_labels.font.size = Pt(9)


def _labels(plot, number_format):
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = number_format, False
    dl.font.size, dl.font.name = Pt(9), style.FONT
    dl.font.color.rgb = _rgb(style.BODY)
    return dl


def add_column_chart(slide, x, y, w, h, categories, values, highlight_idx, number_format="0"):
    chart = _chart(slide, XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, w, h, categories, values, number_format)
    _style_axes(chart)
    plot = chart.plots[0]
    plot.gap_width = 60
    _labels(plot, number_format).position = XL_LABEL_POSITION.OUTSIDE_END
    for i, pt in enumerate(plot.series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(style.VIOLET if i in highlight_idx else style.LAVENDER)
    return chart


def add_bar_chart(slide, x, y, w, h, categories, values, color=style.LAVENDER, number_format="0"):
    pairs = list(zip(categories, values))[::-1]          # PowerPoint draws bars bottom-up; largest on top
    chart = _chart(slide, XL_CHART_TYPE.BAR_CLUSTERED, x, y, w, h, [c for c, _ in pairs], [v for _, v in pairs],
                   number_format)
    _style_axes(chart)
    plot = chart.plots[0]
    plot.gap_width = 50
    _labels(plot, number_format).position = XL_LABEL_POSITION.OUTSIDE_END
    plot.series[0].format.fill.solid()
    plot.series[0].format.fill.fore_color.rgb = _rgb(color)
    return chart


def add_line_chart_with_peaks(slide, x, y, w, h, categories, values, peak_idx):
    chart = _chart(slide, XL_CHART_TYPE.LINE_MARKERS, x, y, w, h, categories, values, "0")
    _style_axes(chart)
    series = chart.plots[0].series[0]
    series.smooth = True
    series.format.line.color.rgb = _rgb(style.POWDER_BLUE)
    series.format.line.width = Pt(2)
    series.marker.style = XL_MARKER_STYLE.NONE
    for i in peak_idx:
        pt = series.points[i]
        pt.marker.style, pt.marker.size = XL_MARKER_STYLE.CIRCLE, 9
        pt.marker.format.fill.solid()
        pt.marker.format.fill.fore_color.rgb = _rgb(style.VIOLET)
        pt.marker.format.line.color.rgb = _rgb(style.VIOLET)
        dl = pt.data_label
        dl.show_value, dl.position = True, XL_LABEL_POSITION.ABOVE
        dl.font.bold, dl.font.size = True, Pt(10)
        dl.font.color.rgb = _rgb(style.VIOLET)
    return chart


def add_doughnut(slide, x, y, w, h, categories, values, number_format='0.0"%"'):
    chart = _chart(slide, XL_CHART_TYPE.DOUGHNUT, x, y, w, h, categories, values, number_format)
    chart.has_legend = True
    chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.RIGHT, False
    chart.legend.font.size = Pt(9)
    plot = chart.plots[0]
    _labels(plot, number_format)
    for i, pt in enumerate(plot.series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(style.PALETTE[i % len(style.PALETTE)])
    return chart


def _card(slide, x, y, w, h):
    card = _rect(slide, x, y, w, h, style.CARD_FILL, style.CARD_LINE, MSO_SHAPE.ROUNDED_RECTANGLE)
    card.adjustments[0] = 0.06
    return card


def add_insight_cards(slide, x, y, w, h, insights: list[dict], cols: int):
    if not insights:
        return
    gap = 0.15
    rows = -(-len(insights) // cols)
    cw, ch = (w - gap * (cols - 1)) / cols, (h - gap * (rows - 1)) / rows
    for i, ins in enumerate(insights):
        cx, cy = x + (i % cols) * (cw + gap), y + (i // cols) * (ch + gap)
        _card(slide, cx, cy, cw, ch)
        add_text(slide, cx + 0.15, cy + 0.08, cw - 0.3, 0.4, ins["headline"], style.CARD_HEAD_PT, True, style.VIOLET)
        add_text(slide, cx + 0.15, cy + 0.5, cw - 0.3, ch - 0.58,
                 ins["text"] + citation_suffix(ins["citations"]), style.BODY_PT)


def add_kpi_tiles(slide, x, y, w, h, tiles: list[dict]):
    gap = 0.2
    tw = (w - gap * (len(tiles) - 1)) / len(tiles)
    for i, t in enumerate(tiles):
        tx = x + i * (tw + gap)
        _card(slide, tx, y, tw, h)
        add_text(slide, tx + 0.15, y + 0.12, tw - 0.3, 0.8, t["value"], 32, True, style.VIOLET, PP_ALIGN.CENTER)
        add_text(slide, tx + 0.15, y + 0.95, tw - 0.3, 0.4, t["label"], 11, True, "1F1F1F", PP_ALIGN.CENTER)
        add_text(slide, tx + 0.15, y + 1.38, tw - 0.3, h - 1.48, t["note"], style.BODY_PT, False, style.BODY,
                 PP_ALIGN.CENTER)


def add_table(slide, x, y, w, h, header: list[str], rows: list[list[str]], col_widths: list[float]):
    table = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w), Inches(h)).table
    for j, cw in enumerate(col_widths):
        table.columns[j].width = Inches(cw)
    for r, values in enumerate([header] + rows):
        for c, v in enumerate(values):
            cell = table.cell(r, c)
            cell.text = str(v)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(style.FOOTER_BAND if r == 0 else (style.WHITE if r % 2 else style.CARD_FILL))
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.name, run.font.size, run.font.bold = style.FONT, Pt(9 if r == 0 else 8), r == 0
                    run.font.color.rgb = _rgb(style.VIOLET if r == 0 else style.BODY)
    return table
```

- [ ] **Step 5: Run to verify pass.**

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/deliverable/style.py agent/app/domains/deliverable/blocks.py agent/tests/test_deliverable_blocks.py
git commit -m "feat(deliverable): Hunter light-theme slide blocks with peak-highlighted native charts"
```

---

### Task 6: amCharts gauge (brand-affiliation %)

**Files:**
- Create: `agent/app/domains/deliverable/gauge.py`
- Test: append to `agent/tests/test_deliverable_blocks.py`

**Interfaces:**
- Produces: `gauge.gauge_html(value: float, label: str) -> str`; `gauge.render_gauge_png(value: float, label: str, out_path: Path) -> Path` (Playwright Chromium, 900×560 CSS px at 2× scale, white background)

- [ ] **Step 1: Write the failing test** (append)

```python
from agent.app.domains.deliverable import gauge


def test_gauge_html_embeds_value_and_light_background():
    html = gauge.gauge_html(37.5, "Brand-affiliated experts")
    assert "37.5" in html and "Brand-affiliated experts" in html
    assert "cdn.amcharts.com/lib/5/index.js" in html
    assert "#FFFFFF" in html.upper()
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `gauge.py`**

```python
"""amCharts 5 gauge rendered locally to PNG (native PPTX charts can't draw a gauge)."""
from __future__ import annotations

import json
from pathlib import Path

from . import style


def gauge_html(value: float, label: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.amcharts.com/lib/5/index.js"></script>
<script src="https://cdn.amcharts.com/lib/5/xy.js"></script>
<script src="https://cdn.amcharts.com/lib/5/radar.js"></script>
<style>html,body{{margin:0;background:#FFFFFF}}#c{{width:900px;height:560px}}</style></head>
<body><div id="c"></div><script>
const root = am5.Root.new("c");
const chart = root.container.children.push(am5radar.RadarChart.new(root, {{startAngle:180, endAngle:360, innerRadius:-28}}));
const axis = chart.xAxes.push(am5xy.ValueAxis.new(root, {{min:0, max:100, strictMinMax:true,
  renderer: am5radar.AxisRendererCircular.new(root, {{strokeOpacity:0}})}}));
axis.get("renderer").labels.template.setAll({{fontSize:18, fill:am5.color(0x{style.BODY})}});
const band = axis.createAxisRange(axis.makeDataItem({{value:0, endValue:100}}));
band.get("axisFill").setAll({{visible:true, fill:am5.color(0x{style.FOOTER_BAND}), fillOpacity:1}});
const fill = axis.createAxisRange(axis.makeDataItem({{value:0, endValue:{json.dumps(value)}}}));
fill.get("axisFill").setAll({{visible:true, fill:am5.color(0x{style.VIOLET}), fillOpacity:1}});
chart.radarContainer.children.push(am5.Label.new(root, {{text:"{value:g}%", fontSize:64, fontWeight:"700",
  fill:am5.color(0x{style.VIOLET}), centerX:am5.p50, centerY:am5.p100}}));
chart.children.push(am5.Label.new(root, {{text:{json.dumps(label)}, fontSize:22, fill:am5.color(0x{style.BODY}),
  x:am5.p50, centerX:am5.p50, y:am5.percent(88)}}));
root.events.once("frameended", () => {{ document.body.dataset.ready = "1"; }});
</script></body></html>"""


def render_gauge_png(value: float, label: str, out_path: Path) -> Path:
    from playwright.sync_api import sync_playwright
    out_path = Path(out_path)
    html_path = out_path.with_suffix(".html")
    html_path.write_text(gauge_html(value, label), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 560}, device_scale_factor=2)
        page.goto(html_path.as_uri())
        page.wait_for_selector("body[data-ready='1']", timeout=20000)
        page.wait_for_timeout(800)
        page.locator("#c").screenshot(path=str(out_path))
        browser.close()
    return out_path
```

- [ ] **Step 4: Run to verify pass, then smoke-render once**

```bash
PY -m pytest agent/tests/test_deliverable_blocks.py -v
PY -c "from pathlib import Path; from agent.app.domains.deliverable.gauge import render_gauge_png; print(render_gauge_png(37.5,'test',Path('C:/Users/KHADAR~1.SYE/AppData/Local/Temp/gauge.png')))"
```
If Chromium is missing: `PY -m playwright install chromium`, then retry. Open the PNG: a half-ring gauge reading "37.5%" on white. (The free amCharts build shows a small amCharts logo — acceptable for the reference deck; licence is an open item in the engine spec.)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/gauge.py agent/tests/test_deliverable_blocks.py
git commit -m "feat(deliverable): amCharts 5 gauge rendered locally via Playwright"
```

---

### Task 7: Deck assembly (17 slides) + paginated citations

**Files:**
- Create: `agent/app/domains/deliverable/deck.py`
- Test: `agent/tests/test_deliverable_deck.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces:
  - `deck.paginate(entries: list, per_page: int) -> list[list]`
  - `deck.keep_cover_and_closing(prs) -> None` (removes every slide except the first and last)
  - `deck.build_deck(cfg: dict, m: dict, cm: dict, ins: dict[str, list[dict]], registry: CitationRegistry, articles_by_url: dict[str, Article], logos: dict[str, Path | None], gauge_png: Path | None, out_path: Path) -> Path`
  - `ins` keys: `exec, mix, deal, parenting, expert, celebrity, brands, takeaways, implications`
  - `cm` must additionally carry `cm["expert"]["named"]: list[list[str]]` (Expert, Type, Affiliation, Outlet, Cite) and `cm["parenting"]["rows"]: list[list[str]]` (Article, Topic, Outlet, Cite) — prepared by the CLI in Task 8.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_deliverable_deck.py`:
```python
from datetime import date
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from agent.app.domains.deliverable import deck, style
from agent.app.domains.deliverable.citations import CitationRegistry
from agent.app.domains.deliverable.ingest import Article


def test_paginate():
    assert deck.paginate(list(range(45)), 20) == [list(range(20)), list(range(20, 40)), list(range(40, 45))]
    assert deck.paginate([], 20) == [[]]


def _base(tmp_path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(style.SLIDE_W), Inches(style.SLIDE_H)
    for t in ("COVER TITLE", "middle", "THANK YOU"):
        prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = t
    p = tmp_path / "base.pptx"
    prs.save(p)
    return p


def _theme():
    return {"count": 3, "share": 100.0, "date_min": "2026-01-01", "date_max": "2026-03-31",
            "monthly": [{"month": "2026-01", "count": 2}, {"month": "2026-02", "count": 0},
                        {"month": "2026-03", "count": 1}],
            "peaks": [{"month": "2026-01", "count": 2, "rank": 1, "top_urls": ["u1"]}],
            "outlets": [{"outlet": "A", "count": 2}], "sentiment": {"positive": 2, "neutral": 1}}


def _inputs(tmp_path, n_citations=1):
    reg = CitationRegistry()
    arts = {}
    for i in range(n_citations):
        a = Article(url=f"https://u{i}", norm_url=f"u{i}", title="T", date=date(2026, 1, 2), outlet="A", text="",
                    sentiment="positive", reach=0, themes={"deal"})
        reg.cite(a)
        arts[a.norm_url] = a
    ins = {k: [{"headline": "H", "text": "T", "citations": [1]}] for k in
           ("exec", "mix", "deal", "parenting", "expert", "celebrity", "brands", "takeaways", "implications")}
    m = {"base_n": 3, "multi_theme": 0, "themes": {k: _theme() for k in ("deal", "parenting", "expert", "celebrity")}}
    cm = {"expert": {"type_counts": {"dermatologist": 2}, "experts_total": 2, "type_unknown": 0, "affiliated_pct": 50.0,
                     "affiliated_n": 1, "affiliation_known_n": 2, "affiliation_unknown": 0, "affiliated_brands": [],
                     "articles_with_expert": 1, "named": [["Dr A", "dermatologist", "affiliated (X)", "A", "[1]"]]},
          "celebrity": {"top": [{"name": "C", "count": 1}], "roles": {}},
          "deal": {"retailers": [{"retailer": "R", "count": 1}], "deal_types": {}},
          "parenting": {"topics": {"sun_safety": 1}, "rows": [["Sun tips", "sun safety", "A", "[1]"]]},
          "brands": [{"brand": "X", "count": 1}]}
    cfg = {"title": "Baby Skincare Category", "subtitle": "Earned Editorial Analysis",
           "period_label": "Oct 2025 – Oct 2026", "date_label": "October 2026", "geography": "US",
           "brief_questions": ["q1", "q2", "q3", "q4"], "reference_deck": str(_base(tmp_path)),
           "themes": [{"key": k, "label": k.title()} for k in ("deal", "parenting", "expert", "celebrity")]}
    return cfg, m, cm, ins, reg, arts


def _slide_text(slide) -> str:
    parts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
    parts += [c.text for sh in slide.shapes if sh.has_table for r in sh.table.rows for c in r.cells]
    return " ".join(parts)


def test_build_deck_structure(tmp_path):
    cfg, m, cm, ins, reg, arts = _inputs(tmp_path)
    out = deck.build_deck(cfg, m, cm, ins, reg, arts, {}, None, tmp_path / "out.pptx")
    prs = Presentation(out)
    assert len(prs.slides) == 17
    assert "Baby Skincare Category" in _slide_text(prs.slides[0])
    assert "THANK YOU" in _slide_text(prs.slides[-1])
    assert "https://u0" in _slide_text(prs.slides[15])
    for s in list(prs.slides)[1:-1]:
        assert str(s.background.fill.fore_color.rgb) == style.WHITE


def test_citation_appendix_paginates(tmp_path):
    cfg, m, cm, ins, reg, arts = _inputs(tmp_path, n_citations=40)
    prs = Presentation(deck.build_deck(cfg, m, cm, ins, reg, arts, {}, None, tmp_path / "out.pptx"))
    assert len(prs.slides) == 19                      # 18 per page → 3 citation slides
    assert "THANK YOU" in _slide_text(prs.slides[-1])
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `deck.py`**

```python
"""Assemble the Baby Skincare reference deck on top of the Hunter base deck."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from . import blocks, style
from .citations import CitationRegistry
from .metrics import month_label

CITES_PER_PAGE = 18


def paginate(entries: list, per_page: int) -> list[list]:
    return [entries[i:i + per_page] for i in range(0, len(entries), per_page)] or [[]]


def keep_cover_and_closing(prs) -> None:
    ids = prs.slides._sldIdLst
    for sld in list(ids)[1:-1]:
        prs.part.drop_rel(sld.rId)
        ids.remove(sld)


def _move_to_end(prs, index: int) -> None:
    ids = prs.slides._sldIdLst
    el = list(ids)[index]
    ids.remove(el)
    ids.append(el)


def _replace_text(shape, lines: list[str]) -> None:
    tf = shape.text_frame
    first = tf.paragraphs[0].runs[0] if tf.paragraphs[0].runs else None
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    if first is None:
        tf.paragraphs[0].add_run().text = lines[0]
    else:
        first.text = lines[0]
        for r in list(tf.paragraphs[0].runs)[1:]:
            r._r.getparent().remove(r._r)
    for line in lines[1:]:
        r = tf.add_paragraph().add_run()
        r.text = line
        if first is not None:
            r.font.name, r.font.size, r.font.bold = first.font.name, first.font.size, False
            if first.font.color and first.font.color.type is not None:
                r.font.color.rgb = first.font.color.rgb


def _set_cover(slide, title: str, subtitle: str, date_label: str) -> None:
    boxes = [sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    for sh in boxes:
        txt = sh.text_frame.text.strip()
        low = txt.lower()
        if "©" in txt or "infovision" in low or "invision" in low:
            continue
        if any(ch.isdigit() for ch in txt) and len(txt) < 20:
            _replace_text(sh, [date_label])
    title_box = max((sh for sh in boxes if not any(ch.isdigit() for ch in sh.text_frame.text)
                     and "©" not in sh.text_frame.text), key=lambda sh: sh.width * sh.height, default=None)
    if title_box is not None:
        _replace_text(title_box, [title, subtitle] if subtitle else [title])


def _source(cfg, theme_metrics=None) -> str:
    if theme_metrics and theme_metrics.get("date_min"):
        return (f"SOURCE: MELTWATER  |  {month_label(theme_metrics['date_min'][:7])} – "
                f"{month_label(theme_metrics['date_max'][:7])}")
    return f"SOURCE: MELTWATER  |  {cfg['period_label']}"


def _content(prs, cfg, m, kicker, title, summary, theme_metrics=None):
    s = blocks.new_content_slide(prs)
    blocks.add_header(s, kicker, title, summary)
    blocks.add_footer(s, _source(cfg, theme_metrics), m["base_n"])
    return s


def _summary(ins: list[dict]) -> str:
    return ins[0]["text"] + blocks.citation_suffix(ins[0]["citations"]) if ins else ""


def _peak_callout(t: dict, registry: CitationRegistry, articles_by_url: dict) -> str:
    parts = []
    for p in t["peaks"]:
        cite = next((f" [{registry.cite(articles_by_url[u])}]" for u in p["top_urls"] if u in articles_by_url), "")
        parts.append(f"#{p['rank']} {month_label(p['month'])}: {p['count']}{cite}")
    return "Top-5 peaks — " + "; ".join(parts) if parts else ""


def _trend_slide(prs, cfg, m, key, label, ins, side_bars: list[dict], side_title: str,
                 registry: CitationRegistry, articles_by_url: dict):
    t = m["themes"][key]
    s = _content(prs, cfg, m, f"{cfg['title']} - Editorial", f"{label}: Volume & Peaks", _summary(ins), t)
    cats = [month_label(x["month"]) for x in t["monthly"]]
    vals = [x["count"] for x in t["monthly"]]
    peak_months = {p["month"] for p in t["peaks"]}
    if cats:
        blocks.add_line_chart_with_peaks(s, 0.4, 1.45, 8.2, 2.5, cats, vals,
                                         {i for i, x in enumerate(t["monthly"]) if x["month"] in peak_months})
    blocks.add_text(s, 0.45, 3.98, 8.1, 0.35, _peak_callout(t, registry, articles_by_url), 9, True, style.VIOLET)
    blocks.add_text(s, 7.3, 1.5, 1.3, 0.3, f"N = {t['count']}", 11, True)
    bars = side_bars or [{"name": o["outlet"], "count": o["count"]} for o in t["outlets"][:6]]
    blocks.add_text(s, 8.9, 1.45, 4.0, 0.3, side_title, 10, True, style.VIOLET)
    if bars:
        blocks.add_bar_chart(s, 8.8, 1.75, 4.2, 2.5, [b["name"] for b in bars], [b["count"] for b in bars], style.PEACH)
    blocks.add_insight_cards(s, 0.4, 4.4, 12.5, 2.75, ins[1:4] or ins, cols=3)
    return s


def build_deck(cfg, m, cm, ins, registry: CitationRegistry, articles_by_url, logos, gauge_png, out_path) -> Path:
    prs = Presentation(cfg["reference_deck"])
    keep_cover_and_closing(prs)
    _set_cover(prs.slides[0], cfg["title"], cfg.get("subtitle", ""), cfg["date_label"])
    labels = {t["key"]: t["label"] for t in cfg["themes"]}
    kicker = f"{cfg['title']} - Editorial"
    share_line = (f"Share of collected category coverage (N={m['base_n']} unique articles, "
                  f"Meltwater + manual extraction, {cfg['period_label']}).")

    # 2 Contents
    s = _content(prs, cfg, m, kicker, "Contents", "")
    blocks.add_text(s, 0.8, 1.7, 11.5, 5.3, "\n".join([
        "1. Objective & Scope", "2. Executive Summary", "3. Coverage Mix", "4. Deal / Sale-led Coverage",
        "5. Parenting Advice", "6. Expert-led Coverage", "7. Celebrity-led Coverage", "8. Brands in the Conversation",
        "9. Key Takeaways & Implications", "10. Appendix: Methodology & Citations"]), 18, False, "1F1F1F")
    # 3 Objective & scope
    s = _content(prs, cfg, m, kicker, "Objective & Scope", "Earned editorial coverage of the baby skincare category.")
    blocks.add_text(s, 0.6, 1.7, 7.4, 4.0, "Questions from the brief:\n" +
                    "\n".join(f"• {q}" for q in cfg["brief_questions"]), 13, False, "1F1F1F")
    blocks.add_text(s, 8.3, 1.7, 4.6, 4.0, f"Geography: {cfg['geography']}\nTime period: {cfg['period_label']}\n"
                    f"Sources: Meltwater exports + manual extraction\nBase: N={m['base_n']} unique articles "
                    f"({m['multi_theme']} appear in two themes)", 12, True, style.VIOLET)
    # 4 Executive summary
    s = _content(prs, cfg, m, kicker, "Executive Summary", share_line)
    order = ("deal", "parenting", "expert", "celebrity")
    blocks.add_kpi_tiles(s, 0.5, 1.55, 12.3, 2.25, [
        {"value": f"{m['themes'][k]['share']}%", "label": labels[k],
         "note": f"{m['themes'][k]['count']} of {m['base_n']} articles"} for k in order])
    blocks.add_insight_cards(s, 0.5, 3.95, 12.3, 3.2, ins["exec"][:4], cols=2)
    # 5 Coverage mix
    s = _content(prs, cfg, m, kicker, "Coverage Mix", share_line)
    keys = ("celebrity", "deal", "expert", "parenting")
    blocks.add_doughnut(s, 0.4, 1.45, 5.6, 3.0, [labels[k] for k in keys], [m["themes"][k]["share"] for k in keys])
    blocks.add_text(s, 0.4, 4.45, 5.6, 0.3, "Shares can sum to more than 100%: an article can carry two themes.", 8)
    blocks.add_bar_chart(s, 6.4, 1.45, 6.5, 3.0, [labels[k] for k in keys], [m["themes"][k]["count"] for k in keys])
    blocks.add_insight_cards(s, 0.4, 4.85, 12.5, 2.3, ins["mix"][:3], cols=3)
    # 6 Deal-led
    _trend_slide(prs, cfg, m, "deal", labels["deal"], ins["deal"],
                 [{"name": r["retailer"], "count": r["count"]} for r in cm["deal"]["retailers"][:6]], "Top retailers",
                 registry, articles_by_url)
    # 7 Parenting advice
    s = _content(prs, cfg, m, kicker, "Parenting Advice", _summary(ins["parenting"]), m["themes"]["parenting"])
    blocks.add_text(s, 0.5, 1.42, 12, 0.3, f"Small sample: n={m['themes']['parenting']['count']} articles — "
                    "read as directional.", 9, True, style.PEACH)
    rows = cm["parenting"]["rows"][:14]
    if rows:
        blocks.add_table(s, 0.5, 1.8, 7.6, 0.3 * (len(rows) + 1), ["Article", "Topic", "Outlet", "Cite"], rows,
                         [4.2, 1.4, 1.4, 0.6])
    blocks.add_insight_cards(s, 8.4, 1.8, 4.5, 5.3, ins["parenting"][1:3] or ins["parenting"], cols=1)
    # 8 Expert: who is cited
    e = cm["expert"]
    s = _content(prs, cfg, m, kicker, "Expert-led: Who Is Cited", _summary(ins["expert"]), m["themes"]["expert"])
    if e["type_counts"]:
        blocks.add_doughnut(s, 0.4, 1.45, 5.2, 3.2, [k.replace("_", " ").title() for k in e["type_counts"]],
                            list(e["type_counts"].values()), "0")
    if gauge_png and Path(gauge_png).exists():
        s.shapes.add_picture(str(gauge_png), Inches(5.8), Inches(1.45), Inches(3.4))
    blocks.add_text(s, 5.8, 3.75, 3.4, 0.8, f"Brand-affiliated: {e['affiliated_n']} of {e['affiliation_known_n']} "
                    f"experts with a stated affiliation ({e['affiliation_unknown']} not stated)", 9)
    outlets = m["themes"]["expert"]["outlets"][:6]
    if outlets:
        blocks.add_bar_chart(s, 9.4, 1.45, 3.6, 3.2, [o["outlet"] for o in outlets], [o["count"] for o in outlets],
                             style.MINT)
    blocks.add_insight_cards(s, 0.4, 4.85, 12.5, 2.3, ins["expert"][1:4] or ins["expert"], cols=3)
    # 9 Expert: named experts
    s = _content(prs, cfg, m, kicker, "Expert-led: Named Experts",
                 "Experts quoted or cited, with their stated brand affiliation.", m["themes"]["expert"])
    named = e.get("named", [])[:16]
    if named:
        blocks.add_table(s, 0.5, 1.55, 12.3, 0.32 * (len(named) + 1), ["Expert", "Type", "Affiliation", "Outlet", "Cite"],
                         named, [3.0, 2.2, 3.0, 3.3, 0.8])
    # 10 Celebrity: volume & peaks
    _trend_slide(prs, cfg, m, "celebrity", labels["celebrity"], ins["celebrity"],
                 [{"name": c["name"], "count": c["count"]} for c in cm["celebrity"]["top"][:6]],
                 "Most-featured celebrities", registry, articles_by_url)
    # 11 Celebrity: sentiment drivers
    t = m["themes"]["celebrity"]
    s = _content(prs, cfg, m, kicker, "Celebrity-led: Sentiment Drivers", _summary(ins["celebrity"]), t)
    if t["sentiment"]:
        sk = [k for k in ("positive", "neutral", "negative") if k in t["sentiment"]]
        total = sum(t["sentiment"][k] for k in sk)
        blocks.add_doughnut(s, 0.4, 1.45, 4.8, 3.2, [k.title() for k in sk],
                            [round(100 * t["sentiment"][k] / total, 1) for k in sk])
    blocks.add_insight_cards(s, 5.4, 1.45, 7.5, 5.7, ins["celebrity"][4:8] or ins["celebrity"][:2], cols=2)
    # 12 Brands
    s = _content(prs, cfg, m, kicker, "Brands in the Conversation", _summary(ins["brands"]))
    brands = cm["brands"][:8]
    if brands:
        blocks.add_bar_chart(s, 1.6, 1.45, 6.4, 5.6, [b["brand"] for b in brands], [b["count"] for b in brands])
        step = 5.6 / len(brands)
        for i, b in enumerate(brands):
            logo = logos.get(b["brand"])
            if logo and Path(logo).exists():
                s.shapes.add_picture(str(logo), Inches(0.5), Inches(1.55 + i * step),
                                     height=Inches(min(0.5, step * 0.75)))
    blocks.add_insight_cards(s, 8.3, 1.45, 4.6, 5.7, ins["brands"][1:3] or ins["brands"], cols=1)
    # 13 Key takeaways
    s = _content(prs, cfg, m, kicker, "Key Takeaways", "")
    blocks.add_insight_cards(s, 0.4, 1.45, 12.5, 5.7, ins["takeaways"][:6], cols=3)
    # 14 Implications
    s = _content(prs, cfg, m, kicker, "Implications: Consumer Intent & Whitespace", "")
    blocks.add_insight_cards(s, 0.4, 1.45, 12.5, 5.7, ins["implications"][:4], cols=2)
    # 15 Methodology
    s = _content(prs, cfg, m, "Appendix", "Definitions & Methodology", "")
    blocks.add_text(s, 0.6, 1.55, 12, 5.5, "\n\n".join([
        f"Base: union of the four theme exports, de-duplicated by URL — N={m['base_n']} unique articles; "
        f"{m['multi_theme']} articles appear in two themes, so theme shares can sum to more than 100%.",
        "Shares reflect the collected theme exports; each export's breadth depends on its query, so shares are "
        "not a census of all category coverage.",
        "Date ranges differ by theme; each trend slide states its own range. Peaks are the five months with the "
        "most articles.",
        "Expert type, brand affiliation, celebrities, retailers and topics were labelled from article text by an AI "
        "model with a fixed label set; anything the text does not state is reported as 'not stated'.",
        "Every insight cites the numbered articles that support it; see the citation list.",
    ]), 11)
    # 16+ Citations (paginated)
    pages = paginate(registry.entries(), CITES_PER_PAGE)
    for pi, page in enumerate(pages, start=1):
        title = "Citations" + (f" ({pi}/{len(pages)})" if len(pages) > 1 else "")
        s = _content(prs, cfg, m, "Appendix", title, "")
        rows = [[f"[{c['n']}]", c["outlet"][:28], c["date"], c["title"][:70], c["url"][:80]] for c in page]
        if rows:
            blocks.add_table(s, 0.3, 1.5, 12.7, 0.3 * (len(rows) + 1), ["#", "Outlet", "Date", "Headline", "URL"],
                             rows, [0.5, 1.9, 1.0, 4.5, 4.8])
    # the closing slide sits at index 1 after pruning; move it to the end
    _move_to_end(prs, 1)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    return out_path
```

- [ ] **Step 4: Run to verify pass.** Fix `deck.py`, not the tests, if counts differ.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/deck.py agent/tests/test_deliverable_deck.py
git commit -m "feat(deliverable): assemble reference deck on Hunter base with paginated citations"
```

---

### Task 8: QC + CLI + real build

**Files:**
- Create: `agent/app/domains/deliverable/qc.py`, `agent/app/domains/deliverable/cli.py`
- Test: `agent/tests/test_deliverable_qc.py`

**Interfaces:**
- Produces:
  - `qc.estimate_overflow(text: str, width_in: float, height_in: float, font_pt: float) -> bool`
  - `qc.check_layout(pptx_path: Path) -> list[dict]` — `{"slide": int, "kind": "off_slide"|"overlap"|"overflow"|"dark_background", "detail": str}`
  - `qc.export_pngs(pptx_path: Path, out_dir: Path) -> list[Path]` (PowerPoint COM via PowerShell)
  - `cli.main(argv: list[str]) -> int`

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_deliverable_qc.py`:
```python
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches

from agent.app.domains.deliverable import blocks, qc, style


def test_overflow_estimate():
    assert qc.estimate_overflow("word " * 400, 2.0, 1.0, 9) is True
    assert qc.estimate_overflow("short text", 4.0, 1.0, 9) is False


def test_check_layout_flags_overlap_offslide_and_overflow(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(style.SLIDE_W), Inches(style.SLIDE_H)
    s = blocks.new_content_slide(prs)
    blocks.add_text(s, 1, 1, 3, 1, "A", 9)
    blocks.add_text(s, 2, 1.5, 3, 1, "B", 9)               # overlaps A
    blocks.add_text(s, 12.5, 7.0, 2, 1, "C", 9)             # off-slide
    blocks.add_text(s, 1, 4, 1.5, 0.4, "long " * 200, 9)    # overflow
    p = tmp_path / "q.pptx"
    prs.save(p)
    kinds = {i["kind"] for i in qc.check_layout(p)}
    assert {"overlap", "off_slide", "overflow"} <= kinds


def test_header_and_footer_pass_qc(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(style.SLIDE_W), Inches(style.SLIDE_H)
    s = blocks.new_content_slide(prs)
    blocks.add_header(s, "Kicker", "Title", "Summary")
    blocks.add_footer(s, "SOURCE", 778)
    p = tmp_path / "ok.pptx"
    prs.save(p)
    assert qc.check_layout(p) == []


def test_check_layout_flags_dark_background(tmp_path):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor(0x20, 0x20, 0x20)
    p = tmp_path / "d.pptx"
    prs.save(p)
    assert any(i["kind"] == "dark_background" for i in qc.check_layout(p))
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement `qc.py`**

```python
"""Layout QC: geometry checks on text boxes + PowerPoint PNG export for visual review."""
from __future__ import annotations

import subprocess
from pathlib import Path

from pptx import Presentation

EMU_PER_IN = 914400
CHAR_W_FACTOR = 0.5     # average Arial glyph width ≈ 0.5 × font size
LINE_H_FACTOR = 1.2
OVERLAP_EMU = 45720     # 0.05 in
DARK_LUMINANCE = 0.6
TEXT_BOX = 17


def estimate_overflow(text: str, width_in: float, height_in: float, font_pt: float) -> bool:
    chars_per_line = max(1, int((width_in * 72 - 14) / (font_pt * CHAR_W_FACTOR)))
    lines = sum(max(1, -(-len(p) // chars_per_line)) for p in text.split("\n"))
    return lines * font_pt * LINE_H_FACTOR > height_in * 72 - 7


def _luminance(hex_rgb: str) -> float:
    c = [int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _font_pt(shape) -> float:
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            if r.font.size:
                return r.font.size.pt
    return 12.0


def check_layout(pptx_path: Path) -> list[dict]:
    prs = Presentation(pptx_path)
    sw, sh_ = prs.slide_width, prs.slide_height
    issues = []
    for n, slide in enumerate(prs.slides, start=1):
        fill = slide.background.fill
        if fill.type == 1 and _luminance(str(fill.fore_color.rgb)) < DARK_LUMINANCE:
            issues.append({"slide": n, "kind": "dark_background", "detail": str(fill.fore_color.rgb)})
        for s in slide.shapes:
            if s.left is None:
                continue
            if s.left < 0 or s.top < 0 or s.left + s.width > sw + 9144 or s.top + s.height > sh_ + 9144:
                issues.append({"slide": n, "kind": "off_slide", "detail": s.name})
        boxes = [s for s in slide.shapes if s.shape_type == TEXT_BOX and s.text_frame.text.strip()]
        for b in boxes:
            if estimate_overflow(b.text_frame.text, b.width / EMU_PER_IN, b.height / EMU_PER_IN, _font_pt(b)):
                issues.append({"slide": n, "kind": "overflow", "detail": b.text_frame.text[:50]})
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                ox = min(a.left + a.width, b.left + b.width) - max(a.left, b.left)
                oy = min(a.top + a.height, b.top + b.height) - max(a.top, b.top)
                if ox > OVERLAP_EMU and oy > OVERLAP_EMU:
                    issues.append({"slide": n, "kind": "overlap",
                                   "detail": f"{a.text_frame.text[:25]!r} x {b.text_frame.text[:25]!r}"})
    return issues


def export_pngs(pptx_path: Path, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("slide_*.png"):
        old.unlink()
    src = str(Path(pptx_path).resolve()).replace("'", "''")
    dst = str(out_dir.resolve()).replace("'", "''")
    script = (
        "$pp=New-Object -ComObject PowerPoint.Application;"
        f"$p=$pp.Presentations.Open('{src}',$true,$false,$false);"
        "$i=1;foreach($s in $p.Slides){"
        f"$s.Export('{dst}\\slide_' + $i.ToString('00') + '.png','PNG',1600,900);$i++}};"
        "$p.Close();$pp.Quit()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=600)
    return sorted(out_dir.glob("slide_*.png"))
```

(The kicker/title boxes in `add_header` stack vertically at y 0.15–0.5 and 0.5–1.3, and the summary sits at x ≥ 6.35, so the header passes the overlap check — `test_header_and_footer_pass_qc` pins this. The reference deck's apostrophe in the path is handled by doubling `'` for PowerShell.)

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Implement `cli.py`**

```python
"""Build a reference deck from a deliverable project config.

Usage: python -m agent.app.domains.deliverable.cli agent/app/domains/deliverable/projects/baby_skincare.json
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import requests

from ...core.anthropic_client import get_llm_client
from ..research.brandfetch import resolve_logo
from . import classify, config, deck, gauge, ingest, insights, metrics, qc
from .citations import CitationRegistry

logger = logging.getLogger("deliverable")
THEMES = ("deal", "parenting", "expert", "celebrity")
MAX_CANDIDATES = 12


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _peak_articles(t: dict, by_url: dict) -> list:
    return [by_url[u] for p in t["peaks"] for u in p["top_urls"] if u in by_url]


def _theme_facts(key: str, label: str, m: dict, cm: dict) -> list[str]:
    t = m["themes"][key]
    facts = [f"{label} share of collected coverage is {t['share']}% ({t['count']} of {m['base_n']} articles)"]
    facts += [f"Peak {p['rank']}: {metrics.month_label(p['month'])} with {p['count']} articles" for p in t["peaks"]]
    facts += [f"Top outlet {o['outlet']} with {o['count']} articles" for o in t["outlets"][:5]]
    facts += [f"{k} sentiment: {v} articles" for k, v in t["sentiment"].items()]
    if key == "expert":
        e = cm["expert"]
        facts += [f"{k.replace('_', ' ')} cited {v} times" for k, v in e["type_counts"].items()]
        if e["affiliated_pct"] is not None:
            facts.append(f"{e['affiliated_pct']}% of experts with a stated affiliation are brand-affiliated "
                         f"({e['affiliated_n']} of {e['affiliation_known_n']})")
    if key == "celebrity":
        facts += [f"{c['name']} featured in {c['count']} articles" for c in cm["celebrity"]["top"][:6]]
    if key == "deal":
        facts += [f"Retailer {r['retailer']} in {r['count']} deal articles" for r in cm["deal"]["retailers"][:6]]
    if key == "parenting":
        facts += [f"Topic {k.replace('_', ' ')}: {v} articles" for k, v in cm["parenting"]["topics"].items()]
    return facts


def _download_logos(brands: list[dict], folder: Path) -> dict[str, Path | None]:
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path | None] = {}
    for b in brands:
        out[b["brand"]] = None
        info = resolve_logo(b["brand"])
        if not info.get("logo_url"):
            continue
        try:
            r = requests.get(info["logo_url"], timeout=20)
        except requests.RequestException as e:
            logger.warning("logo download failed for %s: %s", b["brand"], e)
            continue
        ctype = r.headers.get("content-type", "")
        if r.ok and ctype.startswith("image/") and "svg" not in ctype:
            p = folder / (re.sub(r"[^a-z0-9]+", "_", b["brand"].lower()) + ".png")
            p.write_bytes(r.content)
            out[b["brand"]] = p
    return out


def _table_rows(classified: dict, by_url: dict, registry: CitationRegistry) -> tuple[list, list]:
    named = []
    for u, rec in classified["expert"].items():
        for e in rec.get("experts", []):
            if not e["name"]:
                continue
            if e["affiliation"] == "affiliated":
                aff = f"affiliated ({e['brand']})" if e["brand"] else "affiliated"
            else:
                aff = "not stated" if e["affiliation"] == "unknown" else e["affiliation"]
            named.append([e["name"], e["expert_type"].replace("_", " "), aff, by_url[u].outlet,
                          f"[{registry.cite(by_url[u])}]"])
    parenting = [[by_url[u].title[:60],
                  ", ".join(t["topic"].replace("_", " ") for t in rec.get("topics", [])) or "not stated",
                  by_url[u].outlet, f"[{registry.cite(by_url[u])}]"] for u, rec in classified["parenting"].items()]
    return named, parenting


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config.load_config(argv[0])
    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = get_llm_client()
    if llm is None:
        logger.error("Azure OpenAI chat is not configured/reachable — stopping (spec: no invented labels).")
        return 2

    articles, ingest_stats = ingest.load_articles(cfg)
    by_url = {a.norm_url: a for a in articles}
    m = metrics.compute_metrics(articles, list(THEMES))
    m["ingest"] = ingest_stats
    _write_json(out_dir / "metrics.json", m)
    logger.info("Ingested %d unique articles %s", m["base_n"], ingest_stats)

    cache_path = out_dir / "classifications.json"
    cache = _load_json(cache_path)
    classified = {}
    for key in THEMES:
        classified[key] = classify.classify_theme([a for a in articles if key in a.themes], key, llm, cache)
        _write_json(cache_path, cache)
        logger.info("Classified %s: %d articles", key, len(classified[key]))
    cm = metrics.compute_classified_metrics(classified)

    registry = CitationRegistry()
    labels = {t["key"]: t["label"] for t in cfg["themes"]}
    ins: dict[str, list[dict]] = {}
    all_facts: list[str] = []
    for key in THEMES:
        facts = _theme_facts(key, labels[key], m, cm)
        all_facts += facts
        cands = (_peak_articles(m["themes"][key], by_url) or [a for a in articles if key in a.themes])[:MAX_CANDIDATES]
        ins[key] = insights.draft_section(labels[key], facts, cands, registry, llm,
                                          n_insights=8 if key == "celebrity" else 4)
    exec_cands = [a for k in THEMES for a in _peak_articles(m["themes"][k], by_url)[:2]]
    ins["exec"] = insights.draft_section("Executive summary: answer each brief question", all_facts, exec_cands,
                                         registry, llm, 4)
    ins["mix"] = insights.draft_section("Coverage mix across themes", all_facts, exec_cands, registry, llm, 3)
    brand_facts = [f"{b['brand']} mentioned in {b['count']} articles" for b in cm["brands"]]
    brand_cands = [by_url[u] for k in THEMES for u, rec in classified[k].items() if rec.get("brands")][:MAX_CANDIDATES]
    ins["brands"] = insights.draft_section("Brands in the conversation", brand_facts, brand_cands, registry, llm, 3)
    ins["takeaways"] = insights.draft_section("Key takeaways", all_facts + brand_facts, exec_cands, registry, llm, 6)
    ins["implications"] = insights.draft_section("Implications for consumer intent, messaging and whitespace",
                                                 all_facts + brand_facts, exec_cands, registry, llm, 4)
    cm["expert"]["named"], cm["parenting"]["rows"] = _table_rows(classified, by_url, registry)
    _write_json(out_dir / "insights.json", {"insights": ins, "citations": registry.entries()})

    logos = _download_logos(cm["brands"][:8], out_dir / "logos")
    gauge_png = None
    if cm["expert"]["affiliated_pct"] is not None:
        gauge_png = gauge.render_gauge_png(cm["expert"]["affiliated_pct"], "Brand-affiliated experts",
                                           out_dir / "gauge_affiliation.png")

    out = deck.build_deck(cfg, m, cm, ins, registry, by_url, logos, gauge_png, out_dir / cfg["output_name"])
    issues = qc.check_layout(out)
    _write_json(out_dir / "qc_issues.json", issues)
    pngs = qc.export_pngs(out, out_dir / "qc_png")
    logger.info("Deck: %s | slides exported: %d | QC issues: %d", out, len(pngs), len(issues))
    for i in issues:
        logger.warning("QC slide %s %s: %s", i["slide"], i["kind"], i["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 6: Run the full deliverable suite + existing suite**

```bash
PY -m pytest agent/tests/test_deliverable_ingest.py agent/tests/test_deliverable_metrics.py agent/tests/test_deliverable_classify.py agent/tests/test_deliverable_insights.py agent/tests/test_deliverable_blocks.py agent/tests/test_deliverable_deck.py agent/tests/test_deliverable_qc.py -v
PY -m pytest agent/tests/ -x -q --ignore=agent/tests/test_e2e_live_workflow.py
```
Expected: all PASS (no existing test regresses — the new package touches nothing outside `domains/deliverable/`).

- [ ] **Step 7: Real build**

Check Azure first:
```bash
PY -c "from agent.app.core.anthropic_client import get_llm_client; c=get_llm_client(); print(c and c.chat([{'role':'user','content':'Reply with the word ok'}]))"
```
Expected: prints `ok` (or similar). If `None`/error: stop and report — the spec forbids building without classification.
Then:
```bash
PY -m agent.app.domains.deliverable.cli agent/app/domains/deliverable/projects/baby_skincare.json
```
Expected log: `Ingested 778 unique articles`, four `Classified …` lines, `Deck: …Hunter PR Research_Baby Skincare Category_Editorial_Oct 2026.pptx | slides exported: ≥17 | QC issues: N`.

- [ ] **Step 8: Visual QC loop**

Read every `Baby-Skincare_Category/output/qc_png/slide_*.png`. For each entry in `qc_issues.json` and anything visibly wrong (clipped text, labels colliding, logo misaligned, empty card, missing `[n]`): fix geometry or text caps in `blocks.py` / `deck.py`, re-run Step 7 (classifications are cached, so only insights and rendering repeat). Done when `qc_issues.json` is `[]`, every insight shows `[n]`, every share slide shows the base line, and no slide background is dark or grey.

- [ ] **Step 9: Commit code only (never client data or output)**

```bash
git add agent/app/domains/deliverable/ agent/tests/test_deliverable_qc.py
git status --short   # confirm nothing under Baby-Skincare_Category/ or PPT Templates/ is staged
git commit -m "feat(deliverable): layout QC, PowerPoint PNG export and CLI that builds the reference deck"
```

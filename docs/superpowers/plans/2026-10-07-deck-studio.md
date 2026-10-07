# Deck Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the deliverable engine's computed findings into a brand-led HTML deck (plus pixel-perfect PPTX and PDF) whose layouts are learned from any reference decks, with full questions, logos beside labels, slide-matched photos and a "Did we answer the brief?" scorecard and checklist.

**Architecture:** A new `agent/app/domains/deckstudio/` package. An indexer learns slide types and design rules from `config.TEMPLATES_DIR`; a planner turns engine output plus the research spec's asks into a versioned slide spec (`DeckSpec`); an art director sets brand-led design tokens; an asset finder fetches photos and logos; a renderer turns the spec into one HTML deck (Jinja templates + inline SVG charts), optionally improved per slide by a guarded LLM creative pass; an exporter screenshots each slide into a PPTX and a PDF. The deliverable engine runs these as new stages after QC and the Deliverables page previews and downloads the result.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`core/db.py` migrations), python-pptx, Jinja2, Pillow, Playwright (Chromium), requests, Scrapling (fallback fetch), Azure OpenAI via `core.llm_provider`, React 18 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-07-deck-studio-design.md`

## Global Constraints

- Nothing organisation-specific in code or skill: design rules come from whatever decks are in `config.TEMPLATES_DIR`.
- Decks over 50 MB, `~$*` lock files and unreadable files are skipped by the indexer.
- Never copy text from a reference slide into output; only geometry and style patterns are reused.
- Full question text on slides; never "RQ1"-style codes on any slide.
- Look is fully brand-led (palette, typography, mood from the brand and project intent); agency wordmark on cover and closing only.
- Treatment by chart density: A (full-bleed photo + overlay + frosted panel) for KPI, doughnut, ≤ 6 bars, takeaways, scorecard; C (full-height photo panel, left 672 px of 1920) for trendlines, > 6 bars, tables; `full` for cover, dividers, closing; `plain` for checklist, methodology, citations.
- Photos: licensed (Pexels) and brand-owned first, SerpAPI fallback; no credit text on slides; source URL and licence class written to the run log.
- Logos sit beside the label they belong to.
- Every number on a slide must be in that slide's allowed facts (half-up rounding of decimals allowed).
- Every slide fits 1920 × 1080 with no overflow and no off-slide text.
- Secrets (`PEXEL_API_KEY`, `SERP_API_KEY`, `BRANDFETCH_API_KEY`, Azure keys) are never logged, cached or returned.
- Python: `C:/Users/khadar.syed/AppData/Local/Programs/Python/Python312/python.exe` (written `PY`). Tests: `PY -m pytest agent/tests/<file> -q -p no:cacheprovider`. `agent/tests` is git-ignored: never `git add` tests.
- Edits keep each file's line endings (CRLF files stay CRLF).

## Review Focus

1. A reference deck that is corrupted, huge, or all pictures — the indexer keeps going. (Task 2 `test_index_skips_broken_and_huge_decks`.)
2. No brand colours and no LLM — tokens still pass contrast and fonts are loadable. (Task 5 `test_fallback_tokens_without_brand_colours_pass_contrast`.)
3. No photo anywhere (offline) — slides get a token gradient, not an empty box. (Task 6 `test_no_photo_found_gives_gradient_background`, Task 7 renders `linear-gradient`.)
4. Very long questions or brand names — text clamps and the layout guard passes. (Task 7 `test_long_question_fits_the_slide`.)
5. A creative pass that invents a number or copies reference text — the slide falls back to its template. (Task 9 `test_creative_slide_with_invented_number_falls_back`, `test_copied_reference_text_falls_back`.)

---

### Task 1: Package, migration and repository

**Files:** Create `agent/app/domains/deckstudio/__init__.py` (docstring only), `agent/app/domains/deckstudio/repository.py`; Modify `agent/app/core/db.py` (append migration 20), `agent/app/core/store.py` (re-export), `agent/app/domains/deliverable/repository.py` (if `update_deliverable_run` whitelists columns, allow the four new ones); Test `agent/tests/test_deckstudio_repository.py`

**Interfaces — Produces:** `upsert_reference_deck(path, digest, family, n_slides) -> int`, `get_reference_deck(path) -> dict|None`, `list_reference_decks() -> list[dict]`, `delete_reference_deck(path) -> None`, `replace_reference_slides(deck_id, slides:list[dict]) -> None`, `list_reference_slides(slide_type=None) -> list[dict]` (each `{deck_id, deck_path, family, n, type, features}`); run columns `html_path, pdf_path, studio_pptx_path, deck_dir`.

- [ ] **Step 1: failing test**

```python
"""Reference deck library storage."""
from __future__ import annotations
import os, pathlib, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.core import store


def setup_module(_):
    store.init_intelligence_db()


def test_reference_decks_and_slides_round_trip():
    deck_id = store.upsert_reference_deck("D:/x/a.pptx", "h1", "topic_map", 3)
    store.replace_reference_slides(deck_id, [{"n": 1, "type": "cover", "features": {"words": 4}},
                                             {"n": 2, "type": "bar_with_cards", "features": {"words": 90}}])
    assert store.get_reference_deck("D:/x/a.pptx")["hash"] == "h1"
    bars = store.list_reference_slides("bar_with_cards")
    assert bars[0]["deck_path"] == "D:/x/a.pptx" and bars[0]["features"]["words"] == 90
    assert store.upsert_reference_deck("D:/x/a.pptx", "h2", "audit", 3) == deck_id
    store.replace_reference_slides(deck_id, [{"n": 1, "type": "cover", "features": {}}])
    assert store.list_reference_slides("bar_with_cards") == []
    store.delete_reference_deck("D:/x/a.pptx")
    assert store.get_reference_deck("D:/x/a.pptx") is None and store.list_reference_slides() == []


def test_run_has_studio_output_columns():
    from agent.tests.test_deliverable_rows import _project
    pid = _project(pathlib.Path(tempfile.mkdtemp()))
    run_id = store.create_deliverable_run(pid)
    store.update_deliverable_run(run_id, html_path="a.html", pdf_path="a.pdf", studio_pptx_path="a.pptx", deck_dir="d")
    run = store.get_deliverable_run(run_id)
    assert (run["html_path"], run["pdf_path"], run["studio_pptx_path"], run["deck_dir"]) == ("a.html", "a.pdf", "a.pptx", "d")
```

- [ ] **Step 2: run, expect FAIL** (`AttributeError: ... upsert_reference_deck`).
- [ ] **Step 3: implement.** Migration 20:

```python
    (20, "deck studio", [
        """CREATE TABLE IF NOT EXISTS deck_reference_decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, hash TEXT NOT NULL,
            family TEXT NOT NULL, n_slides INTEGER NOT NULL, indexed_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS deck_reference_slides (
            id INTEGER PRIMARY KEY AUTOINCREMENT, deck_id INTEGER NOT NULL, n INTEGER NOT NULL,
            type TEXT NOT NULL, features_json TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_deck_ref_slides_type ON deck_reference_slides(type)",
        "ALTER TABLE intel_deliverable_runs ADD COLUMN html_path TEXT",
        "ALTER TABLE intel_deliverable_runs ADD COLUMN pdf_path TEXT",
        "ALTER TABLE intel_deliverable_runs ADD COLUMN studio_pptx_path TEXT",
        "ALTER TABLE intel_deliverable_runs ADD COLUMN deck_dir TEXT",
    ]),
```

`deckstudio/repository.py`:

```python
"""SQLite access for the reference deck library."""
from __future__ import annotations
import json, time
from typing import Optional
from ...core.db import _conn


def upsert_reference_deck(path: str, digest: str, family: str, n_slides: int) -> int:
    conn = _conn()
    row = conn.execute("SELECT id FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    if row:
        conn.execute("UPDATE deck_reference_decks SET hash=?, family=?, n_slides=?, indexed_at=? WHERE id=?",
                     (digest, family, n_slides, time.time(), row["id"]))
        deck_id = row["id"]
    else:
        deck_id = conn.execute("INSERT INTO deck_reference_decks (path, hash, family, n_slides, indexed_at) "
                               "VALUES (?, ?, ?, ?, ?)", (path, digest, family, n_slides, time.time())).lastrowid
    conn.commit(); conn.close()
    return deck_id


def get_reference_deck(path: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_reference_decks() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM deck_reference_decks ORDER BY path").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_reference_deck(path: str) -> None:
    conn = _conn()
    row = conn.execute("SELECT id FROM deck_reference_decks WHERE path = ?", (path,)).fetchone()
    if row:
        conn.execute("DELETE FROM deck_reference_slides WHERE deck_id = ?", (row["id"],))
        conn.execute("DELETE FROM deck_reference_decks WHERE id = ?", (row["id"],))
    conn.commit(); conn.close()


def replace_reference_slides(deck_id: int, slides: list[dict]) -> None:
    conn = _conn()
    conn.execute("DELETE FROM deck_reference_slides WHERE deck_id = ?", (deck_id,))
    conn.executemany("INSERT INTO deck_reference_slides (deck_id, n, type, features_json) VALUES (?, ?, ?, ?)",
                     [(deck_id, s["n"], s["type"], json.dumps(s.get("features") or {}, default=str)) for s in slides])
    conn.commit(); conn.close()


def list_reference_slides(slide_type: str | None = None) -> list[dict]:
    conn = _conn()
    sql = ("SELECT s.deck_id, s.n, s.type, s.features_json, d.path AS deck_path, d.family "
           "FROM deck_reference_slides s JOIN deck_reference_decks d ON d.id = s.deck_id")
    rows = conn.execute(sql + (" WHERE s.type = ?" if slide_type else "") + " ORDER BY d.path, s.n",
                        (slide_type,) if slide_type else ()).fetchall()
    conn.close()
    return [{"deck_id": r["deck_id"], "deck_path": r["deck_path"], "family": r["family"], "n": r["n"],
             "type": r["type"], "features": json.loads(r["features_json"])} for r in rows]
```

`core/store.py`: add `from ..domains.deckstudio.repository import *  # noqa: F401,F403`.

- [ ] **Step 4: run, expect PASS** (2 passed).
- [ ] **Step 5: commit** `feat(deckstudio): reference deck library storage and run output columns`.

---

### Task 2: Indexer — slide types, families, design rules

**Files:** Create `agent/app/domains/deckstudio/indexer.py`; Test `agent/tests/test_deckstudio_indexer.py`

**Interfaces — Consumes:** Task 1 via `store`. **Produces:** `SLIDE_TYPES`, `SHINGLE = 6`, `MAX_DECK_MB = 50`, `FAMILY_WORDS: dict[str, tuple[str,...]]`, `slide_features(slide, slide_w, slide_h) -> dict` (`words, text, chart_kinds, n_charts, n_tables, n_pictures, picture_cover, big_numbers, fonts, fills`), `classify(features, index, n_slides) -> str`, `deck_family(name, slides) -> str` (`topic_map|audit|travel|brand_social|follow_up`), `index_library(folder=None, progress=None) -> dict` (`{indexed, unchanged, skipped, removed}`), `design_rules(family) -> dict` (`{title_font, body_font, fills, slide_types}`), `reference_text_shingles() -> set[tuple[str,...]]`.

- [ ] **Step 1: failing tests**

```python
"""The indexer learns slide types and families from whatever decks are in the folder."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from pathlib import Path
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from agent.app.core import store
from agent.app.domains.deckstudio import indexer


def setup_module(_):
    store.init_intelligence_db()


def _deck(path: Path, first_words: str) -> Path:
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank); s.shapes.add_textbox(0, 0, Inches(5), Inches(1)).text_frame.text = first_words
    s = prs.slides.add_slide(blank); s.shapes.add_textbox(0, 0, Inches(5), Inches(1)).text_frame.text = "Table of Contents"
    s = prs.slides.add_slide(blank)
    d = CategoryChartData(); d.categories = ["A", "B"]; d.add_series("s", (3, 4))
    s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, 0, Inches(1.5), Inches(6), Inches(4), d)
    s.shapes.add_textbox(Inches(7), Inches(1.5), Inches(5), Inches(3)).text_frame.text = "Key themes explained in a long card " * 5
    s = prs.slides.add_slide(blank)
    d2 = CategoryChartData(); d2.categories = ["Pos", "Neg"]; d2.add_series("s", (70, 30))
    s.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, 0, Inches(1.5), Inches(4), Inches(4), d2)
    d3 = CategoryChartData(); d3.categories = ["Jan", "Feb", "Mar"]; d3.add_series("s", (1, 5, 2))
    s.shapes.add_chart(XL_CHART_TYPE.LINE, Inches(5), Inches(1.5), Inches(7), Inches(4), d3)
    s = prs.slides.add_slide(blank); s.shapes.add_textbox(0, 0, Inches(4), Inches(1)).text_frame.text = "Thank you"
    prs.save(path); return path


def test_types_are_classified_from_shapes(tmp_path):
    deck = _deck(tmp_path / "Brand_Topic Map_May.pptx", "Brand Topic Map")
    prs = Presentation(deck)
    types = [indexer.classify(indexer.slide_features(s, prs.slide_width, prs.slide_height), i, len(prs.slides))
             for i, s in enumerate(prs.slides)]
    assert types == ["cover", "contents", "bar_with_cards", "sov_doughnut_trend", "closing"]


def test_family_from_name_and_content():
    assert indexer.deck_family("Hunter PR_Paycom & Competitors_C-Suite Audit.pptx", []) == "audit"
    assert indexer.deck_family("Travel Template Bahamas.pptx", []) == "travel"
    assert indexer.deck_family("X_Verbatims.pptx", [{"type": "verbatim_wall"}] * 3) == "follow_up"
    assert indexer.deck_family("Celsius_Topic Map.pptx", [{"type": "bar_with_cards"}] * 20) == "topic_map"


def test_index_picks_up_new_and_changed_decks_and_drops_removed(tmp_path):
    a = _deck(tmp_path / "A_Topic Map.pptx", "A")
    assert indexer.index_library(tmp_path)["indexed"] == 1 and store.list_reference_slides("bar_with_cards")
    assert indexer.index_library(tmp_path)["unchanged"] == 1
    _deck(tmp_path / "B_Social Audit.pptx", "B")
    assert indexer.index_library(tmp_path)["indexed"] == 1
    a.unlink()
    assert indexer.index_library(tmp_path)["removed"] == 1


def test_index_skips_broken_and_huge_decks(tmp_path, monkeypatch):
    (tmp_path / "broken.pptx").write_bytes(b"not a deck")
    (tmp_path / "~$lock.pptx").write_bytes(b"x")
    _deck(tmp_path / "Ok_Topic Map.pptx", "Ok")
    monkeypatch.setattr(indexer, "MAX_DECK_MB", 0.00001)
    assert indexer.index_library(tmp_path)["skipped"] >= 2
    monkeypatch.setattr(indexer, "MAX_DECK_MB", 50)
    result = indexer.index_library(tmp_path)
    assert result["skipped"] == 2 and result["indexed"] + result["unchanged"] >= 1


def test_rules_and_shingles_come_from_the_library(tmp_path):
    _deck(tmp_path / "R_Topic Map.pptx", "Rules deck")
    indexer.index_library(tmp_path)
    assert indexer.design_rules("topic_map")["slide_types"].get("bar_with_cards", 0) >= 1
    assert ("key", "themes", "explained", "in", "a", "long") in indexer.reference_text_shingles()
```

- [ ] **Step 2: run, expect FAIL** (module missing).
- [ ] **Step 3: implement `indexer.py`:**

```python
"""Learns slide types, deck families and design rules from whatever decks are in the reference folder.
Only geometry and style are reused; slide text is kept solely to detect copying (shingles)."""
from __future__ import annotations
import hashlib, logging, re
from collections import Counter
from pathlib import Path
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from ...core import config, store

logger = logging.getLogger(__name__)
MAX_DECK_MB = 50
SHINGLE = 6
SLIDE_TYPES = ("cover", "contents", "objectives", "divider", "kpi_dashboard", "sov_doughnut_trend", "bar_with_cards",
               "trend_with_peaks", "sentiment_split", "theme_cards", "verbatim_wall", "person_cards",
               "comparison_table", "takeaways", "appendix_list", "closing", "other")
FAMILY_WORDS = {"audit": ("audit", "c-suite", "csuite"), "travel": ("travel", "7cs", "destination", "hotel", "bahamas"),
                "brand_social": ("social",), "topic_map": ("topic map",)}
_BIG_NUMBER = re.compile(r"^\s*\d{1,3}(?:[.,]\d+)?%?\s*$")
_WORD = re.compile(r"[a-z0-9']+")


def _chart_kind(chart) -> str:
    name = str(chart.chart_type).lower()
    return next((k for k in ("doughnut", "pie", "line", "bar", "column", "area") if k in name), "other")


def slide_features(slide, slide_w: int, slide_h: int) -> dict:
    texts, kinds, fonts, fills = [], [], Counter(), Counter()
    n_tables = n_pictures = big_numbers = 0
    cover = 0.0
    for sh in slide.shapes:
        if getattr(sh, "has_chart", False) and sh.has_chart:
            kinds.append(_chart_kind(sh.chart))
        if getattr(sh, "has_table", False) and sh.has_table:
            n_tables += 1
        if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            n_pictures += 1
            if sh.width and sh.height and slide_w and slide_h:
                cover = max(cover, (sh.width * sh.height) / (slide_w * slide_h))
        if sh.has_text_frame and sh.text_frame.text.strip():
            texts.append(sh.text_frame.text)
            big_numbers += bool(_BIG_NUMBER.match(sh.text_frame.text))
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.name:
                        fonts[r.font.name] += 1
        try:
            if sh.fill.type == 1:
                fills[str(sh.fill.fore_color.rgb)] += 1
        except (AttributeError, TypeError, ValueError, NotImplementedError):
            pass
    text = "\n".join(texts)
    return {"words": len(_WORD.findall(text.lower())), "text": text[:4000], "chart_kinds": kinds, "n_charts": len(kinds),
            "n_tables": n_tables, "n_pictures": n_pictures, "picture_cover": round(cover, 3), "big_numbers": big_numbers,
            "fonts": [f for f, _ in fonts.most_common(3)], "fills": [f for f, _ in fills.most_common(5)]}


def classify(f: dict, index: int, n_slides: int) -> str:
    low, kinds = f["text"].lower(), set(f["chart_kinds"])
    if index == 0:
        return "cover"
    if index == n_slides - 1 and f["words"] < 60:
        return "closing"
    if re.search(r"table of contents|agenda|\bcontents\b", low):
        return "contents"
    if re.search(r"objective|scope", low) and not kinds:
        return "objectives"
    if f["picture_cover"] > 0.8 and f["words"] < 25:
        return "divider"
    if {"doughnut", "pie"} & kinds and "line" in kinds:
        return "sov_doughnut_trend"
    if f["big_numbers"] >= 3:
        return "kpi_dashboard"
    if f["n_tables"]:
        return "comparison_table"
    if "line" in kinds:
        return "trend_with_peaks"
    if {"doughnut", "pie"} & kinds:
        return "sentiment_split" if ("sentiment" in low or "positive" in low) else "kpi_dashboard"
    if {"bar", "column"} & kinds:
        return "bar_with_cards"
    if f["n_pictures"] >= 6:
        return "verbatim_wall"
    if f["n_pictures"] >= 3 and re.search(r"journalist|influencer|ceo|founder|reporter", low):
        return "person_cards"
    if re.search(r"takeaway|recommend|implication|so what", low):
        return "takeaways"
    if low.count("http") >= 4:
        return "appendix_list"
    return "theme_cards" if f["words"] > 60 else "other"


def deck_family(name: str, slides: list[dict]) -> str:
    low = name.lower()
    for family in ("audit", "travel"):
        if any(w in low for w in FAMILY_WORDS[family]):
            return family
    if ("verbatim" in low or "follow" in low or "additional" in low) and len(slides) <= 8:
        return "follow_up"
    if "social" in low and len(slides) > 20:
        return "brand_social"
    return "topic_map"


def _digest(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index_library(folder: Path | None = None, progress=None) -> dict:
    folder = Path(folder or config.TEMPLATES_DIR)
    result = {"indexed": 0, "unchanged": 0, "skipped": 0, "removed": 0}
    paths = sorted(folder.glob("*.pptx")) if folder.exists() else []
    for i, path in enumerate(paths, start=1):
        if progress:
            progress(i, len(paths), path.stem)
        if path.name.startswith("~$") or path.stat().st_size > MAX_DECK_MB * 1024 * 1024:
            result["skipped"] += 1
            continue
        digest = _digest(path)
        known = store.get_reference_deck(str(path))
        if known and known["hash"] == digest:
            result["unchanged"] += 1
            continue
        try:
            prs = Presentation(str(path))
            feats = [slide_features(s, prs.slide_width, prs.slide_height) for s in prs.slides]
        except Exception as e:      # a broken deck must not stop the library
            logger.warning("reference deck %s skipped: %s", path.name, type(e).__name__)
            result["skipped"] += 1
            continue
        slides = [{"n": n, "type": classify(f, n - 1, len(feats)), "features": f} for n, f in enumerate(feats, start=1)]
        deck_id = store.upsert_reference_deck(str(path), digest, deck_family(path.name, slides), len(slides))
        store.replace_reference_slides(deck_id, slides)
        result["indexed"] += 1
    for deck in store.list_reference_decks():
        if deck["path"].startswith(str(folder)) and not Path(deck["path"]).exists():
            store.delete_reference_deck(deck["path"])
            result["removed"] += 1
    return result


def design_rules(family: str) -> dict:
    slides = [s for s in store.list_reference_slides() if s["family"] == family] or store.list_reference_slides()
    fonts = [f for f, _ in Counter(f for s in slides for f in s["features"].get("fonts", [])).most_common(4)]
    fills = Counter(c for s in slides for c in s["features"].get("fills", []))
    return {"title_font": fonts[0] if fonts else "Georgia", "body_font": fonts[1] if len(fonts) > 1 else "Arial",
            "fills": [c for c, _ in fills.most_common(8)], "slide_types": dict(Counter(s["type"] for s in slides))}


def reference_text_shingles() -> set[tuple[str, ...]]:
    out = set()
    for s in store.list_reference_slides():
        words = _WORD.findall(s["features"].get("text", "").lower())
        out.update(tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))
    return out
```

- [ ] **Step 4: run, expect PASS** (5 passed). A failing type assertion means fixing the rule order in `classify`, not the test.
- [ ] **Step 5: commit** `feat(deckstudio): indexer learns slide types, families and rules from the reference folder`.

---

### Task 3: Slide spec types and planner

**Files:** Create `agent/app/domains/deckstudio/spec.py`, `agent/app/domains/deckstudio/planner.py`; Test `agent/tests/test_deckstudio_planner.py`

**Interfaces — Consumes:** `deliverable.engine_types.RQ, Section`; `store.list_reference_slides`; `indexer.FAMILY_WORDS`. **Produces:** `spec.py`: `SPEC_VERSION = 1`, dataclasses `DeckTokens`, `SlideSpec`, `DeckSpec` (fields below) with `DeckSpec.to_dict()` / `DeckSpec.from_dict(d)`. `planner.py`: `PlanInput` (fields below), `treatment(slide_type, charts, tables) -> "A"|"C"|"full"`, `choose_family(scope_text) -> (family, reason)`, `pick_reference(slide_type, family) -> {deck, slide, why}|{}`, `build_deck_spec(inp) -> DeckSpec`. Slide ids: `cover`, `objectives`, `executive-summary`, `<rq>-divider`, `<rq>-<module>-<i>` (evidence; entity sections keep their full section id suffix e.g. `rq3-entities-experts-1`), `takeaways`, `scorecard`, `checklist-<k>`, `methodology`, `citations-<k>`, `closing`.

- [ ] **Step 1: failing tests**

```python
"""Planner: full questions, A/C by density, sequence with scorecard and checklist."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.core import store
from agent.app.domains.deckstudio import planner
from agent.app.domains.deckstudio.spec import DeckSpec
from agent.app.domains.deliverable.engine_types import RQ, Section

Q1 = "What proportion of earned editorial coverage in the baby skincare category is deal/sale-led?"


def setup_module(_):
    store.init_intelligence_db()


def make_input(**kw):
    rq = RQ("RQ1", Q1)
    secs = [Section("rq1-share_kpi", "RQ1", "share_kpi", "Share", chart={"kind": "kpi", "categories": ["Share"], "values": [29.2], "unit": "percent", "peaks": []}, facts=["RQ1: 227 of 778 articles (29.2%) answer this question"]),
            Section("rq1-volume_trend", "RQ1", "volume_trend", "Coverage over time", chart={"kind": "line_peaks", "categories": [f"M{i}" for i in range(12)], "values": list(range(12)), "peaks": [5], "unit": "count"}, facts=["Peak 1: M5 with 5 articles"]),
            Section("rq1-brand_sov", "RQ1", "brand_sov", "Brands", chart={"kind": "bar", "categories": ["Aveeno", "Cetaphil"], "values": [60.0, 40.0], "unit": "percent", "peaks": []}, facts=["Brand Aveeno: 6 of 10 brand mentions (60.0%)"]),
            Section("rq1-top_articles", "RQ1", "top_articles", "Top articles", table={"header": ["Headline", "Outlet"], "rows": [["A", "B"]], "col_widths": [6, 6]})]
    base = dict(title="Baby Skincare Category", subtitle="Earned Editorial", period="Jan 2025 - Dec 2026", base_n=778,
                rqs=[rq], rq_titles={"RQ1": "Deal-Led Coverage"}, sections_by_rq={"RQ1": secs},
                insights_by_rq={"RQ1": [{"headline": "29% of coverage is deal-led", "text": "227 of 778 articles", "citations": [1]}]},
                answers=[{"rq_id": "RQ1", "question": Q1, "value": "29.2%", "answer": "227 of 778 articles (29.2%)"}],
                takeaways=[{"headline": "Deals lead", "text": "29.2% of coverage", "citations": [1]}],
                overview=Section("overview", None, "overview", "Overview", chart={"kind": "bar", "categories": ["RQ1"], "values": [227], "unit": "count", "peaks": []}, facts=["Base: 778 unique articles across all questions"]),
                methodology=["5 files, 865 rows, 778 unique articles"],
                citations=[{"n": 1, "outlet": "o", "title": "t", "url": "https://x.com/a", "date": "", "domain": "x.com"}],
                scope_text="baby skincare editorial coverage", brands=["Aveeno", "Cetaphil"], geography="United States",
                sources="Meltwater", checklist=[{"ask": Q1, "kind": "question", "status": "covered", "slides": [], "note": "", "rq_id": "RQ1", "modules": []}])
    base.update(kw)
    return planner.PlanInput(**base)


def test_treatment_follows_chart_density():
    assert planner.treatment("evidence", [{"kind": "kpi", "categories": ["x"]}], []) == "A"
    assert planner.treatment("evidence", [{"kind": "bar", "categories": list("abcdef")}], []) == "A"
    assert planner.treatment("evidence", [{"kind": "bar", "categories": list("abcdefg")}], []) == "C"
    assert planner.treatment("evidence", [{"kind": "line_peaks", "categories": ["a"]}], []) == "C"
    assert planner.treatment("evidence", [], [{"rows": [[1]]}]) == "C"
    assert planner.treatment("divider", [], []) == "full"


def test_deck_sequence_full_questions_and_no_rq_codes():
    spec = planner.build_deck_spec(make_input())
    types = [s.type for s in spec.slides]
    assert types[:3] == ["cover", "objectives", "executive_summary"]
    assert types[-5:] == ["scorecard", "checklist", "methodology", "citations", "closing"]
    assert "divider" in types and "takeaways" in types
    divider = next(s for s in spec.slides if s.type == "divider")
    assert divider.question == Q1 and divider.treatment == "full"
    on_slide = " ".join(f"{s.kicker} {s.title} {s.question} {s.so_what}" for s in spec.slides)
    assert "RQ1" not in on_slide


def test_every_slide_carries_its_allowed_facts_and_spec_round_trips():
    spec = planner.build_deck_spec(make_input())
    trend = next(s for s in spec.slides if any(c["kind"] == "line_peaks" for c in s.charts))
    assert trend.treatment == "C" and "Peak 1: M5 with 5 articles" in trend.facts_allowed
    assert DeckSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()


def test_family_choice_says_why():
    family, why = planner.choose_family("C-suite audit of executive coverage for Paycom")
    assert family == "audit" and "audit" in why.lower()
    assert planner.choose_family("baby skincare editorial")[0] == "topic_map"
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement `spec.py`:**

```python
"""The slide spec: the contract every renderer (HTML now; editable PPTX and video later) reads."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field

SPEC_VERSION = 1


@dataclass
class DeckTokens:
    background: str = "FFFFFF"
    surface: str = "F7F5FB"
    primary: str = "3D1A6B"
    accent: str = "A87DC8"
    text: str = "1F1F1F"
    muted: str = "5A5A6A"
    on_dark: str = "FFFFFF"
    series: list[str] = field(default_factory=lambda: ["5E35B1", "E4572E", "196B24", "0F9ED5", "A02B93", "E97132"])
    overlay: str = "linear-gradient(90deg, rgba(30,10,60,.85), rgba(30,10,60,.2))"
    title_font: str = "Playfair Display"
    body_font: str = "Inter"
    mood: list[str] = field(default_factory=list)


@dataclass
class SlideSpec:
    id: str
    type: str
    treatment: str = "plain"
    kicker: str = ""
    title: str = ""
    question: str = ""
    so_what: str = ""
    n_label: str = ""
    charts: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    logos: dict[str, str] = field(default_factory=dict)
    image: dict = field(default_factory=dict)
    facts_allowed: list[str] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    notes: str = ""
    reference: dict = field(default_factory=dict)


@dataclass
class DeckSpec:
    version: int
    title: str
    subtitle: str
    period: str
    base_n: int
    family: str
    family_reason: str
    tokens: DeckTokens | None
    slides: list[SlideSpec]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DeckSpec":
        tokens = DeckTokens(**d["tokens"]) if d.get("tokens") else None
        return DeckSpec(**{**d, "tokens": tokens, "slides": [SlideSpec(**s) for s in d["slides"]]})
```

`planner.py`:

```python
"""Turns engine findings and the brief into a slide spec: sequence, full questions, A/C treatment by chart
density, the closest reference layout per slide (from any deck), scorecard and checklist."""
from __future__ import annotations
from dataclasses import dataclass, field
from ...core import store
from ..deliverable.engine_types import RQ, Section
from .indexer import FAMILY_WORDS
from .spec import SPEC_VERSION, DeckSpec, SlideSpec

LIGHT_MAX_BARS = 6
CHECKLIST_ROWS_PER_SLIDE = 9
CITES_PER_SLIDE = 14
DENSE_KINDS = {"line_peaks", "column", "treemap"}
TYPE_FOR_CHART = {"kpi": "kpi_dashboard", "doughnut": "sentiment_split", "gauge": "kpi_dashboard",
                  "line_peaks": "trend_with_peaks", "column": "trend_with_peaks", "bar": "bar_with_cards",
                  "treemap": "theme_cards"}


@dataclass
class PlanInput:
    title: str
    subtitle: str
    period: str
    base_n: int
    rqs: list[RQ]
    rq_titles: dict[str, str]
    sections_by_rq: dict[str, list[Section]]
    insights_by_rq: dict[str, list[dict]]
    answers: list[dict]
    takeaways: list[dict]
    overview: Section
    methodology: list[str]
    citations: list[dict]
    scope_text: str
    brands: list[str]
    geography: str
    sources: str
    checklist: list[dict] = field(default_factory=list)


def treatment(slide_type: str, charts: list[dict], tables: list[dict]) -> str:
    if slide_type in ("cover", "divider", "closing"):
        return "full"
    if tables or any(c["kind"] in DENSE_KINDS or len(c.get("categories", [])) > LIGHT_MAX_BARS for c in charts):
        return "C"
    return "A"


def choose_family(scope_text: str) -> tuple[str, str]:
    low = scope_text.lower()
    for family in ("audit", "travel", "brand_social"):
        hits = [w for w in FAMILY_WORDS[family] if w in low]
        if hits:
            return family, f"the brief mentions {', '.join(hits)}, which matches the {family.replace('_', ' ')} family"
    return "topic_map", "a category/editorial brief, which matches the topic map family"


def pick_reference(slide_type: str, family: str) -> dict:
    candidates = store.list_reference_slides(slide_type)
    if not candidates:
        return {}
    same = [c for c in candidates if c["family"] == family]
    best = (same or candidates)[0]
    why = "same family" if same else f"closest {slide_type.replace('_', ' ')} layout in any deck"
    return {"deck": best["deck_path"], "slide": best["n"], "why": why}


def _facts(sections: list[Section]) -> list[str]:
    return [f for s in sections for f in s.facts]


def _evidence(rq: RQ, kicker: str, sections: list[Section], insights: list[dict], family: str) -> list[SlideSpec]:
    out = []
    drawn = [s for s in sections if not s.skipped and (s.chart or s.table) and (s.chart or {}).get("kind") != "kpi"]
    for i, sec in enumerate(drawn):
        charts = [sec.chart] if sec.chart else []
        tables = [sec.table] if sec.table else []
        slide_type = TYPE_FOR_CHART.get((sec.chart or {}).get("kind", ""), "comparison_table")
        cards = insights[:3] if i == 0 else []
        out.append(SlideSpec(
            id=f"{sec.id}-{i}", type=slide_type, treatment=treatment("evidence", charts, tables), kicker=kicker,
            title=sec.title, question=rq.question, so_what=sec.facts[0].split(": ", 1)[-1] if sec.facts else "",
            charts=charts, tables=tables, cards=cards, facts_allowed=_facts(sections),
            citations=[n for c in cards for n in c.get("citations", [])],
            image={"query": f"{kicker} {sec.title}", "role": "panel"}, reference=pick_reference(slide_type, family)))
    return out


def build_deck_spec(inp: PlanInput) -> DeckSpec:
    family, why = choose_family(inp.scope_text)
    all_facts = _facts([inp.overview] + [s for secs in inp.sections_by_rq.values() for s in secs]) + inp.methodology
    slides = [
        SlideSpec(id="cover", type="cover", treatment="full", title=inp.title, so_what=inp.subtitle, notes=inp.period,
                  image={"query": f"{inp.title} {inp.subtitle}", "role": "background"}, reference=pick_reference("cover", family)),
        SlideSpec(id="objectives", type="objectives", treatment="A", title="Objectives & scope",
                  cards=[{"headline": q.question, "text": ""} for q in inp.rqs],
                  notes=f"Brands: {', '.join(inp.brands)} · Sources: {inp.sources} · Geography: {inp.geography} · Period: {inp.period}",
                  image={"query": f"{inp.title} research", "role": "background"}, facts_allowed=all_facts,
                  reference=pick_reference("objectives", family)),
        SlideSpec(id="executive-summary", type="executive_summary", treatment="A", title="What the coverage says",
                  so_what=f"Base: {inp.base_n} unique articles across {len(inp.rqs)} questions",
                  cards=[{"headline": a["value"], "text": a["question"], "note": a["answer"]} for a in inp.answers],
                  facts_allowed=all_facts + [str(len(inp.rqs))], image={"query": f"{inp.title} overview", "role": "background"},
                  reference=pick_reference("kpi_dashboard", family))]
    for k, rq in enumerate(inp.rqs, start=1):
        kicker = inp.rq_titles.get(rq.id) or f"Question {k}"
        answer = next((a for a in inp.answers if a["rq_id"] == rq.id), {})
        sections = inp.sections_by_rq.get(rq.id, [])
        slides.append(SlideSpec(id=f"{rq.id.lower()}-divider", type="divider", treatment="full",
                                kicker=f"Question {k} of {len(inp.rqs)}", question=rq.question,
                                so_what=answer.get("answer", ""), facts_allowed=_facts(sections) + [str(k), str(len(inp.rqs))],
                                image={"query": kicker, "role": "background"}, reference=pick_reference("divider", family)))
        slides += _evidence(rq, kicker, sections, inp.insights_by_rq.get(rq.id, []), family)
    slides.append(SlideSpec(id="takeaways", type="takeaways", treatment="A", title="Key takeaways", cards=inp.takeaways[:6],
                            facts_allowed=all_facts, citations=[n for c in inp.takeaways for n in c.get("citations", [])],
                            image={"query": f"{inp.title} takeaways", "role": "background"},
                            reference=pick_reference("takeaways", family)))
    counts = {s: sum(1 for r in inp.checklist if r["status"] == s) for s in ("covered", "partial", "missing")}
    gaps = [r for r in inp.checklist if r["status"] != "covered"]
    slides.append(SlideSpec(id="scorecard", type="scorecard", treatment="A", title="Did we answer the brief?",
                            cards=[{"headline": str(counts[s]), "text": s} for s in ("covered", "partial", "missing")],
                            tables=[{"header": ["Brief asked", "Status", "Why"], "rows": [[g["ask"], g["status"], g["note"]] for g in gaps]}],
                            facts_allowed=all_facts + [str(v) for v in counts.values()],
                            image={"query": f"{inp.title} brief", "role": "background"}))
    for p in range(0, max(1, len(inp.checklist)), CHECKLIST_ROWS_PER_SLIDE):
        rows = inp.checklist[p:p + CHECKLIST_ROWS_PER_SLIDE]
        slides.append(SlideSpec(id=f"checklist-{p // CHECKLIST_ROWS_PER_SLIDE + 1}", type="checklist", treatment="plain",
                                title="Brief checklist", facts_allowed=list(all_facts),
                                tables=[{"header": ["Brief asked", "Status", "Where", "Note"],
                                         "rows": [[r["ask"], r["status"], "—", r["note"]] for r in rows]}]))
    slides.append(SlideSpec(id="methodology", type="methodology", treatment="plain", title="Definitions & methodology",
                            cards=[{"headline": "", "text": m} for m in inp.methodology], facts_allowed=all_facts))
    for p in range(0, max(1, len(inp.citations)), CITES_PER_SLIDE):
        page = inp.citations[p:p + CITES_PER_SLIDE]
        slides.append(SlideSpec(id=f"citations-{p // CITES_PER_SLIDE + 1}", type="citations", treatment="plain", title="Sources",
                                tables=[{"header": ["#", "Source", "Headline", "Date"],
                                         "rows": [[str(c["n"]), c.get("outlet") or c.get("domain", ""), c["title"], c["date"]] for c in page]}],
                                facts_allowed=all_facts + [str(c["n"]) for c in page] + [c["date"] for c in page],
                                notes="\n".join(c["url"] for c in page)))
    slides.append(SlideSpec(id="closing", type="closing", treatment="full", title="Thank you", so_what=inp.title,
                            image={"query": f"{inp.title} thank you", "role": "background"}, reference=pick_reference("closing", family)))
    return DeckSpec(version=SPEC_VERSION, title=inp.title, subtitle=inp.subtitle, period=inp.period, base_n=inp.base_n,
                    family=family, family_reason=why, tokens=None, slides=slides)
```

- [ ] **Step 4: run, expect PASS** (4 passed).
- [ ] **Step 5: commit** `feat(deckstudio): slide spec and planner with full questions and A/C treatment`.

---

### Task 4: Brief checklist

**Files:** Create `agent/app/domains/deckstudio/checklist.py`; Test `agent/tests/test_deckstudio_checklist.py`

**Interfaces — Consumes:** `RQ`, `Section`, `store.get_latest_spec`, Task 3 `DeckSpec`. **Produces:** `brief_asks(project_id) -> list[tuple[str,str]]` (`(kind, text)`, kind `analysis|deliverable`, read from `spec["source_spec"]["included_scope"]`), `build_checklist(rqs, sections_by_rq, asks, has_brief_doc=True) -> list[dict]` (rows `{ask, kind, status, slides, note, rq_id, modules}`; status `covered|partial|missing`), `attach_slide_numbers(spec, rows) -> list[dict]` (fills `slides`, rewrites the checklist slides' tables and facts).

- [ ] **Step 1: failing tests**

```python
"""Every question, expected analysis and deliverable is covered / partial / missing, with a reason."""
from __future__ import annotations
from agent.app.domains.deckstudio import checklist as C
from agent.app.domains.deckstudio.spec import DeckSpec, SlideSpec
from agent.app.domains.deliverable.engine_types import RQ, Section

RQS = [RQ("RQ1", "What share is deal-led?"), RQ("RQ4", "What percentage of experts are affiliated with a brand?"),
       RQ("RQ9", "Which platforms carry celebrity coverage?")]
SECS = {"RQ1": [Section("rq1-share_kpi", "RQ1", "share_kpi", "Share", chart={"kind": "kpi"}, facts=["x"]),
                Section("rq1-theme_clusters", "RQ1", "theme_clusters", "Themes", chart={"kind": "treemap"}, facts=["t"])],
        "RQ4": [Section("rq4-share_kpi", "RQ4", "share_kpi", "Share", chart={"kind": "kpi"}, facts=["y"]),
                Section("rq4-entities-experts", "RQ4", "entities", "Experts", chart={"kind": "doughnut"},
                        facts=["Brand affiliation not stated for 22 of 22 experts"])],
        "RQ9": [Section("rq9-share_kpi", "RQ9", "share_kpi", "Share", skipped="No articles for this question")]}


def test_questions_get_status_and_reason():
    by = {r["rq_id"]: r for r in C.build_checklist(RQS, SECS, []) if r["kind"] == "question"}
    assert by["RQ1"]["status"] == "covered"
    assert by["RQ4"]["status"] == "partial" and "not stated" in by["RQ4"]["note"]
    assert by["RQ9"]["status"] == "missing" and "No articles" in by["RQ9"]["note"]


def test_expected_analyses_and_deliverables_are_matched_to_modules():
    asks = [("analysis", "Breakdown of coverage by theme"), ("analysis", "Quantification of expert types cited"),
            ("analysis", "Share of coverage by platform"), ("deliverable", "Written summary"),
            ("deliverable", "Quantitative findings report with visual breakdowns")]
    rows = {r["ask"]: r for r in C.build_checklist(RQS, SECS, asks)}
    assert rows["Breakdown of coverage by theme"]["status"] == "covered"
    assert rows["Quantification of expert types cited"]["status"] == "covered"
    assert rows["Share of coverage by platform"]["status"] == "missing" and rows["Share of coverage by platform"]["note"]
    assert rows["Written summary"]["status"] == "covered"
    assert rows["Quantitative findings report with visual breakdowns"]["status"] == "covered"


def test_slide_numbers_come_from_the_deck_order():
    rows = C.build_checklist(RQS[:1], {"RQ1": SECS["RQ1"]}, [("analysis", "Breakdown of coverage by theme")])
    spec = DeckSpec(1, "t", "s", "p", 1, "topic_map", "", None, [
        SlideSpec("cover", "cover"), SlideSpec("rq1-divider", "divider"), SlideSpec("rq1-theme_clusters-0", "theme_cards"),
        SlideSpec("scorecard", "scorecard", tables=[{"header": [], "rows": []}]),
        SlideSpec("checklist-1", "checklist", tables=[{"header": ["Brief asked", "Status", "Where", "Note"], "rows": []}])])
    rows = C.attach_slide_numbers(spec, rows)
    assert rows[0]["slides"] == [2, 3]
    assert next(r for r in rows if r["ask"].startswith("Breakdown"))["slides"] == [3]
    assert spec.slides[4].tables[0]["rows"][0][2] == "2, 3"
```

Note: platforms ("Which platforms carry celebrity coverage?") has no module; its question row is "missing" because its share KPI was skipped — which is what the third assert checks.

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""'Did we answer the brief?': every research question, expected analysis and requested deliverable, marked
covered / partial / missing with the slides that answer it and a reason when something is short."""
from __future__ import annotations
import re
from ...core import store
from ..deliverable.engine_types import RQ, Section
from .spec import DeckSpec

ASK_MODULES = [
    (r"theme|topic|breakdown", {"theme_clusters"}), (r"expert", {"entities:experts"}), (r"affiliat", {"entities:experts"}),
    (r"celebrit", {"entities:celebrities"}), (r"brand|share of voice|competitor", {"brand_sov", "entities:brands"}),
    (r"sentiment|tone", {"sentiment_split"}), (r"outlet|publication", {"outlet_ranking"}),
    (r"trend|over time|month|volume", {"volume_trend"}), (r"reach|audience", {"reach"}), (r"retailer", {"entities:retailers"}),
]
DELIVERED = re.compile(r"written summary|report|deck|presentation|visual|quantitative|findings", re.I)
NOT_STATED = re.compile(r"not stated", re.I)


def brief_asks(project_id: int) -> list[tuple[str, str]]:
    spec = (store.get_latest_spec(project_id) or {}).get("spec") or {}
    scope = (spec.get("source_spec") or {}).get("included_scope") or {}
    return [("analysis", a) for a in scope.get("expected_analyses") or []] + \
           [("deliverable", d) for d in scope.get("deliverables") or []]


def _keys(section: Section) -> set[str]:
    if section.module == "entities":
        return {"entities", f"entities:{section.id.rsplit('-', 1)[-1]}"}
    return {section.module}


def _question_row(rq: RQ, sections: list[Section]) -> dict:
    kpi = next((s for s in sections if s.module == "share_kpi"), None)
    row = {"ask": rq.question, "kind": "question", "rq_id": rq.id, "slides": [], "modules": [s.id for s in sections]}
    if kpi is None or kpi.skipped:
        return {**row, "status": "missing", "note": (kpi.skipped if kpi else "") or "No articles for this question"}
    skipped = [s for s in sections if s.skipped and s.module != "share_kpi"]
    unstated = next((f for s in sections for f in s.facts if NOT_STATED.search(f)), "")
    if skipped or unstated:
        return {**row, "status": "partial", "note": unstated or "; ".join(f"{s.title}: {s.skipped}" for s in skipped)}
    return {**row, "status": "covered", "note": ""}


def _ask_row(kind: str, ask: str, sections: list[Section], has_brief_doc: bool) -> dict:
    low = ask.lower()
    row = {"ask": ask, "kind": kind, "rq_id": None, "slides": [], "modules": []}
    wanted = set().union(*[mods for pattern, mods in ASK_MODULES if re.search(pattern, low)])
    if not wanted:
        if DELIVERED.search(low) and (has_brief_doc or "summary" not in low):
            return {**row, "status": "covered", "note": "Delivered as this deck and the Word brief"}
        return {**row, "status": "missing", "note": "No analysis in this run matches this request"}
    drawn = [s for s in sections if not s.skipped and _keys(s) & wanted]
    if not drawn:
        return {**row, "status": "missing", "note": "The data has no field for this, so no matching analysis could run"}
    unstated = next((f for s in drawn for f in s.facts if NOT_STATED.search(f)), "")
    partial = bool(re.search("affiliat", low) and unstated)
    return {**row, "status": "partial" if partial else "covered", "note": unstated if partial else "",
            "modules": [s.id for s in drawn]}


def build_checklist(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], asks: list[tuple[str, str]],
                    has_brief_doc: bool = True) -> list[dict]:
    every = [s for secs in sections_by_rq.values() for s in secs]
    return [_question_row(rq, sections_by_rq.get(rq.id, [])) for rq in rqs] + \
           [_ask_row(kind, ask, every, has_brief_doc) for kind, ask in asks]


def attach_slide_numbers(spec: DeckSpec, rows: list[dict]) -> list[dict]:
    order = {s.id: n for n, s in enumerate(spec.slides, start=1)}
    out = []
    for r in rows:
        if r["rq_id"]:
            prefix = r["rq_id"].lower() + "-"
            slides = [n for sid, n in order.items() if sid.startswith(prefix)]
        else:
            slides = [n for sid, n in order.items() for m in r["modules"] if sid.startswith(m + "-")]
        out.append({**r, "slides": sorted(set(slides))})
    pages = [s for s in spec.slides if s.type == "checklist"]
    per = max(1, -(-len(out) // max(1, len(pages))))
    for i, slide in enumerate(pages):
        chunk = out[i * per:(i + 1) * per]
        slide.tables[0]["rows"] = [[r["ask"], r["status"], ", ".join(map(str, r["slides"])) or "—", r["note"]] for r in chunk]
        slide.facts_allowed = slide.facts_allowed + [str(n) for r in chunk for n in r["slides"]]
    return out
```

- [ ] **Step 4: run, expect PASS** (3 passed).
- [ ] **Step 5: commit** `feat(deckstudio): brief checklist with status, slides and reasons`.

---

### Task 5: Art director — brand-led tokens

**Files:** Create `agent/app/domains/deckstudio/art_director.py`; Test `agent/tests/test_deckstudio_art.py`

**Interfaces — Consumes:** `deliverable.brand_kit.contrast_ratio`, `DeckTokens`. **Produces:** `GOOGLE_FONTS`, `MIN_CONTRAST = 4.5`, `fallback_tokens(brand_colors) -> DeckTokens`, `choose_tokens(llm, brand_colors, intent, rules) -> (DeckTokens, "llm"|"fallback")`, `fonts_href(tokens) -> str`.

- [ ] **Step 1: failing tests**

```python
"""Brand-led tokens: the LLM picks, guards keep text readable, fallback without colours or LLM."""
from __future__ import annotations
import json
from agent.app.domains.deckstudio import art_director as A
from agent.app.domains.deliverable.brand_kit import contrast_ratio


class LLM:
    def __init__(self, payload): self.payload = payload
    def is_reachable(self): return True
    def chat(self, messages, format_json=False): return json.dumps(self.payload)


def test_llm_tokens_are_used_when_valid():
    tokens, source = A.choose_tokens(LLM({"background": "FFFDF8", "surface": "FFF1E8", "primary": "C2185B", "accent": "FFB74D",
                                          "text": "2B2B2B", "muted": "5F5F5F",
                                          "series": ["C2185B", "FFB74D", "4DB6AC", "7986CB", "A1887F", "90A4AE"],
                                          "title_font": "Fraunces", "body_font": "Nunito Sans", "mood": ["gentle", "warm"]}),
                                     ["C2185B"], "baby skincare, gentle and trusted", {})
    assert source == "llm" and tokens.primary == "C2185B" and tokens.title_font == "Fraunces"


def test_unreadable_llm_text_colour_is_corrected():
    tokens, _ = A.choose_tokens(LLM({"background": "FFFFFF", "text": "EEEEEE", "primary": "FFEEEE", "title_font": "Comic Sans MS"}),
                                ["FF0000"], "x", {})
    assert contrast_ratio(tokens.text, tokens.background) >= A.MIN_CONTRAST
    assert contrast_ratio(tokens.primary, tokens.background) >= 3
    assert tokens.title_font in A.GOOGLE_FONTS


def test_fallback_tokens_without_brand_colours_pass_contrast():
    tokens, source = A.choose_tokens(None, [], "anything", {})
    assert source == "fallback" and len(tokens.series) == 6
    assert contrast_ratio(tokens.text, tokens.background) >= A.MIN_CONTRAST
    assert "fonts.googleapis.com" in A.fonts_href(tokens)
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""Brand-led design tokens: the LLM reads the brand colours and the project intent and proposes palette,
fonts and mood; guards keep text readable and fonts loadable; without an LLM the brand colours drive it."""
from __future__ import annotations
import colorsys, json, logging, re
from urllib.parse import quote_plus
from ..deliverable.brand_kit import contrast_ratio
from .spec import DeckTokens

logger = logging.getLogger(__name__)
MIN_CONTRAST = 4.5
MIN_ACCENT_CONTRAST = 3.0
GOOGLE_FONTS = ("Inter", "Nunito Sans", "Source Sans 3", "Work Sans", "DM Sans", "Manrope", "Lato", "Montserrat",
                "Poppins", "Raleway", "Playfair Display", "Fraunces", "Lora", "Merriweather", "DM Serif Display",
                "Libre Baskerville", "Cormorant Garamond", "Space Grotesk", "Outfit", "Quicksand")
_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_PROMPT = ("You are an art director. From the brand colours and the project intent, propose design tokens for a "
           "research presentation that feels like the brand. Return JSON with keys background, surface, primary, "
           "accent, text, muted, series (6 distinguishable chart colours), title_font, body_font, mood (3-5 words "
           "for photo search). Hex colours without '#'. Fonts must come from this list: {fonts}.")


def _hex(v, default: str) -> str:
    v = str(v or "").lstrip("#")
    return v.upper() if _HEX.match(v) else default


def _darken(h: str, bg: str, minimum: float) -> str:
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    while contrast_ratio(h, bg) < minimum and light > 0.05:
        light -= 0.05
        r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        h = f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
    return h if contrast_ratio(h, bg) >= minimum else "1F1F1F"


def _series(base: list[str]) -> list[str]:
    out = list(dict.fromkeys(base))
    return (out + [c for c in DeckTokens().series if c not in out])[:6]


def _guard(t: DeckTokens) -> DeckTokens:
    t.text = _darken(t.text, t.background, MIN_CONTRAST)
    t.muted = _darken(t.muted, t.background, MIN_CONTRAST)
    t.primary = _darken(t.primary, t.background, MIN_ACCENT_CONTRAST)
    t.title_font = t.title_font if t.title_font in GOOGLE_FONTS else "Playfair Display"
    t.body_font = t.body_font if t.body_font in GOOGLE_FONTS else "Inter"
    r, g, b = (int(t.primary[i:i + 2], 16) for i in (0, 2, 4))
    t.overlay = f"linear-gradient(90deg, rgba({r},{g},{b},.88) 0%, rgba({r},{g},{b},.55) 55%, rgba({r},{g},{b},.15) 100%)"
    return t


def fallback_tokens(brand_colors: list[str]) -> DeckTokens:
    colors = [c for c in (_hex(c, "") for c in brand_colors) if c]
    t = DeckTokens()
    if colors:
        t.primary = colors[0]
        t.accent = colors[1] if len(colors) > 1 else t.accent
        t.series = _series(colors)
    return _guard(t)


def choose_tokens(llm, brand_colors: list[str], intent: str, rules: dict) -> tuple[DeckTokens, str]:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return fallback_tokens(brand_colors), "fallback"
    try:
        raw = json.loads(llm.chat([{"role": "system", "content": _PROMPT.format(fonts=", ".join(GOOGLE_FONTS))},
                                   {"role": "user", "content": json.dumps({"brand_colours": brand_colors, "intent": intent[:1500],
                                                                           "reference_fonts": [rules.get("title_font"), rules.get("body_font")]})}],
                                  format_json=True))
    except Exception as e:      # any LLM failure falls back to the brand colours
        logger.warning("art direction fell back: %s", type(e).__name__)
        return fallback_tokens(brand_colors), "fallback"
    base = fallback_tokens(brand_colors)
    t = DeckTokens(background=_hex(raw.get("background"), base.background), surface=_hex(raw.get("surface"), base.surface),
                   primary=_hex(raw.get("primary"), base.primary), accent=_hex(raw.get("accent"), base.accent),
                   text=_hex(raw.get("text"), base.text), muted=_hex(raw.get("muted"), base.muted),
                   series=_series([c for c in (_hex(c, "") for c in raw.get("series") or []) if c] or base.series),
                   title_font=str(raw.get("title_font") or ""), body_font=str(raw.get("body_font") or ""),
                   mood=[str(m) for m in raw.get("mood") or []][:5])
    return _guard(t), "llm"


def fonts_href(t: DeckTokens) -> str:
    fams = "&".join(f"family={quote_plus(f)}:wght@400;600;700" for f in dict.fromkeys([t.title_font, t.body_font]))
    return f"https://fonts.googleapis.com/css2?{fams}&display=swap"
```

- [ ] **Step 4: run, expect PASS** (3 passed).
- [ ] **Step 5: commit** `feat(deckstudio): brand-led design tokens with contrast and font guards`.

---

### Task 6: Asset finder — photos

**Files:** Create `agent/app/domains/deckstudio/assets.py`; Test `agent/tests/test_deckstudio_assets.py`

**Interfaces — Produces:** `Photo(path: Path|None, source_url: str, licence: "licensed"|"brand"|"web"|"none")`, `find_photo(query, role, folder, used:set[str], brand_image=None) -> Photo`, `crop_to(path, role, out) -> Path` (`background` → 1920×1080, `panel` → 672×1080), `MIN_WIDTH`, internals `_pexels(query) -> list[dict]`, `_serpapi(query) -> list[dict]` (`{url, width, title}`), `_download(url) -> bytes|None`.

- [ ] **Step 1: failing tests**

```python
"""Photos: licensed first, SerpAPI fallback, no repeats, cropped to the treatment, nothing -> no photo."""
from __future__ import annotations
from io import BytesIO
from PIL import Image
from agent.app.domains.deckstudio import assets


def _jpeg(w=2000, h=1300):
    buf = BytesIO(); Image.new("RGB", (w, h), (200, 150, 180)).save(buf, "JPEG"); return buf.getvalue()


def test_licensed_photo_is_preferred_and_cropped(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [{"url": "https://p/1.jpg", "width": 2400, "title": "baby lotion"}])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [{"url": "https://s/1.jpg", "width": 3000, "title": "x"}])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg())
    photo = assets.find_photo("baby lotion deals", "background", tmp_path, set())
    assert photo.licence == "licensed" and photo.source_url == "https://p/1.jpg"
    assert Image.open(photo.path).size == (1920, 1080)


def test_serpapi_fills_in_and_photos_never_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [{"url": "https://p/1.jpg", "width": 2400, "title": "baby"}])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [{"url": "https://s/2.jpg", "width": 2000, "title": "baby skincare"}])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg())
    used = {"https://p/1.jpg"}
    photo = assets.find_photo("baby skincare", "panel", tmp_path, used)
    assert photo.licence == "web" and photo.source_url == "https://s/2.jpg" and "https://s/2.jpg" in used
    assert Image.open(photo.path).size == (672, 1080)


def test_small_images_are_rejected_for_full_bleed(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [{"url": "https://p/s.jpg", "width": 800, "title": "baby"}])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg(800, 500))
    assert assets.find_photo("baby", "background", tmp_path, set()).licence == "none"


def test_no_photo_found_gives_gradient_background(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    photo = assets.find_photo("anything", "background", tmp_path, set())
    assert photo.path is None and photo.licence == "none"


def test_brand_image_is_used_before_web(tmp_path, monkeypatch):
    banner = tmp_path / "banner.png"; Image.new("RGB", (2000, 1200), "white").save(banner)
    monkeypatch.setattr(assets, "_pexels", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [{"url": "https://s/9.jpg", "width": 3000, "title": "x"}])
    assert assets.find_photo("brand", "background", tmp_path, set(), brand_image=banner).licence == "brand"
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""Slide photos: licensed (Pexels) and brand-owned first, SerpAPI Google Images as fallback; never the same
image twice; cropped to the slide treatment. Keys come from the environment and are never logged."""
from __future__ import annotations
import hashlib, logging, os, re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import requests
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
TIMEOUT_S = 15
MIN_WIDTH = {"background": 1600, "panel": 900}
SIZES = {"background": (1920, 1080), "panel": (672, 1080)}
PEXELS_URL = "https://api.pexels.com/v1/search"
SERP_URL = "https://serpapi.com/search.json"
MAX_TRIES = 4
_WORD = re.compile(r"[a-z]{3,}")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


@dataclass
class Photo:
    path: Path | None
    source_url: str
    licence: str


def _pexels(query: str) -> list[dict]:
    key = os.environ.get("PEXEL_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(PEXELS_URL, params={"query": query, "per_page": 10, "orientation": "landscape"},
                         headers={"Authorization": key}, timeout=TIMEOUT_S)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("pexels search failed: %s", type(e).__name__)
        return []
    return [{"url": p["src"].get("original") or p["src"].get("large2x"), "width": p.get("width", 0), "title": p.get("alt") or ""}
            for p in r.json().get("photos") or []]


def _serpapi(query: str) -> list[dict]:
    key = os.environ.get("SERP_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(SERP_URL, params={"engine": "google_images", "q": query, "api_key": key, "safe": "active"},
                         timeout=TIMEOUT_S)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("serpapi image search failed: %s", type(e).__name__)
        return []
    return [{"url": i.get("original"), "width": i.get("original_width") or 0, "title": i.get("title") or ""}
            for i in r.json().get("images_results") or [] if i.get("original")]


def _download(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT_S)
        if r.ok and r.headers.get("content-type", "image/").startswith("image/"):
            return r.content
    except requests.RequestException:
        pass
    try:      # some sites refuse plain requests; Scrapling fetches like a browser
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=TIMEOUT_S)
        return page.body if getattr(page, "status", 0) == 200 else None
    except Exception as e:
        logger.warning("image download failed: %s", type(e).__name__)
        return None


def crop_to(path: Path, role: str, out: Path) -> Path:
    img = ImageOps.fit(Image.open(path).convert("RGB"), SIZES[role], method=Image.LANCZOS, centering=(0.5, 0.45))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=86)
    return out


def _relevance(query: str, title: str) -> int:
    return len(set(_WORD.findall(query.lower())) & set(_WORD.findall(title.lower())))


def find_photo(query: str, role: str, folder: Path, used: set[str], brand_image: Path | None = None) -> Photo:
    slug = hashlib.sha1(f"{query}|{role}".encode()).hexdigest()[:12]
    if brand_image and brand_image.exists() and str(brand_image) not in used:
        with Image.open(brand_image) as im:
            wide_enough = im.width >= MIN_WIDTH[role]
        if wide_enough:
            used.add(str(brand_image))
            return Photo(crop_to(brand_image, role, folder / f"{slug}.jpg"), str(brand_image), "brand")
    for licence, results in (("licensed", _pexels(query)), ("web", _serpapi(query))):
        ranked = sorted((c for c in results if c["url"] and c["url"] not in used and c["width"] >= MIN_WIDTH[role]),
                        key=lambda c: -_relevance(query, c["title"]))
        for cand in ranked[:MAX_TRIES]:
            data = _download(cand["url"])
            if not data:
                continue
            try:
                with Image.open(BytesIO(data)) as im:
                    if im.width < MIN_WIDTH[role]:
                        continue
            except Exception:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            raw = folder / f"{slug}.src"
            raw.write_bytes(data)
            used.add(cand["url"])
            return Photo(crop_to(raw, role, folder / f"{slug}.jpg"), cand["url"], licence)
    return Photo(None, "", "none")
```

- [ ] **Step 4: run, expect PASS** (5 passed).
- [ ] **Step 5: commit** `feat(deckstudio): licensed-first photo finder with SerpAPI fallback, no repeats`.

---

### Task 7: Charts (inline SVG) and the HTML renderer

**Files:** Create `agent/app/domains/deckstudio/charts.py`, `agent/app/domains/deckstudio/renderer.py`, `agent/app/domains/deckstudio/templates/deck.html.j2`, `.../templates/slide.html.j2`, `.../templates/table.html.j2`; Test `agent/tests/test_deckstudio_render.py`

Ruling to ledger when executed: deck charts are inline SVG generated in Python, not amCharts (spec §5.5) — deterministic for screenshots, offline-safe, and logos sit exactly beside labels; the web page keeps amCharts.

**Interfaces — Consumes:** `DeckSpec, SlideSpec, DeckTokens`, `fonts_href`. **Produces:** `chart_svg(chart, tokens, logos, width, height) -> str`, `render_slide(slide, tokens, n, total, base_n, period, source, out_dir) -> str`, `render_deck(spec, out_dir, slide_html=None, source="Meltwater") -> Path` (writes `deck.html` + `assets/`), `slide_text(html) -> str`.

- [ ] **Step 1: failing tests**

```python
"""HTML deck: one file + assets, full questions, logos beside labels, photos by treatment, fits."""
from __future__ import annotations
from pathlib import Path
from PIL import Image
from agent.app.domains.deckstudio import charts, renderer
from agent.app.domains.deckstudio.spec import DeckSpec, DeckTokens, SlideSpec

Q = "What proportion of earned editorial coverage in the baby skincare category is deal/sale-led?"


def _png(path: Path, size=(40, 40)) -> str:
    Image.new("RGB", size, (90, 44, 157)).save(path); return str(path)


def make_spec(tmp_path, question=Q):
    photo = _png(tmp_path / "photo.jpg", (1920, 1080))
    logo = _png(tmp_path / "aveeno.png")
    slides = [SlideSpec("cover", "cover", "full", title="Baby Skincare", image={"path": photo}),
              SlideSpec("rq1-divider", "divider", "full", kicker="Question 1 of 1", question=question,
                        so_what="227 of 778 articles (29.2%)", image={"path": photo},
                        facts_allowed=["227 of 778 articles (29.2%)", "1"]),
              SlideSpec("rq1-brand_sov-0", "bar_with_cards", "A", kicker="Deals", title="Brands in deal-led coverage",
                        question=question, so_what="Aveeno leads",
                        charts=[{"kind": "bar", "categories": ["Aveeno", "Cetaphil"], "values": [60.0, 40.0], "unit": "percent", "peaks": []}],
                        logos={"Aveeno": logo}, image={"path": photo},
                        facts_allowed=["Brand Aveeno: 6 of 10 brand mentions (60.0%)", "Brand Cetaphil: 4 of 10 (40.0%)"]),
              SlideSpec("rq1-volume_trend-1", "trend_with_peaks", "C", kicker="Deals", title="Coverage over time", question=question,
                        charts=[{"kind": "line_peaks", "categories": [f"M{i}" for i in range(24)], "values": [i % 7 for i in range(24)], "peaks": [6], "unit": "count"}],
                        image={"path": photo}, facts_allowed=["Peak 1: M6 with 6 articles"])]
    return DeckSpec(1, "Baby Skincare", "Earned Editorial", "Jan 2025 - Dec 2026", 778, "topic_map", "", DeckTokens(), slides)


def test_bar_chart_has_logo_beside_its_label():
    svg = charts.chart_svg({"kind": "bar", "categories": ["Aveeno", "Cetaphil"], "values": [60.0, 40.0], "unit": "percent", "peaks": []},
                           DeckTokens(), {"Aveeno": "assets/aveeno.png"}, 900, 400)
    assert "<image" in svg and "assets/aveeno.png" in svg and "60.0%" in svg and "Cetaphil" in svg


def test_long_trend_axis_skips_labels():
    svg = charts.chart_svg({"kind": "line_peaks", "categories": [f"M{i}" for i in range(40)], "values": list(range(40)), "peaks": [39], "unit": "count"},
                           DeckTokens(), {}, 1100, 500)
    assert svg.count('class="xlab"') <= 12 and ">39<" in svg


def test_deck_is_one_file_with_assets_and_full_questions(tmp_path):
    html = renderer.render_deck(make_spec(tmp_path), tmp_path / "out").read_text(encoding="utf-8")
    assert html.count('<section class="slide"') == 4 and Q in html and "RQ1" not in renderer.slide_text(html)
    assert (tmp_path / "out" / "assets").exists() and "assets/" in html
    assert 'data-treatment="A"' in html and 'data-treatment="C"' in html


def test_missing_photo_becomes_a_token_gradient(tmp_path):
    spec = make_spec(tmp_path)
    spec.slides[2].image = {}
    html = renderer.render_deck(spec, tmp_path / "g").read_text(encoding="utf-8")
    assert "linear-gradient(135deg" in html


def test_long_question_fits_the_slide(tmp_path):
    from agent.app.domains.deckstudio import guards
    long_q = "How does " + "very detailed parenting and skincare coverage " * 8 + "change?"
    path = renderer.render_deck(make_spec(tmp_path, long_q), tmp_path / "long")
    assert guards.layout_issues(path) == []
```

(`test_long_question_fits_the_slide` needs Task 8's `guards`; it fails until Task 8 lands, then passes.)

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement `charts.py`:**

```python
"""Inline SVG charts for the HTML deck: deterministic, offline, screenshot-safe; logos beside labels,
skipped axis labels on long series, annotated peaks."""
from __future__ import annotations
import math
from html import escape
from .spec import DeckTokens

MAX_X_LABELS = 12
LABEL_W = 230
LOGO = 26
MAX_LABEL_CHARS = 24


def _short(s: str) -> str:
    s = str(s)
    return s if len(s) <= MAX_LABEL_CHARS else s[:MAX_LABEL_CHARS - 1] + "…"


def _fmt(v: float, unit: str) -> str:
    v = float(v)
    return f"{v:.1f}%" if unit == "percent" else (str(int(v)) if v.is_integer() else f"{v:.1f}")


def _bars(c, t, logos, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    top = max(vals) or 1
    row = min(56, (h - 10) / max(1, len(cats)))
    out = []
    for i, (cat, v) in enumerate(zip(cats, vals)):
        y = 5 + i * row
        bw = (w - LABEL_W - 110) * v / top
        label_x = LABEL_W - (LOGO + 14 if cat in logos else 8)
        out.append(f'<text class="ylab" x="{label_x}" y="{y + row * .62:.1f}" text-anchor="end">{escape(_short(cat))}</text>')
        if cat in logos:
            out.append(f'<image href="{escape(logos[cat])}" x="{LABEL_W - LOGO - 4}" y="{y + row / 2 - LOGO / 2:.1f}" '
                       f'width="{LOGO}" height="{LOGO}" preserveAspectRatio="xMidYMid meet"/>')
        out.append(f'<rect x="{LABEL_W + 6}" y="{y + row * .18:.1f}" width="{max(bw, 3):.1f}" height="{row * .64:.1f}" rx="4" '
                   f'fill="#{t.series[0]}" opacity="{0.45 + 0.55 * v / top:.2f}"/>')
        out.append(f'<text class="val" x="{LABEL_W + 14 + bw:.1f}" y="{y + row * .62:.1f}">{_fmt(v, c.get("unit", "count"))}</text>')
    return out


def _line(c, t, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    top, n = (max(vals) or 1), max(1, len(vals) - 1)
    pl, pb, pt = 40, 46, 40
    xs = [pl + (w - pl - 30) * i / n for i in range(len(vals))]
    ys = [pt + (h - pt - pb) * (1 - v / top) for v in vals]
    step = max(1, -(-len(cats) // MAX_X_LABELS))
    out = [f'<line x1="{pl}" y1="{h - pb}" x2="{w - 30}" y2="{h - pb}" stroke="#{t.muted}" stroke-opacity=".35"/>',
           f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))}" fill="none" '
           f'stroke="#{t.series[0]}" stroke-width="4" stroke-linejoin="round"/>']
    out += [f'<text class="xlab" x="{xs[i]:.1f}" y="{h - pb + 28}" text-anchor="middle">{escape(_short(cats[i]))}</text>'
            for i in range(0, len(cats), step)]
    for p in c.get("peaks") or []:
        if 0 <= p < len(vals):
            out.append(f'<circle cx="{xs[p]:.1f}" cy="{ys[p]:.1f}" r="8" fill="#{t.primary}"/>')
            out.append(f'<text class="peak" x="{xs[p]:.1f}" y="{ys[p] - 16:.1f}" text-anchor="middle">{_fmt(vals[p], "count")}</text>')
    return out


def _doughnut(c, t, w, h):
    cats, vals = c["categories"], [float(v) for v in c["values"]]
    total = sum(vals) or 1
    cx = cy = h / 2
    r = h / 2 - 30
    out, a0 = [], -math.pi / 2
    for i, (cat, v) in enumerate(zip(cats, vals)):
        a1 = a0 + 2 * math.pi * v / total - 1e-4
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        out.append(f'<path d="M{x0:.1f},{y0:.1f} A{r:.1f},{r:.1f} 0 {1 if a1 - a0 > math.pi else 0} 1 {x1:.1f},{y1:.1f}" '
                   f'fill="none" stroke="#{t.series[i % 6]}" stroke-width="{r * .42:.1f}"/>')
        ly = 40 + i * 40
        out.append(f'<rect x="{h + 30}" y="{ly}" width="18" height="18" rx="4" fill="#{t.series[i % 6]}"/>')
        out.append(f'<text class="ylab" x="{h + 58}" y="{ly + 16}">{escape(_short(cat))} · {_fmt(v, c.get("unit", "count"))}</text>')
        a0 = a1 + 1e-4
    return out


def _kpi(c, t, w, h):
    v = (c.get("values") or [0])[0]
    return [f'<text class="kpi" x="{w / 2}" y="{h * .66:.1f}" text-anchor="middle" fill="#{t.primary}">{_fmt(v, c.get("unit", "percent"))}</text>']


def chart_svg(chart: dict, tokens: DeckTokens, logos: dict[str, str], width: int, height: int) -> str:
    kind = chart.get("kind")
    if kind in ("bar", "treemap"):
        body = _bars(chart, tokens, logos, width, height)
    elif kind in ("line_peaks", "column"):
        body = _line(chart, tokens, width, height)
    elif kind == "doughnut":
        body = _doughnut(chart, tokens, width, height)
    else:
        body = _kpi(chart, tokens, width, height)
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="100%" '
            f'preserveAspectRatio="xMinYMin meet" xmlns="http://www.w3.org/2000/svg">{"".join(body)}</svg>')
```

`renderer.py`:

```python
"""Renders a DeckSpec into one HTML deck (frontend-slides-style viewport-safe base) with an assets folder."""
from __future__ import annotations
import re, shutil
from html import unescape
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .art_director import fonts_href
from .charts import chart_svg
from .spec import DeckSpec, DeckTokens, SlideSpec

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
_TAG = re.compile(r"<[^>]+>")
CHART_SIZE = {"A": (1000, 540), "C": (1100, 600), "plain": (1600, 600), "full": (900, 420)}


def _asset(path: str | None, out_dir: Path) -> str | None:
    if not path or not Path(path).exists():
        return None
    target = out_dir / "assets" / Path(path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(path).resolve() != target.resolve():
        shutil.copyfile(path, target)
    return f"assets/{target.name}"


def render_slide(slide: SlideSpec, tokens: DeckTokens, n: int, total: int, base_n: int, period: str, source: str,
                 out_dir: Path) -> str:
    image = _asset(slide.image.get("path"), out_dir)
    logos = {name: rel for name, p in slide.logos.items() if (rel := _asset(p, out_dir))}
    w, h = CHART_SIZE.get(slide.treatment, (1000, 540))
    charts = [chart_svg(c, tokens, logos, w, h) for c in slide.charts]
    return _env.get_template("slide.html.j2").render(s=slide, t=tokens, n=n, total=total, base_n=base_n, period=period,
                                                     source=source, image=image, charts=charts)


def render_deck(spec: DeckSpec, out_dir: Path, slide_html: dict[str, str] | None = None, source: str = "Meltwater") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = spec.tokens or DeckTokens()
    parts = [(slide_html or {}).get(s.id) or render_slide(s, tokens, n, len(spec.slides), spec.base_n, spec.period, source, out_dir)
             for n, s in enumerate(spec.slides, start=1)]
    html = _env.get_template("deck.html.j2").render(spec=spec, t=tokens, fonts=fonts_href(tokens), slides=parts)
    path = out_dir / "deck.html"
    path.write_text(html, encoding="utf-8")
    return path


def slide_text(html: str) -> str:
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", html))).strip()
```

`templates/deck.html.j2` (viewport-safe base adapted from frontend-slides: every slide is a 1920×1080 stage scaled to the window; `?export=1` stacks slides for screenshots; clamped text classes `title`, `question`, `sowhat`, `card h3`, `card p` hide extra lines by design):

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ spec.title }} — {{ spec.subtitle }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="{{ fonts }}" rel="stylesheet">
<style>
:root{--bg:#{{t.background}};--surface:#{{t.surface}};--primary:#{{t.primary}};--accent:#{{t.accent}};--text:#{{t.text}};
--muted:#{{t.muted}};--on-dark:#{{t.on_dark}};--overlay:{{t.overlay}};--title:'{{t.title_font}}',Georgia,serif;--body:'{{t.body_font}}',Arial,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#111;height:100%;overflow:hidden;font-family:var(--body);color:var(--text)}
.deck{position:relative;width:100vw;height:100vh}
.slide{position:absolute;left:50%;top:50%;width:1920px;height:1080px;overflow:hidden;background:var(--bg);display:none}
.slide.active{display:block}
body.export{overflow:visible;background:#fff;height:auto}
body.export .deck{width:1920px;height:auto}
body.export .slide{position:relative;left:0;top:0;transform:none!important;display:block}
.photo{position:absolute;background-size:cover;background-position:center}
.overlay{position:absolute;inset:0;background:var(--overlay)}
.kicker{font:700 20px/1.2 var(--body);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.clamp{overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical}
.title{font:700 50px/1.12 var(--title);color:var(--text);-webkit-line-clamp:3}
.question{font:700 44px/1.2 var(--title);-webkit-line-clamp:4}
.sowhat{font:700 24px/1.4 var(--body);-webkit-line-clamp:6}
.panel{position:absolute;background:rgba(255,255,255,.94);border-radius:22px;padding:28px;box-shadow:0 18px 50px rgba(0,0,0,.18)}
.cards{display:grid;gap:22px}
.card{background:var(--surface);border-radius:18px;padding:24px;overflow:hidden}
.card h3{font:700 24px/1.25 var(--title);color:var(--primary);margin-bottom:10px;-webkit-line-clamp:3}
.card p{font:400 19px/1.45 var(--body);-webkit-line-clamp:6}
.footer{position:absolute;left:0;right:0;bottom:0;height:44px;padding:12px 60px;font:600 14px var(--body);letter-spacing:.12em;
text-transform:uppercase;color:var(--muted);display:flex;justify-content:space-between}
.nlabel{font:700 20px var(--body);color:var(--primary)}
table{width:100%;border-collapse:collapse;font:400 17px/1.35 var(--body);table-layout:fixed}
th{background:var(--primary);color:var(--on-dark);text-align:left;padding:12px 14px;font-weight:700}
td{padding:10px 14px;border-bottom:1px solid rgba(0,0,0,.08);vertical-align:top;overflow:hidden;word-wrap:break-word}
.status-covered{color:#2E7D32;font-weight:700}.status-partial{color:#B26A00;font-weight:700}.status-missing{color:#C62828;font-weight:700}
svg.chart text{font-family:var(--body);fill:var(--text)} svg .ylab{font-size:22px} svg .xlab{font-size:18px;fill:var(--muted)}
svg .val{font-size:21px;font-weight:700} svg .peak{font-size:21px;font-weight:700;fill:var(--primary)} svg .kpi{font:700 160px var(--title)}
@media (prefers-reduced-motion:no-preference){body:not(.export) .slide.active .reveal{animation:rise .6s ease both}}
@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
</style></head>
<body><div class="deck">
{% for html in slides %}{{ html | safe }}
{% endfor %}</div>
<script>
// Presentation controller: keyboard, wheel and touch navigation; scales the 1920x1080 stage to the window.
const slides=[...document.querySelectorAll('.slide')];let i=0;
const exportMode=new URLSearchParams(location.search).has('export');
if(exportMode){document.body.classList.add('export');slides.forEach(s=>s.classList.add('active'));}
function fit(){if(exportMode)return;const k=Math.min(innerWidth/1920,innerHeight/1080);
slides.forEach(s=>s.style.transform=`translate(-50%,-50%) scale(${k})`);}
function show(n){i=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,j)=>s.classList.toggle('active',j===i));}
addEventListener('resize',fit);
addEventListener('keydown',e=>{if(['ArrowRight','PageDown',' '].includes(e.key))show(i+1);if(['ArrowLeft','PageUp'].includes(e.key))show(i-1);});
let lock=0;addEventListener('wheel',e=>{if(Date.now()-lock<500)return;lock=Date.now();show(i+(e.deltaY>0?1:-1));});
let x0=null;addEventListener('touchstart',e=>x0=e.touches[0].clientX);
addEventListener('touchend',e=>{if(x0===null)return;const dx=e.changedTouches[0].clientX-x0;if(Math.abs(dx)>40)show(i+(dx<0?1:-1));x0=null;});
fit();if(!exportMode)show(0);
</script></body></html>
```

`templates/slide.html.j2`:

```html
{% set bg = ("url('" ~ image ~ "')") if image else ("linear-gradient(135deg,#" ~ t.accent ~ ",#" ~ t.primary ~ ")") %}
<section class="slide" data-id="{{ s.id }}" data-type="{{ s.type }}" data-treatment="{{ s.treatment }}">
{% if s.treatment == "full" %}
  <div class="photo" style="inset:0;background-image:{{ bg }}"></div><div class="overlay"></div>
  <div class="reveal" style="position:absolute;left:110px;right:110px;top:{{ 520 if s.type == 'cover' else 330 }}px;color:var(--on-dark)">
    {% if s.kicker %}<div class="kicker" style="color:var(--on-dark);opacity:.85">{{ s.kicker }}</div>{% endif %}
    {% if s.question %}<div class="question clamp" style="margin-top:18px">{{ s.question }}</div>
    {% else %}<div class="title clamp" style="color:var(--on-dark);font-size:84px">{{ s.title }}</div>{% endif %}
    {% if s.so_what %}<div class="sowhat clamp" style="margin-top:22px;opacity:.95">{{ s.so_what }}</div>{% endif %}
    {% if s.type == 'cover' and s.notes %}<div class="kicker" style="margin-top:26px;color:var(--on-dark);opacity:.8">{{ s.notes }}</div>{% endif %}
  </div>
{% elif s.treatment == "A" %}
  <div class="photo" style="inset:0;background-image:{{ bg }}"></div><div class="overlay"></div>
  <div style="position:absolute;left:70px;top:56px;width:1120px;color:var(--on-dark)">
    {% if s.kicker %}<div class="kicker" style="color:var(--on-dark);opacity:.85">{{ s.kicker }}</div>{% endif %}
    <div class="title clamp" style="color:var(--on-dark);margin-top:10px;font-size:46px">{{ s.question or s.title }}</div>
  </div>
  {% if s.so_what %}<div class="sowhat clamp" style="position:absolute;right:70px;top:66px;width:560px;color:var(--on-dark)">{{ s.so_what }}</div>{% endif %}
  <div class="panel reveal" style="left:70px;top:320px;width:{{ 1090 if (charts and s.cards) else 1780 }}px;height:680px">
    {% if s.title and s.question %}<div class="kicker" style="margin-bottom:12px">{{ s.title }}</div>{% endif %}
    {% if charts %}<div style="height:580px">{{ charts[0] | safe }}</div>
    {% elif s.tables and s.type != 'scorecard' %}{% include "table.html.j2" %}
    {% else %}<div class="cards" style="grid-template-columns:repeat({{ [s.cards|length, 3]|min or 1 }},1fr)">
      {% for c in s.cards[:6] %}<div class="card"><h3 class="clamp">{{ c.headline }}</h3><p class="clamp">{{ c.text }}{% if c.note %} — {{ c.note }}{% endif %}</p></div>{% endfor %}</div>
      {% if s.type == 'scorecard' and s.tables and s.tables[0].rows %}<div style="margin-top:22px">{% include "table.html.j2" %}</div>{% endif %}
    {% endif %}
  </div>
  {% if charts and s.cards %}<div class="cards reveal" style="position:absolute;left:1190px;right:70px;top:320px;grid-template-columns:1fr">
    {% for c in s.cards[:3] %}<div class="card" style="background:rgba(255,255,255,.94)"><h3 class="clamp">{{ c.headline }}</h3><p class="clamp">{{ c.text }}</p></div>{% endfor %}</div>{% endif %}
  {% if charts %}<div class="nlabel" style="position:absolute;right:80px;top:280px;color:var(--on-dark)">N = {{ base_n }}</div>{% endif %}
{% elif s.treatment == "C" %}
  <div class="photo" style="left:0;top:0;bottom:0;width:672px;background-image:{{ bg }}"></div>
  <div class="overlay" style="right:auto;width:672px"></div>
  {% if s.so_what %}<div class="sowhat clamp" style="position:absolute;left:56px;bottom:90px;width:560px;color:var(--on-dark)">{{ s.so_what }}</div>{% endif %}
  <div style="position:absolute;left:740px;right:70px;top:56px">
    {% if s.kicker %}<div class="kicker">{{ s.kicker }}</div>{% endif %}
    <div class="title clamp" style="margin-top:10px;font-size:40px">{{ s.question or s.title }}</div>
    {% if s.question and s.title %}<div class="kicker" style="margin-top:14px;color:var(--muted)">{{ s.title }}</div>{% endif %}
  </div>
  <div class="nlabel" style="position:absolute;right:80px;top:290px">N = {{ base_n }}</div>
  <div class="reveal" style="position:absolute;left:740px;right:70px;top:330px;height:660px;overflow:hidden">
    {% if charts %}{{ charts[0] | safe }}{% elif s.tables %}{% include "table.html.j2" %}{% endif %}
  </div>
{% else %}
  <div style="position:absolute;left:70px;right:70px;top:56px">
    {% if s.kicker %}<div class="kicker">{{ s.kicker }}</div>{% endif %}
    <div class="title clamp" style="margin-top:10px">{{ s.title }}</div>
  </div>
  <div class="reveal" style="position:absolute;left:70px;right:70px;top:210px;bottom:80px;overflow:hidden">
    {% if s.tables %}{% include "table.html.j2" %}
    {% else %}{% for c in s.cards %}<p style="font-size:22px;line-height:1.5;margin-bottom:12px">{{ c.text }}</p>{% endfor %}{% endif %}
  </div>
{% endif %}
  {% if s.type not in ("cover", "closing", "divider") %}
  <div class="footer"><span>Source: {{ source }} | {{ period }}</span><span>{{ n }} / {{ total }}</span></div>{% endif %}
</section>
```

`templates/table.html.j2`:

```html
{% set tb = s.tables[0] %}<table><thead><tr>{% for h in tb.header %}<th>{{ h }}</th>{% endfor %}</tr></thead><tbody>
{% for row in tb.rows[:12] %}<tr>{% for cell in row %}<td{% if cell in ("covered", "partial", "missing") %} class="status-{{ cell }}"{% endif %}>{{ cell }}</td>{% endfor %}</tr>{% endfor %}
</tbody></table>
```

- [ ] **Step 4: run** — all but `test_long_question_fits_the_slide` PASS (that one after Task 8).
- [ ] **Step 5: commit** `feat(deckstudio): SVG charts with logos beside labels and the HTML deck renderer`.

---

### Task 8: Guards — numbers, layout, reference text

**Files:** Create `agent/app/domains/deckstudio/guards.py`; Test `agent/tests/test_deckstudio_guards.py`

**Interfaces — Consumes:** `core.llm_synthesis._figures`, `deliverable.factcheck._with_rounding`, `indexer.SHINGLE`, `renderer.slide_text`. **Produces:** `number_issues(text, facts_allowed) -> list[str]`, `copied_text(text, shingles) -> list[str]`, `layout_issues(html_path) -> list[dict]` (`{slide_id, kind: overflow|off_slide, detail}`), `slide_html_map(html) -> dict[str,str]`, `slide_visible_text(section_html) -> str`.

- [ ] **Step 1: failing tests**

```python
"""Guards that decide whether a slide ships."""
from __future__ import annotations
from pathlib import Path
from agent.app.domains.deckstudio import guards


def test_numbers_must_come_from_facts():
    assert guards.number_issues("29.2% of 778 articles; 29% overall", ["227 of 778 articles (29.2%)"]) == []
    assert guards.number_issues("41% of coverage", ["227 of 778 articles (29.2%)"]) == ["41%"]


def test_copied_reference_text_is_found():
    shingles = {("the", "above", "insights", "are", "based", "on")}
    assert guards.copied_text("Note: the above insights are based on a sample", shingles)
    assert guards.copied_text("Our own sentence about coverage here", shingles) == []


def _page(tmp_path: Path, inner: str) -> Path:
    p = tmp_path / "d.html"
    p.write_text("<html><body class='export'><style>.slide{position:relative;width:1920px;height:1080px;overflow:hidden}"
                 ".clamp{overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2}</style>"
                 "<section class='slide' data-id='s1'>" + inner + "</section></body></html>", encoding="utf-8")
    return p


def test_layout_flags_overflow_and_off_slide_but_not_clamped_text(tmp_path):
    ok = _page(tmp_path, "<div style='position:absolute;left:10px;top:10px;width:300px'>fine</div>"
                         "<div class='clamp' style='position:absolute;left:10px;top:400px;width:200px'>" + "word " * 200 + "</div>")
    assert guards.layout_issues(ok) == []
    bad = _page(tmp_path, "<div style='position:absolute;left:1800px;top:10px;width:400px'>off the edge</div>"
                          "<div style='position:absolute;left:10px;top:200px;width:200px;height:30px;overflow:hidden'>" + "word " * 200 + "</div>")
    assert {"off_slide", "overflow"} <= {i["kind"] for i in guards.layout_issues(bad)}
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""Guards: a slide ships only if its numbers are in its facts, it fits 1920x1080, and it copies no
reference-deck text."""
from __future__ import annotations
import re
from pathlib import Path
from ...core.llm_synthesis import _figures
from ..deliverable.factcheck import _with_rounding
from .indexer import SHINGLE
from .renderer import slide_text

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_SLIDE_COUNT = re.compile(r"\b\d+\s*/\s*\d+\b")
_WORD = re.compile(r"[a-z0-9']+")
_SECTION = re.compile(r'(<section class="slide[^"]*" data-id="([^"]+)".*?</section>)', re.S)
_LAYOUT_JS = """() => {
  const out = [];
  document.querySelectorAll('.slide').forEach(slide => {
    const id = slide.dataset.id, box = slide.getBoundingClientRect();
    slide.querySelectorAll('*').forEach(el => {
      if (el.closest('svg')) return;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (!own) return;
      if (r.right > box.right + 1 || r.bottom > box.bottom + 1 || r.left < box.left - 1 || r.top < box.top - 1)
        out.push({slide_id: id, kind: 'off_slide', detail: el.textContent.trim().slice(0, 60)});
      const cs = getComputedStyle(el), clamped = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
      if (!clamped && cs.overflow !== 'visible' && (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2))
        out.push({slide_id: id, kind: 'overflow', detail: el.textContent.trim().slice(0, 60)});
    });
  });
  return out;
}"""


def number_issues(text: str, facts_allowed: list[str]) -> list[str]:
    allowed = _with_rounding(_figures(" ".join(facts_allowed)))
    return sorted(_figures(_SLIDE_COUNT.sub(" ", _YEAR.sub(" ", text))) - allowed)


def copied_text(text: str, shingles: set) -> list[str]:
    words = _WORD.findall(text.lower())
    return sorted({" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)
                   if tuple(words[i:i + SHINGLE]) in shingles})


def layout_issues(html_path: Path) -> list[dict]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(html_path).resolve().as_uri() + "?export=1")
        page.wait_for_timeout(400)
        issues = page.evaluate(_LAYOUT_JS)
        browser.close()
    return issues


def slide_html_map(html: str) -> dict[str, str]:
    return {m.group(2): m.group(1) for m in _SECTION.finditer(html)}


def slide_visible_text(section_html: str) -> str:
    return slide_text(section_html)
```

- [ ] **Step 4: run** guards → PASS; re-run `test_deckstudio_render.py` → all PASS.
- [ ] **Step 5: commit** `feat(deckstudio): number, layout and reference-text guards`.

---

### Task 9: LLM creative pass with fallback

**Files:** Create `agent/app/domains/deckstudio/creative.py`; Test `agent/tests/test_deckstudio_creative.py`

**Interfaces — Consumes:** `render_deck`, guards, `DeckSpec`. **Produces:** `_sanitise(html) -> str`, `creative_slide(llm, slide_html, slide, tokens, reference) -> str|None`, `compose(spec, out_dir, llm, shingles, progress=None, workers=4) -> (Path, list[dict])` (report rows `{slide_id, source: creative|template, reasons}`).

- [ ] **Step 1: failing tests**

```python
"""The creative pass may restyle a slide; a slide that invents numbers, copies reference text or breaks the
layout falls back to its template."""
from __future__ import annotations
from agent.app.domains.deckstudio import creative
from agent.tests.test_deckstudio_render import make_spec


class LLM:
    def __init__(self, html_for): self.html_for = html_for
    def is_reachable(self): return True
    def chat(self, messages, format_json=False):
        sid = messages[-1]["content"].split('data-id="', 1)[1].split('"', 1)[0]
        return self.html_for(sid)


def _section(sid, body):
    return (f'<section class="slide" data-id="{sid}" data-type="x" data-treatment="A">'
            f'<div style="position:absolute;left:80px;top:80px;width:900px">{body}</div></section>')


def test_creative_slide_is_kept_when_guards_pass(tmp_path):
    llm = LLM(lambda sid: _section(sid, "Aveeno leads with 60.0% of brand mentions"))
    path, report = creative.compose(make_spec(tmp_path), tmp_path / "out", llm, set())
    assert {r["slide_id"]: r for r in report}["rq1-brand_sov-0"]["source"] == "creative"
    assert "Aveeno leads with 60.0%" in path.read_text(encoding="utf-8")


def test_creative_slide_with_invented_number_falls_back(tmp_path):
    llm = LLM(lambda sid: _section(sid, "Aveeno leads with 73% of mentions"))
    path, report = creative.compose(make_spec(tmp_path), tmp_path / "out", llm, set())
    row = next(r for r in report if r["slide_id"] == "rq1-brand_sov-0")
    assert row["source"] == "template" and any("73%" in r for r in row["reasons"])
    assert "73%" not in path.read_text(encoding="utf-8")


def test_copied_reference_text_falls_back(tmp_path):
    llm = LLM(lambda sid: _section(sid, "the above insights are based on analysis"))
    _, report = creative.compose(make_spec(tmp_path), tmp_path / "out", llm, {("the", "above", "insights", "are", "based", "on")})
    assert all(r["source"] == "template" for r in report)


def test_scripts_and_remote_urls_are_stripped():
    html = creative._sanitise('<section class="slide" data-id="a"><script>x()</script><img src="https://evil/x.png">'
                              '<div onclick="x()">ok</div></section>')
    assert "<script" not in html and "evil" not in html and "onclick" not in html and "ok" in html


def test_no_llm_means_template_only(tmp_path):
    path, report = creative.compose(make_spec(tmp_path), tmp_path / "out", None, set())
    assert path.exists() and all(r["source"] == "template" for r in report)
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""Per-slide LLM creative pass. The model may restyle a slide's HTML within the deck's tokens; the result
ships only if every guard passes, otherwise the template version does."""
from __future__ import annotations
import logging, re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import guards
from .renderer import render_deck
from .spec import DeckSpec, DeckTokens, SlideSpec

logger = logging.getLogger(__name__)
_SECTION = re.compile(r"<section\b.*?</section>", re.S | re.I)
_BAD = [re.compile(p, re.S | re.I) for p in (r"<script\b.*?</script>", r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')",
                                               r"<iframe\b.*?</iframe>", r"<link\b[^>]*>")]
_REMOTE = re.compile(r"""\s(src|href)\s*=\s*["'](https?:)?//[^"']*["']""", re.I)
_PROMPT = ("You are a presentation designer. Improve this one slide's HTML (a 1920x1080 <section>) so it looks "
           "premium and on-brand. Keep the same data-id, every number and every word of the question exactly as "
           "given; never add numbers. Use only the CSS variables --primary, --accent, --text, --muted, --surface, "
           "--on-dark, --overlay, --title, --body and the existing assets/ images. No scripts, no external URLs, "
           "nothing outside the slide. Return only the <section>...</section>.")


def _sanitise(html: str) -> str:
    for bad in _BAD:
        html = bad.sub("", html)
    return _REMOTE.sub("", html)


def creative_slide(llm, slide_html: str, slide: SlideSpec, tokens: DeckTokens, reference: dict) -> str | None:
    try:
        reply = llm.chat([{"role": "system", "content": _PROMPT},
                          {"role": "user", "content": f"Reference layout: {reference or 'none'}\nSlide:\n{slide_html}"}])
    except Exception as e:      # the creative pass is optional
        logger.warning("creative pass skipped for %s: %s", slide.id, type(e).__name__)
        return None
    m = _SECTION.search(reply or "")
    if not m or f'data-id="{slide.id}"' not in m.group(0):
        return None
    return _sanitise(m.group(0))


def compose(spec: DeckSpec, out_dir: Path, llm, shingles: set, progress=None, workers: int = 4) -> tuple[Path, list[dict]]:
    template_path = render_deck(spec, out_dir)
    template_html = guards.slide_html_map(template_path.read_text(encoding="utf-8"))
    report = {s.id: {"slide_id": s.id, "source": "template", "reasons": []} for s in spec.slides}
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return template_path, list(report.values())
    tokens = spec.tokens or DeckTokens()
    candidates: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {s.id: pool.submit(creative_slide, llm, template_html.get(s.id, ""), s, tokens, s.reference) for s in spec.slides}
        for k, s in enumerate(spec.slides, start=1):
            html = futures[s.id].result()
            if progress:
                progress(k, len(spec.slides), s.id)
            if not html:
                report[s.id]["reasons"].append("no usable creative version")
                continue
            text = guards.slide_visible_text(html)
            allowed = s.facts_allowed + [str(spec.base_n), s.question, s.kicker, s.title, spec.period]
            bad = guards.number_issues(text, allowed)
            copied = guards.copied_text(text, shingles)
            if bad or copied:
                report[s.id]["reasons"] += [f"number not in facts: {n}" for n in bad] + [f"copied: {c}" for c in copied]
                continue
            candidates[s.id] = html
    path = render_deck(spec, out_dir, candidates)
    for issue in guards.layout_issues(path):
        if candidates.pop(issue["slide_id"], None) is not None:
            report[issue["slide_id"]]["reasons"].append(f"layout: {issue['kind']} ({issue['detail']})")
    for sid in candidates:
        report[sid]["source"] = "creative"
    return render_deck(spec, out_dir, candidates), list(report.values())
```

- [ ] **Step 4: run, expect PASS** (5 passed).
- [ ] **Step 5: commit** `feat(deckstudio): guarded LLM creative pass per slide`.

---

### Task 10: Exporter — pixel-perfect PPTX and PDF

**Files:** Create `agent/app/domains/deckstudio/exporter.py`; Test `agent/tests/test_deckstudio_export.py`

**Interfaces — Produces:** `screenshot_slides(html_path, out_dir) -> list[Path]`, `build_pptx(pngs, spec, out) -> Path`, `build_pdf(pngs, out) -> Path`, `export_all(html_path, spec, out_dir, stem) -> {"pngs", "pptx", "pdf"}`.

- [ ] **Step 1: failing test**

```python
"""Pixel-perfect PPTX and PDF: one full-slide picture per slide, titles and notes kept."""
from __future__ import annotations
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from agent.app.domains.deckstudio import exporter, renderer
from agent.tests.test_deckstudio_render import make_spec


def test_every_html_slide_becomes_one_pptx_slide_and_pdf_page(tmp_path):
    spec = make_spec(tmp_path)
    html = renderer.render_deck(spec, tmp_path / "deck")
    out = exporter.export_all(html, spec, tmp_path / "export", "Baby Skincare")
    assert len(out["pngs"]) == len(spec.slides)
    prs = Presentation(out["pptx"])
    assert len(prs.slides) == len(spec.slides)
    second = prs.slides[1]
    pics = [sh for sh in second.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert pics and pics[0].width == prs.slide_width and pics[0].height == prs.slide_height
    assert spec.slides[1].question in second.notes_slide.notes_text_frame.text
    assert out["pdf"].read_bytes()[:4] == b"%PDF"
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement:**

```python
"""Pixel-perfect exports of the HTML deck: each slide screenshotted at 1920x1080 into a 16:9 PPTX (one full
picture per slide; the title kept under it for search and accessibility; slide text in the notes) and a PDF."""
from __future__ import annotations
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Inches
from .spec import DeckSpec

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
SETTLE_MS = 900


def screenshot_slides(html_path: Path, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(html_path).resolve().as_uri() + "?export=1", wait_until="networkidle")
        page.wait_for_timeout(SETTLE_MS)
        for k, el in enumerate(page.query_selector_all("section.slide"), start=1):
            path = out_dir / f"slide_{k:02d}.png"
            el.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths


def build_pptx(pngs: list[Path], spec: DeckSpec, out: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    layout = prs.slide_layouts[5]          # "Title Only": the title stays searchable under the picture
    for png, s in zip(pngs, spec.slides):
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = s.question or s.title or spec.title
        slide.shapes.add_picture(str(png), Emu(0), Emu(0), SLIDE_W, SLIDE_H)
        lines = [s.kicker, s.question or s.title, s.so_what] + [f"{c.get('headline', '')}: {c.get('text', '')}" for c in s.cards]
        slide.notes_slide.notes_text_frame.text = "\n".join(x for x in lines if x)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out


def build_pdf(pngs: list[Path], out: Path) -> Path:
    images = [Image.open(p).convert("RGB") for p in pngs]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=144)
    return out


def export_all(html_path: Path, spec: DeckSpec, out_dir: Path, stem: str) -> dict:
    pngs = screenshot_slides(html_path, out_dir / "slides")
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in " -_").strip() or "Deck"
    return {"pngs": pngs, "pptx": build_pptx(pngs, spec, out_dir / f"{safe} - Deck.pptx"),
            "pdf": build_pdf(pngs, out_dir / f"{safe} - Deck.pdf")}
```

- [ ] **Step 4: run, expect PASS.**
- [ ] **Step 5: commit** `feat(deckstudio): pixel-perfect PPTX and PDF export`.

---

### Task 11: Engine stages, downloads and the Deliverables page

**Files:** Create `agent/app/domains/deckstudio/pipeline.py`; Modify `agent/app/domains/deliverable/engine.py`, `agent/app/domains/deliverable/generic_deck.py` (`DeckInput.brand_colors`), `agent/app/domains/deliverable/router.py`, `web/src/components/deliverable/RunTimeline.tsx`, `web/src/components/deliverable/RunProgress.tsx`, `web/src/services/intel-api.ts`, `web/src/pages/DeliverablesPage.tsx`; Test `agent/tests/test_deckstudio_pipeline.py`

**Interfaces — Produces:** `run_studio(run, project_id, llm, plan_input, brand_colors, brand_image, logos, out_dir) -> dict` (`html, pptx, pdf, family, family_reason, checklist, scorecard, report, assets, spec, deck_dir`); engine STAGES += `index, design, assets, compose, export`; weights `gate 1, ingest 3, routing 2, plan 5, classify 28, compute 3, insights 14, template 2, render 8, qc 4, index 4, design 3, assets 8, compose 10, export 5`; run columns filled; `studio` section `{id, family, family_reason, checklist, scorecard, slides:[{id,type,treatment,reference,source}]}`; downloads `html|pdf|studio_pptx`; `GET /api/intel/deliverable/{pid}/runs/{rid}/deck/{asset_path:path}` (files inside `deck_dir` only); frontend `deliverableDeckUrl(pid, runId, path)`.

- [ ] **Step 1: failing tests** (copy the auth override from `agent/tests/test_deliverable_api.py` if it differs)

```python
"""The engine produces the studio deck (HTML, PPTX, PDF) with checklist and per-slide sources; offline works."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from pathlib import Path
from agent.app.core import store
from agent.app.domains.deckstudio import assets, indexer
from agent.app.domains.deliverable import engine
from agent.tests.test_deliverable_engine import _offline
from agent.tests.test_deliverable_rows import _project


def studio_offline(monkeypatch, tmp_path):
    _offline(monkeypatch, tmp_path)
    monkeypatch.setattr(engine, "_gate_reasons", lambda project_id: [])
    monkeypatch.setattr(assets, "_pexels", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    monkeypatch.setattr(indexer, "index_library", lambda folder=None, progress=None:
                        {"indexed": 0, "unchanged": 0, "skipped": 0, "removed": 0})


def test_run_produces_studio_outputs_and_section(tmp_path, monkeypatch):
    studio_offline(monkeypatch, tmp_path)
    pid = _project(tmp_path)
    monkeypatch.setattr(engine, "broadcast", lambda m: None)
    run_id = engine.start_run(pid, llm=None, threaded=False)
    run = store.get_deliverable_run(run_id)
    assert run["status"] == "completed", run["error"]
    for key in ("html_path", "pdf_path", "studio_pptx_path"):
        assert Path(run[key]).exists()
    studio = next(s for s in engine.run_payload(run_id)["sections"] if s["id"] == "studio")
    assert studio["checklist"] and set(studio["scorecard"]) == {"covered", "partial", "missing"}
    assert {"index", "design", "assets", "compose", "export"} <= set(run["stages"])
    body = Path(run["html_path"]).read_text(encoding="utf-8").split("<body", 1)[1].split("<script", 1)[0]
    assert "RQ1" not in body
```

API test (append; follows the existing API test file's client/auth pattern):

```python
def test_deck_assets_are_served_only_from_the_run_folder(tmp_path, monkeypatch):
    from agent.tests.test_deliverable_api import client_for   # or the equivalent helper that file defines
    studio_offline(monkeypatch, tmp_path)
    pid = _project(tmp_path)
    monkeypatch.setattr(engine, "broadcast", lambda m: None)
    run_id = engine.start_run(pid, llm=None, threaded=False)
    client = client_for(pid)
    assert "<section" in client.get(f"/api/intel/deliverable/{pid}/runs/{run_id}/deck/deck.html").text
    assert client.get(f"/api/intel/deliverable/{pid}/runs/{run_id}/deck/..%2F..%2Fmemory.db").status_code == 404
    pdf = client.get(f"/api/intel/deliverable/{pid}/runs/{run_id}/download/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement `pipeline.py`:**

```python
"""Deck Studio stages inside a deliverable run: index the reference library, design (checklist + plan +
tokens), find assets, compose (render + creative pass), export."""
from __future__ import annotations
import json
from pathlib import Path
from . import art_director, assets, checklist, creative, exporter, indexer, planner
from .planner import PlanInput


def run_studio(run, project_id: int, llm, plan_input: PlanInput, brand_colors: list[str], brand_image: Path | None,
               logos: dict[str, Path], out_dir: Path) -> dict:
    deck_dir = out_dir / "deck"
    run.stage("index", "running")
    summary = indexer.index_library(progress=lambda i, n, name: run.within("index", i / max(1, n), f"Reading reference deck {i} of {n}"))
    run.log(f"Reference library: {summary['indexed']} indexed, {summary['unchanged']} unchanged, "
            f"{summary['skipped']} skipped, {summary['removed']} removed")
    run.stage("index", "done")

    run.stage("design", "running")
    rows = checklist.build_checklist(plan_input.rqs, plan_input.sections_by_rq, checklist.brief_asks(project_id))
    plan_input.checklist = rows
    spec = planner.build_deck_spec(plan_input)
    rows = checklist.attach_slide_numbers(spec, rows)
    spec.tokens, source = art_director.choose_tokens(llm, brand_colors, plan_input.scope_text, indexer.design_rules(spec.family))
    run.log(f"Design family: {spec.family} - {spec.family_reason}")
    run.log(f"Palette and fonts ({source}): {spec.tokens.title_font} / {spec.tokens.body_font}, primary #{spec.tokens.primary}")
    for s in spec.slides:
        if s.reference:
            run.log(f"{s.id}: layout from {Path(s.reference['deck']).stem} slide {s.reference['slide']} ({s.reference['why']})")
    run.stage("design", "done", spec.family)

    run.stage("assets", "running")
    used: set[str] = set()
    found = []
    mood = " ".join(spec.tokens.mood[:2])
    for k, s in enumerate(spec.slides, start=1):
        run.within("assets", k / len(spec.slides), f"Finding photos and logos for slide {k} of {len(spec.slides)}")
        if s.treatment in ("A", "C", "full") and s.image.get("query"):
            role = "panel" if s.treatment == "C" else "background"
            photo = assets.find_photo(f"{s.image['query']} {mood}".strip(), role, deck_dir / "photos", used,
                                      brand_image if s.type == "cover" else None)
            s.image["path"] = str(photo.path) if photo.path else None
            found.append({"slide": s.id, "source": photo.source_url, "licence": photo.licence})
            if photo.path:
                run.log(f"Photo for {s.id}: {photo.licence} source {photo.source_url[:90]}")
        names = [c for ch in s.charts for c in ch.get("categories", [])]
        s.logos = {n: str(logos[n]) for n in names if n in logos}
    run.stage("assets", "done", f"{sum(1 for f in found if f['licence'] != 'none')} photos")

    run.stage("compose", "running")
    html, report = creative.compose(spec, deck_dir, llm, indexer.reference_text_shingles(),
                                    progress=lambda i, n, sid: run.within("compose", i / max(1, n), f"Designing slide {i} of {n}"))
    for r in report:
        if r["reasons"] and r["reasons"][0] != "no usable creative version":
            run.log(f"{r['slide_id']}: template version kept - {r['reasons'][0]}")
    run.stage("compose", "done", f"{sum(1 for r in report if r['source'] == 'creative')} slides restyled")
    (deck_dir / "spec.json").write_text(json.dumps(spec.to_dict(), default=str), encoding="utf-8")

    run.stage("export", "running")
    out = exporter.export_all(html, spec, deck_dir, spec.title)
    run.stage("export", "done", f"{len(out['pngs'])} slides")
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("covered", "partial", "missing")}
    return {"html": html, "pptx": out["pptx"], "pdf": out["pdf"], "family": spec.family, "family_reason": spec.family_reason,
            "checklist": rows, "scorecard": counts, "report": report, "assets": found, "spec": spec, "deck_dir": deck_dir}
```

Engine (`deliverable/engine.py`): extend `STAGES` with `"index", "design", "assets", "compose", "export"`, replace `STAGE_WEIGHTS` with the weights above, add labels to `_STAGE_LABELS` ("Reading reference decks", "Designing the deck", "Finding photos & logos", "Composing slides", "Exporting PPTX & PDF"). Add `brand_colors: list[str] = field(default_factory=list)` to `generic_deck.DeckInput` and pass `brand_colors=kit.colors` in `_deck_input`. Add:

```python
def _plan_input(project: dict, inp, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways, methodology,
                base: int, rq_titles: dict[str, str]) -> PlanInput:
    spec = project.get("spec") or {}
    geography = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
    return PlanInput(title=inp.title, subtitle=inp.subtitle, period=inp.period_label, base_n=base, rqs=rqs,
                     rq_titles=rq_titles, sections_by_rq=sections_by_rq, insights_by_rq=insights_by_rq,
                     answers=answers, takeaways=takeaways, overview=overview, methodology=methodology,
                     citations=inp.citations, scope_text=_scope_text(project), brands=list(inp.logos),
                     geography=str(geography), sources="Meltwater")
```

and, after the QC block and before the completion update:

```python
        current = "index"
        studio = run_studio(run, project_id, llm,
                            _plan_input(project, inp, rqs, overview, sections_by_rq, insights_by_rq, answers, takeaways,
                                        methodology, base, {q.id: plans[q.id]["title"] for q in rqs}),
                            inp.brand_colors, inp.brand_image, inp.logos, out_dir)
        run.section({"id": "studio", "rq_id": None, "module": "studio", "title": "Deck",
                     "family": studio["family"], "family_reason": studio["family_reason"],
                     "checklist": studio["checklist"], "scorecard": studio["scorecard"],
                     "slides": [{"id": s.id, "type": s.type, "treatment": s.treatment, "reference": s.reference,
                                 "source": next((r["source"] for r in studio["report"] if r["slide_id"] == s.id), "template")}
                                for s in studio["spec"].slides]})
```

The completion `store.update_deliverable_run(...)` gains `html_path=str(studio["html"]), pdf_path=str(studio["pdf"]), studio_pptx_path=str(studio["pptx"]), deck_dir=str(studio["deck_dir"])`. Imports: `from ..deckstudio.pipeline import run_studio` and `from ..deckstudio.planner import PlanInput`.

Router:

```python
_MEDIA.update({"html": "text/html", "pdf": "application/pdf",
               "studio_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"})


@router.get("/deliverable/{project_id}/runs/{run_id}/deck/{asset_path:path}", response_class=FileResponse)
def deck_asset(project_id: ProjectId, run_id: RunId, asset_path: str, _: Access):
    run = _owned_run(project_id, run_id)
    root = Path(run.get("deck_dir") or "")
    target = (root / asset_path).resolve()
    if not run.get("deck_dir") or not target.is_file() or root.resolve() not in target.parents:
        raise HTTPException(404, "File not available")
    return FileResponse(target)
```

Frontend: `RunTimeline.tsx` and `RunProgress.tsx` stage arrays and names gain the five stages; `intel-api.ts`: `deliverableDownloadUrl(pid, runId, kind: "pptx" | "docx" | "html" | "pdf" | "studio_pptx")`, `deliverableDeckUrl = (pid, runId, path) => \`${API_BASE}/deliverable/${pid}/runs/${runId}/deck/${path}\``, and `DeliverableSection` gains `family?, family_reason?, checklist?: {ask, kind, status, slides: number[], note}[], scorecard?: {covered, partial, missing}`; `DeliverablesPage.tsx`: when the `studio` section exists, a "Presentation" card above the classic outputs with the iframe preview (`aspect-video w-full rounded-xl border`), "Design: {family} — {family_reason}", covered/partial/missing pills and the gap rows, and buttons "Download .pptx" (`studio_pptx`), "Download .pdf", "Open HTML deck" (new tab, `deliverableDeckUrl(..., "deck.html")`); the existing buttons are relabelled "Classic deck (.pptx)" and "Word brief (.docx)".

- [ ] **Step 4: run** pipeline tests → PASS; `PY -m pytest agent/tests/ -q -k "deliverable or deckstudio or evidence_source" -p no:cacheprovider` → all PASS; `cd web && npx tsc --noEmit && npm run build` → clean.
- [ ] **Step 5: commit** `feat(deckstudio): studio stages in the deliverable run, deck downloads and page preview`.

---

### Task 12: The generic deck-studio skill (fork of frontend-slides) and CLI

**Files:** Create `.claude/skills/deck-studio/SKILL.md`, `.claude/skills/deck-studio/DESIGN_RULES.md`, `agent/app/domains/deckstudio/cli.py`; Test `agent/tests/test_deckstudio_cli.py`

**Interfaces — Produces:** CLI `PY -m agent.app.domains.deckstudio.cli {index | rules [--family F] | spec --run ID | render --spec S --out D [--no-creative] | export --html H --spec S --out D}`.

- [ ] **Step 1: failing test**

```python
"""The skill's CLI renders and exports a deck from a saved slide spec."""
from __future__ import annotations
import json, subprocess, sys
from agent.tests.test_deckstudio_render import make_spec


def test_cli_render_and_export_from_spec(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(make_spec(tmp_path).to_dict()), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "agent.app.domains.deckstudio.cli", "render", "--spec", str(spec_path),
                        "--out", str(tmp_path / "deck"), "--no-creative"], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "deck" / "deck.html").exists()
    r = subprocess.run([sys.executable, "-m", "agent.app.domains.deckstudio.cli", "export", "--html", str(tmp_path / "deck" / "deck.html"),
                        "--spec", str(spec_path), "--out", str(tmp_path / "deck")], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    assert list((tmp_path / "deck").glob("*.pptx")) and list((tmp_path / "deck").glob("*.pdf"))
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement `cli.py`:**

```python
"""Command line for the deck-studio skill: index references, show rules, render and export from a slide spec."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from ...core import store
from . import exporter, indexer
from .creative import compose
from .spec import DeckSpec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deck-studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    sub.add_parser("rules").add_argument("--family", default="topic_map")
    sub.add_parser("spec").add_argument("--run", type=int, required=True)
    rd = sub.add_parser("render"); rd.add_argument("--spec", required=True); rd.add_argument("--out", required=True)
    rd.add_argument("--no-creative", action="store_true")
    ex = sub.add_parser("export"); ex.add_argument("--html", required=True); ex.add_argument("--spec", required=True)
    ex.add_argument("--out", required=True)
    a = p.parse_args(argv)
    store.init_intelligence_db()
    if a.cmd == "index":
        print(json.dumps(indexer.index_library()))
    elif a.cmd == "rules":
        print(json.dumps(indexer.design_rules(a.family), indent=2))
    elif a.cmd == "spec":
        print(Path((store.get_deliverable_run(a.run) or {}).get("deck_dir") or "") / "spec.json")
    elif a.cmd == "render":
        spec = DeckSpec.from_dict(json.loads(Path(a.spec).read_text(encoding="utf-8")))
        llm = None
        if not a.no_creative:
            from ...core.anthropic_client import get_llm_client
            llm = get_llm_client()
        path, report = compose(spec, Path(a.out), llm, indexer.reference_text_shingles())
        print(json.dumps({"html": str(path), "slides": report}))
    else:
        spec = DeckSpec.from_dict(json.loads(Path(a.spec).read_text(encoding="utf-8")))
        out = exporter.export_all(Path(a.html), spec, Path(a.out), spec.title)
        print(json.dumps({"pptx": str(out["pptx"]), "pdf": str(out["pdf"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`.claude/skills/deck-studio/SKILL.md`:

```markdown
---
name: deck-studio
description: Build or refine a brand-led presentation (HTML deck + pixel-perfect PPTX/PDF) whose layouts are learned from a folder of reference decks. Use when the user wants a deck for research findings, wants to restyle or fix slides of a generated deck, or adds new reference decks. Fork of frontend-slides that follows the reference library's design rules instead of fixed presets.
---

# Deck Studio

Turns structured findings into a presentation that looks like the decks in the reference folder (any
organisation's decks), styled for the client's brand. Uses the app's renderer, guards and exporter.

## Non-negotiables (kept from frontend-slides)
1. One self-contained HTML deck plus `assets/`; every slide is one 1920x1080 stage and fits with no scrolling.
2. Distinctive, brand-led design; never a generic template look.
3. Every number on a slide comes from the run's facts; questions appear in full; no reference-deck text is copied.
4. Logos sit beside the label they belong to; photos by chart density (A full-bleed for light slides, C photo
   panel for dense ones); no photo credit text on slides.

## Workflow
1. **Find the material.** For an app run: `python -m agent.app.domains.deckstudio.cli spec --run <id>` prints the
   slide spec path. Otherwise ask for the findings (questions, numbers, sources) and write a spec JSON following
   `DESIGN_RULES.md` → Slide spec.
2. **Clarify only what is missing**, one question at a time: purpose and audience, the brand (colours, logo), the
   intent or mood, anything the brief asked for that the material does not cover.
3. **Learn the references:** `cli index`, then `cli rules --family <family>`; choose the family the brief fits.
4. **Art direction:** set `deck.tokens` from the brand colours and the intent (`DESIGN_RULES.md` → Tokens);
   text contrast at least 4.5:1; fonts from the Google Fonts list.
5. **Edit the spec** for the user's requests: reorder, rewrite a so-what, change a treatment, swap a photo query.
6. **Render:** `cli render --spec spec.json --out <dir>` (`--no-creative` for template-only). The report says which
   slides kept their template version and why.
7. **Export:** `cli export --html <dir>/deck.html --spec spec.json --out <dir>` gives the `.pptx` and `.pdf`.
8. **Check before handing over:** no overflow, every question in full, the "Did we answer the brief?" scorecard
   and checklist present, every Missing or Partial row has a reason.
```

`DESIGN_RULES.md`: the `DeckSpec` / `SlideSpec` / `DeckTokens` fields with one line each (copy from `spec.py`), the token guards (contrast 4.5 text / 3.0 primary, Google Fonts list), the treatment rule (A / C / full / plain with the 6-bar threshold and dense kinds), the planner's slide sequence, and the reference-library findings from the spec §4.

- [ ] **Step 4: run, expect PASS.**
- [ ] **Step 5: commit** `feat(deckstudio): generic deck-studio skill and CLI` (adds `.claude/skills/deck-studio/*` and `cli.py`).

---

### Task 13: Acceptance on project 261

**Files:** Create `agent/tests/acceptance_deckstudio_261.py` (local only)

- [ ] **Step 1: write the checker**

```python
"""Checks the latest deliverable run of project 261 against the Deck Studio spec §8."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pptx import Presentation
from agent.app.core import store
from agent.app.domains.deckstudio import guards, indexer
from agent.app.domains.deckstudio.renderer import slide_text
from agent.app.domains.deliverable.rows import load_rqs

run = store.get_latest_deliverable_run(261)
assert run and run["status"] == "completed", run
studio = next(s for s in store.list_deliverable_sections(run["id"]) if s["id"] == "studio")
html_path = Path(run["html_path"]); html = html_path.read_text(encoding="utf-8")
body = slide_text(html.split("<body", 1)[1].split("<script", 1)[0])
slides = guards.slide_html_map(html)
pdf = Path(run["pdf_path"]).read_bytes()
checks = {
    "every slide fits (no overflow/off-slide)": guards.layout_issues(html_path) == [],
    "no RQ codes on slides": not re.search(r"\bRQ\d+\b", body),
    "every question in full": all(q.question in body for q in load_rqs(261)),
    "no reference deck text": guards.copied_text(body, indexer.reference_text_shingles()) == [],
    "photos or gradients on A/C/full slides": all(("assets/" in h or "linear-gradient(135deg" in h)
                                                   for h in slides.values() if re.search(r'data-treatment="(A|C|full)"', h)),
    "logos beside labels": "<image" in html,
    "scorecard + checklist": any('data-type="scorecard"' in h for h in slides.values())
                             and any('data-type="checklist"' in h for h in slides.values()),
    "gaps have reasons": all(r["note"] for r in studio["checklist"] if r["status"] != "covered"),
    "pptx slides == html slides": len(Presentation(run["studio_pptx_path"]).slides) == len(slides),
    "pdf pages == html slides": pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") == len(slides),
    "no photo credit text": "Pexels" not in body and "Photo:" not in body,
}
print(f"slides={len(slides)} family={studio['family']} creative={sum(1 for s in studio['slides'] if s['source'] == 'creative')}")
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
```

- [ ] **Step 2:** restart the backend (GateGuard facts first), regenerate 261 in-process (`engine.start_run(261, llm=get_llm_client(), threaded=False)` script in `$TEMP/gen261.py`), run the checker. Expected: all PASS.
- [ ] **Step 3:** visual review — read 6–8 PNGs from `deck_dir/slides/` (cover, divider, an A slide, a C slide, scorecard, checklist, closing); fix ugliness at its source with a failing test first.
- [ ] **Step 4:** full suite `PY -m pytest agent/tests/ -q --ignore=agent/tests/test_e2e_live_workflow.py -p no:cacheprovider` → green; commit fixes as they arise.

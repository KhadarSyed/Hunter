# Deliverable Engine (Visual Deck + Streaming Page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Generate Deliverable" turns any project's approved scope, RQs and uploaded files into a cited,
brand-styled PPTX (charts, tables, logos, brand colours, fonts and images, icons, labels) plus a Word brief,
streaming every stage and section live on the Deliverables page.

**Architecture:** A generalised engine in `agent/app/domains/deliverable/` runs ten persisted stages
(gate → ingest → routing → plan → classify → compute → insights → template → render → qc) in a background
thread, broadcasting `deliverable_*` messages on the existing `/ws`. It reuses the reference deck's proven
pieces (`blocks.py` native charts/tables/cards, `insights.draft_section` validated cited insights,
`CitationRegistry`, `qc.py`, `gauge.py`) and replaces the Baby-Skincare-only theme wiring with an
LLM-chosen, catalog-validated module plan per RQ. The brand kit (colours, fonts, images, logo) comes from the
Brandfetch Brand API. The frontend draws the same persisted chart specs with amCharts 5 through one
`ChartRenderer`.

**Tech Stack:** Python 3.12, FastAPI, SQLite, python-pptx, python-docx, Playwright (PNG rendering of
amCharts gauge/treemap and Iconify icons), Pillow, Brandfetch Brand API v2, PowerPoint COM (QC PNG export);
React 18 + TypeScript + Vite, `@amcharts/amcharts5` 5.20.8.

**Spec:** `docs/superpowers/specs/2026-10-06-streaming-deliverable-engine-design.md` (revised 2026-10-07,
approved: both phases at once; charts = native PPTX + free amCharts for gauge/treemap and the web page;
brand colours, fonts and images from Brandfetch).

## Global Constraints

- Light backgrounds only (white + soft tint); no dark or grey slide backgrounds (`qc.DARK_LUMINANCE = 0.6`).
- Deck charts are native, editable PPTX charts with data labels; amCharts only for gauge and treemap images and
  for the web page; amCharts pinned to `5.20.8` (its free-build logo is accepted).
- Brand kit from Brandfetch (`GET https://api.brandfetch.io/v2/brands/{domain}`, `Authorization: Bearer
  BRANDFETCH_API_KEY`): colours → light chart tints (contrast-checked against white); title font used for
  headings only when it is a Google or system-safe font, else Arial; banner image on the cover. No kit → house
  palette + Arial; nothing breaks. `BRANDFETCH_API_KEY` is never logged, cached or returned.
- No invented numbers: every figure on a slide, in an insight or in the Word brief must appear in the computed
  facts; insights without a valid citation are dropped.
- A failed stage stops the run visibly (`deliverable_failed`); nothing is invented to fill a gap. When Azure is
  unreachable, modules needing extraction are skipped and labelled; enrichment-based modules run.
- Services reach SQLite only through `from ...core import store`; new SQL lives in
  `agent/app/domains/deliverable/repository.py` (re-exported by `core/store.py`).
- File paths come from `core.config` constants (`DELIVERABLE_DIR`, `TEMPLATES_DIR`), never `Path(__file__)`.
- Services never import a `router.py`.
- Base N = unique articles (by normalised URL) across all RQs; every share states its base.
- Tests live in `agent/tests/`; run with the real interpreter
  (`/c/Users/khadar.syed/AppData/Local/Programs/Python/Python312/python.exe -m pytest …`, written below as
  `python -m pytest`). Frontend checks: `cd web && npx tsc --noEmit` and `npm run build`.

## Review Focus

1. An RQ whose files were all removed or excluded (zero rows) → its section says "No articles for this
   question" and no empty chart is drawn; the run still completes. (Task 6, Task 10 tests)
2. Rows with no parseable date → the trend module is skipped for that RQ with a note "N undated articles";
   other modules still render. (Task 6 test)
3. Azure unreachable / `llm.is_reachable()` False → default plan, extraction modules marked skipped, insights
   fall back to `draft_section`'s deterministic backfill; run status `completed`. (Task 13 test)
4. Malformed Meltwater Boolean (unbalanced parentheses or quotes, trailing operator) → evaluator returns "no
   match" for that query instead of raising; file routing still applies. (Task 2 test)
5. A second "Generate" while a run is active for the same project → HTTP 409 "A deliverable run is already in
   progress". (Task 14 test)
6. Brand with no Brandfetch kit, a dark-only brand palette, or a custom (non-Google) brand font → house
   palette / lightened tints / Arial headings; no dark fills, no missing-font substitution surprises. (Task 9 test)

---

## File Structure

Backend (`agent/app/domains/deliverable/`):

| File | Responsibility |
|---|---|
| `engine_types.py` (new) | `EngineRow`, `RQ`, `Section` dataclasses shared by every stage |
| `repository.py` (new) | SQL for runs, sections, classification cache, reference-deck index |
| `boolean_query.py` (new) | Local Meltwater Boolean evaluator |
| `rows.py` (new) | Ingest approved datasets → `EngineRow`s, RQ routing, stories/copies, base N |
| `catalog.py` (new) | Module catalog, plan validation, default plan, LLM planner |
| `extract.py` (new) | Per-article LLM entity extraction with URL cache |
| `analytics.py` (new) | Module computations → `Section`s with chart/table specs and facts |
| `engine_insights.py` (new) | Per-RQ cited insights + executive answers (wraps `insights.draft_section`) |
| `templates_index.py` (new) | Index `PPT Templates/`, choose the closest usable reference deck |
| `brand_kit.py` (new) | Brandfetch Brand API → colours, fonts, images, logo; palette + font selection |
| `visuals.py` (new) | Logos for many brands, Iconify icons → PNG, country flags, category hero image |
| `amcharts_png.py` (new) | Treemap HTML + shared Playwright PNG renderer |
| `generic_deck.py` (new) | Render the PPTX from sections for any project |
| `word_brief.py` (new) | Word brief mirroring the sections |
| `factcheck.py` (new) | Every slide figure ⊆ facts; QC auto-fix loop |
| `engine.py` (new) | Orchestrator: stages, persistence, `/ws` events, concurrency lock |
| `schemas.py`, `router.py` (new) | API |
| `blocks.py` (modify) | `add_doughnut(..., colors=None)`, `add_text(..., font=None)`, `add_header(..., font=None)` |

Also: `core/config.py` (paths), `core/db.py` (migration 19), `core/store.py` (re-export),
`domains/__init__.py` (mount), `domains/execution/*` + `methods/executors.py` (evidence source fields).

Frontend: `web/package.json` (amCharts), `web/src/components/deliverable/ChartRenderer.tsx` (new),
`web/src/components/deliverable/RunTimeline.tsx` (new), `web/src/services/intel-api.ts` (deliverable API),
`web/src/pages/DeliverablesPage.tsx` (rewrite), `web/src/pages/DataSources.tsx` (proceed button).

---

### Task 1: Paths, schema and repository

**Files:**
- Modify: `agent/app/core/config.py` (after `EXPORT_DIR`)
- Modify: `agent/app/core/db.py` (append migration 19 to `MIGRATIONS`)
- Create: `agent/app/domains/deliverable/repository.py`
- Modify: `agent/app/core/store.py` (add re-export)
- Test: `agent/tests/test_deliverable_repository.py`

**Interfaces:**
- Produces: `config.DELIVERABLE_DIR: Path`, `config.TEMPLATES_DIR: Path`;
  `store.create_deliverable_run(project_id) -> int`, `store.update_deliverable_run(run_id, **fields) -> None`
  (fields: `status, stage, stages_json (dict), pptx_path, docx_path, thumbs_dir, error, finished_at`),
  `store.get_deliverable_run(run_id) -> dict | None` (decodes `stages`),
  `store.get_latest_deliverable_run(project_id) -> dict | None`,
  `store.get_active_deliverable_run(project_id) -> dict | None` (status `running`),
  `store.save_deliverable_section(run_id, section: dict) -> int`,
  `store.list_deliverable_sections(run_id) -> list[dict]` (decoded section dicts in insert order),
  `store.get_cached_classification(norm_url, field) -> list | None`,
  `store.save_cached_classification(norm_url, field, value: list, model: str) -> None`,
  `store.save_reference_deck(path, text, embedding: list[float] | None) -> None`,
  `store.list_reference_decks() -> list[dict]` (`path, text, embedding`).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_repository.py
"""Persistence for deliverable runs, streamed sections, the classification cache and the template index."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.core import config, store


def setup_module(_):
    store.init_intelligence_db()


def test_paths_come_from_config():
    assert config.DELIVERABLE_DIR.name == "deliverables" and config.DELIVERABLE_DIR.exists()
    assert config.TEMPLATES_DIR.name == "PPT Templates"


def test_run_lifecycle_and_active_lookup(tmp_path):
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Run {tmp_path.name}"}})
    run = store.create_deliverable_run(pid)
    assert store.get_active_deliverable_run(pid)["id"] == run
    store.update_deliverable_run(run, stage="render", stages_json={"gate": "done"}, status="completed",
                                 pptx_path="x.pptx")
    got = store.get_deliverable_run(run)
    assert got["stage"] == "render" and got["stages"] == {"gate": "done"} and got["pptx_path"] == "x.pptx"
    assert store.get_active_deliverable_run(pid) is None
    assert store.get_latest_deliverable_run(pid)["id"] == run


def test_sections_round_trip_in_order(tmp_path):
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Sec {tmp_path.name}"}})
    run = store.create_deliverable_run(pid)
    store.save_deliverable_section(run, {"id": "rq1-kpi", "rq_id": "RQ1", "module": "share_kpi",
                                         "chart": {"kind": "kpi"}, "facts": ["54 of 225 articles (24%)"]})
    store.save_deliverable_section(run, {"id": "rq1-trend", "rq_id": "RQ1", "module": "volume_trend"})
    assert [s["id"] for s in store.list_deliverable_sections(run)] == ["rq1-kpi", "rq1-trend"]
    assert store.list_deliverable_sections(run)[0]["facts"] == ["54 of 225 articles (24%)"]


def test_classification_cache_and_template_index():
    assert store.get_cached_classification("https://a.com/x", "experts") is None
    store.save_cached_classification("https://a.com/x", "experts", [{"name": "Dr A"}], "gpt")
    assert store.get_cached_classification("https://a.com/x", "experts") == [{"name": "Dr A"}]
    store.save_reference_deck("PPT Templates/a.pptx", "baby skincare editorial", [0.1, 0.2])
    assert any(d["path"] == "PPT Templates/a.pptx" and d["embedding"] == [0.1, 0.2]
               for d in store.list_reference_decks())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_repository.py -q`
Expected: FAIL — `AttributeError: module 'agent.app.core.config' has no attribute 'DELIVERABLE_DIR'`.

- [ ] **Step 3: Implement**

`agent/app/core/config.py` — after `EXPORT_DIR = DATA_DIR / "exports"` add:

```python
DELIVERABLE_DIR = DATA_DIR / "deliverables"
DELIVERABLE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = AGENT_DIR.parent / "PPT Templates"   # reference decks shipped with the repo
```

`agent/app/core/db.py` — append to `MIGRATIONS` (after version 18):

```python
    (19, "deliverable engine", [
        "ALTER TABLE intel_evidence ADD COLUMN url TEXT",
        "ALTER TABLE intel_evidence ADD COLUMN document_id TEXT",
        "ALTER TABLE intel_evidence ADD COLUMN source_file TEXT",
        "ALTER TABLE intel_evidence ADD COLUMN row_index INTEGER",
        """CREATE TABLE IF NOT EXISTS intel_deliverable_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'running', stage TEXT, stages_json TEXT,
            pptx_path TEXT, docx_path TEXT, thumbs_dir TEXT, error TEXT,
            created_at REAL NOT NULL, finished_at REAL)""",
        "CREATE INDEX IF NOT EXISTS idx_deliv_runs_project ON intel_deliverable_runs(project_id)",
        """CREATE TABLE IF NOT EXISTS intel_deliverable_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, section_key TEXT NOT NULL,
            rq_id TEXT, module TEXT, payload_json TEXT NOT NULL, created_at REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_deliv_sections_run ON intel_deliverable_sections(run_id)",
        """CREATE TABLE IF NOT EXISTS intel_article_classifications (
            norm_url TEXT NOT NULL, field TEXT NOT NULL, value_json TEXT NOT NULL, model TEXT,
            created_at REAL NOT NULL, PRIMARY KEY (norm_url, field))""",
        """CREATE TABLE IF NOT EXISTS intel_reference_decks (
            path TEXT PRIMARY KEY, text TEXT, embedding_json TEXT, indexed_at REAL NOT NULL)""",
    ]),
```

`agent/app/domains/deliverable/repository.py`:

```python
"""SQLite access for the deliverable engine: runs, streamed sections, classification cache, template index."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from ...core.db import _conn

_RUN_FIELDS = {"status", "stage", "pptx_path", "docx_path", "thumbs_dir", "error", "finished_at"}


def create_deliverable_run(project_id: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_deliverable_runs (project_id, status, stages_json, created_at) "
        "VALUES (?, 'running', '{}', ?)", (project_id, time.time()))
    conn.commit()
    conn.close()
    return cur.lastrowid


def update_deliverable_run(run_id: int, **fields: Any) -> None:
    sets, vals = [], []
    for key, value in fields.items():
        if key == "stages_json":
            sets.append("stages_json = ?")
            vals.append(json.dumps(value))
        elif key in _RUN_FIELDS:
            sets.append(f"{key} = ?")
            vals.append(value)
    if not sets:
        return
    conn = _conn()
    conn.execute(f"UPDATE intel_deliverable_runs SET {', '.join(sets)} WHERE id = ?", (*vals, run_id))
    conn.commit()
    conn.close()


def _run(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d["stages"] = json.loads(d.pop("stages_json") or "{}")
    return d


def get_deliverable_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return _run(row)


def get_latest_deliverable_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE project_id = ? "
                       "ORDER BY created_at DESC, id DESC LIMIT 1", (project_id,)).fetchone()
    conn.close()
    return _run(row)


def get_active_deliverable_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_deliverable_runs WHERE project_id = ? AND status = 'running' "
                       "ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    conn.close()
    return _run(row)


def save_deliverable_section(run_id: int, section: dict) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_deliverable_sections (run_id, section_key, rq_id, module, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, section.get("id", ""), section.get("rq_id"), section.get("module"),
         json.dumps(section, ensure_ascii=False, default=str), time.time()))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_deliverable_sections(run_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT payload_json FROM intel_deliverable_sections WHERE run_id = ? ORDER BY id",
                        (run_id,)).fetchall()
    conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


def get_cached_classification(norm_url: str, field: str) -> Optional[list]:
    conn = _conn()
    row = conn.execute("SELECT value_json FROM intel_article_classifications WHERE norm_url = ? AND field = ?",
                       (norm_url, field)).fetchone()
    conn.close()
    return json.loads(row["value_json"]) if row else None


def save_cached_classification(norm_url: str, field: str, value: list, model: str) -> None:
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO intel_article_classifications VALUES (?, ?, ?, ?, ?)",
                 (norm_url, field, json.dumps(value, ensure_ascii=False), model, time.time()))
    conn.commit()
    conn.close()


def save_reference_deck(path: str, text: str, embedding: Optional[list[float]]) -> None:
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO intel_reference_decks VALUES (?, ?, ?, ?)",
                 (path, text, json.dumps(embedding) if embedding is not None else None, time.time()))
    conn.commit()
    conn.close()


def list_reference_decks() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT path, text, embedding_json FROM intel_reference_decks").fetchall()
    conn.close()
    return [{"path": r["path"], "text": r["text"] or "",
             "embedding": json.loads(r["embedding_json"]) if r["embedding_json"] else None} for r in rows]
```

`agent/app/core/store.py` — after the `auth.repository` import line add:

```python
from ..domains.deliverable.repository import *  # noqa: F401,F403
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_repository.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/core/config.py agent/app/core/db.py agent/app/core/store.py agent/app/domains/deliverable/repository.py agent/tests/test_deliverable_repository.py
git commit -m "feat(deliverable): runs, sections, classification cache and template index tables"
```

---

### Task 2: Meltwater Boolean evaluator

**Files:**
- Create: `agent/app/domains/deliverable/boolean_query.py`
- Test: `agent/tests/test_deliverable_boolean.py`

**Interfaces:**
- Produces: `matches(query: str, text: str) -> bool` — never raises; malformed query → `False`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_boolean.py
from agent.app.domains.deliverable.boolean_query import matches

TEXT = "Pediatricians recommend gentle baby lotion; the Johnson's sale ends Friday."


def test_and_or_not_phrases_and_parentheses():
    assert matches('("baby lotion" OR "baby cream") AND (sale OR discount)', TEXT)
    assert not matches('"baby lotion" AND NOT sale', TEXT)
    assert matches('pediatrician* AND "baby lotion"', TEXT)


def test_near_is_cooccurrence_within_n_words():
    assert matches('pediatricians NEAR/4 lotion', TEXT)
    assert not matches('pediatricians NEAR/2 sale', TEXT)


def test_case_insensitive_and_implicit_and():
    assert matches("BABY lotion", TEXT)


def test_malformed_queries_never_raise():
    for q in ['("baby lotion" AND sale', '"unclosed AND sale', "baby AND", "", "OR"]:
        assert matches(q, TEXT) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_boolean.py -q`
Expected: FAIL — `ModuleNotFoundError: ... boolean_query`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/boolean_query.py
"""Local evaluation of Meltwater Boolean queries: AND / OR / NOT, quoted phrases, parentheses, `*` wildcards
and NEAR/n (co-occurrence within n words). Adjacent terms are an implicit AND. A malformed query matches
nothing rather than raising."""
from __future__ import annotations

import re

_TOKEN = re.compile(r'"[^"]*"|\(|\)|NEAR/\d+|AND|OR|NOT|[^\s()"]+')
_WORD = re.compile(r"[a-z0-9']+")


class _Malformed(ValueError):
    pass


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("’", "'"))


def _term_parts(term: str) -> list[str]:
    if term.startswith('"'):
        return [p for p in term.strip('"').lower().replace("’", "'").split() if p]
    return [term.lower().replace("’", "'")]


def _hit(word: str, part: str) -> bool:
    if part.endswith("*"):
        return word.startswith(part[:-1])
    return word == re.sub(r"[^a-z0-9']", "", part)


def _term_positions(term: str, words: list[str]) -> list[int]:
    parts = _term_parts(term)
    if not parts:
        return []
    return [i for i in range(len(words) - len(parts) + 1)
            if all(_hit(words[i + k], parts[k]) for k in range(len(parts)))]


class _Parser:
    def __init__(self, tokens: list[str], words: list[str]):
        self.t, self.i, self.words = tokens, 0, words

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise _Malformed("unexpected end")
        self.i += 1
        return tok

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == "OR":
            self.take()
            right = self.parse_and()
            left = left or right
        return left

    def parse_and(self):
        left = self.parse_unary()
        while self.peek() not in (None, "OR", ")"):
            if self.peek() == "AND":
                self.take()
            right = self.parse_unary()
            left = left and right
        return left

    def parse_unary(self):
        if self.peek() == "NOT":
            self.take()
            return not self.parse_unary()
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok == "(":
            self.take()
            value = self.parse_or()
            if self.take() != ")":
                raise _Malformed("missing )")
            return value
        if tok in (None, ")", "AND", "OR") or tok.startswith("NEAR/"):
            raise _Malformed(f"unexpected {tok}")
        term = self.take()
        positions = _term_positions(term, self.words)
        if (self.peek() or "").startswith("NEAR/"):
            n = int(self.take().split("/")[1])
            other = self.take()
            if other in ("(", ")", "AND", "OR", "NOT") or other.startswith("NEAR/"):
                raise _Malformed("NEAR needs a term")
            others = _term_positions(other, self.words)
            return any(abs(a - b) <= n for a in positions for b in others)
        return bool(positions)


def matches(query: str, text: str) -> bool:
    query = (query or "").strip()
    if not query or query.count('"') % 2:
        return False
    try:
        parser = _Parser(_TOKEN.findall(query), _words(text))
        result = parser.parse_or()
        if parser.peek() is not None:
            raise _Malformed("trailing tokens")
        return bool(result)
    except (_Malformed, ValueError, IndexError):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_boolean.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/boolean_query.py agent/tests/test_deliverable_boolean.py
git commit -m "feat(deliverable): local Meltwater Boolean evaluator"
```

---

### Task 3: Ingest and RQ routing

**Files:**
- Create: `agent/app/domains/deliverable/engine_types.py`
- Create: `agent/app/domains/deliverable/rows.py`
- Test: `agent/tests/test_deliverable_rows.py`

**Interfaces:**
- Consumes: `boolean_query.matches`; `ingest.Article`, `ingest.normalize_url`, `ingest.parse_date`;
  `execution.service._is_excluded`, `execution.service._load_dataset`; `store.get_datasets_by_project`,
  `store.get_enriched_records_by_project`, `store.get_latest_strategy`.
- Produces:

```python
@dataclass
class EngineRow:          # one unique URL
    article: Article
    rq_ids: set[str]
    copies: int = 1       # articles in this row's story (syndicated copies incl. itself)
    story_key: str = ""
    media_type: str = ""
    themes: list[str] = field(default_factory=list)       # enrichment theme labels
    entities: dict = field(default_factory=dict)          # enrichment entities {brands, people, organizations}

@dataclass
class RQ:
    id: str
    question: str
    query: str = ""

@dataclass
class Section:
    id: str
    rq_id: str | None
    module: str
    title: str
    chart: dict | None = None      # {"kind", "categories", "values", "peaks", "unit", "series_label"}
    table: dict | None = None      # {"header": [...], "rows": [[...]], "col_widths": [...]}
    facts: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None
    def to_dict(self) -> dict
```

  `rows.load_rqs(project_id) -> list[RQ]`, `rows.load_rows(project_id, rqs) -> list[EngineRow]`,
  `rows.route(rows, rqs) -> list[EngineRow]`, `rows.assign_stories(rows) -> list[EngineRow]`,
  `rows.base_n(rows) -> int`, `rows.rq_rows(rows, rq_id) -> list[EngineRow]`,
  `rows.ingest_summary(project_id, rows) -> dict` (`files, unique_urls, stories, base_n, by_rq`).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_rows.py
"""Ingest: every approved dataset, exclusions dropped, rows merged by URL, routed by file and by Boolean query."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.core import store
from agent.app.domains.deliverable import rows as R


def _rec(url, title, **kw):
    return {"id": url, "title": title, "content": f"{title} body", "url": url, "date": "2026-03-04 00:00:00",
            "source_name": "Outlet", "review_status": "relevant", "approval_status": "pending",
            "overall_sentiment": "Positive", "media_type": "Article",
            "themes": {"primary": "Deals", "secondary": "Sun care"},
            "entities": {"brands": ["Aveeno"], "people": [], "organizations": []}, **kw}


def _project(tmp_path):
    store.init_intelligence_db()
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Rows {tmp_path.name}"}})
    sid = store.save_search_strategy(pid, {"research_question_queries": [
        {"question_id": "RQ1", "question": "deal-led?", "query": "sale OR discount"},
        {"question_id": "RQ2", "question": "experts?", "query": "pediatrician*"}]})
    store.approve_strategy(sid, "t")
    for rq, recs in (("RQ1", [_rec("https://a.com/1", "Lotion sale"), _rec("https://a.com/2", "Lotion sale"),
                              _rec("https://a.com/3", "Junk", review_status="irrelevant")]),
                     ("RQ2", [_rec("https://a.com/1", "Lotion sale"),
                              _rec("https://b.com/9", "Pediatricians on eczema")])):
        path = tmp_path / f"{rq}.csv"
        path.write_text("Title,URL\n")
        ds = store.save_dataset(pid, path.name, str(path), len(recs), {}, {}, [], research_question_id=rq)
        store.approve_dataset(ds, "t")
        store.update_dataset_enrichment(ds, "done", recs)
    return pid


def test_rqs_come_from_the_strategy(tmp_path):
    pid = _project(tmp_path)
    assert [(q.id, q.query) for q in R.load_rqs(pid)] == [("RQ1", "sale OR discount"), ("RQ2", "pediatrician*")]


def test_rows_merge_by_url_drop_exclusions_and_route(tmp_path):
    pid = _project(tmp_path)
    rqs = R.load_rqs(pid)
    rows = R.assign_stories(R.route(R.load_rows(pid, rqs), rqs))
    by_url = {r.article.norm_url: r for r in rows}
    assert set(by_url) == {"https://a.com/1", "https://a.com/2", "https://b.com/9"}   # junk excluded
    assert by_url["https://a.com/1"].rq_ids == {"RQ1", "RQ2"}                         # two files
    assert by_url["https://b.com/9"].rq_ids == {"RQ2"}
    assert R.base_n(rows) == 3
    assert by_url["https://a.com/1"].story_key == by_url["https://a.com/2"].story_key
    assert by_url["https://a.com/1"].copies == 2
    assert by_url["https://a.com/1"].themes == ["Deals", "Sun care"]
    assert by_url["https://a.com/1"].entities["brands"] == ["Aveeno"]


def test_boolean_routing_and_summary(tmp_path):
    pid = _project(tmp_path)
    rqs = R.load_rqs(pid)
    rows = R.route(R.load_rows(pid, rqs), rqs)
    # a.com/2 was uploaded for RQ1 only; it says "sale" (RQ1) but no "pediatrician", so it stays RQ1-only
    assert next(r for r in rows if r.article.norm_url == "https://a.com/2").rq_ids == {"RQ1"}
    summary = R.ingest_summary(pid, R.assign_stories(rows))
    assert summary["base_n"] == 3 and summary["by_rq"] == {"RQ1": 2, "RQ2": 2} and summary["files"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_rows.py -q`
Expected: FAIL — `ModuleNotFoundError: ... rows`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/engine_types.py
"""Data shapes shared by every deliverable-engine stage."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .ingest import Article


@dataclass
class EngineRow:
    article: Article
    rq_ids: set[str]
    copies: int = 1
    story_key: str = ""
    media_type: str = ""
    themes: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)


@dataclass
class RQ:
    id: str
    question: str
    query: str = ""


@dataclass
class Section:
    id: str
    rq_id: str | None
    module: str
    title: str
    chart: dict | None = None
    table: dict | None = None
    facts: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
```

```python
# agent/app/domains/deliverable/rows.py
"""Ingest stage: approved datasets → one EngineRow per unique URL, routed to RQs by file and by query."""
from __future__ import annotations

import re
from pathlib import Path

from ...core import store
from ..execution.service import _is_excluded, _load_dataset
from .boolean_query import matches
from .engine_types import RQ, EngineRow
from .ingest import Article, normalize_url, parse_date


def load_rqs(project_id: int) -> list[RQ]:
    strategy = (store.get_latest_strategy(project_id) or {}).get("strategy") or {}
    return [RQ(id=q.get("question_id") or f"RQ{i}", question=q.get("question") or "", query=q.get("query") or "")
            for i, q in enumerate(strategy.get("research_question_queries") or [], start=1)]


def _approved_datasets(project_id: int) -> list[dict]:
    return [d for d in store.get_datasets_by_project(project_id)
            if d.get("approval_status") == "approved" and (d.get("processing_status") or "done") == "done"]


def _theme_labels(themes) -> list[str]:
    if isinstance(themes, dict):
        return [str(themes[k]) for k in ("primary", "secondary") if themes.get(k)]
    return [str(t) for t in themes or [] if t]


def _to_float(v) -> float:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _row(rec: dict, rq: str | None, source_file: str, index: int) -> EngineRow | None:
    url = str(rec.get("url") or "").strip()
    if not url:
        return None
    title = str(rec.get("title") or rec.get("headline") or "").strip()
    article = Article(url=url, norm_url=normalize_url(url), title=title, date=parse_date(rec.get("date")),
                      outlet=str(rec.get("source_name") or rec.get("source") or ""),
                      text=str(rec.get("content") or title),
                      sentiment=rec.get("overall_sentiment") or rec.get("sentiment") or None,
                      reach=_to_float(rec.get("reach")), source_file=source_file, row_index=index)
    return EngineRow(article=article, rq_ids={rq} if rq else set(), media_type=str(rec.get("media_type") or ""),
                     themes=_theme_labels(rec.get("themes")), entities=rec.get("entities") or {})


def load_rows(project_id: int, rqs: list[RQ]) -> list[EngineRow]:
    datasets = _approved_datasets(project_id)
    approved = {d["id"] for d in datasets}
    merged: dict[str, EngineRow] = {}

    def add(row: EngineRow | None) -> None:
        if row is None:
            return
        existing = merged.get(row.article.norm_url)
        if existing:
            existing.rq_ids |= row.rq_ids
        else:
            merged[row.article.norm_url] = row

    enriched = [r for r in store.get_enriched_records_by_project(project_id) if r.get("dataset_id") in approved]
    enriched_ids = {r["dataset_id"] for r in enriched}
    for i, rec in enumerate(enriched):
        if not _is_excluded(rec):
            add(_row(rec, rec.get("research_question_id"), rec.get("dataset_file_name") or "", i))
    for ds in datasets:
        fp = ds.get("file_path") or ""
        if ds["id"] in enriched_ids or not fp or not Path(fp).exists():
            continue
        for i, rec in enumerate(_load_dataset(fp)):
            add(_row(rec, ds.get("research_question_id"), ds.get("file_name") or "", i))
    return list(merged.values())


def route(rows: list[EngineRow], rqs: list[RQ]) -> list[EngineRow]:
    """Adds every RQ whose Meltwater query matches the article (on top of the file it was uploaded for)."""
    for row in rows:
        text = f"{row.article.title}\n{row.article.text}"
        for rq in rqs:
            if rq.query and rq.id not in row.rq_ids and matches(rq.query, text):
                row.rq_ids.add(rq.id)
    return rows


def _story_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:120]


def assign_stories(rows: list[EngineRow]) -> list[EngineRow]:
    """Syndicated copies (same normalised headline, different URLs) form one story; each row records its size."""
    groups: dict[str, list[EngineRow]] = {}
    for row in rows:
        row.story_key = _story_key(row.article.title) or row.article.norm_url
        groups.setdefault(row.story_key, []).append(row)
    for members in groups.values():
        for row in members:
            row.copies = len(members)
    return rows


def base_n(rows: list[EngineRow]) -> int:
    return len({r.article.norm_url for r in rows if r.rq_ids})


def rq_rows(rows: list[EngineRow], rq_id: str) -> list[EngineRow]:
    return [r for r in rows if rq_id in r.rq_ids]


def ingest_summary(project_id: int, rows: list[EngineRow]) -> dict:
    by_rq: dict[str, int] = {}
    for r in rows:
        for q in r.rq_ids:
            by_rq[q] = by_rq.get(q, 0) + 1
    return {"files": len(_approved_datasets(project_id)), "unique_urls": len(rows),
            "stories": len({r.story_key for r in rows}), "base_n": base_n(rows), "by_rq": dict(sorted(by_rq.items()))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_rows.py -q`
Expected: 3 passed. (If `store.get_latest_strategy` keeps the strategy dict under a key other than
`strategy`, print one row in the test, fix `load_rqs`, and say so in the commit message.)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/engine_types.py agent/app/domains/deliverable/rows.py agent/tests/test_deliverable_rows.py
git commit -m "feat(deliverable): ingest approved datasets and route rows to RQs by file and Boolean query"
```

---

### Task 4: Module catalog and LLM planner

**Files:**
- Create: `agent/app/domains/deliverable/catalog.py`
- Test: `agent/tests/test_deliverable_catalog.py`

**Interfaces:**
- Consumes: `RQ`, `EngineRow`.
- Produces: `MODULES: dict[str, dict]` (keys `share_kpi, volume_trend, sentiment_split, outlet_ranking, reach,
  theme_clusters, entities, brand_sov, top_articles`), `ENTITY_KINDS = ("experts", "celebrities", "brands",
  "products", "retailers")`, `validate_plan(plan: dict, rq_id: str) -> dict | None`,
  `default_plan(rq: RQ, rows: list[EngineRow]) -> dict`, `plan_rq(llm, rq, rows) -> tuple[dict, str]`
  (plan, `"llm"` | `"default"`). Plan shape:
  `{"rq_id": str, "title": str, "modules": [{"module": str, "title": str, "entity_kind": str | None}]}`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_catalog.py
import json
from datetime import date

from agent.app.domains.deliverable import catalog
from agent.app.domains.deliverable.engine_types import RQ, EngineRow
from agent.app.domains.deliverable.ingest import Article


def _row(dated=True):
    a = Article(url="u", norm_url="u", title="t", date=date(2026, 1, 1) if dated else None, outlet="o",
                text="x", sentiment="Positive", reach=0)
    return EngineRow(article=a, rq_ids={"RQ1"})


class FakeLLM:
    def __init__(self, reply): self.reply = reply
    def is_reachable(self): return True
    def chat(self, messages, format_json=False): return self.reply


def test_default_plan_follows_the_question():
    plan = catalog.default_plan(RQ("RQ3", "Which experts are cited, and are they brand-affiliated?"), [_row()])
    mods = [m["module"] for m in plan["modules"]]
    assert mods[0] == "share_kpi" and "volume_trend" in mods and "entities" in mods
    assert next(m for m in plan["modules"] if m["module"] == "entities")["entity_kind"] == "experts"


def test_default_plan_skips_trend_without_dates():
    plan = catalog.default_plan(RQ("RQ1", "How much coverage is deal-led?"), [_row(dated=False)])
    assert "volume_trend" not in [m["module"] for m in plan["modules"]]


def test_llm_plan_is_validated_against_the_catalog():
    good = {"title": "Celebrity-led coverage", "modules": [
        {"module": "share_kpi", "title": "Share"}, {"module": "entities", "title": "Who", "entity_kind": "celebrities"},
        {"module": "made_up_module", "title": "x"}]}
    plan, source = catalog.plan_rq(FakeLLM(json.dumps(good)), RQ("RQ5", "celebrities?"), [_row()])
    assert source == "llm" and [m["module"] for m in plan["modules"]] == ["share_kpi", "entities"]


def test_invalid_or_unreachable_llm_falls_back_to_default():
    plan, source = catalog.plan_rq(FakeLLM("not json"), RQ("RQ1", "deal-led?"), [_row()])
    assert source == "default" and plan["modules"][0]["module"] == "share_kpi"
    plan, source = catalog.plan_rq(None, RQ("RQ1", "deal-led?"), [_row()])
    assert source == "default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_catalog.py -q`
Expected: FAIL — `ModuleNotFoundError: ... catalog`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/catalog.py
"""Analysis plan: the LLM picks modules from a fixed catalog per RQ; it never supplies numbers."""
from __future__ import annotations

import json
import logging

from .engine_types import RQ, EngineRow

logger = logging.getLogger(__name__)

MODULES: dict[str, dict] = {
    "share_kpi": {"needs_extraction": False, "desc": "share of coverage for this question (KPI tile)"},
    "volume_trend": {"needs_extraction": False, "desc": "monthly volume line with the top-5 peaks labelled"},
    "sentiment_split": {"needs_extraction": False, "desc": "positive / neutral / negative split (doughnut)"},
    "outlet_ranking": {"needs_extraction": False, "desc": "top outlets by articles (bar chart)"},
    "reach": {"needs_extraction": False, "desc": "total and top-outlet reach (bar chart)"},
    "theme_clusters": {"needs_extraction": False, "desc": "top themes from enrichment (treemap)"},
    "entities": {"needs_extraction": True, "desc": "named experts / celebrities / brands / products / retailers (table + chart)"},
    "brand_sov": {"needs_extraction": False, "desc": "brand share of voice with logos (bar chart)"},
    "top_articles": {"needs_extraction": False, "desc": "most-read articles (table)"},
}
ENTITY_KINDS = ("experts", "celebrities", "brands", "products", "retailers")
MAX_MODULES = 6
_ENTITY_HINTS = (("expert", "experts"), ("dermatolog", "experts"), ("pediatric", "experts"), ("hcp", "experts"),
                 ("celebrit", "celebrities"), ("influencer", "celebrities"), ("retailer", "retailers"),
                 ("deal", "retailers"), ("product", "products"))


def validate_plan(plan: dict, rq_id: str) -> dict | None:
    if not isinstance(plan, dict) or not isinstance(plan.get("modules"), list):
        return None
    modules = []
    for m in plan["modules"]:
        if not isinstance(m, dict) or m.get("module") not in MODULES:
            continue
        kind = m.get("entity_kind")
        if m["module"] == "entities" and kind not in ENTITY_KINDS:
            continue
        modules.append({"module": m["module"], "title": str(m.get("title") or m["module"]).strip()[:80],
                        "entity_kind": kind if m["module"] == "entities" else None})
    if not modules:
        return None
    if modules[0]["module"] != "share_kpi":
        modules = [{"module": "share_kpi", "title": "Share of coverage", "entity_kind": None}] + \
                  [m for m in modules if m["module"] != "share_kpi"]
    return {"rq_id": rq_id, "title": str(plan.get("title") or rq_id).strip()[:90], "modules": modules[:MAX_MODULES]}


def default_plan(rq: RQ, rows: list[EngineRow]) -> dict:
    text = rq.question.lower()
    modules = [{"module": "share_kpi", "title": "Share of coverage", "entity_kind": None}]
    if any(r.article.date for r in rows):
        modules.append({"module": "volume_trend", "title": "Coverage over time", "entity_kind": None})
    kind = next((k for hint, k in _ENTITY_HINTS if hint in text), None)
    if kind:
        modules.append({"module": "entities", "title": f"Named {kind}", "entity_kind": kind})
    if any(w in text for w in ("brand", "competitor", "share of voice")):
        modules.append({"module": "brand_sov", "title": "Brand share of voice", "entity_kind": None})
    modules += [{"module": "outlet_ranking", "title": "Top outlets", "entity_kind": None},
                {"module": "sentiment_split", "title": "Sentiment", "entity_kind": None},
                {"module": "top_articles", "title": "Most-read articles", "entity_kind": None}]
    return {"rq_id": rq.id, "title": rq.question[:90] or rq.id, "modules": modules[:MAX_MODULES]}


def _profile(rows: list[EngineRow]) -> dict:
    return {"articles": len(rows), "dated": sum(1 for r in rows if r.article.date),
            "with_sentiment": sum(1 for r in rows if r.article.sentiment),
            "with_reach": sum(1 for r in rows if r.article.reach),
            "outlets": len({r.article.outlet for r in rows if r.article.outlet}),
            "brands_mentioned": sum(1 for r in rows if (r.entities or {}).get("brands"))}


def plan_rq(llm, rq: RQ, rows: list[EngineRow]) -> tuple[dict, str]:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return default_plan(rq, rows), "default"
    messages = [
        {"role": "system", "content": "You plan the analysis slides for one research question of a media-research "
         "deck. Choose 3-6 modules from CATALOG that best answer the question, in presentation order, starting with "
         "share_kpi. For 'entities' set entity_kind to one of " + ", ".join(ENTITY_KINDS) + ". Never include numbers. "
         "Return JSON only: {\"title\": \"<slide title, max 8 words>\", \"modules\": [{\"module\": \"<catalog key>\", "
         "\"title\": \"<chart title>\", \"entity_kind\": null}]}"},
        {"role": "user", "content": f"QUESTION: {rq.question}\nDATA PROFILE: {json.dumps(_profile(rows))}\n"
         f"CATALOG: {json.dumps({k: v['desc'] for k, v in MODULES.items()})}"},
    ]
    try:
        plan = validate_plan(json.loads(llm.chat(messages, format_json=True)), rq.id)
    except (json.JSONDecodeError, TypeError, RuntimeError) as e:
        logger.warning("plan for %s failed (%s); using default plan", rq.id, e)
        plan = None
    if plan is None:
        return default_plan(rq, rows), "default"
    if not any(r.article.date for r in rows):
        plan["modules"] = [m for m in plan["modules"] if m["module"] != "volume_trend"]
    return plan, "llm"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_catalog.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/catalog.py agent/tests/test_deliverable_catalog.py
git commit -m "feat(deliverable): module catalog, plan validation and LLM planner"
```

---

### Task 5: Entity extraction with URL cache

**Files:**
- Create: `agent/app/domains/deliverable/extract.py`
- Test: `agent/tests/test_deliverable_extract.py`

**Interfaces:**
- Consumes: `store.get_cached_classification`, `store.save_cached_classification`, `EngineRow`.
- Produces: `class ExtractionUnavailable(RuntimeError)`; `FIELDS: dict[str, dict]`;
  `extract(llm, rows: list[EngineRow], kind: str) -> dict[str, list[dict]]` keyed by `norm_url`. Items:
  experts `{"name", "expert_type" ∈ dermatologist|pediatrician|other_hcp|non_hcp_expert|unknown, "affiliation" ∈
  affiliated|independent|unknown, "brand"}`; celebrities `{"name", "role" ∈ spokesperson|product_mention|
  lifestyle|unknown}`; brands/products/retailers `{"name"}`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_extract.py
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

import pytest

from agent.app.core import store
from agent.app.domains.deliverable import extract
from agent.app.domains.deliverable.engine_types import EngineRow
from agent.app.domains.deliverable.ingest import Article


def _row(i):
    a = Article(url=f"https://x.com/{i}", norm_url=f"https://x.com/{i}", title=f"T{i}", date=None, outlet="o",
                text=f"Dr Lee, a dermatologist at Aveeno, says {i}", sentiment=None, reach=0)
    return EngineRow(article=a, rq_ids={"RQ3"})


class FakeLLM:
    def __init__(self): self.calls = 0
    def is_reachable(self): return True
    def chat(self, messages, format_json=False):
        self.calls += 1
        ids = [a["id"] for a in json.loads(messages[-1]["content"].split("ARTICLES:", 1)[1])]
        return json.dumps({"results": [{"id": i, "items": [
            {"name": "Dr Lee", "expert_type": "dermatologist", "affiliation": "affiliated", "brand": "Aveeno",
             "bogus": 1}, {"name": "", "expert_type": "x"}]} for i in ids]})


def setup_module(_):
    store.init_intelligence_db()


def test_items_are_cleaned_and_cached_by_url():
    llm = FakeLLM()
    rows = [_row(i) for i in range(3)]
    out = extract.extract(llm, rows, "experts")
    assert out["https://x.com/0"] == [{"name": "Dr Lee", "expert_type": "dermatologist",
                                       "affiliation": "affiliated", "brand": "Aveeno"}]
    calls = llm.calls
    assert extract.extract(llm, rows, "experts") == out and llm.calls == calls   # second run: cache only


def test_unreachable_llm_raises_unavailable():
    with pytest.raises(extract.ExtractionUnavailable):
        extract.extract(None, [_row(9)], "celebrities")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_extract.py -q`
Expected: FAIL — `ModuleNotFoundError: ... extract`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/extract.py
"""Per-article entity extraction for the fields a plan needs, cached by URL so re-runs are free and stable."""
from __future__ import annotations

import json
import logging

from ...core import store
from .engine_types import EngineRow

logger = logging.getLogger(__name__)
BATCH = 8
MAX_TEXT = 3000

FIELDS: dict[str, dict] = {
    "experts": {"name": None, "expert_type": ["dermatologist", "pediatrician", "other_hcp", "non_hcp_expert"],
                "affiliation": ["affiliated", "independent"], "brand": None},
    "celebrities": {"name": None, "role": ["spokesperson", "product_mention", "lifestyle"]},
    "brands": {"name": None},
    "products": {"name": None},
    "retailers": {"name": None},
}
_INSTRUCTIONS = {
    "experts": "List every expert quoted or cited. expert_type: dermatologist, pediatrician, other_hcp (nurse, "
               "pharmacist, other clinician) or non_hcp_expert. affiliation 'affiliated' only if the article states a "
               "brand tie (works for, paid by, partners with, spokesperson for) and put that brand in brand; "
               "'independent' only if stated; otherwise 'unknown'.",
    "celebrities": "List every celebrity named. role: spokesperson (paid / brand partner), product_mention, or lifestyle.",
    "brands": "List every consumer brand named.",
    "products": "List every specific product named.",
    "retailers": "List every retailer named (Amazon, Target, Walmart, ...).",
}


class ExtractionUnavailable(RuntimeError):
    pass


def _clean(item: dict, schema: dict) -> dict | None:
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return None
    out = {}
    for key, allowed in schema.items():
        value = item.get(key)
        if allowed is None:
            out[key] = str(value).strip() if value else ""
        else:
            out[key] = value if value in allowed else "unknown"
    return out


def extract(llm, rows: list[EngineRow], kind: str) -> dict[str, list[dict]]:
    schema = FIELDS[kind]
    out: dict[str, list[dict]] = {}
    todo = []
    for row in rows:
        cached = store.get_cached_classification(row.article.norm_url, kind)
        if cached is None:
            todo.append(row)
        else:
            out[row.article.norm_url] = cached
    if not todo:
        return out
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        raise ExtractionUnavailable("Azure OpenAI is not reachable")
    model = getattr(llm, "model_name", "") or "azure-openai"
    example = json.dumps({k: (v[0] if v else "") for k, v in schema.items()})
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        arts = [{"id": i, "title": r.article.title, "text": r.article.text[:MAX_TEXT]} for i, r in enumerate(batch)]
        messages = [
            {"role": "system", "content": _INSTRUCTIONS[kind] + " Use only what each article says; unknown stays "
             f"'unknown'. Return JSON only: {{\"results\": [{{\"id\": <id>, \"items\": [{example}]}}]}}"},
            {"role": "user", "content": "ARTICLES:" + json.dumps(arts, ensure_ascii=False)},
        ]
        try:
            parsed = json.loads(llm.chat(messages, format_json=True))
        except (json.JSONDecodeError, RuntimeError) as e:
            raise ExtractionUnavailable(f"extraction failed: {e}") from e
        by_id = {r.get("id"): r.get("items") or [] for r in parsed.get("results") or [] if isinstance(r, dict)}
        for i, row in enumerate(batch):
            items = [c for c in (_clean(it, schema) for it in by_id.get(i, [])) if c]
            store.save_cached_classification(row.article.norm_url, kind, items, model)
            out[row.article.norm_url] = items
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_extract.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/extract.py agent/tests/test_deliverable_extract.py
git commit -m "feat(deliverable): cached per-article entity extraction"
```

---

### Task 6: Analytics modules → sections

**Files:**
- Create: `agent/app/domains/deliverable/analytics.py`
- Test: `agent/tests/test_deliverable_analytics.py`

**Interfaces:**
- Consumes: `EngineRow`, `RQ`, `Section`, `metrics.month_label`, `metrics.TOP_PEAKS`.
- Produces: `compute_module(module: dict, rq: RQ, rows: list[EngineRow], base_n: int,
  extraction: dict[str, list[dict]] | None) -> Section`; `overview_section(rqs, rows_by_rq, base_n) -> Section`.
  Chart kinds: `kpi`, `line_peaks`, `bar`, `doughnut` (values are percentages), `treemap`, `gauge`. Every number
  in a section's chart labels or table also appears in `facts`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_analytics.py
from datetime import date

from agent.app.domains.deliverable import analytics
from agent.app.domains.deliverable.engine_types import RQ, EngineRow
from agent.app.domains.deliverable.ingest import Article

RQ1 = RQ("RQ1", "How much coverage is deal-led?")


def _row(i, month=1, outlet="Outlet A", sentiment="Positive", copies=1, dated=True, reach=100.0):
    a = Article(url=f"https://x.com/{i}", norm_url=f"https://x.com/{i}", title=f"Story {i}",
                date=date(2026, month, 5) if dated else None, outlet=outlet, text="Aveeno lotion sale",
                sentiment=sentiment, reach=reach)
    return EngineRow(article=a, rq_ids={"RQ1"}, copies=copies, story_key=f"s{i}", themes=["Deals"],
                     entities={"brands": ["Aveeno"]})


def _mod(name, kind=None):
    return {"module": name, "title": name, "entity_kind": kind}


def test_share_kpi_states_its_base():
    s = analytics.compute_module(_mod("share_kpi"), RQ1, [_row(i) for i in range(54)], 225, None)
    assert s.chart == {"kind": "kpi", "categories": ["Share of coverage"], "values": [24.0], "unit": "percent",
                       "peaks": [], "series_label": "RQ1"}
    assert "54 of 225 articles (24.0%)" in s.facts[0]


def test_trend_labels_top_peaks_and_reports_undated():
    rows = [_row(i, month=1 + (i % 3)) for i in range(9)] + [_row(99, month=6), _row(100, dated=False)]
    s = analytics.compute_module(_mod("volume_trend"), RQ1, rows, 225, None)
    assert s.chart["kind"] == "line_peaks" and s.chart["categories"][0] == "Jan-26"
    assert len(s.chart["peaks"]) <= 5 and s.notes == ["1 undated article not shown on the trend"]
    assert any(f.startswith("Peak 1:") for f in s.facts)


def test_trend_skipped_when_nothing_is_dated():
    s = analytics.compute_module(_mod("volume_trend"), RQ1, [_row(1, dated=False)], 225, None)
    assert s.skipped == "No dated articles" and s.chart is None


def test_zero_rows_section_draws_nothing():
    s = analytics.compute_module(_mod("outlet_ranking"), RQ1, [], 225, None)
    assert s.skipped == "No articles for this question" and s.chart is None and s.table is None


def test_outlets_sentiment_entities_and_overview():
    rows = [_row(i, outlet="Outlet A" if i < 6 else "Outlet B", sentiment="Negative" if i == 0 else "Positive")
            for i in range(10)]
    out = analytics.compute_module(_mod("outlet_ranking"), RQ1, rows, 225, None)
    assert out.chart["categories"][:2] == ["Outlet A", "Outlet B"] and out.chart["values"][:2] == [6, 4]
    sen = analytics.compute_module(_mod("sentiment_split"), RQ1, rows, 225, None)
    assert sen.chart["kind"] == "doughnut" and dict(zip(sen.chart["categories"], sen.chart["values"]))["Negative"] == 10.0
    ext = {r.article.norm_url: [{"name": "Dr Lee", "expert_type": "dermatologist", "affiliation": "affiliated",
                                 "brand": "Aveeno"}] for r in rows[:4]}
    ent = analytics.compute_module(_mod("entities", "experts"), RQ1, rows, 225, ext)
    assert ent.table["rows"][0][:2] == ["Dr Lee", "dermatologist"] and ent.chart["kind"] == "gauge"
    assert "1 of 1 experts with a stated affiliation are brand-affiliated (100.0%)" in ent.facts
    ov = analytics.overview_section([RQ1], {"RQ1": rows}, 225)
    assert ov.chart["kind"] == "bar" and ov.chart["values"] == [10]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_analytics.py -q`
Expected: FAIL — `ModuleNotFoundError: ... analytics`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/analytics.py
"""Compute stage: deterministic values for every chart and table; each value is also written as a fact."""
from __future__ import annotations

from collections import Counter

from .engine_types import RQ, EngineRow, Section
from .metrics import TOP_PEAKS, month_label

TOP_N = 8
NO_ROWS = "No articles for this question"


def _pct(n: int, base: int) -> float:
    return round(100 * n / base, 1) if base else 0.0


def _section(module: dict, rq: RQ, **kw) -> Section:
    suffix = f"-{module['entity_kind']}" if module.get("entity_kind") else ""
    return Section(id=f"{rq.id.lower()}-{module['module']}{suffix}", rq_id=rq.id, module=module["module"],
                   title=module.get("title") or module["module"], **kw)


def _share_kpi(module, rq, rows, base_n, _):
    n, share = len(rows), _pct(len(rows), base_n)
    stories = len({r.story_key for r in rows})
    return _section(module, rq, chart={"kind": "kpi", "categories": ["Share of coverage"], "values": [share],
                                       "unit": "percent", "peaks": [], "series_label": rq.id},
                    facts=[f"{rq.id}: {n} of {base_n} articles ({share}%) answer this question",
                           f"{rq.id}: {stories} unique stories ({n - stories} syndicated copies)"],
                    candidate_urls=[r.article.norm_url for r in rows[:12]])


def _months(first: str, last: str) -> list[str]:
    y, m, out = int(first[:4]), int(first[5:]), []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _trend(module, rq, rows, base_n, _):
    dated = [r for r in rows if r.article.date]
    if not dated:
        return _section(module, rq, skipped="No dated articles")
    by_month = Counter(r.article.date.strftime("%Y-%m") for r in dated)
    series = _months(min(by_month), max(by_month))
    values = [by_month.get(k, 0) for k in series]
    top = [i for i in sorted(range(len(values)), key=lambda i: -values[i])[:TOP_PEAKS] if values[i] > 0]
    facts, cands = [], []
    for rank, i in enumerate(top, start=1):
        drivers = [r for r in dated if r.article.date.strftime("%Y-%m") == series[i]]
        lead = max(drivers, key=lambda r: (r.copies, r.article.reach))
        facts.append(f"Peak {rank}: {month_label(series[i])} with {values[i]} articles, led by \"{lead.article.title}\"")
        cands.append(lead.article.norm_url)
    undated = len(rows) - len(dated)
    notes = [f"{undated} undated article{'s' if undated != 1 else ''} not shown on the trend"] if undated else []
    return _section(module, rq, chart={"kind": "line_peaks", "categories": [month_label(k) for k in series],
                                       "values": values, "peaks": sorted(top), "unit": "count", "series_label": "Articles"},
                    facts=facts, candidate_urls=cands, notes=notes)


def _outlets(module, rq, rows, base_n, _):
    top = Counter(r.article.outlet for r in rows if r.article.outlet).most_common(TOP_N)
    if not top:
        return _section(module, rq, skipped="No outlet names in the data")
    return _section(module, rq, chart={"kind": "bar", "categories": [o for o, _ in top], "values": [c for _, c in top],
                                       "unit": "count", "peaks": [], "series_label": "Articles"},
                    facts=[f"Top outlet for {rq.id}: {o} with {c} articles" for o, c in top],
                    candidate_urls=[next(r.article.norm_url for r in rows if r.article.outlet == o) for o, _ in top[:5]])


def _sentiment(module, rq, rows, base_n, _):
    labels = Counter((r.article.sentiment or "").strip().title() for r in rows)
    known = {k: labels[k] for k in ("Positive", "Neutral", "Negative") if labels.get(k)}
    total = sum(known.values())
    if not total:
        return _section(module, rq, skipped="No sentiment in the data")
    cats = list(known)
    vals = [_pct(known[k], total) for k in cats]
    return _section(module, rq, chart={"kind": "doughnut", "categories": cats, "values": vals, "unit": "percent",
                                       "peaks": [], "series_label": "Sentiment"},
                    facts=[f"{rq.id} sentiment: {known[k]} of {total} articles {k.lower()} ({v}%)" for k, v in zip(cats, vals)])


def _reach(module, rq, rows, base_n, _):
    by_outlet = Counter()
    for r in rows:
        if r.article.reach and r.article.outlet:
            by_outlet[r.article.outlet] += int(r.article.reach)
    if not by_outlet:
        return _section(module, rq, skipped="No reach in the data")
    top = by_outlet.most_common(TOP_N)
    return _section(module, rq, chart={"kind": "bar", "categories": [o for o, _ in top], "values": [v for _, v in top],
                                       "unit": "count", "peaks": [], "series_label": "Reach"},
                    facts=[f"{rq.id} total reach: {sum(by_outlet.values())}"] + [f"Reach for {o}: {v}" for o, v in top])


def _themes(module, rq, rows, base_n, _):
    top = Counter(t for r in rows for t in set(r.themes)).most_common(TOP_N)
    if not top:
        return _section(module, rq, skipped="No themes in the data")
    return _section(module, rq, chart={"kind": "treemap", "categories": [t for t, _ in top], "values": [c for _, c in top],
                                       "unit": "count", "peaks": [], "series_label": "Articles"},
                    facts=[f"Theme \"{t}\": {c} of {len(rows)} articles" for t, c in top])


def _brand_sov(module, rq, rows, base_n, _):
    counts = Counter(b for r in rows for b in {str(x).strip() for x in (r.entities or {}).get("brands") or [] if x})
    if not counts:
        return _section(module, rq, skipped="No brands named in the data")
    top, total = counts.most_common(TOP_N), sum(counts.values())
    return _section(module, rq, chart={"kind": "bar", "categories": [b for b, _ in top],
                                       "values": [_pct(c, total) for _, c in top], "unit": "percent", "peaks": [],
                                       "series_label": "Share of brand mentions"},
                    facts=[f"Brand {b}: {c} of {total} brand mentions ({_pct(c, total)}%)" for b, c in top],
                    notes=["logos"])


def _top_articles(module, rq, rows, base_n, _):
    ranked = sorted(rows, key=lambda r: (-r.article.reach, -r.copies, r.article.title))[:TOP_N]
    table_rows = [[r.article.title[:70], r.article.outlet, r.article.date.isoformat() if r.article.date else "",
                   f"{int(r.article.reach)}" if r.article.reach else "", str(r.copies)] for r in ranked]
    return _section(module, rq, table={"header": ["Headline", "Outlet", "Date", "Reach", "Copies"], "rows": table_rows,
                                       "col_widths": [5.6, 2.4, 1.4, 1.4, 1.0]},
                    facts=[f"\"{r.article.title[:70]}\" ({r.article.outlet}) reach {int(r.article.reach)}, {r.copies} copies"
                           for r in ranked],
                    candidate_urls=[r.article.norm_url for r in ranked])


def _entities(module, rq, rows, base_n, extraction):
    kind = module["entity_kind"]
    if extraction is None:
        return _section(module, rq, skipped="Entity extraction unavailable (Azure OpenAI not reachable)")
    people: dict[str, dict] = {}
    for r in rows:
        for item in extraction.get(r.article.norm_url, []):
            entry = people.setdefault(item["name"].lower(), {**item, "count": 0, "urls": []})
            entry["count"] += 1
            entry["urls"].append(r.article.norm_url)
    if not people:
        return _section(module, rq, skipped=f"No {kind} named in these articles")
    ranked = sorted(people.values(), key=lambda e: (-e["count"], e["name"]))
    facts = [f"{e['name']} named in {e['count']} articles" for e in ranked[:10]]
    cols = [k for k in ("expert_type", "affiliation", "brand", "role") if k in ranked[0]]
    header = ["Name"] + [c.replace("_", " ").title() for c in cols] + ["Articles"]
    rows_out = [[e["name"]] + [str(e.get(c) or "") for c in cols] + [str(e["count"])] for e in ranked[:10]]
    chart = {"kind": "bar", "categories": [e["name"] for e in ranked[:TOP_N]],
             "values": [e["count"] for e in ranked[:TOP_N]], "unit": "count", "peaks": [], "series_label": "Articles"}
    if kind == "experts":
        known = [e for e in ranked if e.get("affiliation") in ("affiliated", "independent")]
        aff = [e for e in known if e["affiliation"] == "affiliated"]
        if known:
            pct = _pct(len(aff), len(known))
            facts.append(f"{len(aff)} of {len(known)} experts with a stated affiliation are brand-affiliated ({pct}%)")
            chart = {"kind": "gauge", "categories": ["Brand-affiliated experts"], "values": [pct], "unit": "percent",
                     "peaks": [], "series_label": "Affiliation"}
        types = Counter(e.get("expert_type") for e in ranked)
        facts += [f"{t.replace('_', ' ')} experts: {c}" for t, c in types.most_common() if t and t != "unknown"]
    return _section(module, rq, chart=chart, table={"header": header, "rows": rows_out,
                                                     "col_widths": [3.2] + [2.2] * len(cols) + [1.2]},
                    facts=facts, candidate_urls=[e["urls"][0] for e in ranked[:6]])


_HANDLERS = {"share_kpi": _share_kpi, "volume_trend": _trend, "outlet_ranking": _outlets,
             "sentiment_split": _sentiment, "reach": _reach, "theme_clusters": _themes, "brand_sov": _brand_sov,
             "top_articles": _top_articles, "entities": _entities}


def compute_module(module: dict, rq: RQ, rows: list[EngineRow], base_n: int,
                   extraction: dict[str, list[dict]] | None) -> Section:
    if not rows:
        return _section(module, rq, skipped=NO_ROWS)
    return _HANDLERS[module["module"]](module, rq, rows, base_n, extraction)


def overview_section(rqs: list[RQ], rows_by_rq: dict[str, list[EngineRow]], base_n: int) -> Section:
    counts = [len(rows_by_rq.get(q.id, [])) for q in rqs]
    return Section(id="overview", rq_id=None, module="overview", title="Share of coverage by question",
                   chart={"kind": "bar", "categories": [q.id for q in rqs], "values": counts, "unit": "count",
                          "peaks": [], "series_label": "Articles"},
                   facts=[f"Base: {base_n} unique articles across all questions"] +
                         [f"{q.id}: {c} of {base_n} articles ({_pct(c, base_n)}%)" for q, c in zip(rqs, counts)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_analytics.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/analytics.py agent/tests/test_deliverable_analytics.py
git commit -m "feat(deliverable): deterministic analytics modules with chart/table specs and facts"
```

---

### Task 7: Per-RQ cited insights and executive answers

**Files:**
- Create: `agent/app/domains/deliverable/engine_insights.py`
- Test: `agent/tests/test_deliverable_engine_insights.py`

**Interfaces:**
- Consumes: `insights.draft_section(section, facts, candidates, registry, llm, n_insights, entities)`,
  `CitationRegistry`, `Section`, `EngineRow`.
- Produces: `rq_insights(rq, sections, rows, registry, llm) -> list[dict]` (`{"headline", "text", "citations"}`),
  `executive_answers(rqs, sections_by_rq, base_n) -> list[dict]` (one per RQ:
  `{"rq_id", "question", "value", "answer"}`).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_engine_insights.py
from datetime import date

from agent.app.domains.deliverable import engine_insights as E
from agent.app.domains.deliverable.citations import CitationRegistry
from agent.app.domains.deliverable.engine_types import RQ, EngineRow, Section
from agent.app.domains.deliverable.ingest import Article

RQ1 = RQ("RQ1", "How much coverage is deal-led?")


def _rows():
    return [EngineRow(article=Article(url=f"https://x.com/{i}", norm_url=f"https://x.com/{i}", title=f"Deal {i}",
                                      date=date(2026, 1, 2), outlet="O", text="sale", sentiment=None, reach=0),
                      rq_ids={"RQ1"}) for i in range(3)]


def _sections():
    return [Section(id="rq1-share_kpi", rq_id="RQ1", module="share_kpi", title="Share",
                    chart={"kind": "kpi", "values": [24.0]}, facts=["RQ1: 54 of 225 articles (24.0%) answer this question"],
                    candidate_urls=["https://x.com/0", "https://x.com/1"])]


def test_without_llm_insights_are_backfilled_from_facts_and_cited():
    reg = CitationRegistry()
    out = E.rq_insights(RQ1, _sections(), _rows(), reg, None)
    assert out and all(i["citations"] for i in out)
    assert reg.entries()[0]["url"].startswith("https://x.com/")


def test_executive_answer_quotes_the_kpi_with_its_base():
    assert E.executive_answers([RQ1], {"RQ1": _sections()}, 225) == [
        {"rq_id": "RQ1", "question": RQ1.question, "value": "24.0%",
         "answer": "54 of 225 articles (24.0%) answer this question"}]
    assert E.executive_answers([RQ1], {"RQ1": []}, 225)[0]["answer"] == "No articles for this question"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_engine_insights.py -q`
Expected: FAIL — `ModuleNotFoundError: ... engine_insights`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/engine_insights.py
"""Insights stage: cited, number-checked insight cards per RQ (draft_section does the validation)."""
from __future__ import annotations

from .citations import CitationRegistry
from .engine_types import RQ, EngineRow, Section
from .insights import draft_section

N_INSIGHTS = 3
CANDIDATES = 12


def _candidates(sections: list[Section], rows: list[EngineRow]):
    by_url = {r.article.norm_url: r.article for r in rows}
    ordered = [u for s in sections for u in s.candidate_urls if u in by_url] + [r.article.norm_url for r in rows]
    seen, out = set(), []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(by_url[u])
    return out[:CANDIDATES]


def rq_insights(rq: RQ, sections: list[Section], rows: list[EngineRow], registry: CitationRegistry, llm) -> list[dict]:
    facts = [f for s in sections if not s.skipped for f in s.facts]
    if not facts or not rows:
        return []
    return draft_section(rq.question or rq.id, facts, _candidates(sections, rows), registry, llm, N_INSIGHTS)


def executive_answers(rqs: list[RQ], sections_by_rq: dict[str, list[Section]], base_n: int) -> list[dict]:
    answers = []
    for rq in rqs:
        kpi = next((s for s in sections_by_rq.get(rq.id, []) if s.module == "share_kpi" and not s.skipped), None)
        if kpi is None:
            answers.append({"rq_id": rq.id, "question": rq.question, "value": "n/a",
                            "answer": "No articles for this question"})
        else:
            answers.append({"rq_id": rq.id, "question": rq.question, "value": f"{kpi.chart['values'][0]}%",
                            "answer": kpi.facts[0].split(": ", 1)[1]})
    return answers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_engine_insights.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/engine_insights.py agent/tests/test_deliverable_engine_insights.py
git commit -m "feat(deliverable): per-RQ cited insights and executive answers"
```

---

### Task 8: Reference-deck index and selection

**Files:**
- Create: `agent/app/domains/deliverable/templates_index.py`
- Test: `agent/tests/test_deliverable_templates.py`

**Interfaces:**
- Consumes: `config.TEMPLATES_DIR`, `store.save_reference_deck`, `store.list_reference_decks`, optional
  `llm.embed(text) -> list[float]` (may raise).
- Produces: `index_templates(llm=None) -> int`, `is_usable(path: Path) -> bool` (layout named "Blank" and ≥2
  slides), `choose_template(scope_text: str, llm=None) -> Path` (falls back to `DEFAULT_TEMPLATE`),
  `DEFAULT_TEMPLATE: Path`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_templates.py
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from pptx import Presentation

from agent.app.core import store
from agent.app.domains.deliverable import templates_index as T


def _deck(path, words):
    prs = Presentation()
    for _ in range(2):
        s = prs.slides.add_slide(prs.slide_layouts[6])   # default template's layout 6 is named "Blank"
        s.shapes.add_textbox(0, 0, 100, 100).text_frame.text = words
    prs.save(path)
    return path


def setup_module(_):
    store.init_intelligence_db()


def test_token_overlap_picks_the_closest_usable_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(T.config, "TEMPLATES_DIR", tmp_path)
    _deck(tmp_path / "baby.pptx", "baby skincare editorial dermatologist coverage")
    _deck(tmp_path / "auto.pptx", "automotive launch dealership")
    assert T.index_templates() == 2
    assert T.choose_template("Baby Skincare Category earned editorial").name == "baby.pptx"


def test_unusable_or_missing_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setattr(T.config, "TEMPLATES_DIR", tmp_path / "empty")
    assert T.choose_template("anything") == T.DEFAULT_TEMPLATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_templates.py -q`
Expected: FAIL — `ModuleNotFoundError: ... templates_index`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/templates_index.py
"""Template stage: index the reference decks once and pick the one closest to the project's scope."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from pptx import Presentation

from ...core import config, store

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE = config.TEMPLATES_DIR / "Hunter PR Research_Johnson’s (Baby) Editorial _May 2026.pptx"
_WORD = re.compile(r"[a-z]{3,}")
MAX_TEXT = 4000


def is_usable(path: Path) -> bool:
    try:
        prs = Presentation(str(path))
    except Exception:
        return False
    return len(prs.slides) >= 2 and any(l.name == "Blank" for l in prs.slide_layouts)


def _deck_text(path: Path) -> str:
    prs = Presentation(str(path))
    parts = [path.stem] + [sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame]
    return " ".join(parts)[:MAX_TEXT]


def _embed(llm, text: str):
    try:
        return llm.embed(text) if llm is not None and hasattr(llm, "embed") else None
    except Exception as e:   # embeddings are optional: token overlap still works
        logger.info("template embedding unavailable (%s)", e)
        return None


def index_templates(llm=None) -> int:
    folder = Path(config.TEMPLATES_DIR)
    count = 0
    for path in sorted(folder.glob("*.pptx")) if folder.exists() else []:
        if path.name.startswith("~$") or not is_usable(path):
            continue
        text = _deck_text(path)
        store.save_reference_deck(str(path), text, _embed(llm, text))
        count += 1
    return count


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def choose_template(scope_text: str, llm=None) -> Path:
    folder = str(Path(config.TEMPLATES_DIR))

    def current():
        return [d for d in store.list_reference_decks() if d["path"].startswith(folder) and Path(d["path"]).exists()]

    decks = current() or (current() if index_templates(llm) else [])
    if not decks:
        return DEFAULT_TEMPLATE
    query_vec = _embed(llm, scope_text) if any(d["embedding"] for d in decks) else None
    query_tokens = _tokens(scope_text)

    def score(d):
        if query_vec and d["embedding"]:
            return _cosine(query_vec, d["embedding"])
        return len(query_tokens & _tokens(d["text"])) / (len(query_tokens) or 1)

    best = max(decks, key=score)
    return Path(best["path"]) if score(best) > 0 else DEFAULT_TEMPLATE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_templates.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/templates_index.py agent/tests/test_deliverable_templates.py
git commit -m "feat(deliverable): index reference decks and choose the closest template"
```

---

### Task 9: Brand kit (Brandfetch colours, fonts, images, logo) and visuals

**Files:**
- Create: `agent/app/domains/deliverable/brand_kit.py`
- Create: `agent/app/domains/deliverable/visuals.py`
- Create: `agent/app/domains/deliverable/amcharts_png.py`
- Test: `agent/tests/test_deliverable_brand_kit.py`, `agent/tests/test_deliverable_visuals.py`

**Interfaces:**
- Consumes: `research.brandfetch.resolve_brand_domain(name) -> str | None`, `research.brandfetch.is_reachable()`,
  env `BRANDFETCH_API_KEY` (never logged), `cli._download_logos(brands: list[dict], folder) -> dict[str, Path | None]`
  (expects `[{"brand": name}]`), `cli.save_logo_png(data: bytes, path) -> Path | None`,
  `research.pexels.resolve_background_image(query) -> dict` (`image_url`, `photographer`),
  `gauge._CDN`, `gauge.RENDER_TIMEOUT_MS`, `gauge.SETTLE_MS`, Playwright sync API.
- Produces:

```python
@dataclass
class BrandKit:
    name: str
    domain: str | None = None
    colors: list[str] = field(default_factory=list)      # raw brand hex, no '#', ordered brand > accent > dark > light
    title_font: str = "Arial"                             # safe to use in PPTX
    body_font: str = "Arial"
    logo: Path | None = None
    banner: Path | None = None                            # brand banner / hero image
    palette: list[str] = field(default_factory=list)      # 4 light chart tints derived from colors (or logo)
    accent: str = "5B2C9D"                                # heading accent; brand colour if it contrasts on white
```

  `brand_kit.fetch_kit(brand_name: str, folder: Path) -> BrandKit` (never raises; no kit → house palette, Arial),
  `brand_kit.tints(hexes: list[str]) -> list[str]`, `brand_kit.safe_font(name: str, origin: str | None) -> str`,
  `brand_kit.contrast_ratio(a: str, b: str) -> float`;
  `visuals.palette_from_logo(path) -> list[str]`, `visuals.logos(names, folder) -> dict[str, Path]`,
  `visuals.ICONS: dict[str, str]`, `visuals.icon_png(icon_id, folder, color="5B2C9D") -> Path | None`,
  `visuals.country_flag_png(country, folder) -> Path | None`, `visuals.hero_image(query, folder) -> tuple[Path | None, str]`;
  `amcharts_png.render_html_png(html, out_path, width=900, height=560) -> Path`,
  `amcharts_png.render_treemap_png(categories, values, out_path) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_deliverable_brand_kit.py
"""Brandfetch brand kit: colours become light chart tints, fonts are used only when safe, banner goes on the cover."""
from pathlib import Path

from PIL import Image

from agent.app.domains.deliverable import brand_kit as B
from agent.app.domains.deliverable.style import PALETTE, VIOLET


def _lum(hex_rgb):
    r, g, b = (int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _api_reply(tmp_path):
    return {"name": "Aveeno", "domain": "aveeno.com",
            "colors": [{"hex": "#0B3D91", "type": "brand"}, {"hex": "#F2A900", "type": "accent"},
                       {"hex": "#111111", "type": "dark"}, {"hex": "#FAFAFA", "type": "light"}],
            "fonts": [{"name": "Montserrat", "type": "title", "origin": "google"},
                      {"name": "Aveeno Sans", "type": "body", "origin": "custom"}],
            "images": [{"type": "banner", "formats": [{"src": "https://cdn/banner.jpg", "format": "jpeg"}]}],
            "logos": [{"type": "logo", "formats": [{"src": "https://cdn/logo.png", "format": "png"}]}]}


def test_kit_from_brandfetch_uses_colours_fonts_and_images(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "resolve_brand_domain", lambda name: "aveeno.com")
    monkeypatch.setattr(B, "_brand_api", lambda domain: _api_reply(tmp_path))
    def fake_download(url, path):
        Image.new("RGB", (20, 20), (11, 61, 145)).save(path)
        return path
    monkeypatch.setattr(B, "_download_image", fake_download)
    kit = B.fetch_kit("Aveeno", tmp_path)
    assert kit.colors[:2] == ["0B3D91", "F2A900"]                       # brand, accent first; dark/light last
    assert len(kit.palette) == 4 and all(_lum(c) > 0.55 for c in kit.palette)   # light tints for white slides
    assert kit.accent == "0B3D91"                                       # dark brand blue contrasts on white
    assert kit.title_font == "Montserrat" and kit.body_font == "Arial"  # custom font is not trusted to render
    assert kit.banner and kit.banner.exists() and kit.logo and kit.logo.exists()


def test_no_kit_falls_back_to_house_style(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "resolve_brand_domain", lambda name: None)
    kit = B.fetch_kit("Baby Skincare Category", tmp_path)
    assert kit.palette == list(PALETTE) and kit.accent == VIOLET and kit.title_font == "Arial" and kit.banner is None


def test_light_brand_colour_is_not_used_as_heading_accent(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "resolve_brand_domain", lambda name: "x.com")
    monkeypatch.setattr(B, "_brand_api", lambda d: {"colors": [{"hex": "#FFE066", "type": "brand"}], "fonts": [], "images": [], "logos": []})
    kit = B.fetch_kit("Yellow", tmp_path)
    assert kit.accent == VIOLET and B.contrast_ratio("FFE066", "FFFFFF") < 4.5


def test_api_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "resolve_brand_domain", lambda name: "x.com")
    def boom(domain):
        raise B.requests.RequestException("down")
    monkeypatch.setattr(B, "_brand_api", boom)
    assert B.fetch_kit("X", tmp_path).palette == list(PALETTE)
```

```python
# agent/tests/test_deliverable_visuals.py
from PIL import Image

from agent.app.domains.deliverable import visuals
from agent.app.domains.deliverable.style import PALETTE


def _lum(hex_rgb):
    r, g, b = (int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_palette_from_a_logo_is_light_and_on_brand(tmp_path):
    logo = tmp_path / "logo.png"
    img = Image.new("RGB", (60, 60), "white")
    for x in range(30):
        for y in range(60):
            img.putpixel((x, y), (0, 82, 165))
    img.save(logo)
    pal = visuals.palette_from_logo(logo)
    assert len(pal) == 4 and all(_lum(c) > 0.55 for c in pal)
    r, g, b = (int(pal[0][i:i + 2], 16) for i in (0, 2, 4))
    assert b > r and b > g


def test_palette_without_logo_is_the_house_palette():
    assert visuals.palette_from_logo(None) == list(PALETTE)


def test_every_module_has_an_icon():
    from agent.app.domains.deliverable.catalog import MODULES
    assert set(MODULES) <= set(visuals.ICONS)


def test_icon_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(visuals, "_fetch_svg", lambda icon_id, color: None)
    assert visuals.icon_png("lucide:star", tmp_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest agent/tests/test_deliverable_brand_kit.py agent/tests/test_deliverable_visuals.py -q`
Expected: FAIL — `ModuleNotFoundError: ... brand_kit` / `visuals`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/brand_kit.py
"""Brand kit from the Brandfetch Brand API: colours → light chart tints and a heading accent, fonts (only when
they will render), banner image and logo. Any failure falls back to the house style; never raises."""
from __future__ import annotations

import colorsys
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

from ..research.brandfetch import resolve_brand_domain
from . import style

logger = logging.getLogger(__name__)
BRAND_API = "https://api.brandfetch.io/v2/brands"
TIMEOUT_S = 15
MIN_HEADING_CONTRAST = 4.5        # WCAG AA for text on white
TINT_LIGHTNESS = (0.82, 0.74, 0.88, 0.78)
_COLOR_ORDER = {"brand": 0, "accent": 1, "dark": 2, "light": 3}
SAFE_FONTS = {"arial", "calibri", "segoe ui", "georgia", "verdana", "tahoma", "trebuchet ms", "helvetica"}


@dataclass
class BrandKit:
    name: str
    domain: str | None = None
    colors: list[str] = field(default_factory=list)
    title_font: str = style.FONT
    body_font: str = style.FONT
    logo: Path | None = None
    banner: Path | None = None
    palette: list[str] = field(default_factory=lambda: list(style.PALETTE))
    accent: str = style.VIOLET


def _brand_api(domain: str) -> dict:
    r = requests.get(f"{BRAND_API}/{domain}", timeout=TIMEOUT_S,
                     headers={"Authorization": f"Bearer {os.environ.get('BRANDFETCH_API_KEY', '')}"})
    r.raise_for_status()
    return r.json() or {}


def _luminance(hex_rgb: str) -> float:
    c = [int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tints(hexes: list[str]) -> list[str]:
    """Four light tints of the brand hues (skipping near-greys), light enough for a white slide."""
    hues = []
    for h in hexes:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        if sat > 0.2:
            hues.append((hue, sat))
    if not hues:
        return list(style.PALETTE)
    out = []
    for i, light in enumerate(TINT_LIGHTNESS):
        hue, sat = hues[i % len(hues)]
        hue = (hue + 0.07 * (i // len(hues))) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, light, min(0.65, max(0.35, sat)))
        out.append(f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return out


def safe_font(name: str, origin: str | None) -> str:
    """Google fonts and common system fonts are used; custom brand fonts would be silently substituted on a
    viewer's machine, so they fall back to the house font."""
    if name and (origin == "google" or name.strip().lower() in SAFE_FONTS):
        return name.strip()
    return style.FONT


def _download_image(url: str, path: Path) -> Path | None:
    from .cli import save_logo_png
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("brand image unavailable: %s", e)
        return None
    if not r.ok or not r.headers.get("content-type", "image/").startswith("image/"):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    return save_logo_png(r.content, path)


def _first_src(entries: list[dict], types: tuple[str, ...]) -> str | None:
    for wanted in types:
        for e in entries or []:
            if e.get("type") == wanted:
                fmts = sorted(e.get("formats") or [], key=lambda f: f.get("format") not in ("png", "jpeg", "jpg"))
                if fmts and fmts[0].get("src"):
                    return fmts[0]["src"]
    return None


def fetch_kit(brand_name: str, folder: Path) -> BrandKit:
    kit = BrandKit(name=brand_name)
    try:
        domain = resolve_brand_domain(brand_name)
        if not domain:
            return kit
        data = _brand_api(domain)
    except (requests.RequestException, ValueError) as e:
        logger.warning("brand kit for %r unavailable: %s", brand_name, type(e).__name__)
        return kit
    kit.domain = domain
    colors = sorted((c for c in data.get("colors") or [] if re.fullmatch(r"#?[0-9A-Fa-f]{6}", c.get("hex") or "")),
                    key=lambda c: _COLOR_ORDER.get(c.get("type"), 9))
    kit.colors = [c["hex"].lstrip("#").upper() for c in colors]
    kit.palette = tints(kit.colors)
    kit.accent = next((c for c in kit.colors if contrast_ratio(c, style.WHITE) >= MIN_HEADING_CONTRAST
                       and c not in ("000000", "111111")), style.VIOLET)
    for f in data.get("fonts") or []:
        if f.get("type") == "title":
            kit.title_font = safe_font(f.get("name") or "", f.get("origin"))
        elif f.get("type") == "body":
            kit.body_font = safe_font(f.get("name") or "", f.get("origin"))
    slug = re.sub(r"[^a-z0-9]+", "_", brand_name.lower())
    banner = _first_src(data.get("images") or [], ("banner", "other"))
    if banner:
        kit.banner = _download_image(banner, folder / f"{slug}_banner.png")
    logo = _first_src(data.get("logos") or [], ("logo", "symbol", "icon"))
    if logo:
        kit.logo = _download_image(logo, folder / f"{slug}_logo.png")
    return kit
```

```python
# agent/app/domains/deliverable/amcharts_png.py
"""Charts PowerPoint can't draw natively (treemap; the gauge lives in gauge.py) rendered with amCharts 5 → PNG."""
from __future__ import annotations

import json
from pathlib import Path

from . import style
from .gauge import _CDN, RENDER_TIMEOUT_MS, SETTLE_MS


def render_html_png(html: str, out_path: Path, width: int = 900, height: int = 560) -> Path:
    from playwright.sync_api import sync_playwright
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html, wait_until="networkidle", timeout=RENDER_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        page.screenshot(path=str(out_path))
        browser.close()
    return out_path


def treemap_html(categories: list[str], values: list[float], palette: list[str] | None = None) -> str:
    data = [{"name": c, "value": v} for c, v in zip(categories, values)]
    colors = [f"#{c}" for c in (palette or style.PALETTE)]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<script src="{_CDN}/index.js"></script><script src="{_CDN}/hierarchy.js"></script>
<style>html,body{{margin:0;background:#FFFFFF}}#c{{width:900px;height:560px}}</style></head>
<body><div id="c"></div><script>
const root = am5.Root.new("c");
const s = root.container.children.push(am5hierarchy.Treemap.new(root, {{
  downDepth: 1, initialDepth: 1, valueField: "value", categoryField: "name", childDataField: "children",
  nodePaddingOuter: 4, nodePaddingInner: 4}}));
s.set("colors", am5.ColorSet.new(root, {{colors: {json.dumps(colors)}.map(c => am5.color(c))}}));
s.labels.template.setAll({{fontSize: 18, fill: am5.color("#{style.BODY}"), text: "{{category}}\\n{{sum}}"}});
s.data.setAll([{{name: "root", children: {json.dumps(data)}}}]);
s.set("selectedDataItem", s.dataItems[0]);
</script></body></html>"""


def render_treemap_png(categories: list[str], values: list[float], out_path: Path,
                       palette: list[str] | None = None) -> Path:
    return render_html_png(treemap_html(categories, values, palette), out_path)
```

```python
# agent/app/domains/deliverable/visuals.py
"""Logos for many brands, Iconify icons and country flags as PNG, and the category hero image."""
from __future__ import annotations

import colorsys
import logging
import re
from pathlib import Path

import requests
from PIL import Image

from . import style

logger = logging.getLogger(__name__)
ICON_API = "https://api.iconify.design"
TIMEOUT_S = 15
LIGHTNESS = (0.80, 0.72, 0.86, 0.76)

ICONS = {
    "share_kpi": "lucide:pie-chart", "volume_trend": "lucide:trending-up", "sentiment_split": "lucide:smile",
    "outlet_ranking": "lucide:newspaper", "reach": "lucide:radio-tower", "theme_clusters": "lucide:layout-grid",
    "entities": "lucide:users", "brand_sov": "lucide:award", "top_articles": "lucide:file-text",
    "takeaway": "lucide:lightbulb", "methodology": "lucide:database", "overview": "lucide:bar-chart-3",
}
_ISO = {"united states": "us", "usa": "us", "us": "us", "united kingdom": "gb", "uk": "gb", "canada": "ca",
        "india": "in", "australia": "au", "germany": "de", "france": "fr"}


def palette_from_logo(path: Path | None) -> list[str]:
    """Fallback palette when Brandfetch has no colours: light tints of the logo's saturated hues."""
    if not path or not Path(path).exists():
        return list(style.PALETTE)
    img = Image.open(path).convert("RGB").resize((80, 80))
    hues = []
    for _, (r, g, b) in sorted(img.quantize(colors=6).convert("RGB").getcolors(80 * 80) or [], reverse=True):
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s > 0.25 and 0.12 < l < 0.9:
            hues.append((h, s))
    if not hues:
        return list(style.PALETTE)
    out = []
    for i, light in enumerate(LIGHTNESS):
        h, s = hues[i % len(hues)]
        h = (h + 0.08 * (i // len(hues))) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, light, min(0.65, max(0.35, s)))
        out.append(f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}")
    return out


def logos(names: list[str], folder: Path) -> dict[str, Path]:
    from .cli import _download_logos
    folder.mkdir(parents=True, exist_ok=True)
    got = _download_logos([{"brand": n} for n in names if n], folder)
    return {name: path for name, path in got.items() if path}


def _fetch_svg(icon_id: str, color: str) -> str | None:
    prefix, name = icon_id.split(":", 1)
    params = {"height": 96} if prefix == "circle-flags" else {"color": f"#{color}", "height": 96}
    try:
        r = requests.get(f"{ICON_API}/{prefix}/{name}.svg", params=params, timeout=TIMEOUT_S)
        return r.text if r.ok and r.text.lstrip().startswith("<svg") else None
    except requests.RequestException as e:
        logger.warning("icon %s unavailable: %s", icon_id, e)
        return None


def icon_png(icon_id: str, folder: Path, color: str = style.VIOLET) -> Path | None:
    out = folder / (re.sub(r"[^a-z0-9]+", "_", f"{icon_id}_{color}".lower()) + ".png")
    if out.exists():
        return out
    svg = _fetch_svg(icon_id, color)
    if not svg:
        return None
    from playwright.sync_api import sync_playwright
    folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 96, "height": 96})
        page.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
        page.locator("svg").screenshot(path=str(out), omit_background=True)
        browser.close()
    return out


def country_flag_png(country: str, folder: Path) -> Path | None:
    code = _ISO.get((country or "").strip().lower())
    return icon_png(f"circle-flags:{code}", folder) if code else None


def hero_image(query: str, folder: Path) -> tuple[Path | None, str]:
    from ..research.pexels import resolve_background_image
    info = resolve_background_image(query) or {}
    url = info.get("image_url")
    if not url:
        return None, ""
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        logger.warning("hero image unavailable: %s", e)
        return None, ""
    if not r.ok:
        return None, ""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "hero.jpg"
    out.write_bytes(r.content)
    return out, f"Photo: {info.get('photographer') or 'Pexels'} / Pexels"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_deliverable_brand_kit.py agent/tests/test_deliverable_visuals.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/brand_kit.py agent/app/domains/deliverable/visuals.py agent/app/domains/deliverable/amcharts_png.py agent/tests/test_deliverable_brand_kit.py agent/tests/test_deliverable_visuals.py
git commit -m "feat(deliverable): Brandfetch brand kit (colours, fonts, images, logo), icons, flags and hero image"
```

---

### Task 10: Generic deck renderer

**Files:**
- Modify: `agent/app/domains/deliverable/blocks.py` (`add_doughnut`, `add_text`, `add_header`)
- Create: `agent/app/domains/deliverable/generic_deck.py`
- Test: `agent/tests/test_deliverable_generic_deck.py`

**Interfaces:**
- Consumes: `blocks.*`, `deck.keep_cover_and_closing, deck._set_cover, deck._move_to_end, deck._add_logo,
  deck.paginate`, `gauge.render_gauge_png`, `amcharts_png.render_treemap_png`, `BrandKit` fields via `DeckInput`.
- Produces:

```python
@dataclass
class DeckInput:
    title: str; subtitle: str; date_label: str; period_label: str
    rqs: list[RQ]
    overview: Section
    sections_by_rq: dict[str, list[Section]]
    insights_by_rq: dict[str, list[dict]]
    answers: list[dict]                   # executive_answers()
    takeaways: list[dict]                 # {"headline","text","citations"}
    methodology: list[str]
    citations: list[dict]                 # CitationRegistry.entries()
    base_n: int
    palette: list[str]                    # BrandKit.palette
    accent: str                           # BrandKit.accent (headings, kickers)
    title_font: str                       # BrandKit.title_font
    logos: dict[str, Path]
    icons: dict[str, Path]                # module key → png
    hero: Path | None                     # category stock photo (Pexels)
    hero_credit: str
    brand_image: Path | None              # BrandKit.banner
    flag: Path | None

def build_generic_deck(inp: DeckInput, template: Path, work_dir: Path, out_path: Path) -> tuple[Path, list[int]]
```

  Returns the PPTX path and the 1-based slide numbers of the citation appendix (skipped by the fact check).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_generic_deck.py
"""The generic deck renders charts, tables, cards and pictures for any set of RQs, on light backgrounds,
in the brand's heading font and accent."""
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from PIL import Image

from agent.app.domains.deliverable import generic_deck as G
from agent.app.domains.deliverable.engine_types import RQ, Section


def _template(tmp_path):
    prs = Presentation()
    for text in ("Cover title", "Closing"):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(0, 0, 3000000, 500000).text_frame.text = text
    path = tmp_path / "tpl.pptx"
    prs.save(path)
    return path


def _png(tmp_path, name):
    p = tmp_path / name
    Image.new("RGB", (40, 40), (90, 44, 157)).save(p)
    return p


def _input(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "render_gauge_png", lambda v, label, out: _png(tmp_path, "gauge.png"))
    monkeypatch.setattr(G, "render_treemap_png", lambda c, v, out, palette=None: _png(tmp_path, "tree.png"))
    rq1, rq2 = RQ("RQ1", "How much coverage is deal-led?"), RQ("RQ2", "Which experts are cited?")
    s1 = [Section("rq1-share_kpi", "RQ1", "share_kpi", "Share", chart={"kind": "kpi", "categories": ["Share"], "values": [24.0], "unit": "percent", "peaks": []}, facts=["RQ1: 54 of 225 articles (24.0%) answer this question"]),
          Section("rq1-volume_trend", "RQ1", "volume_trend", "Trend", chart={"kind": "line_peaks", "categories": ["Jan-26", "Feb-26", "Mar-26"], "values": [3, 9, 4], "peaks": [1], "unit": "count"}, facts=["Peak 1: Feb-26 with 9 articles"]),
          Section("rq1-sentiment_split", "RQ1", "sentiment_split", "Sentiment", chart={"kind": "doughnut", "categories": ["Positive", "Negative"], "values": [80.0, 20.0], "unit": "percent", "peaks": []}),
          Section("rq1-theme_clusters", "RQ1", "theme_clusters", "Themes", chart={"kind": "treemap", "categories": ["Deals"], "values": [5], "unit": "count", "peaks": []}),
          Section("rq1-brand_sov", "RQ1", "brand_sov", "Brands", chart={"kind": "bar", "categories": ["Aveeno"], "values": [100.0], "unit": "percent", "peaks": []}, notes=["logos"]),
          Section("rq1-top_articles", "RQ1", "top_articles", "Top", table={"header": ["Headline", "Outlet"], "rows": [["A", "B"]], "col_widths": [6, 6]})]
    s2 = [Section("rq2-share_kpi", "RQ2", "share_kpi", "Share", skipped="No articles for this question")]
    return G.DeckInput(
        title="Baby Skincare Category", subtitle="Earned Media Analysis", date_label="October 2026",
        period_label="Oct 2025 – Oct 2026", rqs=[rq1, rq2],
        overview=Section("overview", None, "overview", "Overview", chart={"kind": "bar", "categories": ["RQ1", "RQ2"], "values": [54, 0], "unit": "count", "peaks": []}, facts=["Base: 225 unique articles across all questions"]),
        sections_by_rq={"RQ1": s1, "RQ2": s2},
        insights_by_rq={"RQ1": [{"headline": "Deals lead", "text": "54 of 225 articles", "citations": [1]}], "RQ2": []},
        answers=[{"rq_id": "RQ1", "question": rq1.question, "value": "24.0%", "answer": "54 of 225 articles"},
                 {"rq_id": "RQ2", "question": rq2.question, "value": "n/a", "answer": "No articles for this question"}],
        takeaways=[{"headline": "Act on deals", "text": "Deal coverage is 24.0%", "citations": [1]}],
        methodology=["5 files, 865 rows, 778 unique articles"],
        citations=[{"n": 1, "outlet": "O", "title": "T", "url": "https://x", "date": "2026-01-02"}],
        base_n=225, palette=["D9C8F0", "FDE3D2", "D4E6F7", "D3F0E3"], accent="0B3D91", title_font="Montserrat",
        logos={"Aveeno": _png(tmp_path, "aveeno.png")},
        icons={"share_kpi": _png(tmp_path, "i1.png"), "takeaway": _png(tmp_path, "i2.png")},
        hero=_png(tmp_path, "hero.png"), hero_credit="Photo: X / Pexels", brand_image=_png(tmp_path, "banner.png"),
        flag=_png(tmp_path, "us.png"))


def test_deck_has_visuals_on_light_backgrounds_in_brand_style(tmp_path, monkeypatch):
    out, appendix = G.build_generic_deck(_input(tmp_path, monkeypatch), _template(tmp_path), tmp_path, tmp_path / "d.pptx")
    prs = Presentation(out)
    charts = sum(1 for s in prs.slides for sh in s.shapes if getattr(sh, "has_chart", False) and sh.has_chart)
    tables = sum(1 for s in prs.slides for sh in s.shapes if getattr(sh, "has_table", False) and sh.has_table)
    pictures = sum(1 for s in prs.slides for sh in s.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert charts >= 4 and tables >= 2 and pictures >= 6
    texts = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert "No articles for this question" in texts and "Deals lead" in texts and "[1]" in texts
    fonts = {r.font.name for s in prs.slides for sh in s.shapes if sh.has_text_frame
             for p in sh.text_frame.paragraphs for r in p.runs}
    assert "Montserrat" in fonts
    assert prs.slides[-1].shapes[0].text_frame.text == "Closing"
    assert appendix and all(1 <= n <= len(prs.slides) for n in appendix)
    for s in prs.slides:
        fill = s.background.fill
        if fill.type == 1:
            assert str(fill.fore_color.rgb) not in ("000000", "404040", "808080")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_generic_deck.py -q`
Expected: FAIL — `ModuleNotFoundError: ... generic_deck`.

- [ ] **Step 3: Implement**

`blocks.py`:
- `add_doughnut(slide, x, y, w, h, categories, values, number_format=PERCENT_FORMAT, colors=None)`; inside the
  point loop use `palette = colors or style.PALETTE` and `palette[i % len(palette)]`.
- `add_text(..., align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font=None)`; set
  `r.font.name = font or style.FONT`.
- `add_header(slide, kicker, title, summary, font=None, accent=None)`: pass `font` to the kicker and title
  `add_text` calls and use `accent or style.VIOLET` for their colour (read the current body of `add_header`
  and thread the two parameters through; the summary line keeps `style.FONT` and `style.BODY`).
Existing callers pass neither, so the reference deck is unchanged.

```python
# agent/app/domains/deliverable/generic_deck.py
"""Render stage: one visual deck for any project — cover with brand banner and category photo, executive answers,
overview, per-RQ chart slides with cited insight cards, tables, logos and icons, takeaways, methodology and a
citation appendix — in the brand's heading font, accent and chart tints."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from . import blocks, style
from .amcharts_png import render_treemap_png
from .deck import _add_logo, _move_to_end, _set_cover, keep_cover_and_closing, paginate
from .engine_types import RQ, Section
from .gauge import render_gauge_png

CITES_PER_PAGE = 14
CHART_TOP = 1.5
FOOT_SOURCE = "SOURCE: MELTWATER"
EMU_PER_IN = 914400


@dataclass
class DeckInput:
    title: str
    subtitle: str
    date_label: str
    period_label: str
    rqs: list[RQ]
    overview: Section
    sections_by_rq: dict[str, list[Section]]
    insights_by_rq: dict[str, list[dict]]
    answers: list[dict]
    takeaways: list[dict]
    methodology: list[str]
    citations: list[dict]
    base_n: int
    palette: list[str]
    accent: str
    title_font: str
    logos: dict[str, Path]
    icons: dict[str, Path]
    hero: Path | None
    hero_credit: str
    brand_image: Path | None
    flag: Path | None


def _slide(prs, inp: DeckInput, kicker: str, title: str, summary: str = "", icon: Path | None = None):
    s = blocks.new_content_slide(prs)
    blocks.add_header(s, kicker, title, summary, font=inp.title_font, accent=inp.accent)
    blocks.add_footer(s, f"{FOOT_SOURCE}  |  {inp.period_label}", inp.base_n)
    if icon and icon.exists():
        s.shapes.add_picture(str(icon), Inches(style.SLIDE_W - 0.95), Inches(0.3), height=Inches(0.5))
    return s


def _picture(slide, path: Path, x, y, w, h):
    slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))


def _draw_chart(slide, sec: Section, inp: DeckInput, work: Path, x, y, w, h):
    c = sec.chart
    kind, cats, vals = c["kind"], c.get("categories", []), c.get("values", [])
    if kind == "line_peaks":
        blocks.add_line_chart_with_peaks(slide, x, y, w, h, cats, vals, c.get("peaks", []))
    elif kind == "bar":
        fmt = blocks.PERCENT_FORMAT if c.get("unit") == "percent" else "0"
        blocks.add_bar_chart(slide, x, y, w, h, cats, vals, color=inp.palette[0], number_format=fmt)
    elif kind == "column":
        blocks.add_column_chart(slide, x, y, w, h, cats, vals, c.get("peaks", []))
    elif kind == "doughnut":
        blocks.add_doughnut(slide, x, y, w, h, cats, vals, colors=inp.palette)
    elif kind == "gauge":
        png = render_gauge_png(vals[0], cats[0] if cats else "", work / f"{sec.id}-gauge.png")
        _picture(slide, png, x, y, w, min(h, w * 0.62))
    elif kind == "treemap":
        png = render_treemap_png(cats, vals, work / f"{sec.id}-treemap.png", palette=inp.palette)
        _picture(slide, png, x, y, w, min(h, w * 0.62))
    elif kind == "kpi":
        note = sec.facts[0].split(": ", 1)[-1] if sec.facts else ""
        blocks.add_kpi_tiles(slide, x, y, w, min(h, 2.2), [{"value": f"{vals[0]}%", "label": cats[0] if cats else "", "note": note}])


def _cover(prs, inp: DeckInput):
    cover = prs.slides[0]
    _set_cover(cover, inp.title, inp.subtitle, inp.date_label)
    image = inp.brand_image if inp.brand_image and inp.brand_image.exists() else inp.hero
    if image and image.exists():
        pic = cover.shapes.add_picture(str(image), Inches(style.SLIDE_W - 4.6), Inches(1.2), width=Inches(4.2))
        credit = "" if image == inp.brand_image else inp.hero_credit
        if credit:
            blocks.add_text(cover, style.SLIDE_W - 4.6, 1.2 + pic.height / EMU_PER_IN + 0.05, 4.2, 0.3, credit, 7)
    if inp.flag and inp.flag.exists():
        cover.shapes.add_picture(str(inp.flag), Inches(0.6), Inches(6.2), height=Inches(0.45))


def _exec_summary(prs, inp: DeckInput):
    s = _slide(prs, inp, "EXECUTIVE SUMMARY", "What the coverage says",
               f"Base: {inp.base_n} unique articles across {len(inp.rqs)} questions", inp.icons.get("overview"))
    tiles = [{"value": a["value"], "label": a["rq_id"], "note": a["answer"]} for a in inp.answers[:4]]
    blocks.add_kpi_tiles(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 2.4, tiles)
    rows = [[a["rq_id"], a["question"][:80], a["answer"]] for a in inp.answers]
    blocks.add_table(s, style.MARGIN, 4.1, style.SLIDE_W - 2 * style.MARGIN, 0.3 * (len(rows) + 1),
                     ["Question", "Asked", "Answer"], rows, [1.0, 6.0, 5.4])


def _overview(prs, inp: DeckInput, work: Path):
    s = _slide(prs, inp, "OVERVIEW", inp.overview.title, inp.overview.facts[0] if inp.overview.facts else "",
               inp.icons.get("overview"))
    _draw_chart(s, inp.overview, inp, work, style.MARGIN, CHART_TOP, 7.4, 4.6)
    blocks.add_text(s, 8.2, CHART_TOP, 4.6, 4.6, "\n".join(inp.overview.facts[1:8]), 10)


def _logo_row(slide, inp: DeckInput, names: list[str], x: float, y: float):
    for j, name in enumerate([n for n in names if n in inp.logos][:6]):
        _add_logo(slide, inp.logos[name], x + (j % 3) * 1.45, y + (j // 3) * 0.75, 0.55)


def _rq_slides(prs, inp: DeckInput, rq: RQ, work: Path):
    sections = inp.sections_by_rq.get(rq.id, [])
    drawable = [x for x in sections if not x.skipped and x.chart and x.chart["kind"] != "kpi"]
    kpi = next((x for x in sections if x.module == "share_kpi" and not x.skipped), None)
    insights = inp.insights_by_rq.get(rq.id, [])
    summary = kpi.facts[0].split(": ", 1)[-1] if kpi else "No articles for this question"
    s = _slide(prs, inp, rq.id, rq.question[:90], summary, inp.icons.get("share_kpi"))
    if not kpi:
        blocks.add_text(s, style.MARGIN, CHART_TOP + 0.4, 12, 0.6, "No articles for this question", 18, True, inp.accent)
        return
    first = drawable[:2]
    width = (style.SLIDE_W - 2 * style.MARGIN - 0.3) / max(1, len(first))
    for i, sec in enumerate(first):
        x = style.MARGIN + i * (width + 0.3)
        blocks.add_text(s, x, CHART_TOP, width, 0.3, sec.title, 11, True, inp.accent, font=inp.title_font)
        _draw_chart(s, sec, inp, work, x, CHART_TOP + 0.3, width, 2.7)
        notes = [n for n in sec.notes if n != "logos"]
        if notes:
            blocks.add_text(s, x, CHART_TOP + 3.0, width, 0.25, "; ".join(notes), 8)
    if insights:
        blocks.add_insight_cards(s, style.MARGIN, CHART_TOP + 3.35, style.SLIDE_W - 2 * style.MARGIN, 2.0,
                                 insights[:3], cols=3)
    for sec in drawable[2:]:
        s2 = _slide(prs, inp, rq.id, sec.title, sec.facts[0] if sec.facts else "", inp.icons.get(sec.module))
        _draw_chart(s2, sec, inp, work, style.MARGIN, CHART_TOP, 7.6, 4.6)
        blocks.add_text(s2, 8.4, CHART_TOP, 4.4, 3.8, "\n".join(sec.facts[1:7]), 10)
        if "logos" in sec.notes:
            _logo_row(s2, inp, sec.chart["categories"], 8.4, 5.6)
    for sec in (x for x in sections if not x.skipped and x.table):
        s3 = _slide(prs, inp, rq.id, sec.title, sec.facts[0] if sec.facts else "", inp.icons.get(sec.module))
        rows = sec.table["rows"][:12]
        blocks.add_table(s3, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 0.32 * (len(rows) + 1),
                         sec.table["header"], rows, sec.table["col_widths"])
    skipped = [x for x in sections if x.skipped and x.module != "share_kpi"]
    if skipped:
        blocks.add_text(s, style.MARGIN, 6.55, 12, 0.25,
                        "Not shown: " + "; ".join(f"{x.title} ({x.skipped})" for x in skipped), 8)


def _takeaways(prs, inp: DeckInput):
    s = _slide(prs, inp, "KEY TAKEAWAYS", "What to do next", "", inp.icons.get("takeaway"))
    blocks.add_insight_cards(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 4.8, inp.takeaways[:6], cols=3)


def _methodology(prs, inp: DeckInput):
    s = _slide(prs, inp, "APPENDIX", "Definitions & Methodology", "", inp.icons.get("methodology"))
    blocks.add_text(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 4.8, "\n".join(inp.methodology), 10)


def _citations(prs, inp: DeckInput) -> list[int]:
    pages = paginate(inp.citations, CITES_PER_PAGE)
    numbers = []
    for i, page in enumerate(pages, start=1):
        s = _slide(prs, inp, "APPENDIX", f"Citations ({i}/{len(pages)})")
        rows = [[str(c["n"]), c["outlet"], c["title"][:70], c["date"], c["url"][:60]] for c in page]
        blocks.add_table(s, style.MARGIN, CHART_TOP, style.SLIDE_W - 2 * style.MARGIN, 0.3 * (len(rows) + 1),
                         ["#", "Outlet", "Headline", "Date", "URL"], rows, [0.5, 2.0, 5.2, 1.2, 3.5])
        numbers.append(len(prs.slides))
    return numbers


def build_generic_deck(inp: DeckInput, template: Path, work_dir: Path, out_path: Path) -> tuple[Path, list[int]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(template))
    keep_cover_and_closing(prs)
    _cover(prs, inp)
    _exec_summary(prs, inp)
    _overview(prs, inp, work_dir)
    for rq in inp.rqs:
        _rq_slides(prs, inp, rq, work_dir)
    _takeaways(prs, inp)
    _methodology(prs, inp)
    appendix = _citations(prs, inp)
    _move_to_end(prs, 1)                  # the template's closing slide goes last…
    appendix = [n - 1 for n in appendix]  # …so every appendix slide moves up by one
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path, appendix
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_deliverable_generic_deck.py agent/tests -q -k "deliverable or reference_deck"`
Expected: the new test passes; existing reference-deck tests still pass (new parameters default to old behaviour).

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/blocks.py agent/app/domains/deliverable/generic_deck.py agent/tests/test_deliverable_generic_deck.py
git commit -m "feat(deliverable): generic visual deck renderer in the brand's font, accent and tints"
```

---

### Task 11: Word brief

**Files:**
- Create: `agent/app/domains/deliverable/word_brief.py`
- Test: `agent/tests/test_deliverable_word_brief.py`

**Interfaces:**
- Consumes: `DeckInput`.
- Produces: `build_word_brief(inp: DeckInput, out_path: Path, slide_pngs: list[Path] | None = None) -> Path`
  (headings in `inp.title_font`, brand banner at the top when present).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_word_brief.py
from docx import Document

from agent.app.domains.deliverable.word_brief import build_word_brief
from agent.tests.test_deliverable_generic_deck import _input


def test_brief_mirrors_answers_insights_and_citations(tmp_path, monkeypatch):
    out = build_word_brief(_input(tmp_path, monkeypatch), tmp_path / "brief.docx")
    doc = Document(out)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Baby Skincare Category" in text and "RQ1" in text and "Deals lead" in text and "[1]" in text
    assert "No articles for this question" in text
    assert len(doc.tables) >= 2 and len(doc.inline_shapes) >= 1      # answers + citations; banner image
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_word_brief.py -q`
Expected: FAIL — `ModuleNotFoundError: ... word_brief`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/word_brief.py
"""The Word brief mirrors the deck: answers, per-RQ facts and cited insights, takeaways, method, citations."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Inches

from .generic_deck import DeckInput


def _table(doc, header: list[str], rows: list[list[str]]):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Light Grid Accent 1"
    for cell, h in zip(t.rows[0].cells, header):
        cell.text = h
    for r in rows:
        for cell, v in zip(t.add_row().cells, r):
            cell.text = str(v)
    return t


def _heading(doc, text: str, level: int, font: str):
    h = doc.add_heading(text, level)
    for run in h.runs:
        run.font.name = font
    return h


def build_word_brief(inp: DeckInput, out_path: Path, slide_pngs: list[Path] | None = None) -> Path:
    doc = Document()
    if inp.brand_image and inp.brand_image.exists():
        doc.add_picture(str(inp.brand_image), width=Inches(6))
    _heading(doc, f"{inp.title} — {inp.subtitle}", 0, inp.title_font)
    doc.add_paragraph(f"{inp.date_label}  |  {inp.period_label}  |  Base: {inp.base_n} unique articles")
    _heading(doc, "Executive summary", 1, inp.title_font)
    _table(doc, ["Question", "Asked", "Answer"], [[a["rq_id"], a["question"], a["answer"]] for a in inp.answers])
    for i, rq in enumerate(inp.rqs):
        _heading(doc, f"{rq.id}: {rq.question}", 1, inp.title_font)
        sections = [s for s in inp.sections_by_rq.get(rq.id, []) if not s.skipped]
        if not sections:
            doc.add_paragraph("No articles for this question")
            continue
        for s in sections:
            _heading(doc, s.title, 2, inp.title_font)
            for fact in s.facts[:6]:
                doc.add_paragraph(fact, style="List Bullet")
        for ins in inp.insights_by_rq.get(rq.id, []):
            doc.add_paragraph(f"{ins['headline']}: {ins['text']} " + "".join(f"[{c}]" for c in ins["citations"]))
        png = slide_pngs[i] if slide_pngs and i < len(slide_pngs) else None
        if png and Path(png).exists():
            doc.add_picture(str(png), width=Inches(6))
    _heading(doc, "Key takeaways", 1, inp.title_font)
    for t in inp.takeaways:
        doc.add_paragraph(f"{t['headline']}: {t['text']} " + "".join(f"[{c}]" for c in t["citations"]), style="List Bullet")
    _heading(doc, "Methodology", 1, inp.title_font)
    for line in inp.methodology:
        doc.add_paragraph(line)
    _heading(doc, "Citations", 1, inp.title_font)
    _table(doc, ["#", "Outlet", "Headline", "Date", "URL"],
           [[c["n"], c["outlet"], c["title"], c["date"], c["url"]] for c in inp.citations])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_word_brief.py -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/word_brief.py agent/tests/test_deliverable_word_brief.py
git commit -m "feat(deliverable): Word brief mirroring the deck sections"
```

---

### Task 12: QC auto-fix and fact check

**Files:**
- Create: `agent/app/domains/deliverable/factcheck.py`
- Test: `agent/tests/test_deliverable_factcheck.py`

**Interfaces:**
- Consumes: `qc.check_layout(pptx_path, skip) -> list[dict]` (`slide, kind, detail`), `qc.export_pngs(pptx_path,
  out_dir) -> list[Path]`, `core.llm_synthesis._figures`.
- Produces: `fact_check(pptx_path, facts: list[str], skip_slides: set[int]) -> list[dict]` (`slide, figure, text`),
  `autofix(pptx_path, issues) -> int`, `run_qc(pptx_path, facts, skip_slides, png_dir) -> dict`
  (`layout, facts, fixed, pngs, ready`).

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_factcheck.py
from pptx import Presentation
from pptx.util import Inches, Pt

from agent.app.domains.deliverable import factcheck as F


def _deck(tmp_path, texts):
    prs = Presentation()
    for t in texts:
        s = prs.slides.add_slide(prs.slide_layouts[6])
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(0.4))
        tb.text_frame.text = t
        tb.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    path = tmp_path / "d.pptx"
    prs.save(path)
    return path


def test_invented_figure_is_flagged_and_allowed_ones_pass(tmp_path):
    path = _deck(tmp_path, ["54 of 225 articles (24.0%) are deal-led [3]", "Our campaign drove 15% more leads"])
    issues = F.fact_check(path, ["RQ1: 54 of 225 articles (24.0%) answer this question"], skip_slides=set())
    assert [(i["slide"], i["figure"]) for i in issues] == [(2, "15%")]


def test_appendix_slides_are_skipped(tmp_path):
    path = _deck(tmp_path, ["2026-01-02 citation 9999"])
    assert F.fact_check(path, [], skip_slides={1}) == []


def test_autofix_shrinks_overflowing_text(tmp_path):
    path = _deck(tmp_path, ["word " * 120])
    assert F.autofix(path, [{"slide": 1, "kind": "overflow", "detail": "word word"}]) == 1
    size = Presentation(path).slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt
    assert size < 18
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_factcheck.py -q`
Expected: FAIL — `ModuleNotFoundError: ... factcheck`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/factcheck.py
"""QC stage: layout checks with automatic fixes, and a fact check that every slide figure is a computed fact."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt

from ...core.llm_synthesis import _figures
from . import qc

logger = logging.getLogger(__name__)
MIN_FONT_PT = 7
SHRINK_PT = 2
MAX_FIX_ROUNDS = 3
_CITATION = re.compile(r"\[\d+\]")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
FIXABLE = ("overflow", "off_slide", "dark_background")
BLOCKING = FIXABLE + ("table_overflow",)


def _slide_text(slide) -> str:
    parts = []
    for sh in slide.shapes:
        if sh.has_text_frame:
            parts.append(sh.text_frame.text)
        if getattr(sh, "has_table", False) and sh.has_table:
            parts += [c.text for row in sh.table.rows for c in row.cells]
    return "\n".join(parts)


def fact_check(pptx_path: Path, facts: list[str], skip_slides: set[int]) -> list[dict]:
    allowed = _figures(" ".join(facts))
    issues = []
    for n, slide in enumerate(Presentation(str(pptx_path)).slides, start=1):
        if n in skip_slides:
            continue
        text = _slide_text(slide)
        cleaned = _DATE.sub(" ", _YEAR.sub(" ", _CITATION.sub(" ", text)))
        for figure in sorted(_figures(cleaned) - allowed):
            line = next((l for l in text.splitlines() if figure.rstrip("%") in l), "")
            issues.append({"slide": n, "figure": figure, "text": line[:120]})
    return issues


def autofix(pptx_path: Path, issues: list[dict]) -> int:
    prs = Presentation(str(pptx_path))
    fixed = 0
    for issue in issues:
        slide = prs.slides[issue["slide"] - 1]
        if issue["kind"] == "overflow":
            for sh in slide.shapes:
                if sh.has_text_frame and sh.text_frame.text.startswith(issue["detail"][:20]):
                    for p in sh.text_frame.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(max(MIN_FONT_PT, (r.font.size.pt if r.font.size else 12) - SHRINK_PT))
                    fixed += 1
                    break
        elif issue["kind"] == "off_slide":
            for sh in slide.shapes:
                if sh.name == issue["detail"]:
                    sh.left = max(0, min(sh.left, prs.slide_width - sh.width))
                    sh.top = max(0, min(sh.top, prs.slide_height - sh.height))
                    fixed += 1
        elif issue["kind"] == "dark_background":
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            fixed += 1
    if fixed:
        prs.save(str(pptx_path))
    return fixed


def run_qc(pptx_path: Path, facts: list[str], skip_slides: set[int], png_dir: Path) -> dict:
    fixed = 0
    layout = qc.check_layout(pptx_path, skip=skip_slides)
    for _ in range(MAX_FIX_ROUNDS):
        fixable = [i for i in layout if i["kind"] in FIXABLE]
        if not fixable:
            break
        fixed += autofix(pptx_path, fixable)
        layout = qc.check_layout(pptx_path, skip=skip_slides)
    fact_issues = fact_check(pptx_path, facts, skip_slides)
    try:
        pngs = [str(p) for p in qc.export_pngs(pptx_path, png_dir)]
    except Exception as e:   # PowerPoint not installed / COM unavailable: thumbnails are optional
        logger.warning("slide PNG export unavailable: %s", e)
        pngs = []
    blocking = [i for i in layout if i["kind"] in BLOCKING]
    return {"layout": layout, "facts": fact_issues, "fixed": fixed, "pngs": pngs,
            "ready": not blocking and not fact_issues}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_factcheck.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/factcheck.py agent/tests/test_deliverable_factcheck.py
git commit -m "feat(deliverable): QC auto-fix loop and slide fact check"
```

---

### Task 13: Engine orchestrator

**Files:**
- Create: `agent/app/domains/deliverable/engine.py`
- Test: `agent/tests/test_deliverable_engine.py`

**Interfaces:**
- Consumes: everything above; `core.events.broadcast`; `core.anthropic_client.get_llm_client`;
  `store.get_project`, `store.get_latest_spec`, `store.get_latest_strategy`, `store.get_datasets_by_project`.
- Produces: `STAGES = ("gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template",
  "render", "qc")`; `class RunBusy(RuntimeError)`; `start_run(project_id, *, llm=None, threaded=True) -> int`;
  `run_engine(run_id, project_id, llm) -> None`; `run_payload(run_id) -> dict` (`{"run", "sections"}`).
  WS messages: `{"type": "deliverable_stage", "project_id", "run_id", "stage", "status", "detail"}`,
  `{"type": "deliverable_section", "project_id", "run_id", "section"}`,
  `{"type": "deliverable_completed", "project_id", "run_id", "ready"}`,
  `{"type": "deliverable_failed", "project_id", "run_id", "stage", "error"}`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_engine.py
"""End to end without Azure or network: gate, ingest, default plans, sections, deck + brief, QC; busy lock."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from pathlib import Path

import pytest
from PIL import Image

from agent.app.core import store
from agent.app.domains.deliverable import engine
from agent.app.domains.deliverable.brand_kit import BrandKit
from agent.tests.test_deliverable_generic_deck import _template
from agent.tests.test_deliverable_rows import _project


def _offline(monkeypatch, tmp_path):
    png = tmp_path / "p.png"
    Image.new("RGB", (20, 20), "white").save(png)
    monkeypatch.setattr(engine.brand_kit, "fetch_kit", lambda name, folder: BrandKit(name=name))
    monkeypatch.setattr(engine.visuals, "logos", lambda names, folder: {})
    monkeypatch.setattr(engine.visuals, "icon_png", lambda icon, folder, color="5B2C9D": png)
    monkeypatch.setattr(engine.visuals, "country_flag_png", lambda c, folder: None)
    monkeypatch.setattr(engine.visuals, "hero_image", lambda q, folder: (None, ""))
    monkeypatch.setattr(engine.templates_index, "choose_template", lambda text, llm=None: _template(tmp_path))
    monkeypatch.setattr(engine.factcheck.qc, "export_pngs", lambda p, d: [])
    monkeypatch.setattr(engine.generic_deck, "render_gauge_png", lambda v, l, out: png)
    monkeypatch.setattr(engine.generic_deck, "render_treemap_png", lambda c, v, out, palette=None: png)


def test_run_without_llm_completes_with_deck_brief_and_sections(tmp_path, monkeypatch):
    _offline(monkeypatch, tmp_path)
    pid = _project(tmp_path)
    monkeypatch.setattr(engine, "_gate_reasons", lambda project_id: [])
    events = []
    monkeypatch.setattr(engine, "broadcast", events.append)
    run_id = engine.start_run(pid, llm=None, threaded=False)
    run = store.get_deliverable_run(run_id)
    assert run["status"] == "completed", run["error"]
    assert Path(run["pptx_path"]).exists() and Path(run["docx_path"]).exists()
    assert set(run["stages"]) == set(engine.STAGES)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "deliverable_stage" and kinds[-1] == "deliverable_completed" and "deliverable_section" in kinds
    assert any(s["module"] == "share_kpi" for s in engine.run_payload(run_id)["sections"])


def test_gate_failure_is_reported(tmp_path, monkeypatch):
    _offline(monkeypatch, tmp_path)
    pid = _project(tmp_path)
    monkeypatch.setattr(engine, "_gate_reasons", lambda project_id: ["Scope is not approved"])
    events = []
    monkeypatch.setattr(engine, "broadcast", events.append)
    run_id = engine.start_run(pid, llm=None, threaded=False)
    run = store.get_deliverable_run(run_id)
    assert run["status"] == "failed" and "Scope is not approved" in run["error"]
    assert events[-1]["type"] == "deliverable_failed" and events[-1]["stage"] == "gate"


def test_second_run_while_busy_is_refused(tmp_path):
    pid = _project(tmp_path)
    store.create_deliverable_run(pid)            # still 'running'
    with pytest.raises(engine.RunBusy):
        engine.start_run(pid, llm=None, threaded=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: ... engine`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/engine.py
"""Deliverable engine: ten persisted stages, each broadcast on /ws; a failed stage stops the run visibly."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from pathlib import Path

from ...core import config, store
from ...core.events import broadcast
from . import (analytics, brand_kit, catalog, engine_insights, extract, factcheck, generic_deck, templates_index,
               visuals, word_brief)
from . import rows as R
from .citations import CitationRegistry
from .engine_types import Section

logger = logging.getLogger(__name__)
STAGES = ("gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc")
MAX_LOGOS = 10
_lock = threading.Lock()


class RunBusy(RuntimeError):
    pass


class StageFailed(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _gate_reasons(project_id: int) -> list[str]:
    reasons = []
    if (store.get_latest_spec(project_id) or {}).get("approval_status") != "approved":
        reasons.append("Scope is not approved")
    if (store.get_latest_strategy(project_id) or {}).get("approval_status") != "approved":
        reasons.append("Search strategy is not approved")
    if not [d for d in store.get_datasets_by_project(project_id) if d.get("approval_status") == "approved"]:
        reasons.append("No approved dataset")
    return reasons


class _Run:
    def __init__(self, run_id: int, project_id: int):
        self.run_id, self.project_id, self.stages = run_id, project_id, {}

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages[name] = status
        store.update_deliverable_run(self.run_id, stage=name, stages_json=self.stages)
        broadcast({"type": "deliverable_stage", "project_id": self.project_id, "run_id": self.run_id,
                   "stage": name, "status": status, "detail": detail})

    def section(self, payload: dict) -> None:
        store.save_deliverable_section(self.run_id, payload)
        broadcast({"type": "deliverable_section", "project_id": self.project_id, "run_id": self.run_id,
                   "section": payload})


def start_run(project_id: int, *, llm=None, threaded: bool = True) -> int:
    with _lock:
        if store.get_active_deliverable_run(project_id):
            raise RunBusy("A deliverable run is already in progress")
        run_id = store.create_deliverable_run(project_id)
    if threaded:
        if llm is None:
            from ...core.anthropic_client import get_llm_client
            llm = get_llm_client()
        threading.Thread(target=run_engine, args=(run_id, project_id, llm), daemon=True).start()
    else:
        run_engine(run_id, project_id, llm)
    return run_id


def _scope_text(project: dict) -> str:
    spec = project.get("spec") or {}
    return " ".join(filter(None, [(spec.get("commissioning_brand") or {}).get("name"),
                                  (spec.get("industry") or {}).get("name"),
                                  (spec.get("research_subject") or {}).get("description"),
                                  str(spec.get("raw_brief") or "")[:600]]))


def _methodology(summary: dict, rqs) -> list[str]:
    return ([f"{summary['files']} approved files; {summary['unique_urls']} unique article URLs; "
             f"{summary['stories']} unique stories; base {summary['base_n']} unique articles.",
             "Articles are counted once per URL; syndicated copies (same headline) are grouped into stories.",
             "Shares are of the base unless a chart says otherwise."]
            + [f"{q.id} query: {q.query}" for q in rqs if q.query])


def run_engine(run_id: int, project_id: int, llm) -> None:
    run = _Run(run_id, project_id)
    current = "gate"
    try:
        run.stage("gate", "running")
        reasons = _gate_reasons(project_id)
        if reasons:
            raise StageFailed("gate", "; ".join(reasons))
        run.stage("gate", "done")

        current = "ingest"
        run.stage("ingest", "running")
        rqs = R.load_rqs(project_id)
        if not rqs:
            raise StageFailed("ingest", "The search strategy has no research questions")
        rows = R.load_rows(project_id, rqs)
        if not rows:
            raise StageFailed("ingest", "The approved datasets have no usable rows")
        run.stage("ingest", "done", f"{len(rows)} unique articles")

        current = "routing"
        run.stage("routing", "running")
        rows = R.assign_stories(R.route(rows, rqs))
        base = R.base_n(rows)
        rows_by_rq = {q.id: R.rq_rows(rows, q.id) for q in rqs}
        summary = R.ingest_summary(project_id, rows)
        run.section({"id": "data-collection", "rq_id": None, "module": "data_collection", "title": "Data collection",
                     "data": summary, "facts": [f"Base: {base} unique articles across all questions"]})
        run.stage("routing", "done", f"base N = {base}")

        current = "plan"
        run.stage("plan", "running")
        plans = {q.id: catalog.plan_rq(llm, q, rows_by_rq[q.id])[0] for q in rqs}
        run.stage("plan", "done", ", ".join(f"{q.id}: {len(plans[q.id]['modules'])}" for q in rqs))

        current = "classify"
        run.stage("classify", "running")
        extraction: dict[tuple[str, str], dict | None] = {}
        skipped_kinds = set()
        for q in rqs:
            for m in plans[q.id]["modules"]:
                if m["module"] != "entities":
                    continue
                try:
                    extraction[(q.id, m["entity_kind"])] = extract.extract(llm, rows_by_rq[q.id], m["entity_kind"])
                except extract.ExtractionUnavailable as e:
                    extraction[(q.id, m["entity_kind"])] = None
                    skipped_kinds.add(m["entity_kind"])
                    logger.warning("extraction skipped for %s/%s: %s", q.id, m["entity_kind"], e)
        run.stage("classify", "done", f"skipped: {', '.join(sorted(skipped_kinds))}" if skipped_kinds else "")

        current = "compute"
        run.stage("compute", "running")
        overview = analytics.overview_section(rqs, rows_by_rq, base)
        run.section(overview.to_dict())
        sections_by_rq: dict[str, list[Section]] = {}
        for q in rqs:
            sections_by_rq[q.id] = [analytics.compute_module(m, q, rows_by_rq[q.id], base,
                                                             extraction.get((q.id, m.get("entity_kind"))))
                                    for m in plans[q.id]["modules"]]
            for s in sections_by_rq[q.id]:
                run.section(s.to_dict())
        run.stage("compute", "done")

        current = "insights"
        run.stage("insights", "running")
        registry = CitationRegistry()
        insights_by_rq = {}
        for q in rqs:
            insights_by_rq[q.id] = engine_insights.rq_insights(q, sections_by_rq[q.id], rows_by_rq[q.id], registry, llm)
            run.section({"id": f"{q.id.lower()}-insights", "rq_id": q.id, "module": "insights", "title": "Insights",
                         "insights": insights_by_rq[q.id]})
        answers = engine_insights.executive_answers(rqs, sections_by_rq, base)
        takeaways = [i for q in rqs for i in insights_by_rq[q.id][:1]]
        run.section({"id": "executive-summary", "rq_id": None, "module": "executive_summary",
                     "title": "Executive summary", "answers": answers, "takeaways": takeaways})
        run.stage("insights", "done")

        current = "template"
        run.stage("template", "running")
        project = store.get_project(project_id) or {}
        template = templates_index.choose_template(_scope_text(project), llm)
        run.stage("template", "done", template.name)

        current = "render"
        run.stage("render", "running")
        out_dir = config.DELIVERABLE_DIR / f"project_{project_id}" / f"run_{run_id}"
        spec = project.get("spec") or {}
        brand = (spec.get("commissioning_brand") or {}).get("name") or project.get("brand") or "Research"
        kit = brand_kit.fetch_kit(brand, out_dir / "brand")
        competitors = [e["name"] for e in spec.get("validated_entities") or [] if e.get("type") == "competitor"]
        sov_brands = [c for v in sections_by_rq.values() for s in v
                      if s.module == "brand_sov" and s.chart for c in s.chart["categories"]]
        logo_map = visuals.logos(list(dict.fromkeys(competitors + sov_brands))[:MAX_LOGOS], out_dir / "logos")
        if kit.logo:
            logo_map[brand] = kit.logo
        icons = {k: p for k, p in ((k, visuals.icon_png(v, out_dir / "icons", kit.accent))
                                   for k, v in visuals.ICONS.items()) if p}
        country = (spec.get("included_scope") or {}).get("geography") or spec.get("geography") or ""
        hero, credit = visuals.hero_image(f"{brand} {(spec.get('industry') or {}).get('name', '')}".strip(), out_dir)
        dates = sorted(r.article.date for r in rows if r.article.date)
        period = f"{dates[0]:%b %Y} – {dates[-1]:%b %Y}" if dates else str(spec.get("time_period") or "")
        methodology = _methodology(summary, rqs)
        palette = kit.palette if kit.colors else visuals.palette_from_logo(kit.logo)
        inp = generic_deck.DeckInput(
            title=brand, subtitle=project.get("project_name") or "Media Analysis", date_label=f"{date.today():%B %Y}",
            period_label=period, rqs=rqs, overview=overview, sections_by_rq=sections_by_rq,
            insights_by_rq=insights_by_rq, answers=answers, takeaways=takeaways, methodology=methodology,
            citations=registry.entries(), base_n=base, palette=palette, accent=kit.accent,
            title_font=kit.title_font, logos=logo_map, icons=icons, hero=hero, hero_credit=credit,
            brand_image=kit.banner, flag=visuals.country_flag_png(country, out_dir / "icons"))
        safe = "".join(ch for ch in brand if ch.isalnum() or ch in " -_").strip() or "Deliverable"
        pptx_path, appendix = generic_deck.build_generic_deck(inp, template, out_dir / "work",
                                                              out_dir / f"{safe} - Deliverable.pptx")
        run.stage("render", "done", pptx_path.name)

        current = "qc"
        run.stage("qc", "running")
        facts = overview.facts + [f for v in sections_by_rq.values() for s in v for f in s.facts] + methodology
        report = factcheck.run_qc(pptx_path, facts, set(appendix), out_dir / "thumbs")
        rq_pngs = [Path(p) for p in report["pngs"]][3:3 + len(rqs)]
        docx_path = word_brief.build_word_brief(inp, out_dir / f"{safe} - Brief.docx", rq_pngs)
        run.section({"id": "qc", "rq_id": None, "module": "qc", "title": "Quality check", "report": report})
        run.stage("qc", "done", "ready" if report["ready"]
                  else f"{len(report['facts'])} fact / {len(report['layout'])} layout issues")

        store.update_deliverable_run(run_id, status="completed", pptx_path=str(pptx_path), docx_path=str(docx_path),
                                     thumbs_dir=str(out_dir / "thumbs"), finished_at=time.time())
        broadcast({"type": "deliverable_completed", "project_id": project_id, "run_id": run_id, "ready": report["ready"]})
    except Exception as e:
        stage = e.stage if isinstance(e, StageFailed) else current
        logger.error("[deliverable:%s] stage %s failed: %s", run_id, stage, e, exc_info=not isinstance(e, StageFailed))
        run.stages[stage] = "failed"
        store.update_deliverable_run(run_id, status="failed", stage=stage, stages_json=run.stages, error=str(e),
                                     finished_at=time.time())
        broadcast({"type": "deliverable_failed", "project_id": project_id, "run_id": run_id, "stage": stage,
                   "error": str(e)})


def run_payload(run_id: int) -> dict:
    return {"run": store.get_deliverable_run(run_id), "sections": store.list_deliverable_sections(run_id)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_engine.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/engine.py agent/tests/test_deliverable_engine.py
git commit -m "feat(deliverable): engine orchestrator with persisted, broadcast stages"
```

---

### Task 14: API

**Files:**
- Create: `agent/app/domains/deliverable/schemas.py`, `agent/app/domains/deliverable/router.py`
- Modify: `agent/app/domains/__init__.py` (import + include `deliverable`)
- Test: `agent/tests/test_deliverable_api.py`

**Interfaces:**
- Consumes: `engine.start_run`, `engine.run_payload`, `engine.RunBusy`, `core.auth.require_project_access`.
- Produces routes under `/api/intel`: `POST /deliverable/{project_id}/run` → `{"run_id"}` (409 on busy);
  `GET /deliverable/{project_id}/latest` → `{"run", "sections"}`; `GET /deliverable/{project_id}/runs/{run_id}`
  (404 if the run belongs to another project); `GET .../runs/{run_id}/download/{kind}` (`pptx` | `docx`);
  `GET .../runs/{run_id}/thumbnail/{n}` → PNG.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_deliverable_api.py
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient

from agent.app.core import store
from agent.app.core.auth import get_current_user, require_project_access
from agent.app.domains.deliverable import engine
from agent.app.main import app

ADMIN = {"id": 1, "role": "super_admin", "org_id": None}


def _client():
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[require_project_access] = lambda: ADMIN
    return TestClient(app)


def teardown_function(_):
    app.dependency_overrides.clear()


def test_run_busy_latest_and_download(tmp_path, monkeypatch):
    store.init_intelligence_db()
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Api {tmp_path.name}"}})
    pptx = tmp_path / "d.pptx"
    pptx.write_bytes(b"PK")

    def fake_start(project_id, llm=None, threaded=True):
        rid = store.create_deliverable_run(project_id)
        store.update_deliverable_run(rid, status="completed", pptx_path=str(pptx))
        return rid
    monkeypatch.setattr(engine, "start_run", fake_start)
    c = _client()
    rid = c.post(f"/api/intel/deliverable/{pid}/run").json()["run_id"]
    latest = c.get(f"/api/intel/deliverable/{pid}/latest").json()
    assert latest["run"]["id"] == rid and latest["sections"] == []
    assert c.get(f"/api/intel/deliverable/{pid}/runs/{rid}/download/pptx").status_code == 200
    assert c.get(f"/api/intel/deliverable/{pid + 999}/runs/{rid}").status_code == 404

    def busy(*a, **k):
        raise engine.RunBusy("A deliverable run is already in progress")
    monkeypatch.setattr(engine, "start_run", busy)
    r = c.post(f"/api/intel/deliverable/{pid}/run")
    assert r.status_code == 409 and "already in progress" in r.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_deliverable_api.py -q`
Expected: FAIL — 404 for `/api/intel/deliverable/...`.

- [ ] **Step 3: Implement**

```python
# agent/app/domains/deliverable/schemas.py
from __future__ import annotations

from pydantic import BaseModel


class DeliverableRunStarted(BaseModel):
    run_id: int


class DeliverableRunPayload(BaseModel):
    run: dict | None = None
    sections: list[dict] = []
```

```python
# agent/app/domains/deliverable/router.py
"""Deliverable engine API: start a run, read the latest/any run with its streamed sections, download outputs."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam
from fastapi.responses import FileResponse

from ...core import store
from ...core.auth import require_project_access
from . import engine
from .schemas import DeliverableRunPayload, DeliverableRunStarted

router = APIRouter()
_MEDIA = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
ProjectId = Annotated[int, PathParam(ge=1)]
RunId = Annotated[int, PathParam(ge=1)]
Access = Annotated[dict, Depends(require_project_access)]


def _owned_run(project_id: int, run_id: int) -> dict:
    run = store.get_deliverable_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/deliverable/{project_id}/run", response_model=DeliverableRunStarted)
def start(project_id: ProjectId, _: Access):
    try:
        return {"run_id": engine.start_run(project_id)}
    except engine.RunBusy as e:
        raise HTTPException(409, str(e))


@router.get("/deliverable/{project_id}/latest", response_model=DeliverableRunPayload)
def latest(project_id: ProjectId, _: Access):
    run = store.get_latest_deliverable_run(project_id)
    return engine.run_payload(run["id"]) if run else {"run": None, "sections": []}


@router.get("/deliverable/{project_id}/runs/{run_id}", response_model=DeliverableRunPayload)
def get_run(project_id: ProjectId, run_id: RunId, _: Access):
    _owned_run(project_id, run_id)
    return engine.run_payload(run_id)


@router.get("/deliverable/{project_id}/runs/{run_id}/download/{kind}", response_class=FileResponse)
def download(project_id: ProjectId, run_id: RunId, kind: str, _: Access):
    run = _owned_run(project_id, run_id)
    path = run.get(f"{kind}_path") if kind in _MEDIA else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "File not available")
    return FileResponse(path, media_type=_MEDIA[kind], filename=Path(path).name)


@router.get("/deliverable/{project_id}/runs/{run_id}/thumbnail/{n}", response_class=FileResponse)
def thumbnail(project_id: ProjectId, run_id: RunId, n: Annotated[int, PathParam(ge=1)], _: Access):
    run = _owned_run(project_id, run_id)
    folder = Path(run.get("thumbs_dir") or "")
    pngs = sorted(folder.glob("*.png")) if folder.exists() else []
    if n > len(pngs):
        raise HTTPException(404, "Thumbnail not available")
    return FileResponse(pngs[n - 1], media_type="image/png")
```

`agent/app/domains/__init__.py`: add `from .deliverable.router import router as deliverable` with the other
imports and `deliverable,` after `datasources,` in the include tuple.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_deliverable_api.py -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deliverable/schemas.py agent/app/domains/deliverable/router.py agent/app/domains/__init__.py agent/tests/test_deliverable_api.py
git commit -m "feat(deliverable): API to start runs, read streamed sections and download outputs"
```

---

### Task 15: Evidence keeps its source (URL, document id, file, row)

**Files:**
- Modify: `agent/app/domains/execution/repository.py` (`save_evidence`)
- Modify: `agent/app/domains/execution/service.py` (both `store.save_evidence(...)` calls, `_enriched_to_record`)
- Modify: `agent/app/methods/executors.py` (evidence built from a representative record)
- Test: `agent/tests/test_evidence_source.py`

**Interfaces:**
- Produces: `store.save_evidence(..., url=None, document_id=None, source_file=None, row_index=None)`; method
  evidence dicts carry `"url": rep.get("url")` wherever they use a representative record `rep`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_evidence_source.py
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.core import store
from agent.app.methods.registry import get_executor


def test_method_evidence_carries_the_article_url():
    recs = [{"headline": f"Baby lotion deal {i}", "content": "sale discount lotion", "url": f"https://x.com/{i}",
             "sentiment": "positive", "source": "O"} for i in range(4)]
    ev = [e for e in get_executor("Sentiment Analysis").execute(recs, {}) if e["evidence_type"] == "sentiment_distribution"]
    assert ev and all(str(e.get("url", "")).startswith("https://x.com/") for e in ev)


def test_save_evidence_stores_source_fields(tmp_path):
    store.init_intelligence_db()
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Ev {tmp_path.name}"}})
    run = store.create_execution_run(pid, 1, 1)
    eid = store.save_evidence(run_id=run, unit_id="RO1", objective_id="RO1", evidence_type="theme", method="m",
                              text_excerpt="t", url="https://x.com/1", document_id="D1", source_file="f.csv", row_index=3)
    rec = store.get_evidence_record(eid)
    assert (rec["url"], rec["document_id"], rec["source_file"], rec["row_index"]) == ("https://x.com/1", "D1", "f.csv", 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_evidence_source.py -q`
Expected: FAIL — `TypeError: save_evidence() got an unexpected keyword argument 'url'`, and no `url` key on evidence.

- [ ] **Step 3: Implement**

- `execution/repository.py` `save_evidence`: add keyword parameters `url: str | None = None,
  document_id: str | None = None, source_file: str | None = None, row_index: int | None = None`, and add the four
  columns to its INSERT column list and values tuple (read the current INSERT and extend it in the same order).
- `execution/service.py`: in both `store.save_evidence(...)` calls pass `url=ev.get("url"),
  document_id=ev.get("document_id"), source_file=ev.get("source_file"), row_index=ev.get("row_index")`; in
  `_enriched_to_record` add `"document_id": rec.get("id")` and `"source_file": rec.get("dataset_file_name")`;
  in `_select_fields` keep `"document_id"` and `"source_file"` with `url`, `headline`, `_copies`.
- `methods/executors.py`: in every evidence dict built from a representative record `rep` (theme, conversation
  volume, high-engagement, sentiment, share of voice, audience segment, crisis mention, competitive benchmark,
  media framing) add `"url": rep.get("url"),` next to `"date":`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_evidence_source.py agent/tests/test_executor_service.py agent/tests/test_coverage_share.py agent/tests/test_execution_rq_routing.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/execution agent/app/methods/executors.py agent/tests/test_evidence_source.py
git commit -m "feat(evidence): keep article URL, document id, source file and row on evidence"
```

---

### Task 16: amCharts `ChartRenderer`

**Files:**
- Modify: `web/package.json` (dependency), `web/package-lock.json`
- Create: `web/src/components/deliverable/ChartRenderer.tsx`

**Interfaces:**
- Produces: `export interface ChartSpec { kind: "kpi" | "line_peaks" | "bar" | "column" | "doughnut" | "gauge" |
  "treemap"; categories: string[]; values: number[]; peaks?: number[]; unit?: "count" | "percent";
  series_label?: string }`, `export function ChartRenderer({ spec, height, palette }: { spec: ChartSpec;
  height?: number; palette?: string[] })` (palette = hex without `#`, defaults to the house tints).

- [ ] **Step 1: Install the pinned dependency**

Run: `cd web && npm install --save-exact @amcharts/amcharts5@5.20.8`
Expected: `package.json` lists `"@amcharts/amcharts5": "5.20.8"`.

- [ ] **Step 2: Write the component**

```tsx
// web/src/components/deliverable/ChartRenderer.tsx
import { useLayoutEffect, useRef } from "react";
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import * as am5percent from "@amcharts/amcharts5/percent";
import * as am5radar from "@amcharts/amcharts5/radar";
import * as am5hierarchy from "@amcharts/amcharts5/hierarchy";

export interface ChartSpec {
  kind: "kpi" | "line_peaks" | "bar" | "column" | "doughnut" | "gauge" | "treemap";
  categories: string[];
  values: number[];
  peaks?: number[];
  unit?: "count" | "percent";
  series_label?: string;
}

const VIOLET = "#5B2C9D";
const HOUSE = ["D9C8F0", "FDE3D2", "D4E6F7", "D3F0E3"];
const fmt = (v: number, unit?: string) => (unit === "percent" ? `${v}%` : v.toLocaleString());

type Datum = { category: string; value: number; peak: boolean };

function buildXY(root: am5.Root, spec: ChartSpec, fill: string) {
  const horizontal = spec.kind === "bar";
  const chart = root.container.children.push(am5xy.XYChart.new(root, { paddingLeft: 0 }));
  const data: Datum[] = spec.categories.map((c, i) => ({ category: c, value: spec.values[i] ?? 0, peak: (spec.peaks ?? []).includes(i) }));
  if (horizontal) {
    const yAxis = chart.yAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: am5xy.AxisRendererY.new(root, { inversed: true, minGridDistance: 12 }) }));
    const xAxis = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererX.new(root, {}) }));
    yAxis.data.setAll(data);
    const series = chart.series.push(am5xy.ColumnSeries.new(root, { xAxis, yAxis, valueXField: "value", categoryYField: "category" }));
    series.columns.template.setAll({ fill: am5.color(`#${fill}`), strokeOpacity: 0, cornerRadiusTR: 4, cornerRadiusBR: 4 });
    series.bullets.push(() => am5.Bullet.new(root, { locationX: 1, sprite: am5.Label.new(root, {
      text: spec.unit === "percent" ? "{valueX}%" : "{valueX}", populateText: true, fontSize: 11, dx: 6, centerY: am5.p50, fill: am5.color("#404040") }) }));
    series.data.setAll(data);
    return;
  }
  const xAxis = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 30 }) }));
  const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));
  xAxis.data.setAll(data);
  if (spec.kind === "line_peaks") {
    const series = chart.series.push(am5xy.LineSeries.new(root, { xAxis, yAxis, valueYField: "value", categoryXField: "category", stroke: am5.color("#8FB8E0") }));
    series.strokes.template.setAll({ strokeWidth: 2 });
    series.bullets.push((_r, _s, dataItem) => {
      const ctx = dataItem.dataContext as Datum;
      if (!ctx.peak) return undefined;
      const box = am5.Container.new(root, {});
      box.children.push(am5.Circle.new(root, { radius: 6, fill: am5.color(VIOLET) }));
      box.children.push(am5.Label.new(root, { text: String(ctx.value), centerX: am5.p50, centerY: am5.p100, dy: -8, fill: am5.color(VIOLET), fontWeight: "600", fontSize: 12 }));
      return am5.Bullet.new(root, { sprite: box });
    });
    series.data.setAll(data);
  } else {
    const series = chart.series.push(am5xy.ColumnSeries.new(root, { xAxis, yAxis, valueYField: "value", categoryXField: "category" }));
    series.columns.template.setAll({ fill: am5.color(`#${fill}`), strokeOpacity: 0, cornerRadiusTL: 4, cornerRadiusTR: 4 });
    series.bullets.push(() => am5.Bullet.new(root, { locationY: 1, sprite: am5.Label.new(root, {
      text: spec.unit === "percent" ? "{valueY}%" : "{valueY}", populateText: true, fontSize: 11, centerX: am5.p50, dy: -14, fill: am5.color("#404040") }) }));
    series.data.setAll(data);
  }
}

export function ChartRenderer({ spec, height = 280, palette = HOUSE }: { spec: ChartSpec; height?: number; palette?: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!ref.current || spec.kind === "kpi") return;
    const root = am5.Root.new(ref.current);
    const colors = palette.map((c) => am5.color(`#${c}`));
    if (spec.kind === "doughnut") {
      const chart = root.container.children.push(am5percent.PieChart.new(root, { innerRadius: am5.percent(55) }));
      const series = chart.series.push(am5percent.PieSeries.new(root, { valueField: "value", categoryField: "category" }));
      series.get("colors")?.set("colors", colors);
      series.labels.template.setAll({ text: "{category}: {value}%", fontSize: 11 });
      series.data.setAll(spec.categories.map((c, i) => ({ category: c, value: spec.values[i] })));
    } else if (spec.kind === "gauge") {
      const chart = root.container.children.push(am5radar.RadarChart.new(root, { startAngle: 180, endAngle: 360, innerRadius: -20 }));
      const axis = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, max: 100, strictMinMax: true, renderer: am5radar.AxisRendererCircular.new(root, {}) }));
      const range = axis.createAxisRange(axis.makeDataItem({ value: 0, endValue: spec.values[0] }));
      range.get("axisFill")?.setAll({ visible: true, fill: am5.color(VIOLET), fillOpacity: 0.85 });
      chart.radarContainer.children.push(am5.Label.new(root, { text: `${spec.values[0]}%`, centerX: am5.p50, centerY: am5.p100, fontSize: 28, fontWeight: "700", fill: am5.color(VIOLET) }));
    } else if (spec.kind === "treemap") {
      const series = root.container.children.push(am5hierarchy.Treemap.new(root, { valueField: "value", categoryField: "name", childDataField: "children", initialDepth: 1, downDepth: 1 }));
      series.set("colors", am5.ColorSet.new(root, { colors }));
      series.labels.template.setAll({ text: "{category}\n{sum}", fontSize: 12, fill: am5.color("#404040") });
      series.data.setAll([{ name: "root", children: spec.categories.map((c, i) => ({ name: c, value: spec.values[i] })) }]);
      series.set("selectedDataItem", series.dataItems[0]);
    } else {
      buildXY(root, spec, palette[0]);
    }
    return () => root.dispose();
  }, [spec, palette]);

  if (spec.kind === "kpi") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-violet-100 bg-violet-50/40 py-6">
        <span className="text-4xl font-bold" style={{ color: VIOLET }}>{fmt(spec.values[0], spec.unit)}</span>
        <span className="mt-1 text-xs font-medium text-slate-600">{spec.categories[0]}</span>
      </div>
    );
  }
  return <div ref={ref} style={{ width: "100%", height }} role="img" aria-label={spec.series_label || spec.kind} />;
}
```

- [ ] **Step 3: Type-check**

Run: `cd web && npx tsc --noEmit`
Expected: no errors. (If an amCharts generic narrows differently, cast through `unknown` exactly where the
compiler points; behaviour unchanged.)

- [ ] **Step 4: Commit**

```bash
git add web/package.json web/package-lock.json web/src/components/deliverable/ChartRenderer.tsx
git commit -m "feat(web): amCharts ChartRenderer driven by persisted chart specs"
```

---

### Task 17: Streaming Deliverables page

**Files:**
- Modify: `web/src/services/intel-api.ts` (deliverable API + types)
- Create: `web/src/components/deliverable/RunTimeline.tsx`
- Modify: `web/src/pages/DeliverablesPage.tsx` (replace the composer flow with the engine run)

**Interfaces:**
- Consumes: `/api/intel/deliverable/*`, `agentSocket.onMessage` (`web/src/services/ws.ts`), `ChartRenderer`.
- Produces: `intelApi.deliverableRun(projectId) → {run_id}`, `intelApi.deliverableLatest(projectId) →
  DeliverablePayload`, `intelApi.deliverableDownloadUrl(projectId, runId, kind)`,
  `intelApi.deliverableThumbUrl(projectId, runId, n)`; types `DeliverableRun`, `DeliverableSection`,
  `DeliverablePayload`.

- [ ] **Step 1: API client** — add to the `intelApi` object (use the same `get`/`post` helpers and the same
  base-URL expression `rendererDownloadUrl` uses; it is written `BASE` below — replace with that file's name):

```ts
  deliverableRun: (projectId: number) => post<{ run_id: number }>(`/deliverable/${projectId}/run`, {}),
  deliverableLatest: (projectId: number) => get<DeliverablePayload>(`/deliverable/${projectId}/latest`),
  deliverableDownloadUrl: (projectId: number, runId: number, kind: "pptx" | "docx") =>
    `${BASE}/deliverable/${projectId}/runs/${runId}/download/${kind}`,
  deliverableThumbUrl: (projectId: number, runId: number, n: number) =>
    `${BASE}/deliverable/${projectId}/runs/${runId}/thumbnail/${n}`,
```

  and these exported types:

```ts
export interface DeliverableRun {
  id: number; project_id: number; status: "running" | "completed" | "failed"; stage: string | null;
  stages: Record<string, "running" | "done" | "failed">; pptx_path: string | null; docx_path: string | null;
  error: string | null;
}
export interface DeliverableSection {
  id: string; rq_id: string | null; module: string; title: string;
  chart?: import("../components/deliverable/ChartRenderer").ChartSpec | null;
  table?: { header: string[]; rows: string[][] } | null;
  facts?: string[]; notes?: string[]; skipped?: string | null;
  insights?: { headline: string; text: string; citations: number[] }[];
  answers?: { rq_id: string; question: string; value: string; answer: string }[];
  takeaways?: { headline: string; text: string; citations: number[] }[];
  data?: { files: number; unique_urls: number; stories: number; base_n: number; by_rq: Record<string, number> };
  report?: { ready: boolean; facts: unknown[]; layout: unknown[]; pngs: string[]; fixed: number };
}
export interface DeliverablePayload { run: DeliverableRun | null; sections: DeliverableSection[] }
```

- [ ] **Step 2: Timeline component**

```tsx
// web/src/components/deliverable/RunTimeline.tsx
const STAGES = ["gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc"] as const;
const LABELS: Record<string, string> = { gate: "Gate", ingest: "Ingest", routing: "Routing", plan: "Plan",
  classify: "Classify", compute: "Compute", insights: "Insights", template: "Template", render: "Render", qc: "QC" };

export function RunTimeline({ stages, details }: { stages: Record<string, string>; details: Record<string, string> }) {
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Deliverable stages">
      {STAGES.map((s) => {
        const st = stages[s];
        const cls = st === "done" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : st === "running" ? "bg-violet-50 text-violet-700 border-violet-200 animate-pulse"
          : st === "failed" ? "bg-red-50 text-red-700 border-red-200" : "bg-white text-slate-400 border-slate-200";
        return (
          <li key={s} className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${cls}`} title={details[s] || ""}>
            {LABELS[s]}{details[s] ? <span className="ml-1 font-normal opacity-80">· {details[s]}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 3: Rewrite `DeliverablesPage.tsx`** — keep the page shell, header, `useActiveProjectId`,
  `onNavigate` and the "Back to Analysis" button; remove the composer/renderer state, `handleGenerate`,
  `pollStatus`, `handleRevalidate`, the composer restore effect and their imports. Component core:

```tsx
const [payload, setPayload] = useState<DeliverablePayload>({ run: null, sections: [] });
const [details, setDetails] = useState<Record<string, string>>({});
const [startError, setStartError] = useState<string | null>(null);

useEffect(() => {
  agentSocket.connect();
  intelApi.deliverableLatest(projectId).then(setPayload).catch(() => undefined);
  const off = agentSocket.onMessage((msg) => {
    if (msg.project_id !== projectId) return;
    if (msg.type === "deliverable_stage") {
      setPayload((p) => (p.run && p.run.id === msg.run_id
        ? { ...p, run: { ...p.run, stage: msg.stage, stages: { ...p.run.stages, [msg.stage]: msg.status } } } : p));
      if (msg.detail) setDetails((d) => ({ ...d, [msg.stage]: msg.detail }));
    } else if (msg.type === "deliverable_section") {
      setPayload((p) => (p.run && p.run.id === msg.run_id
        ? { ...p, sections: [...p.sections.filter((s) => s.id !== msg.section.id), msg.section] } : p));
    } else if (msg.type === "deliverable_completed" || msg.type === "deliverable_failed") {
      intelApi.deliverableLatest(projectId).then(setPayload).catch(() => undefined);
    }
  });
  return () => { off(); };
}, [projectId]);

const generate = async () => {
  setStartError(null);
  setDetails({});
  try {
    const { run_id } = await intelApi.deliverableRun(projectId);
    setPayload({ run: { id: run_id, project_id: projectId, status: "running", stage: "gate", stages: {},
      pptx_path: null, docx_path: null, error: null }, sections: [] });
  } catch (e) {
    setStartError(e instanceof Error ? e.message : "Could not start the deliverable run");
  }
};

const run = payload.run;
const byId = (id: string) => payload.sections.find((s) => s.id === id);
const rqIds = [...new Set(payload.sections.map((s) => s.rq_id).filter(Boolean))] as string[];
const qc = byId("qc")?.report;
const collection = byId("data-collection")?.data;
const summary = byId("executive-summary");
const overview = byId("overview");
const citeChip = (n: number) => (
  <span key={n} className="ml-0.5 rounded bg-violet-50 px-1 text-[10px] font-medium text-violet-700">{n}</span>
);
```

  JSX, in order (Tailwind cards on a white page, matching the other pages):
  1. Header row: title "Deliverables", subtitle, and a button `Generate Deliverable` (label `Regenerate` when
     `run` exists), `disabled={run?.status === "running"}`, `onClick={generate}`.
  2. Red banner for `startError` or `run?.status === "failed" && run.error`.
  3. `<RunTimeline stages={run?.stages ?? {}} details={details} />` when `run`.
  4. Data collection card when `collection`: Files, Unique URLs, Stories, Base N tiles + per-RQ counts.
  5. Executive answers when `summary?.answers`: a 2–4 column grid of KPI cards (`value`, `rq_id`, `answer`).
  6. Overview chart: `<ChartRenderer spec={overview.chart} />` when `overview?.chart`.
  7. For each `rqId`: a section card titled with the RQ id; for every section with that `rq_id` and a `chart`,
     a sub-card with `section.title` and `<ChartRenderer spec={section.chart} height={260} />`; sections with
     `skipped` render one grey line `"{title}: {skipped}"`; sections with `table` render an HTML table
     (header row violet-tinted, 12 rows max); `notes` render as small grey text; the `"{rq}-insights"` section
     renders insight cards (`headline` bold, `text`, then `citations.map(citeChip)`).
  8. Takeaways (`summary?.takeaways`) as cards with citation chips.
  9. QC card when `qc`: "Ready" (emerald) or "{qc.facts.length} fact issues · {qc.layout.length} layout issues"
     (amber), plus "{qc.fixed} auto-fixed".
  10. Thumbnails grid when `qc?.pngs.length`: `<img loading="lazy" src={intelApi.deliverableThumbUrl(projectId, run.id, i + 1)} />`.
  11. When `run?.status === "completed"`: two links `Download .pptx` / `Download .docx` with
      `href={intelApi.deliverableDownloadUrl(projectId, run.id, "pptx" | "docx")}`.

- [ ] **Step 4: Type-check and build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: no type errors; build outputs to `agent/static`.

- [ ] **Step 5: Commit**

```bash
git add web/src/services/intel-api.ts web/src/components/deliverable/RunTimeline.tsx web/src/pages/DeliverablesPage.tsx
git commit -m "feat(web): streaming Deliverables page with stage timeline, charts, cited insights and downloads"
```

---

### Task 18: Navigation — Data Sources goes straight to the deliverable

**Files:**
- Modify: `web/src/pages/DataSources.tsx`

**Interfaces:**
- Consumes: `onNavigate("deliverables")` (the page key the Deliverables route already uses — confirm in `App.tsx`).

- [ ] **Step 1: Change the proceed target** — in the proceed confirm dialog change the heading "Proceed to Research
  Execution?" to "Generate the deliverable?" and the confirm button's `onNavigate("research-execution")` to
  `onNavigate("deliverables")`; rename the footer button "Research Execution" to "Generate Deliverable". Keep the
  article-review gate unchanged.

- [ ] **Step 2: Type-check and build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/DataSources.tsx
git commit -m "feat(web): Data Sources proceeds straight to Generate Deliverable"
```

---

### Task 19: Acceptance — project 261 end to end

**Files:**
- Create: `agent/tests/acceptance_deliverable_261.py` (manual script; not collected — name lacks `test_`)

- [ ] **Step 1: Write the acceptance checker**

```python
# agent/tests/acceptance_deliverable_261.py
"""Checks the latest deliverable run of project 261 against spec §7. Run after generating from the UI:
python agent/tests/acceptance_deliverable_261.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from agent.app.core import store

run = store.get_latest_deliverable_run(261)
assert run and run["status"] == "completed", run
sections = store.list_deliverable_sections(run["id"])
prs = Presentation(run["pptx_path"])
charts = sum(1 for s in prs.slides for sh in s.shapes if getattr(sh, "has_chart", False) and sh.has_chart)
tables = sum(1 for s in prs.slides for sh in s.shapes if getattr(sh, "has_table", False) and sh.has_table)
pictures = sum(1 for s in prs.slides for sh in s.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
text = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
qc = next(s for s in sections if s["id"] == "qc")["report"]
answers = next(s for s in sections if s["id"] == "executive-summary")["answers"]
checks = {
    "all five RQs answered with a base": len(answers) == 5 and all(" of " in a["answer"] for a in answers if a["value"] != "n/a"),
    "per-RQ trend charts": sum(1 for s in sections if s["module"] == "volume_trend" and not s["skipped"]) >= 4,
    "expert affiliation gauge": any(s["module"] == "entities" and (s.get("chart") or {}).get("kind") == "gauge" for s in sections),
    "native charts >= 10": charts >= 10,
    "tables >= 5": tables >= 5,
    "pictures (logos/icons/images) >= 8": pictures >= 8,
    "citations in text": "[1]" in text,
    "citation appendix": "Citations (1/" in text,
    "fact check clean": not qc["facts"],
    "no dark backgrounds": not [i for i in qc["layout"] if i["kind"] == "dark_background"],
    "word brief exists": Path(run["docx_path"]).exists(),
}
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(checks.values()) else 1)
```

- [ ] **Step 2: Full suite, restart, run from the UI**

Run: `python -m pytest agent/tests/ -q --ignore=agent/tests/test_e2e_live_workflow.py`
Expected: all pass.
Restart the backend on 8002 (stop the listener on the port, clear `agent/app/**/__pycache__`, start uvicorn),
open `http://localhost:8002/261/deliverables` with Playwright, click "Generate Deliverable", wait for the QC
stage to turn green, screenshot to `.playwright-mcp/`.

- [ ] **Step 3: Run the acceptance checker**

Run: `python agent/tests/acceptance_deliverable_261.py`
Expected: every line `PASS`. For any `FAIL`, fix the owning task's code with a failing test first, rerun the suite,
regenerate, rerun the checker.

- [ ] **Step 4: Visual review** — read the QC PNGs (`thumbs_dir`): cover, executive summary, one per-RQ slide, the
  brand share-of-voice slide (logos), takeaways; confirm brand colours/fonts where a kit exists and light
  backgrounds everywhere; fix any overlap or unreadable label (test first), regenerate.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/acceptance_deliverable_261.py
git commit -m "test(deliverable): project 261 acceptance checker"
```

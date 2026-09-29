# Multi-Source Research Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Background Research's stale, plain-string, sequential query pipeline with a
Boolean-query, concurrent, 3-source (Tavily/SerpAPI/Google News RSS) fetch engine that persists
every normalized item per-project and feeds a map-reduce LLM summarizer into the existing Brief
format.

**Architecture:** A new `agent/app/domains/research/multi_source.py` module owns Boolean query
construction, the persisted item store, and map-reduce summarization. `news_search.py` gains
concurrency and real date-bound params. `web_research.py` and `research/service.py` call the new
module instead of their current logic — same job worker, same endpoints, no external contract
changes except one new preview endpoint.

**Tech Stack:** Python/FastAPI backend, SQLite, `requests`, `concurrent.futures.ThreadPoolExecutor`,
existing Azure OpenAI `HybridLLMClient`. React/TypeScript frontend (one dropdown change).

**Spec:** `docs/superpowers/specs/2026-09-29-multi-source-research-pipeline-design.md`

## Global Constraints

- Chat LLM is Azure-only via `core.llm_provider`/`core.anthropic_client.get_llm_client()` — no
  Anthropic/Ollama chat fallback (established earlier this session). Every new LLM call in this
  plan uses this same client.
- No new third-party Python packages — `requests`, `concurrent.futures`, `sqlite3` (via `core.db`)
  cover everything needed.
- Follow the existing "never raise, degrade to empty" house style for external API adapters
  (`brandfetch.py`/`pexels.py`/`news_search.py`).
- Async job pattern for anything long-running: `store.create_job` → return `job_id` immediately →
  `core.jobs.submit` worker → `core.events.broadcast({"type": "intel_job_update", ...})` per stage
  → `store.update_job(status="completed"/"failed", ...)`.
- DB migrations are forward-only, appended to `core/db.py`'s `MIGRATIONS` list — never edit or
  reorder existing entries. Next id is `8`.
- No Phyllo. 3 sources only (Tavily, SerpAPI, Google News RSS) per the approved spec's non-goals.

## Review Focus

- **Zero search results for a project** (new brand, obscure category, all 3 sources down) — the
  map-reduce summarizer and `compose_brief()` must still produce the existing rule-based sections
  rather than crashing or returning empty JSON. Covered in Task 9.
- **A batch's LLM call fails mid-map** (timeout, malformed JSON) — must not abort the whole brief;
  reduce step proceeds with whatever batches succeeded. Covered in Task 8.
- **Duplicate items across reruns** (same URL returned by two sources, or the same research job
  run twice) — `intel_research_items` must not accumulate duplicate rows. Covered in Task 1.
- **Unparseable or out-of-range dates** — today's code silently *keeps* these; the new stringent
  filter must *drop* them, and a test must pin this reversed behavior so it doesn't regress back
  to "keep anyway". Covered in Task 2.
- **A brief with a competitor/product/category the old dead-field bug never surfaced** (e.g. any
  project generated before this session's entity-extraction fixes, or a project with no
  competitors at all) — `build_boolean_queries()` must degrade gracefully (fewer topics, no crash)
  rather than assume every field is populated. Covered in Task 4.

---

### Task 1: `intel_research_items` table + repository functions

**Files:**
- Modify: `agent/app/core/db.py` (append migration id `8` to `MIGRATIONS`, ~line 1181 after the
  `pexels image cache` entry)
- Modify: `agent/app/domains/research/repository.py` (append new functions at end of file)
- Test: `agent/tests/test_research_items_repository.py` (new)

**Interfaces:**
- Produces: `repository.upsert_research_item(project_id: int, research_id: int | None, item: dict) -> int`
  (returns row id), `repository.get_research_items(project_id: int) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_research_items_repository.py
"""Tests for intel_research_items persistence: upsert-dedup, project scoping."""
from __future__ import annotations

import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.core import db as core_db
from agent.app.domains.research import repository


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(core_db, "DB_PATH", str(db_path))
    core_db.init_db()
    yield


def _sample_item(url="https://example.com/a", topic="brand_activity"):
    return {
        "topic": topic,
        "source_api": "tavily",
        "platform": None,
        "publication": "Example News",
        "published_date": 1790000000.0,
        "title": "Sample headline",
        "content": "Sample content",
        "url": url,
    }


def test_upsert_creates_row():
    row_id = repository.upsert_research_item(project_id=1, research_id=None, item=_sample_item())
    items = repository.get_research_items(project_id=1)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/a"
    assert row_id > 0


def test_upsert_same_url_does_not_duplicate():
    repository.upsert_research_item(project_id=1, research_id=None, item=_sample_item())
    repository.upsert_research_item(project_id=1, research_id=None, item=_sample_item(topic="events"))
    items = repository.get_research_items(project_id=1)
    assert len(items) == 1
    assert items[0]["topic"] == "events"  # second write updates the row


def test_items_scoped_by_project():
    repository.upsert_research_item(project_id=1, research_id=None, item=_sample_item("https://example.com/p1"))
    repository.upsert_research_item(project_id=2, research_id=None, item=_sample_item("https://example.com/p2"))
    assert len(repository.get_research_items(project_id=1)) == 1
    assert len(repository.get_research_items(project_id=2)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_research_items_repository.py -v`
Expected: FAIL — `AttributeError: module 'agent.app.domains.research.repository' has no attribute 'upsert_research_item'`

- [ ] **Step 3: Add the migration**

In `agent/app/core/db.py`, append to the `MIGRATIONS` list (after the `(7, "pexels image cache", ...)` entry):

```python
    # Per-item normalized research results (news/social posts from the multi-source
    # research pipeline), linked to project_id — see domains/research/multi_source.py.
    (8, "research items", ["""
        CREATE TABLE IF NOT EXISTS intel_research_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            research_id INTEGER,
            topic TEXT NOT NULL,
            source_api TEXT NOT NULL,
            platform TEXT,
            publication TEXT,
            published_date REAL NOT NULL,
            title TEXT,
            content TEXT,
            url TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(project_id, url),
            FOREIGN KEY (project_id) REFERENCES intel_projects(id),
            FOREIGN KEY (research_id) REFERENCES intel_background_research(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_research_items_project ON intel_research_items(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_research_items_project_date ON intel_research_items(project_id, published_date)",
    ]),
]
```

- [ ] **Step 4: Add the repository functions**

Append to `agent/app/domains/research/repository.py`:

```python
# ─── Research Items (multi-source pipeline) ──────────────────────────────────

def upsert_research_item(project_id: int, research_id: int | None, item: dict) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_research_items "
        "(project_id, research_id, topic, source_api, platform, publication, "
        "published_date, title, content, url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(project_id, url) DO UPDATE SET "
        "research_id = excluded.research_id, topic = excluded.topic, "
        "source_api = excluded.source_api, platform = excluded.platform, "
        "publication = excluded.publication, published_date = excluded.published_date, "
        "title = excluded.title, content = excluded.content",
        (
            project_id, research_id, item["topic"], item["source_api"], item.get("platform"),
            item.get("publication"), item["published_date"], item.get("title"),
            item.get("content"), item["url"], now,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM intel_research_items WHERE project_id = ? AND url = ?",
        (project_id, item["url"]),
    ).fetchone()
    conn.close()
    return row["id"]


def get_research_items(project_id: int, topic: str | None = None) -> list[dict]:
    conn = _conn()
    if topic:
        rows = conn.execute(
            "SELECT * FROM intel_research_items WHERE project_id = ? AND topic = ? "
            "ORDER BY published_date DESC",
            (project_id, topic),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_research_items WHERE project_id = ? ORDER BY published_date DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_research_items_repository.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add agent/app/core/db.py agent/app/domains/research/repository.py agent/tests/test_research_items_repository.py
git commit -m "feat: add intel_research_items table for per-item research persistence"
```

---

### Task 2: Concurrent fan-out + stringent date filtering in `news_search.py`

**Files:**
- Modify: `agent/app/domains/research/news_search.py`
- Test: `agent/tests/test_news_search.py` (new)

**Interfaces:**
- Consumes: nothing new
- Produces: `fetch_and_normalize(query: str, country: str = "US", date_range: tuple | None = None, max_results: int = 20, tavily_query: str | None = None) -> dict`
  — same return shape as today, `tavily_query` is a new optional parameter (defaults to `query`
  when omitted, so every existing caller is unaffected)

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_news_search.py
"""Tests for news_search's date-range strictness and per-source query rendering."""
from __future__ import annotations

from datetime import date, timedelta

from agent.app.domains.research.news_search import _within_range, _search_google_news_rss


def test_unparseable_date_is_dropped_not_kept():
    # Reversed from today's behavior: an unparseable date must fail the range check.
    assert _within_range("not a date", (date(2026, 1, 1), date(2026, 1, 31))) is False


def test_out_of_range_date_is_dropped():
    old_date = "Mon, 01 Jan 2024 10:00:00 GMT"
    assert _within_range(old_date, (date(2026, 1, 1), date(2026, 1, 31))) is False


def test_in_range_date_is_kept():
    in_range = "Wed, 15 Jan 2026 10:00:00 GMT"
    assert _within_range(in_range, (date(2026, 1, 1), date(2026, 1, 31))) is True


def test_rss_query_uses_when_days_not_hours_when_days_given(monkeypatch):
    captured = {}

    class FakeResponse:
        content = b"<rss><channel></channel></rss>"
        def raise_for_status(self): pass

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("agent.app.domains.research.news_search.requests.get", fake_get)
    _search_google_news_rss('"Nike" AND "Adidas"', recency_hours=7 * 24, country="US")
    assert "when%3A168h" in captured["url"] or "when:168h" in captured["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_news_search.py -v`
Expected: FAIL on `test_unparseable_date_is_dropped_not_kept` and `test_out_of_range_date_is_dropped`
(current code returns `True`/keeps for both)

- [ ] **Step 3: Flip `_within_range` to drop unparseable/out-of-range items**

In `news_search.py`, replace the `_within_range` function body:

```python
def _within_range(date_str: str, date_range: tuple) -> bool:
    """Stringent filter: an unparseable date, or one outside the window, fails the check
    (dropped by the caller) — this is a deliberate reversal of the old soft/advisory
    behavior, which kept items it couldn't verify."""
    parsed = _parse_date(date_str)
    if parsed is None:
        logger.debug("Unparseable date %r — dropping item under stringent date filter", date_str)
        return False
    start = _coerce_datetime(date_range[0])
    end = _coerce_datetime(date_range[1])
    return start <= parsed <= end
```

- [ ] **Step 4: Add real date bounds for SerpAPI and Tavily, and a `tavily_query` param**

Replace `_search_serpapi`'s signature and query construction:

```python
def _search_serpapi(query: str, country: str, max_results: int, recency_days: int | None = None) -> list[dict]:
    """Raw SerpAPI Google News engine results. Returns [] on any failure (missing key,
    network error, rate limit, bad response) rather than raising. `recency_days`, when given,
    is embedded as a `when:Nd` prefix — the same Google search operator Google News RSS already
    uses (news_search.py's own `_search_google_news_rss`), since SerpAPI's google_news engine is
    the same underlying Google index and honors the same operator."""
    api_key = os.getenv("SERP_API_KEY", "")
    if not api_key:
        logger.debug("SERP_API_KEY not set — skipping SerpAPI search")
        return []

    q = f"when:{recency_days}d {query}" if recency_days else query
    params = {
        "engine": "google_news",
        "q": q,
        "gl": country.lower(),
        "hl": "en",
        "api_key": api_key,
    }
    try:
        r = requests.get(SERPAPI_URL, params=params, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            raise NewsSearchError(f"SerpAPI request failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        if data.get("error"):
            raise NewsSearchError(f"SerpAPI returned an error: {data['error']}")
    except Exception:
        logger.exception("SerpAPI search failed for query=%r", query)
        return []

    return list(data.get("news_results", []))[:max_results]
```

Replace `_search_tavily`'s payload construction:

```python
def _search_tavily(query: str, country: str, max_results: int, date_range: tuple | None = None) -> list[dict]:
    """Raw Tavily Search API (topic=news) results. Returns [] on any failure. `country` is
    accepted for signature symmetry but not sent (see original docstring note). `date_range`,
    when given, is sent as Tavily's own `start_date`/`end_date` params (confirmed supported
    for topic=news via Tavily's public API reference, 2026-09)."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        logger.debug("TAVILY_API_KEY not set — skipping Tavily search")
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "topic": "news",
        "max_results": max_results,
        "include_answer": False,
        "include_published_date": True,
    }
    if date_range is not None:
        payload["start_date"] = _coerce_datetime(date_range[0]).strftime("%Y-%m-%d")
        payload["end_date"] = _coerce_datetime(date_range[1]).strftime("%Y-%m-%d")
    try:
        r = requests.post(TAVILY_API_URL, json=payload, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            raise NewsSearchError(f"Tavily request failed: {r.status_code}")
        data = r.json()
    except Exception:
        logger.exception("Tavily search failed for query=%r", query)
        return []

    return list(data.get("results", []))[:max_results]
```

- [ ] **Step 5: Parallelize the 3 source calls and thread `tavily_query` through `fetch_and_normalize`**

Replace the top of `fetch_and_normalize`'s body (the three sequential calls) with:

```python
def fetch_and_normalize(
    query: str,
    country: str = "US",
    date_range: tuple | None = None,
    max_results: int = 20,
    tavily_query: str | None = None,
) -> dict:
    """Search SerpAPI + Tavily + Google News RSS concurrently, normalize into social/traditional
    media buckets, dedupe by URL. Never raises — a down source just contributes nothing.

    `tavily_query`, when given, is sent to Tavily instead of `query` (Tavily favors natural
    language over raw Boolean operators; `query` still goes to SerpAPI/RSS, which are both
    Google-search-flavored and handle Boolean syntax the same way). Defaults to `query` so
    existing single-query callers are unaffected.

    Returns {"social_media": [...], "traditional_media": [...], "degraded": bool,
    "failed_sources": [...]}. "degraded" is True only when BOTH SerpAPI and Tavily contributed
    zero results — RSS alone is never enough to avoid the flag.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    recency_days = None
    if date_range is not None:
        recency_days = max(1, (date.today() - _coerce_datetime(date_range[0]).date()).days)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_search_serpapi, query, country, max_results, recency_days): "serpapi",
            pool.submit(_search_tavily, tavily_query or query, country, max_results, date_range): "tavily",
            pool.submit(_search_google_news_rss, query,
                        recency_hours=_recency_hours_for_range(date_range), country=country): "google_news_rss",
        }
        results_by_source: dict[str, list[dict]] = {"serpapi": [], "tavily": [], "google_news_rss": []}
        for future in as_completed(futures, timeout=DEFAULT_TIMEOUT + 5):
            source = futures[future]
            try:
                results_by_source[source] = future.result()
            except Exception:
                logger.exception("%s fetch raised unexpectedly", source)
                results_by_source[source] = []

    serpapi_raw = results_by_source["serpapi"]
    tavily_raw = results_by_source["tavily"]
    rss_raw = results_by_source["google_news_rss"][:max_results]
```

The rest of the function (normalization loop, bucketing, `failed_sources`/`degraded` computation,
final return) is unchanged — it already references `serpapi_raw`/`tavily_raw`/`rss_raw` by those
exact names.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_news_search.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the existing web_research adapter tests to confirm no regression**

Run: `python -m pytest agent/tests/test_web_research_adapter.py -v`
Expected: PASS (this file doesn't call `fetch_and_normalize` directly, but confirms the module
still imports cleanly)

- [ ] **Step 8: Commit**

```bash
git add agent/app/domains/research/news_search.py agent/tests/test_news_search.py
git commit -m "fix: concurrent multi-source fetch with stringent date-range filtering"
```

---

### Task 3: 7-day date-range branch in `web_research.py`

**Files:**
- Modify: `agent/app/domains/research/web_research.py:730-747` (`_extract_date_range`)
- Test: `agent/tests/test_web_research_adapter.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `LiveWebResearchAdapter._extract_date_range(spec) -> tuple[date, date]` — same
  signature, two new matched phrases

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_web_research_adapter.py`:

```python
from datetime import date, timedelta
from agent.app.domains.research.web_research import LiveWebResearchAdapter


class TestDateRangeExtraction:
    def test_past_7_days_maps_to_7_day_window(self):
        adapter = LiveWebResearchAdapter()
        spec = {"included_scope": {"time_period": "Past 7 days"}}
        start, end = adapter._extract_date_range(spec)
        assert (end - start).days == 7

    def test_past_week_phrasing_also_maps_to_7_days(self):
        adapter = LiveWebResearchAdapter()
        spec = {"included_scope": {"time_period": "the past week"}}
        start, end = adapter._extract_date_range(spec)
        assert (end - start).days == 7

    def test_past_30_days_still_maps_to_30_days(self):
        adapter = LiveWebResearchAdapter()
        spec = {"included_scope": {"time_period": "Past 30 days"}}
        start, end = adapter._extract_date_range(spec)
        assert (end - start).days == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_web_research_adapter.py::TestDateRangeExtraction -v`
Expected: FAIL — "Past 7 days" and "Past 30 days" both currently fall through to the 365-day
default (no matching branch for either).

- [ ] **Step 3: Add the branches**

Replace `_extract_date_range` in `web_research.py`:

```python
    def _extract_date_range(self, spec: dict) -> tuple[date, date]:
        scope = spec.get("included_scope", {})
        time_period = ""
        if isinstance(scope, dict):
            time_period = scope.get("time_period", "")

        end = date.today()
        tp = time_period.lower()

        if "12 month" in tp or "past year" in tp:
            start = end - timedelta(days=365)
        elif "6 month" in tp:
            start = end - timedelta(days=182)
        elif "3 month" in tp:
            start = end - timedelta(days=91)
        elif "30 day" in tp or "past month" in tp:
            start = end - timedelta(days=30)
        elif "7 day" in tp or "past week" in tp or "1 week" in tp:
            start = end - timedelta(days=7)
        else:
            # Unmatched time_period strings previously fell through to a silent 365-day
            # default; 30 days is a safer, more representative default for an unrecognized
            # string (most specs specify something in the 7-365 day range, not a full year).
            start = end - timedelta(days=30)
        return start, end
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_web_research_adapter.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/research/web_research.py agent/tests/test_web_research_adapter.py
git commit -m "feat: add 7-day date range branch, fix silent 365-day fallback default"
```

---

### Task 4: `build_boolean_queries()` in new `multi_source.py`

**Files:**
- Create: `agent/app/domains/research/multi_source.py`
- Test: `agent/tests/test_multi_source.py` (new)

**Interfaces:**
- Consumes: a spec dict shaped like `intel_projects.spec_json` (same shape `web_research.py`'s
  `_extract_*` methods already read: `commissioning_brand.name`, `validated_entities` list with
  `type`/`name` keys, `industry.name`, `research_subject.description`, `excluded_scope`)
- Produces:
  ```python
  @dataclass
  class TopicQuery:
      topic: str
      boolean_query: str   # for SerpAPI + Google RSS
      natural_query: str   # for Tavily

  def build_boolean_queries(spec: dict) -> list[TopicQuery]: ...
  ```

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_multi_source.py
"""Tests for multi_source.py: Boolean query building from a Research Specification."""
from __future__ import annotations

import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.domains.research.multi_source import build_boolean_queries


NIKE_SPEC = {
    "commissioning_brand": {"name": "Nike"},
    "industry": {"name": "Athletic Footwear"},
    "research_subject": {"description": "Consumer sentiment around Pegasus launch"},
    "validated_entities": [
        {"name": "Nike", "type": "brand"},
        {"name": "Adidas", "type": "competitor"},
        {"name": "New Balance", "type": "competitor"},
        {"name": "ASICS", "type": "competitor"},
        {"name": "Brooks", "type": "competitor"},
        {"name": "Pegasus", "type": "product"},
        {"name": "Ultraboost", "type": "product"},
        {"name": "Boston Marathon", "type": "event"},
    ],
    "excluded_scope": [{"description": "Nike golf"}],
    "research_questions": [{"question": "What are the key themes and conversations?"}],
}


def test_every_topic_includes_brand_and_all_competitors():
    topics = build_boolean_queries(NIKE_SPEC)
    assert len(topics) > 0
    for t in topics:
        assert '"Nike"' in t.boolean_query
        for comp in ("Adidas", "New Balance", "ASICS", "Brooks"):
            assert f'"{comp}"' in t.boolean_query, f"{comp} missing from topic {t.topic}: {t.boolean_query}"


def test_product_topic_includes_products():
    topics = build_boolean_queries(NIKE_SPEC)
    product_topic = next(t for t in topics if t.topic == "product_mentions")
    assert '"Pegasus"' in product_topic.boolean_query
    assert '"Ultraboost"' in product_topic.boolean_query


def test_event_topic_uses_event_name():
    topics = build_boolean_queries(NIKE_SPEC)
    event_topics = [t for t in topics if t.topic.startswith("event_")]
    assert any('"Boston Marathon"' in t.boolean_query for t in event_topics)


def test_exclusions_appended_as_minus_terms():
    topics = build_boolean_queries(NIKE_SPEC)
    for t in topics:
        assert '-"Nike golf"' in t.boolean_query


def test_natural_query_has_no_boolean_operators():
    topics = build_boolean_queries(NIKE_SPEC)
    for t in topics:
        assert " AND " not in t.natural_query
        assert " OR " not in t.natural_query
        assert '"' not in t.natural_query


def test_no_competitors_degrades_gracefully():
    spec = {"commissioning_brand": {"name": "SoloBrand"}, "validated_entities": [
        {"name": "SoloBrand", "type": "brand"},
    ]}
    topics = build_boolean_queries(spec)
    assert len(topics) > 0
    for t in topics:
        assert '"SoloBrand"' in t.boolean_query
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_multi_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.app.domains.research.multi_source'`

- [ ] **Step 3: Implement `build_boolean_queries()`**

```python
# agent/app/domains/research/multi_source.py
"""Multi-source research pipeline: Boolean query building, concurrent fan-out to
Tavily/SerpAPI/Google News RSS, per-item persistence, and map-reduce LLM summarization.

Replaces web_research.py's build_search_queries() (plain-string, stale spec fields — see
docs/superpowers/specs/2026-09-29-multi-source-research-pipeline-design.md §1) and
research/service.py's single fixed-truncation LLM call.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TopicQuery:
    topic: str
    boolean_query: str   # SerpAPI + Google News RSS (Boolean/Google search syntax)
    natural_query: str    # Tavily (plain language, no operators)


def _entities_by_type(spec: dict, entity_type: str) -> list[str]:
    entities = spec.get("validated_entities", [])
    return [e["name"] for e in entities if isinstance(e, dict) and e.get("type") == entity_type and e.get("name")]


def _or_group(terms: list[str]) -> str:
    return "(" + " OR ".join(f'"{t}"' for t in terms) + ")"


def _exclusion_suffix(spec: dict) -> str:
    excluded = spec.get("excluded_scope", [])
    terms = []
    for item in excluded if isinstance(excluded, list) else []:
        if isinstance(item, dict) and item.get("description"):
            terms.append(item["description"])
        elif isinstance(item, str):
            terms.append(item)
    return "".join(f' -"{t}"' for t in terms)


def build_boolean_queries(spec: dict) -> list[TopicQuery]:
    """Build one TopicQuery per research angle from an approved Research Specification.
    Every topic includes the brand OR'd with every competitor (brand_or_competitors) — no
    topic is brand-only or competitor-only, so no query is blind to the competitive set."""
    brand_name = (spec.get("commissioning_brand") or {}).get("name", "")
    competitors = _entities_by_type(spec, "competitor")
    products = _entities_by_type(spec, "product") + _entities_by_type(spec, "product_group")
    events = _entities_by_type(spec, "event")

    category = (spec.get("industry") or {}).get("name", "")
    if not category:
        category = (spec.get("research_subject") or {}).get("description", "")[:60]

    brand_or_competitors_terms = ([brand_name] if brand_name else []) + competitors
    if not brand_or_competitors_terms:
        return []
    brand_group_bool = _or_group(brand_or_competitors_terms)
    brand_group_natural = ", ".join(brand_or_competitors_terms)
    exclusion = _exclusion_suffix(spec)

    topics: list[TopicQuery] = []

    topics.append(TopicQuery(
        topic="brand_activity",
        boolean_query=f"{brand_group_bool} AND (news OR announcement OR campaign){exclusion}",
        natural_query=f"{brand_group_natural} news and announcements",
    ))

    if category:
        topics.append(TopicQuery(
            topic="competitive_landscape",
            boolean_query=f'{brand_group_bool} AND "{category}"{exclusion}',
            natural_query=f"{brand_group_natural} {category} market",
        ))
        topics.append(TopicQuery(
            topic="category_trends",
            boolean_query=f'{brand_group_bool} AND "{category}" AND (trend OR market){exclusion}',
            natural_query=f"{category} market trends: {brand_group_natural}",
        ))

    if products:
        topics.append(TopicQuery(
            topic="product_mentions",
            boolean_query=f"{brand_group_bool} AND {_or_group(products)}{exclusion}",
            natural_query=f"{brand_group_natural} — {', '.join(products)}",
        ))

    for event in events:
        topics.append(TopicQuery(
            topic=f"event_{event.lower().replace(' ', '_')}",
            boolean_query=f'{brand_group_bool} AND "{event}"{exclusion}',
            natural_query=f"{brand_group_natural} — {event}",
        ))

    research_questions = spec.get("research_questions", [])
    for i, rq in enumerate(research_questions[:3]):
        question = rq.get("question", "") if isinstance(rq, dict) else str(rq)
        if not question:
            continue
        phrase = question[:80]
        topics.append(TopicQuery(
            topic=f"research_question_{i + 1}",
            boolean_query=f'{brand_group_bool} AND "{phrase}"{exclusion}',
            natural_query=f"{brand_group_natural} {phrase}",
        ))

    return topics
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_multi_source.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/research/multi_source.py agent/tests/test_multi_source.py
git commit -m "feat: add Boolean query builder with brand+competitor grouping"
```

---

### Task 5: `fetch_and_persist()` — concurrent per-topic fetch + DB persistence

**Files:**
- Modify: `agent/app/domains/research/multi_source.py` (append)
- Test: `agent/tests/test_multi_source.py` (append)

**Interfaces:**
- Consumes: `TopicQuery` (Task 4), `news_search.fetch_and_normalize()` (Task 2),
  `repository.upsert_research_item()` (Task 1)
- Produces:
  ```python
  def fetch_and_persist(
      project_id: int, topics: list[TopicQuery], date_range: tuple, geography: str,
      research_id: int | None = None, emit=None,
  ) -> dict:  # {"items_fetched": int, "items_persisted": int, "source_status": dict}
  ```

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_multi_source.py`:

```python
from unittest.mock import patch
from agent.app.domains.research.multi_source import fetch_and_persist, TopicQuery
from agent.app.domains.research import repository


def test_fetch_and_persist_writes_items_to_db(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()

    fake_bucket_result = {
        "social_media": [],
        "traditional_media": [{
            "publisher_name": "Example News", "published_url": "https://example.com/1",
            "title": "Nike launches Pegasus", "content": "...", "author": "",
            "published_date": "2026-09-25T00:00:00", "_source": "tavily",
        }],
        "degraded": False,
        "failed_sources": [],
    }
    with patch(
        "agent.app.domains.research.multi_source.news_search.fetch_and_normalize",
        return_value=fake_bucket_result,
    ):
        topics = [TopicQuery(topic="brand_activity", boolean_query='"Nike"', natural_query="Nike")]
        from datetime import date, timedelta
        result = fetch_and_persist(
            project_id=1, topics=topics,
            date_range=(date.today() - timedelta(days=7), date.today()),
            geography="US",
        )

    assert result["items_persisted"] == 1
    items = repository.get_research_items(project_id=1)
    assert len(items) == 1
    assert items[0]["topic"] == "brand_activity"
    assert items[0]["source_api"] in ("tavily", "traditional_media")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_multi_source.py::test_fetch_and_persist_writes_items_to_db -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_and_persist'`

- [ ] **Step 3: Implement `fetch_and_persist()`**

Append to `agent/app/domains/research/multi_source.py`:

```python
import logging
import time
from urllib.parse import urlparse

from . import news_search
from . import repository

logger = logging.getLogger(__name__)

_SOCIAL_PLATFORM_DOMAINS = {
    "twitter.com": "twitter", "x.com": "twitter", "instagram.com": "instagram",
    "facebook.com": "facebook", "reddit.com": "reddit", "linkedin.com": "linkedin",
}


def _platform_for_url(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return None
    for domain, platform in _SOCIAL_PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return None


def _to_normalized_items(bucket_result: dict, topic: str) -> list[dict]:
    items = []
    for bucket_name in ("social_media", "traditional_media"):
        for raw in bucket_result.get(bucket_name, []):
            url = raw.get("published_url", "")
            if not url:
                continue
            title = raw.get("title") or raw.get("content", "")[:80]
            date_str = raw.get("published_date") or raw.get("date_posted") or ""
            published_ts = _parse_to_timestamp(date_str)
            items.append({
                "topic": topic,
                "source_api": raw.get("_source", "unknown"),
                "platform": _platform_for_url(url),
                "publication": raw.get("publisher_name", ""),
                "published_date": published_ts,
                "title": title,
                "content": raw.get("content", ""),
                "url": url,
            })
    return items


def _parse_to_timestamp(date_str: str) -> float:
    from .news_search import _parse_date
    parsed = _parse_date(date_str)
    return parsed.timestamp() if parsed else time.time()


def fetch_and_persist(
    project_id: int,
    topics: list[TopicQuery],
    date_range: tuple,
    geography: str,
    research_id: int | None = None,
    emit=None,
) -> dict:
    """Fetch every topic query (each topic itself fans out to 3 sources concurrently inside
    fetch_and_normalize), normalize, and upsert into intel_research_items as results arrive —
    a worker crash mid-run still leaves partial results queryable."""
    def _emit(step: str, payload: dict) -> None:
        if emit:
            emit(step, payload)

    items_fetched = 0
    items_persisted = 0
    source_status: dict[str, str] = {"tavily": "ok", "serpapi": "ok", "google_rss": "ok"}

    for i, topic in enumerate(topics):
        _emit("fetching_topic", {"topic": topic.topic, "index": i + 1, "total": len(topics)})
        bucket_result = news_search.fetch_and_normalize(
            query=topic.boolean_query,
            country=geography,
            date_range=date_range,
            max_results=15,
            tavily_query=topic.natural_query,
        )
        for failed in bucket_result.get("failed_sources", []):
            key = "google_rss" if failed == "google_news_rss" else failed
            source_status[key] = "degraded"

        normalized = _to_normalized_items(bucket_result, topic.topic)
        items_fetched += len(normalized)
        for item in normalized:
            repository.upsert_research_item(project_id, research_id, item)
            items_persisted += 1

    _emit("fetch_complete", {"items_fetched": items_fetched, "items_persisted": items_persisted})
    return {
        "items_fetched": items_fetched,
        "items_persisted": items_persisted,
        "source_status": source_status,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_multi_source.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/research/multi_source.py agent/tests/test_multi_source.py
git commit -m "feat: add concurrent per-topic fetch with intel_research_items persistence"
```

---

### Task 6: Wire `web_research.py::run_full_research()` to the new engine

**Files:**
- Modify: `agent/app/domains/research/web_research.py:379-536` (`run_full_research`)
- Test: `agent/tests/test_web_research_adapter.py` (append)

**Interfaces:**
- Consumes: `multi_source.build_boolean_queries()`, `multi_source.fetch_and_persist()` (Tasks 4-5)
- Produces: `run_full_research()`'s external return shape is unchanged (still
  `{"status", "news_items", "background_context", "research_gaps", "metadata", ...}`) — callers
  (`research/router.py`) need no changes

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_web_research_adapter.py`:

```python
class TestRunFullResearchUsesMultiSource:
    def test_run_full_research_calls_build_boolean_queries(self, monkeypatch):
        import agent.app.domains.research.web_research as wr_module

        called = {}
        def fake_build(spec):
            called["build_called"] = True
            return []

        def fake_fetch(**kwargs):
            called["fetch_called"] = True
            return {"items_fetched": 0, "items_persisted": 0, "source_status": {}}

        monkeypatch.setattr(wr_module, "build_boolean_queries", fake_build)
        monkeypatch.setattr(wr_module, "fetch_and_persist", fake_fetch)

        adapter = wr_module.LiveWebResearchAdapter()
        spec = {"commissioning_brand": {"name": "Nike"}, "validated_entities": [
            {"name": "Nike", "type": "brand"},
        ]}
        adapter.run_full_research(spec, project_id=1)

        assert called.get("build_called")
        assert called.get("fetch_called")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_web_research_adapter.py::TestRunFullResearchUsesMultiSource -v`
Expected: FAIL — `run_full_research()` doesn't accept `project_id` yet, and doesn't call the new
functions (they're not imported into `web_research.py` yet)

- [ ] **Step 3: Update `run_full_research()`**

At the top of `web_research.py`, add the import:

```python
from . import multi_source
```

Replace the query-building and fetch-loop section of `run_full_research` (the block that builds
`queries = build_search_queries(...)` through the `for i, q in enumerate(queries):` loop and its
`_emit("research_filtering", ...)` call) with:

```python
    def run_full_research(self, spec: dict, *, project_id: int, research_id: int | None = None,
                           emit: EventFn | None = None) -> dict:
        _emit = emit or self._emit
        start = time.time()

        brand_name = self._extract_brand_name(spec)
        geography = self._extract_geography(spec)
        date_range = self._extract_date_range(spec)

        if not brand_name:
            return {
                "status": "failed",
                "error": "Could not identify brand name from specification",
                "web_search_executed": False,
            }

        topics = multi_source.build_boolean_queries(spec)
        _emit("research_started", {"brand": brand_name, "topics": [t.topic for t in topics]})
        _emit("research_queries_built", {"count": len(topics)})

        fetch_result = multi_source.fetch_and_persist(
            project_id=project_id, topics=topics, date_range=date_range,
            geography=geography, research_id=research_id, emit=_emit,
        )

        from . import repository as research_repository
        persisted_items = research_repository.get_research_items(project_id)

        # Reshape persisted DB rows into the legacy {title, snippet, url, source, date, _family,
        # _query} flat item shape the rest of this method (entity validation, dedup-adjacent
        # filtering, date-status tagging) already expects, so everything below this line is
        # unchanged.
        all_raw = [{
            "title": row["title"], "snippet": row["content"], "url": row["url"],
            "source": row["publication"], "date": row["published_date"],
            "_family": row["topic"], "_query": row["topic"],
        } for row in persisted_items]

        _emit("research_filtering", {"total_raw": len(all_raw)})
```

Leave the remainder of `run_full_research()` (blocked-domain filtering, dedup, entity validation,
date-status tagging, final return dict construction) exactly as it is today — it already operates
on an `all_raw`/`filtered`/`deduped` list of that same flat shape, so no further changes are
needed there. Note `date_range` here is already dropped-if-out-of-range at the DB layer (Task 2's
stringent `_within_range`), so the existing `_date_status: "out_of_range"` background-context
logic further down will simply see fewer items in that category than before — that's expected,
not a bug.

- [ ] **Step 4: Update the one caller of `run_full_research()` to pass `project_id`**

In `agent/app/domains/research/router.py`, find `adapter.run_full_research(spec, emit=on_event)`
(inside `start_background_research`'s worker) and change it to:

```python
            web_result = adapter.run_full_research(spec, project_id=project_id, emit=on_event)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_web_research_adapter.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/research/web_research.py agent/app/domains/research/router.py agent/tests/test_web_research_adapter.py
git commit -m "feat: wire run_full_research to the multi-source Boolean query engine"
```

---

### Task 7: Current date/time injection into LLM prompts

**Files:**
- Modify: `agent/app/agents/brief_scope.py:876-881` (`_build_user_prompt`)
- Test: `agent/tests/test_brief_scope.py` — check if this file exists first; if not, create it

**Interfaces:**
- Produces: `_build_user_prompt(brief_text: str, filename: str) -> str` — same signature, output
  now includes a real current-date line

- [ ] **Step 1: Write the failing test**

```python
# add to (or create) agent/tests/test_brief_scope.py
import os
import tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from datetime import datetime
from agent.app.agents.brief_scope import _build_user_prompt


def test_prompt_includes_real_current_date():
    prompt = _build_user_prompt("Some brief text", "brief.pdf")
    today_str = datetime.now().strftime("%Y-%m-%d")
    assert today_str in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_brief_scope.py -v`
Expected: FAIL — today's date string not present in the prompt

- [ ] **Step 3: Add the date line**

Replace `_build_user_prompt` in `brief_scope.py`:

```python
def _build_user_prompt(brief_text: str, filename: str) -> str:
    from datetime import datetime
    now = datetime.now()
    parts = [
        f"Today's date is {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}), "
        f"current time {now.strftime('%H:%M')}. Use this, not your own assumption, for any "
        "relative date/time reasoning ('past 30 days', 'this year', etc.).",
        "Analyze this client brief and return a Project Specification as JSON.\n",
    ]
    if filename:
        parts.append(f"Filename: {filename}\n")
    parts.append(f"--- BRIEF START ---\n{brief_text}\n--- BRIEF END ---")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agent/tests/test_brief_scope.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/app/agents/brief_scope.py agent/tests/test_brief_scope.py
git commit -m "fix: inject real current date/time into brief_scope prompt"
```

(The new map/reduce prompts written in Task 8 get the same treatment inline — no separate task
needed since they don't exist until that task.)

---

### Task 8: `summarize_map_reduce()` — batch map + combine reduce

**Files:**
- Modify: `agent/app/domains/research/multi_source.py` (append)
- Test: `agent/tests/test_multi_source.py` (append)

**Interfaces:**
- Consumes: `repository.get_research_items()` (Task 1), an LLM client with `.chat(messages, format_json=...) -> str` (`core.llm_provider.HybridLLMClient` shape)
- Produces:
  ```python
  def summarize_map_reduce(project_id: int, spec: dict, llm_client, emit=None) -> dict:
      # returns {"company_introduction": str, "executive_summary": str, "brand_developments": str,
      #          "brand_narrative": str, "competitor_developments": str, "industry_context": str,
      #          "methodology": str}
  ```
  (same 7 keys `research/service.py::_compose_with_llm()`'s `parsed` dict already produces —
  `key_issues`/`source_register` stay post-processed/deterministic in Task 9, unchanged)

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_multi_source.py`:

```python
from agent.app.domains.research.multi_source import summarize_map_reduce


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, format_json=False, on_token=None):
        return self._responses.pop(0)


def _seed_items(project_id, count, topic="brand_activity"):
    for i in range(count):
        repository.upsert_research_item(project_id, None, {
            "topic": topic, "source_api": "tavily", "platform": None,
            "publication": "Example", "published_date": time.time(),
            "title": f"Item {i}", "content": f"Content {i}", "url": f"https://example.com/{topic}/{i}",
        })


def test_map_reduce_produces_all_seven_sections(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()
    _seed_items(project_id=1, count=3)

    batch_summary = json.dumps({"topic": "brand_activity", "key_points": ["point 1"], "notable_sources": []})
    final_json = json.dumps({k: f"{k} content" for k in [
        "company_introduction", "executive_summary", "brand_developments",
        "brand_narrative", "competitor_developments", "industry_context", "methodology",
    ]})
    llm = _FakeLLM([batch_summary, final_json])

    result = summarize_map_reduce(project_id=1, spec={"commissioning_brand": {"name": "Nike"}}, llm_client=llm)

    for key in ["company_introduction", "executive_summary", "brand_developments",
                "brand_narrative", "competitor_developments", "industry_context", "methodology"]:
        assert key in result
        assert result[key] == f"{key} content"


def test_map_reduce_skips_failed_batch_without_aborting(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()
    _seed_items(project_id=2, count=3)

    class _FailThenSucceedLLM:
        def __init__(self):
            self.calls = 0
        def chat(self, messages, format_json=False, on_token=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated batch failure")
            final_json = json.dumps({k: "x" for k in [
                "company_introduction", "executive_summary", "brand_developments",
                "brand_narrative", "competitor_developments", "industry_context", "methodology",
            ]})
            return final_json

    result = summarize_map_reduce(project_id=2, spec={"commissioning_brand": {"name": "Nike"}}, llm_client=_FailThenSucceedLLM())
    assert result["company_introduction"] == "x"


def test_map_reduce_with_zero_items_returns_empty_dict(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()

    result = summarize_map_reduce(project_id=3, spec={"commissioning_brand": {"name": "Nike"}}, llm_client=_FakeLLM([]))
    assert result == {}
```

Add `import json` and `import time` at the top of `test_multi_source.py` if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_multi_source.py -k map_reduce -v`
Expected: FAIL — `ImportError: cannot import name 'summarize_map_reduce'`

- [ ] **Step 3: Implement `summarize_map_reduce()`**

Append to `agent/app/domains/research/multi_source.py`:

```python
import json as _json
from datetime import datetime

BATCH_SIZE = 18  # items per map-step LLM call; sized to stay comfortably under a typical
                 # prompt-token budget for ~18 title+300-char-content items

_REDUCE_KEYS = [
    "company_introduction", "executive_summary", "brand_developments",
    "brand_narrative", "competitor_developments", "industry_context", "methodology",
]


def _current_date_prefix() -> str:
    now = datetime.now()
    return (f"Today's date is {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}). "
            "Use this, not your own assumption, for any relative date reasoning.\n\n")


def _batch_items(items: list[dict], batch_size: int) -> list[list[dict]]:
    by_topic: dict[str, list[dict]] = {}
    for item in items:
        by_topic.setdefault(item["topic"], []).append(item)
    batches = []
    for topic_items in by_topic.values():
        for i in range(0, len(topic_items), batch_size):
            batches.append(topic_items[i:i + batch_size])
    return batches


def _map_batch(llm_client, batch: list[dict]) -> dict | None:
    topic = batch[0]["topic"]
    lines = []
    for item in batch:
        lines.append(f"- [{item.get('publication', '')}] {item.get('title', '')}")
        if item.get("content"):
            lines.append(f"  {item['content'][:300]}")

    prompt = (
        _current_date_prefix()
        + f'Summarize these {len(batch)} items about "{topic}" into 3-6 key points a '
        "competitive-intelligence analyst would care about. Return ONLY JSON: "
        '{"topic": "' + topic + '", "key_points": ["...", ...], "notable_sources": ["...", ...]}\n\n'
        + "\n".join(lines)
    )
    try:
        response = llm_client.chat(
            [{"role": "system", "content": "Return only valid JSON."},
             {"role": "user", "content": prompt}],
            format_json=True,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            import re
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        return _json.loads(cleaned)
    except Exception:
        logger.exception("Map-step batch summary failed for topic=%r — skipping this batch", topic)
        return None


def _reduce_batches(llm_client, batch_summaries: list[dict], brand_name: str) -> dict:
    summary_block = _json.dumps(batch_summaries, indent=2)
    prompt = (
        _current_date_prefix()
        + f"You are a senior competitive intelligence analyst writing a brief for {brand_name}. "
        "Below are topic-grouped summaries of research findings. Combine them into a full brief. "
        "Return ONLY JSON with these exact keys:\n"
        + ", ".join(_REDUCE_KEYS) + "\n\n"
        + "SECTION GUIDANCE:\n"
        "- company_introduction: 2-3 paragraph overview of the company.\n"
        "- executive_summary: 3-5 analytical paragraphs, then a "
        f'"## What this means for {brand_name}" sub-heading with 4-6 strategic bullets.\n'
        "- brand_developments: the brand's own most significant developments, \"## Date | Headline\" "
        "format, 2-4 sentences each.\n"
        "- brand_narrative: 4-6 bullets on narrative positioning.\n"
        "- competitor_developments: grouped by competitor, \"## CompetitorName\" then developments.\n"
        "- industry_context: 3-6 industry themes, ending with "
        '"## Key issues to monitor over the next 6-12 months" and 5-8 bullets.\n'
        "- methodology: 5-7 bullets on scope, time window, competitor set, selection rule.\n\n"
        "BATCH SUMMARIES:\n" + summary_block
    )
    response = llm_client.chat(
        [{"role": "system", "content": "You are a senior competitive intelligence analyst. Return only valid JSON."},
         {"role": "user", "content": prompt}],
        format_json=True,
    )
    cleaned = response.strip()
    if cleaned.startswith("```"):
        import re
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    parsed = _json.loads(cleaned)
    return {key: parsed.get(key, "") for key in _REDUCE_KEYS}


def summarize_map_reduce(project_id: int, spec: dict, llm_client, emit=None) -> dict:
    """Batch-summarize every persisted research item for this project (no truncation caps),
    then combine batch summaries into the 7-key Brief section shape. Failed batches are
    skipped, not fatal. Returns {} if there are zero items (caller falls back to
    _compose_rule_based, matching today's zero-results behavior)."""
    def _emit(step: str, payload: dict) -> None:
        if emit:
            emit(step, payload)

    items = repository.get_research_items(project_id)
    if not items:
        return {}

    brand_name = (spec.get("commissioning_brand") or {}).get("name", "the brand")
    batches = _batch_items(items, BATCH_SIZE)
    batch_summaries = []
    for i, batch in enumerate(batches):
        _emit("summarizing_batch", {"index": i + 1, "total": len(batches)})
        summary = _map_batch(llm_client, batch)
        if summary:
            batch_summaries.append(summary)

    if not batch_summaries:
        return {}

    _emit("combining_summaries", {"batch_count": len(batch_summaries)})
    return _reduce_batches(llm_client, batch_summaries, brand_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_multi_source.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/research/multi_source.py agent/tests/test_multi_source.py
git commit -m "feat: add map-reduce LLM summarization over persisted research items"
```

---

### Task 9: Wire `compose_brief()` to `summarize_map_reduce()`

**Files:**
- Modify: `agent/app/domains/research/service.py:90-107` (`compose_brief`'s LLM branch)
- Test: `agent/tests/test_research_service.py` — check if this file exists first; if not, create it

**Interfaces:**
- Consumes: `multi_source.summarize_map_reduce()` (Task 8)
- Produces: `compose_brief()`'s external return shape (`{"brief_id", "brief"}`) is unchanged

- [ ] **Step 1: Write the failing test**

```python
# add to (or create) agent/tests/test_research_service.py
import os
import tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

import json
from agent.app.domains.research import service as research_service
from agent.app.domains.research import repository


class _FakeLLM:
    def is_reachable(self):
        return True

    def chat(self, messages, format_json=False, on_token=None):
        return json.dumps({k: f"{k} via map-reduce" for k in [
            "company_introduction", "executive_summary", "brand_developments",
            "brand_narrative", "competitor_developments", "industry_context", "methodology",
        ]})


def test_compose_brief_uses_map_reduce_when_items_exist(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()
    repository.upsert_research_item(1, None, {
        "topic": "brand_activity", "source_api": "tavily", "platform": None,
        "publication": "Example", "published_date": 1790000000.0,
        "title": "Nike news", "content": "content", "url": "https://example.com/1",
    })
    monkeypatch.setattr(research_service, "_get_llm", lambda: _FakeLLM())

    spec = {"commissioning_brand": {"name": "Nike"}, "research_subject": {"description": "Nike research"}}
    research_data = {"news_items": [], "background_context": [], "research_gaps": [], "metadata": {}}
    result = research_service.compose_brief(project_id=1, research_id=1, spec=spec, research_data=research_data)

    assert result["brief"]["sections"]["executive_summary"]["content"] == "executive_summary via map-reduce"
    assert result["brief"]["enrichment_status"] == "llm_synthesized"


def test_compose_brief_falls_back_to_rule_based_with_zero_items(tmp_path, monkeypatch):
    from agent.app.core import db as core_db
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "test.db"))
    core_db.init_db()
    monkeypatch.setattr(research_service, "_get_llm", lambda: _FakeLLM())

    spec = {"commissioning_brand": {"name": "EmptyBrand"}}
    research_data = {"news_items": [], "background_context": [], "research_gaps": [], "metadata": {}}
    result = research_service.compose_brief(project_id=999, research_id=1, spec=spec, research_data=research_data)

    assert result["brief"]["enrichment_status"] == "rule_based"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agent/tests/test_research_service.py -v`
Expected: FAIL — `compose_brief()` still calls `_compose_with_llm()` with the old fixed-truncation
prompt, not `summarize_map_reduce()`, so the fake LLM's map-reduce-shaped response isn't consumed
correctly

- [ ] **Step 3: Update `compose_brief()`**

In `service.py`, replace the LLM branch (currently `if llm_client: ... sections, llm_succeeded = _compose_with_llm(...)`):

```python
    llm_client = _get_llm()
    sections = {}
    llm_succeeded = False

    if llm_client:
        from . import multi_source
        logger.info("Using map-reduce LLM summarization to synthesize analytical brief content")
        try:
            map_reduce_sections = multi_source.summarize_map_reduce(project_id, spec, llm_client)
        except Exception:
            logger.exception("Map-reduce summarization failed")
            map_reduce_sections = {}

        if map_reduce_sections:
            sections = {}
            for key in ["company_introduction", "executive_summary", "brand_developments",
                        "brand_narrative", "competitor_developments", "industry_context"]:
                title = SECTION_TITLES.get(key, key.replace("_", " ").title())
                if key == "brand_developments":
                    title = f"{brand_name}: Material Developments"
                sections[key] = {"title": title, "content": map_reduce_sections.get(key, ""), "edited": False}

            sections["key_issues"] = {"title": SECTION_TITLES["key_issues"], "content": "", "edited": False}
            industry_content = sections["industry_context"]["content"]
            if "## Key issues to monitor" in industry_content:
                parts = industry_content.split("## Key issues to monitor", 1)
                sections["industry_context"]["content"] = parts[0].rstrip()
                sections["key_issues"]["content"] = parts[1].lstrip().lstrip("#").lstrip()

            sections["methodology"] = {
                "title": SECTION_TITLES["methodology"],
                "content": map_reduce_sections.get("methodology", ""),
                "edited": False,
            }
            sections["source_register"] = _build_source_register_section(source_register)
            llm_succeeded = True

    if not sections:
        logger.warning("No LLM available or zero research items — falling back to rule-based brief")
        sections = _compose_rule_based(
            brand_name, research_subject, category, competitors,
            brand_items, competitor_items, industry_items, research_gaps,
            metadata, source_register, source_lookup
        )
```

This replaces the old `sections, llm_succeeded = _compose_with_llm(...)` call and the `if not
sections:` fallback block immediately after it — everything above (item classification, source
register building) and everything below (the `brief = {...}` dict construction) in `compose_brief`
is unchanged. `_compose_with_llm()` itself is left in the file, unused by this path — it stays as
dead code intentionally for one release in case of rollback, and can be deleted in a follow-up
cleanup once map-reduce is confirmed stable in production.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agent/tests/test_research_service.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `python -m pytest agent/tests/ -x -q --ignore=agent/tests/test_e2e_live_workflow.py`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/research/service.py agent/tests/test_research_service.py
git commit -m "feat: wire compose_brief to map-reduce summarization"
```

---

### Task 10: `POST /api/intel/research/fetch-preview` endpoint

**Files:**
- Modify: `agent/app/domains/research/router.py` (append route)
- Modify: `agent/app/domains/research/schemas.py` (append request/response models)
- Test: manual curl (this is a thin async-job wrapper around already-tested Task 4/5 functions;
  no new unit test needed beyond the existing job-pattern tests elsewhere in this codebase)

**Interfaces:**
- Produces: `POST /research/fetch-preview` — body `{project_id: int}` → `{job_id: str, project_id: int}`

- [ ] **Step 1: Add the request/response schemas**

Append to `agent/app/domains/research/schemas.py`:

```python
class FetchPreviewRequest(BaseModel):
    project_id: int


class FetchPreviewStarted(ApiModel):
    job_id: str
    project_id: int
```

(Match whichever base classes `StartResearchRequest`/`ResearchJobStarted` already use in this
file — `BaseModel` for requests, `ApiModel` for responses, per the existing pattern in this same
file.)

- [ ] **Step 2: Add the route**

Append to `agent/app/domains/research/router.py` (after the `/brandfetch/logo` and `/pexels/image`
routes):

```python
from . import multi_source as multi_source_module
from .schemas import FetchPreviewRequest, FetchPreviewStarted


@router.post("/research/fetch-preview", response_model=FetchPreviewStarted)
def fetch_preview(req: FetchPreviewRequest):
    """Run the multi-source fetch engine directly (no full research/brief flow) — for testing
    the Boolean query builder + 3-source fan-out independently, and the entry point Research
    Execution (stage 6) will call later with an analyst-approved query."""
    project = store.get_project(req.project_id)
    if not project:
        raise HTTPException(404, f"Project {req.project_id} not found")

    job_id = f"fetch_preview_{uuid.uuid4().hex[:12]}"
    store.create_job(job_id, req.project_id, "research_fetch_preview")

    def worker():
        store.update_job(job_id, status="running", progress_pct=5, progress_message="Building queries")
        _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                     "job_type": "research_fetch_preview", "status": "running",
                     "progress_pct": 5, "message": "Building queries"})
        try:
            spec = project.get("spec", {})
            topics = multi_source_module.build_boolean_queries(spec)
            adapter = LiveWebResearchAdapter()
            date_range = adapter._extract_date_range(spec)
            geography = adapter._extract_geography(spec)

            def on_event(step, payload):
                store.update_job(job_id, progress_pct=50, progress_message=step)
                _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                             "job_type": "research_fetch_preview", "status": "running",
                             "progress_pct": 50, "message": step, "detail": payload})

            result = multi_source_module.fetch_and_persist(
                project_id=req.project_id, topics=topics, date_range=date_range,
                geography=geography, emit=on_event,
            )
            store.update_job(job_id, status="completed", progress_pct=100,
                             progress_message="Fetch complete", result=result)
            _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                         "job_type": "research_fetch_preview", "status": "completed",
                         "progress_pct": 100, "message": "Fetch complete", **result})
        except Exception as e:
            logger.exception("fetch-preview failed for project %s", req.project_id)
            store.update_job(job_id, status="failed", error=str(e))
            _broadcast({"type": "intel_job_update", "job_id": job_id, "project_id": req.project_id,
                         "job_type": "research_fetch_preview", "status": "failed", "message": str(e)})

    submit(worker, name=f"research:fetch-preview:{req.project_id}")
    return FetchPreviewStarted(job_id=job_id, project_id=req.project_id)
```

- [ ] **Step 3: Smoke-test the endpoint**

Run: `python -c "from agent.app.main import create_app; app = create_app(); print(len(app.routes))"`
Expected: route count increases by 1 over the pre-Task-10 baseline; no import errors

- [ ] **Step 4: Restart the backend and live-test with curl**

```bash
curl -s -X POST http://127.0.0.1:8002/api/intel/research/fetch-preview -H "Content-Type: application/json" -d '{"project_id": <a real project id>}'
```

Expected: `{"job_id": "fetch_preview_...", "project_id": ...}`, then poll
`GET /api/intel/job/{job_id}` until `status: "completed"` with a `result` containing
`items_fetched`/`items_persisted` counts.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/research/router.py agent/app/domains/research/schemas.py
git commit -m "feat: add POST /research/fetch-preview endpoint"
```

---

### Task 11: "Past 7 days" dropdown option + new default

**Files:**
- Modify: `web/src/pages/NewProject.tsx:53,294` (Time Period `useState` default + `<select>` options)

**Interfaces:** none (pure UI change, no new props/exports)

- [ ] **Step 1: Change the default state value**

At `web/src/pages/NewProject.tsx:53`:

```tsx
const [timePeriod, setTimePeriod] = useState(draft?.timePeriod ?? "Past 7 days");
```

- [ ] **Step 2: Add the dropdown option**

At `web/src/pages/NewProject.tsx:293-298`, add "Past 7 days" as the first option:

```tsx
<select value={timePeriod} onChange={(e) => setTimePeriod(e.target.value)} className={INPUT}>
  <option>Past 7 days</option>
  <option>Past 30 days</option>
  <option>Past 3 months</option>
  <option>Past 6 months</option>
  <option>Past 12 months</option>
</select>
```

- [ ] **Step 3: Type-check**

Run: `cd web && npx tsc --noEmit`
Expected: clean (no output)

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/NewProject.tsx
git commit -m "feat: add Past 7 days time period option, default for POC phase"
```

---

### Task 12: Full test suite + backend smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest agent/tests/ -x -q --ignore=agent/tests/test_e2e_live_workflow.py`
Expected: PASS (all tests, including every new file from Tasks 1-9)

- [ ] **Step 2: Import smoke-test the whole app**

Run: `python -c "from agent.app.main import create_app; app = create_app(); print('routes:', len(app.routes))"`
Expected: no import errors, route count matches (baseline + 1 from Task 10)

- [ ] **Step 3: Frontend type-check**

Run: `cd web && npx tsc --noEmit`
Expected: clean

- [ ] **Step 4: Restart the backend**

Clear `__pycache__` and restart uvicorn per this project's standard restart procedure (see
CLAUDE.md's Quick Start section) so all changes are live for Task 13.

---

### Task 13: Tesla acceptance test (live, manual)

**Files:** none (acceptance test only — creates real data via the running app, not code)

- [ ] **Step 1: Create a fresh Tesla project**

Via the running app (or `curl -X POST /api/intel/projects` matching this session's established
test pattern): client "Tesla", Time Period "Past 7 days", a brief mentioning at least one Tesla
competitor by name (e.g., "Rivian", "Lucid Motors", "Ford") and one product (e.g., "Model 3").

- [ ] **Step 2: Run Brief & Scope generation**

`POST /api/intel/spec/generate` with `use_llm: true`; poll the job to completion; confirm the
generated spec has `validated_entities` with `type=competitor` entries and a populated
`industry.name`.

- [ ] **Step 3: Approve the spec, then run Background Research**

`POST /api/intel/spec/{id}/approve`, then `POST /api/intel/research/start`; poll to completion.

- [ ] **Step 4: Inspect persisted `intel_research_items` rows**

```bash
python -c "
from agent.app.domains.research import repository
items = repository.get_research_items(project_id=<tesla_project_id>)
print('total items:', len(items))
topics = {i['topic'] for i in items}
print('topics covered:', topics)
import time
now = time.time()
stale = [i for i in items if now - i['published_date'] > 8*86400]
print('items older than 8 days (should be empty):', len(stale))
"
```

Expected: `topics covered` includes both brand-only-adjacent and competitor-inclusive topics (per
Task 4's `brand_or_competitors` grouping, every topic should show items mentioning Tesla or a
named competitor), and zero stale items.

- [ ] **Step 5: Inspect the final Brief**

`GET /api/intel/brief/{project_id}` (or via `BackgroundResearch.tsx`) — confirm
`competitor_developments` names the competitors from the brief, `enrichment_status` is
`"llm_synthesized"`, and the item count feeding the brief is not silently capped at the old
20/15/8/30 truncation limits (compare `len(repository.get_research_items(project_id))` against
what shows up referenced across the sections).

- [ ] **Step 6: Report findings back**

If any step fails or the "Review Focus" items (zero results, batch failure, duplicate items,
stale dates, missing competitor coverage) surface unexpectedly, note which and fix before
considering this plan complete.

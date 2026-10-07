# Hunter Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hunter drives a project from brief to delivered deck on its own (autopilot) and answers or acts in chat (copilot). It remembers each project, puts real article and post screenshots on the slides, and finds and fixes its own UI, design and code problems safely, in tiers.

**Architecture:**
- A new `agent/app/domains/agent/` domain holds:
  - project memory and the event log in SQLite;
  - typed tools that drive the app's own `/api/intel` routes in-process, as the user who started the agent (a real session cookie), so auth and validation still apply;
  - an Azure OpenAI tool-calling autopilot with a deterministic next-step fallback;
  - a copilot;
  - a `repair/` package: issue intake, browser QA, diff tiers, git worktrees, the fixer, and apply/rollback.
- Deck Studio gains article screenshots, verbatim slides, in-run slide repair and single-slide revision.
- A tiny supervisor process restarts the backend after an applied fix. On startup the backend verifies the fix and rolls it back if the check fails.

**Tech Stack:** Python 3.12, FastAPI, SQLite migrations (`core/db.py`), Azure OpenAI chat completions with `tools`, Playwright (sync API, Chromium), git CLI (worktrees), React 18 + TypeScript + Tailwind.

**Spec:** `docs/superpowers/specs/2026-10-07-hunter-agent-design.md`

Two items from the 2026-10-07 session are folded in:
- (a) the UTF-16, tab-separated Meltwater CSV bug that failed Band-Aid (263, run 18) and Planet Fitness (264, run 19) at the ingest stage;
- (b) the 9 UI issues from the browser walkthrough.

## Global Constraints

- **Model:** "All Azure OpenAI (tool calling), the app's existing provider". There is no other chat provider. Embeddings stay on NVIDIA NIM.
- **Deterministic tier:** every LLM-dependent feature keeps one (`CLAUDE.md`). With Azure unconfigured, the autopilot still progresses through `status.next_step`.
- **Agent tools:** "Destructive tools (delete project/dataset) are not exposed" to the autopilot or the copilot.
- **Never auto-applied:** "secrets/config, auth, migrations, dependency changes, deletions of data".
- **Apply limits:** "at most one fix in flight, at most N auto-applies per hour; repeated failures disable auto-apply and alert an admin". N = `AUTO_APPLY_PER_HOUR = 3`. Two consecutive rollbacks disable auto-apply.
- **Fixer sandbox:** "The fixer can only read/write inside the repo worktree; no network except the Azure endpoint; no access to `.env` contents; secrets redacted from any prompt."
- **Test gate:** "A fix without a failing-then-passing test is discarded." For UI findings, the failing test is the browser QA finding and the passing test is the post-apply QA re-check (Ruling R3).
- **Secrets:** never log, cache, return or prompt with the values of `BRANDFETCH_API_KEY`, `SERP_API_KEY`, `PEXEL_API_KEY`, `AZURE_OPENAI_*` or `NVIDIA_EMBED_*`.
- **`/ws` is unauthenticated:** broadcasts carry ids, action names and counts only. Never article content, chat text or diffs.
- **Code layout:**
  - Persistence goes through `from ...core import store`.
  - New SQL lives in the owning `repository.py`.
  - Paths come from `core.config` constants.
  - Services never import a `router.py`.
- **Git and data:** nothing is pushed (the user pushes). Project 261 stays archived and is never deleted.
- **Line endings:** preserve each file's existing line endings when editing.
- **Tests:** `agent/tests/` is git-ignored, so tests are written and run but never committed. Commit steps list source files only.
- **Interpreter:** `PY=C:/Users/khadar.syed/AppData/Local/Programs/Python/Python312/python.exe`. Run every command from `D:\HunterAgent`.

## Rulings made while planning (carry into the ledger)

- **R1. In-process HTTP for tools.** Tools drive the existing HTTP routes in-process with `fastapi.testclient.TestClient(app)`, authenticated by a real session from `store.create_session(user_id)`.
  - Why: stage logic lives inside the routers (e.g. `strategy/router.py::_build_deterministic_strategy`). Calling them through HTTP keeps their validation and access checks.
  - Reads go straight to `store`.
  - Cost if wrong: a refactor to service calls later.
- **R2. In-run repair placement.** It lives in `deckstudio/repair.py`, not `domains/agent/repair/`, because it edits `SlideSpec`s mid-compose. The engine records each fix into agent memory through a callback, so deckstudio never imports the agent domain.
  - Cost if wrong: a file move.
- **R3. UI fix gate.** There is no frontend unit-test runner.
  - Red half: the browser QA finding on the live build.
  - Green half: the same QA check re-run after apply, with automatic rollback if the finding is still present.
  - `npx tsc --noEmit` must also pass in the worktree before apply.
  - Python fixes use pytest red→green inside the worktree.
  - Cost if wrong: a UI fix lands, fails its re-check, and rolls back (a restart, not a broken app).
- **R4. No second backend.** The fixer never starts a backend from a worktree. It would share `memory.db`, and its startup cancels live jobs (the 2026-10-07 incident). Worktree tests run with `HUNTER_AGENT_DATA_DIR` pointed at a temp dir.
- **R5. The 9 UI issues.** They are fixed by hand in Tasks 20–21, after:
  - Task 14 records the QA agent finding them on the current (pre-fix) build;
  - Task 19 runs the fixer on them.

  If the fixer already auto-applied a fix, that issue's step in Task 21 sees its QA check pass before the change. It is skipped with a ledger note.
- **R6. Detection paths for issues 5 and 7.**
  - Issue 5 ("Competitor Analysis" on a category brief) is a data and form-option problem that no generic browser check can see. It enters the issue list through the copilot's user-report path (`report_issue` tool), as spec §3.6.2 allows ("user reports from the copilot").
  - Issue 7 (optimistic ETA) is detected by an engine-side calibration check, not by the browser.
- **R7. Acceptance projects.** Band-Aid (263) and Planet Fitness (264) already exist and are approved up to datasets. The autopilot drives them from their current state (last deliverable run failed) to a delivered deck. The full created→deck path is covered by Task 7's tests on a fresh test project with a scripted pipeline. No duplicate client projects are created.
- **R8. Tests in worktrees.** `agent/tests/` is untracked, so a new worktree has no tests.
  - `worktree.create` copies `agent/tests/` into the worktree.
  - On apply, the fix's test file is copied back into the main `agent/tests/`.

## Review Focus

1. **Unsafe dataset URLs.** A dataset row whose URL points at a private, loopback or link-local host, or uses a non-http(s) scheme (`file:`, `javascript:`). Verbatim capture must refuse to open it and fall back to the article card. Pinned by `test_capture_refuses_private_and_non_http_urls` (Task 9).
2. **Uncommitted changes in the user's main working tree when a fix is applied.** Apply must refuse, leave the fix in the inbox with the reason, and never stash or overwrite. Pinned by `test_apply_refuses_dirty_tree` (Task 18).
3. **Backend restart in the middle of an autopilot step.** The restart cancels the running job (the Planet research incident). On startup the autopilot resumes and re-runs that step; it does not mark the project blocked. Pinned by `test_resume_reruns_cancelled_step` (Task 7).
4. **Unsupported or costly copilot requests.** For a request no tool supports ("delete this dataset"), the reply says it cannot, and no tool runs. A costly action returns a pending action that runs only on confirm. Pinned by `test_copilot_cannot_delete` and `test_costly_action_needs_confirm` (Task 8).
5. **Azure OpenAI unreachable.**
   - The autopilot completes steps deterministically.
   - The copilot answers with the project status and says the model is unavailable.
   - The fixer marks the issue `needs_llm` instead of crashing.

   Pinned by `test_autopilot_progresses_without_llm` (Task 7), `test_copilot_without_llm` (Task 8) and `test_fixer_without_llm` (Task 17).

---

## Phase 0: unblock the data

### Task 1: Read UTF-16 / tab-separated CSV exports

**Files:**
- Create: `agent/app/core/tabular.py`
- Modify: `agent/app/domains/execution/service.py:93-109` (`_load_dataset`) and `:161-180` (`_normalize_columns`)
- Modify: `agent/app/domains/strategy/router.py`:
  - `:770-779` (`_read_csv_text`);
  - `:916-917` and `:1103-1104` (the two `csv.DictReader(f)` calls).
- Test: `agent/tests/test_tabular.py`

**Interfaces:**
- Produces:
  - `tabular.decode_text(raw: bytes) -> str`
  - `tabular.sniff_delimiter(text: str) -> str`
  - `tabular.read_csv_dicts(path: str | Path) -> list[dict[str, str]]`. Keys are stripped header names. Extra fields and `None` keys are dropped.

- [ ] **Step 1: Write the failing tests**

```python
"""CSV exports in any encoding/delimiter: Meltwater writes UTF-16 LE tab-separated files."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from pathlib import Path

from agent.app.core import tabular

HEADER = ["Date", "Headline", "URL", "Source Name", "Hit Sentence", "Reach"]
ROW = ["01-Mar-2026 09:12AM", "Kids, knees and plasters", "https://example.com/a", "Example News",
       "Soccer injuries, scrapes\tand more", "1200"]


def _write(tmp: Path, name: str, text: str, encoding: str) -> Path:
    p = tmp / name
    p.write_bytes(text.encode(encoding))
    return p


def _tsv(rows):  # Meltwater quotes fields that contain a delimiter
    return "\r\n".join("\t".join(f'"{c}"' if "\t" in c or "," in c else c for c in r) for r in rows) + "\r\n"


def test_utf16_tab_export_reads_as_records(tmp_path):
    p = _write(tmp_path, "mw.csv", "\ufeff" + _tsv([HEADER, ROW]), "utf-16-le")
    assert tabular.read_csv_dicts(p) == [dict(zip(HEADER, ROW))]


def test_utf16_without_bom_is_detected(tmp_path):
    p = _write(tmp_path, "mw.csv", _tsv([HEADER, ROW]), "utf-16-le")
    assert tabular.read_csv_dicts(p)[0]["URL"] == "https://example.com/a"


def test_cp1252_comma_csv_still_reads(tmp_path):
    text = ",".join(HEADER) + "\r\n" + '01-Mar-2026,Mum\x92s pick,https://e.com/b,E,"a, b",5\r\n'
    p = tmp_path / "x.csv"
    p.write_bytes(text.encode("latin-1"))
    row = tabular.read_csv_dicts(p)[0]
    assert row["Headline"] == "Mum\u2019s pick" and row["Hit Sentence"] == "a, b"


def test_semicolon_delimiter(tmp_path):
    p = _write(tmp_path, "s.csv", "URL;Headline\r\nhttps://e.com/c;Hi\r\n", "utf-8")
    assert tabular.read_csv_dicts(p) == [{"URL": "https://e.com/c", "Headline": "Hi"}]


def test_extra_fields_are_dropped_not_keyed_none(tmp_path):
    p = _write(tmp_path, "e.csv", "URL,Headline\r\nhttps://e.com/d,Hi,extra,more\r\n", "utf-8")
    rows = tabular.read_csv_dicts(p)
    assert rows == [{"URL": "https://e.com/d", "Headline": "Hi"}] and None not in rows[0]


def test_execution_loader_reads_utf16_tab(tmp_path):
    from agent.app.domains.execution.service import _load_dataset
    p = _write(tmp_path, "mw.csv", "\ufeff" + _tsv([HEADER, ROW]), "utf-16-le")
    assert _load_dataset(str(p))[0]["url"] == "https://example.com/a"


def test_normalize_columns_ignores_none_keys():
    from agent.app.domains.execution.service import _normalize_columns
    assert _normalize_columns([{"URL": "https://e.com/e", None: ["x"]}]) == [{"url": "https://e.com/e"}]


def test_upload_parse_maps_utf16_headers(tmp_path):
    from agent.app.domains.strategy.router import _parse_and_analyze
    p = _write(tmp_path, "mw.csv", "\ufeff" + _tsv([HEADER, ROW, ROW]), "utf-16-le")
    headers, preview, total, *_ = _parse_and_analyze(str(p))
    assert "URL" in headers and total == 2 and preview[0]["URL"] == "https://example.com/a"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_tabular.py -q -p no:cacheprovider`
Expected: FAIL. Collection errors with `ModuleNotFoundError: No module named 'agent.app.core.tabular'`.

- [ ] **Step 3: Write `core/tabular.py`**

```python
"""Read CSV exports whatever their encoding and delimiter. Meltwater writes UTF-16 LE, tab-separated files;
Excel on Windows writes cp1252 comma-separated ones."""
from __future__ import annotations

import csv
import io
from pathlib import Path

_BOMS = ((b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"), (b"\xef\xbb\xbf", "utf-8-sig"))
_FALLBACKS = ("utf-8", "cp1252", "latin-1")
_DELIMITERS = ",\t;|"
_NUL_PROBE = 400
_EXTRA = "__extra__"


def decode_text(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    probe = raw[:_NUL_PROBE]
    if probe and probe.count(b"\x00") > len(probe) // 4:      # UTF-16 without a BOM: every other byte is NUL
        return raw.decode("utf-16-le" if probe[1:2] == b"\x00" else "utf-16-be", errors="replace")
    for encoding in _FALLBACKS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    """The delimiter that splits the header line most, counted outside quotes."""
    header = next((line for line in text.lstrip("\ufeff").splitlines() if line.strip()), "")
    counts, quoted = {d: 0 for d in _DELIMITERS}, False
    for ch in header:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    best = max(_DELIMITERS, key=lambda d: counts[d])
    return best if counts[best] else ","


def read_csv_dicts(path: str | Path) -> list[dict[str, str]]:
    text = decode_text(Path(path).read_bytes()).lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=sniff_delimiter(text), restkey=_EXTRA)
    return [{k.strip(): (v or "") for k, v in raw.items() if isinstance(k, str) and k != _EXTRA and k.strip()}
            for raw in reader]
```

- [ ] **Step 4: Use it in the execution loader**

In `agent/app/domains/execution/service.py`, add `from ...core.tabular import read_csv_dicts`. Then replace the encodings loop in `_load_dataset`. The loop currently reads:

```python
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as fh:
                reader = csv.DictReader(fh)
                raw = list(reader)
                return _normalize_columns(raw)
        except (UnicodeDecodeError, csv.Error):
            continue
    return []
```

Replace it with:

```python
    try:
        return _normalize_columns(read_csv_dicts(file_path))
    except (OSError, csv.Error) as e:
        logger.error("Could not read dataset %s: %s", file_path, e)
        return []
```

In `_normalize_columns`:
- `raw_columns = list(records[0].keys())` becomes `raw_columns = [c for c in records[0].keys() if isinstance(c, str)]`.
- The row loop becomes:

```python
        for raw_col, value in r.items():
            if not isinstance(raw_col, str):      # csv extra fields arrive under the key None
                continue
            mapped = col_map.get(raw_col, raw_col.lower().strip().replace(" ", "_"))
            row[mapped] = value
```

- [ ] **Step 5: Use it in the upload parser**

In `agent/app/domains/strategy/router.py`:
- add `from ...core.tabular import decode_text, sniff_delimiter`;
- replace the body of `_read_csv_text` with `return decode_text(Path(file_path).read_bytes())`, and delete `_CSV_ENCODINGS`;
- in both places that build a reader over `io.StringIO(_read_csv_text(file_path), newline="")` (lines 916-917 and 1103-1104), change `csv.DictReader(f)` to `csv.DictReader(f, delimiter=sniff_delimiter(f.getvalue()))`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_tabular.py agent/tests/test_dataset_upload_parsing.py agent/tests/test_executor_service.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Check the real failing projects (read-only)**

Run: `$PY -c "from agent.app.domains.deliverable import rows as R; [print(p, len(R.load_rows(p, R.load_rqs(p)))) for p in (263, 264)]"`
Expected: two lines `263 <n>` and `264 <n>`, each with n > 1000, and no `'NoneType' object has no attribute 'lower'`.

- [ ] **Step 8: Commit**

```bash
git add agent/app/core/tabular.py agent/app/domains/execution/service.py agent/app/domains/strategy/router.py
git commit -m "fix: read UTF-16 tab-separated Meltwater CSV exports at upload and ingest"
```

---

## Phase 1: memory, tools, autopilot, copilot

### Task 2: Agent tables and repository

**Files:**
- Modify: `agent/app/core/db.py`: add migration 21 after the `(20, "deck studio", [...])` entry.
- Create:
  - `agent/app/domains/agent/__init__.py` (docstring only);
  - `agent/app/domains/agent/repository.py`.
- Modify: `agent/app/core/store.py`: add `from ..domains.agent.repository import *  # noqa: F401,F403` after the deckstudio line.
- Test: `agent/tests/test_agent_repository.py`

**Interfaces:**
- Produces (all reachable as `store.<name>`):
  - Memory:
    - `set_memory(project_id: int, kind: str, key: str, value) -> None`;
    - `list_memory(project_id: int, kind: str | None = None) -> list[dict]`. Each row is `{project_id, kind, key, value, updated_at}`, with `value` JSON-decoded;
    - `delete_memory(project_id: int, kind: str, key: str) -> None`.
  - Events:
    - `add_agent_event(project_id: int, actor: str, action: str, detail: dict | None = None, run_id: int | None = None) -> int`;
    - `list_agent_events(project_id: int, limit: int = 50, after_id: int = 0) -> list[dict]`, newest first. Each row is `{id, project_id, run_id, actor, action, detail, at}`.
  - Autopilot state:
    - `upsert_autopilot(project_id: int, user_id: int, status: str, note: str = "", attempts: int | None = None) -> None`;
    - `get_autopilot(project_id: int) -> dict | None`;
    - `list_autopilots(status: str | None = None) -> list[dict]`.
  - Issues:
    - `file_issue_row(fingerprint: str, source: str, kind: str, title: str, detail: dict, project_id: int | None) -> tuple[int, bool]`, returning `(id, is_new)`. Re-filing an open fingerprint bumps `seen` and returns `(id, False)`;
    - `get_issue(issue_id: int) -> dict | None`;
    - `list_issues(status: str | None = None) -> list[dict]`;
    - `set_issue_status(issue_id: int, status: str, note: str = "") -> None`.
  - Fixes:
    - `create_fix(issue_id: int, branch: str, tier: str, diff: str, tests: dict) -> int`;
    - `get_fix(fix_id: int) -> dict | None`;
    - `list_fixes(status: str | None = None) -> list[dict]`;
    - `update_fix(fix_id: int, **fields) -> None`. Allowed fields: `status, note, commit_sha, diff, tier, tests`.
  - Global rows (the auto-apply switch, fix outcomes) use `project_id = 0`.

- [ ] **Step 1: Write the failing test**

```python
"""Agent memory, events, autopilot state, issues and fixes."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import time
from agent.app.core import store


def setup_module(_):
    store.init_intelligence_db()


def test_memory_upserts_by_kind_and_key():
    store.set_memory(9001, "preference", "palette", {"mood": "calm"})
    store.set_memory(9001, "preference", "palette", {"mood": "bold"})
    rows = store.list_memory(9001, "preference")
    assert [(r["key"], r["value"]) for r in rows] == [("palette", {"mood": "bold"})]
    store.delete_memory(9001, "preference", "palette")
    assert store.list_memory(9001) == []


def test_events_newest_first_and_after_id():
    a = store.add_agent_event(9002, "autopilot", "generate_scope", {"ok": True})
    b = store.add_agent_event(9002, "copilot", "read_run", None, run_id=4)
    rows = store.list_agent_events(9002)
    assert [r["id"] for r in rows] == [b, a] and rows[0]["run_id"] == 4 and rows[1]["detail"] == {"ok": True}
    assert [r["id"] for r in store.list_agent_events(9002, after_id=a)] == [b]


def test_autopilot_state_round_trip():
    store.upsert_autopilot(9003, 1, "running", "step 1", attempts=0)
    store.upsert_autopilot(9003, 1, "blocked", "needs a human")
    ap = store.get_autopilot(9003)
    assert ap["status"] == "blocked" and ap["note"] == "needs a human" and ap["attempts"] == 0
    assert 9003 in [r["project_id"] for r in store.list_autopilots("blocked")]


def test_issue_dedupes_open_fingerprint():
    fp = f"fp-{time.time()}"
    i, new = store.file_issue_row(fp, "engine", "exception", "Ingest failed", {"stage": "ingest"}, 263)
    j, again = store.file_issue_row(fp, "engine", "exception", "Ingest failed", {"stage": "ingest"}, 263)
    assert new and not again and i == j and store.get_issue(i)["seen"] == 2
    store.set_issue_status(i, "fixed")
    k, reopened = store.file_issue_row(fp, "engine", "exception", "Ingest failed", {}, 263)
    assert reopened and k != i


def test_fix_round_trip():
    i, _ = store.file_issue_row(f"fp2-{time.time()}", "qa_browser", "faded", "Page faded", {}, None)
    f = store.create_fix(i, "autofix/1", "auto", "diff --git a b", {"red": "1 failed", "green": "1 passed"})
    store.update_fix(f, status="applied", commit_sha="abc123")
    fix = store.get_fix(f)
    assert fix["status"] == "applied" and fix["tests"]["green"] == "1 passed" and fix["commit_sha"] == "abc123"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest agent/tests/test_agent_repository.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'agent.app.core.store' has no attribute 'set_memory'`.

- [ ] **Step 3: Migration 21** (append to `MIGRATIONS` in `core/db.py`)

```python
    (21, "hunter agent", [
        """CREATE TABLE IF NOT EXISTS agent_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, kind TEXT NOT NULL,
            key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(project_id, kind, key))""",
        """CREATE TABLE IF NOT EXISTS agent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, run_id INTEGER,
            actor TEXT NOT NULL, action TEXT NOT NULL, detail_json TEXT, at REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_agent_events_project ON agent_events(project_id, id)",
        """CREATE TABLE IF NOT EXISTS agent_autopilots (
            project_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS agent_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, source TEXT NOT NULL, kind TEXT NOT NULL,
            title TEXT NOT NULL, detail_json TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', seen INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
            updated_at REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_agent_issues_fp ON agent_issues(fingerprint, status)",
        """CREATE TABLE IF NOT EXISTS agent_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL, branch TEXT NOT NULL,
            tier TEXT NOT NULL, diff TEXT NOT NULL, tests_json TEXT NOT NULL, status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', commit_sha TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    ]),
```

- [ ] **Step 4: Write `domains/agent/repository.py`**

```python
"""SQLite access for the Hunter agent: per-project memory, the event log, autopilot state, issues and fixes."""
from __future__ import annotations

import json
import time
from typing import Optional

from ...core.db import _conn

OPEN_ISSUE_STATES = ("open", "fixing", "proposed", "needs_llm")
_FIX_FIELDS = {"status", "note", "commit_sha", "diff", "tier", "tests"}


def _row(r, json_cols: dict[str, str]) -> dict:
    d = dict(r)
    for col, name in json_cols.items():
        raw = d.pop(col)
        d[name] = json.loads(raw) if raw else None
    return d


def set_memory(project_id: int, kind: str, key: str, value) -> None:
    conn = _conn()
    conn.execute("INSERT INTO agent_memory (project_id, kind, key, value_json, updated_at) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(project_id, kind, key) DO UPDATE SET value_json = excluded.value_json, "
                 "updated_at = excluded.updated_at", (project_id, kind, key, json.dumps(value, default=str), time.time()))
    conn.commit()
    conn.close()


def list_memory(project_id: int, kind: str | None = None) -> list[dict]:
    conn = _conn()
    sql = "SELECT project_id, kind, key, value_json, updated_at FROM agent_memory WHERE project_id = ?"
    rows = conn.execute(sql + (" AND kind = ?" if kind else "") + " ORDER BY kind, key",
                        (project_id, kind) if kind else (project_id,)).fetchall()
    conn.close()
    return [_row(r, {"value_json": "value"}) for r in rows]


def delete_memory(project_id: int, kind: str, key: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM agent_memory WHERE project_id = ? AND kind = ? AND key = ?", (project_id, kind, key))
    conn.commit()
    conn.close()


def add_agent_event(project_id: int, actor: str, action: str, detail: dict | None = None,
                    run_id: int | None = None) -> int:
    conn = _conn()
    event_id = conn.execute("INSERT INTO agent_events (project_id, run_id, actor, action, detail_json, at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (project_id, run_id, actor, action,
                             json.dumps(detail, default=str) if detail is not None else None, time.time())).lastrowid
    conn.commit()
    conn.close()
    return event_id


def list_agent_events(project_id: int, limit: int = 50, after_id: int = 0) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_events WHERE project_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
                        (project_id, after_id, limit)).fetchall()
    conn.close()
    return [_row(r, {"detail_json": "detail"}) for r in rows]


def upsert_autopilot(project_id: int, user_id: int, status: str, note: str = "", attempts: int | None = None) -> None:
    conn = _conn()
    current = conn.execute("SELECT attempts FROM agent_autopilots WHERE project_id = ?", (project_id,)).fetchone()
    tries = attempts if attempts is not None else (current["attempts"] if current else 0)
    conn.execute("INSERT INTO agent_autopilots (project_id, user_id, status, note, attempts, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET user_id = excluded.user_id, "
                 "status = excluded.status, note = excluded.note, attempts = excluded.attempts, "
                 "updated_at = excluded.updated_at", (project_id, user_id, status, note, tries, time.time()))
    conn.commit()
    conn.close()


def get_autopilot(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_autopilots WHERE project_id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_autopilots(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_autopilots" + (" WHERE status = ?" if status else "") + " ORDER BY updated_at",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def file_issue_row(fingerprint: str, source: str, kind: str, title: str, detail: dict,
                   project_id: int | None) -> tuple[int, bool]:
    conn = _conn()
    marks = ",".join("?" * len(OPEN_ISSUE_STATES))
    row = conn.execute(f"SELECT id FROM agent_issues WHERE fingerprint = ? AND status IN ({marks})",
                       (fingerprint, *OPEN_ISSUE_STATES)).fetchone()
    now = time.time()
    if row:
        conn.execute("UPDATE agent_issues SET seen = seen + 1, updated_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        conn.close()
        return row["id"], False
    issue_id = conn.execute("INSERT INTO agent_issues (project_id, source, kind, title, detail_json, fingerprint, "
                            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                            (project_id, source, kind, title, json.dumps(detail, default=str), fingerprint, now,
                             now)).lastrowid
    conn.commit()
    conn.close()
    return issue_id, True


def get_issue(issue_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_issues WHERE id = ?", (issue_id,)).fetchone()
    conn.close()
    return _row(row, {"detail_json": "detail"}) if row else None


def list_issues(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_issues" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [_row(r, {"detail_json": "detail"}) for r in rows]


def set_issue_status(issue_id: int, status: str, note: str = "") -> None:
    conn = _conn()
    conn.execute("UPDATE agent_issues SET status = ?, note = ?, updated_at = ? WHERE id = ?",
                 (status, note, time.time(), issue_id))
    conn.commit()
    conn.close()


def create_fix(issue_id: int, branch: str, tier: str, diff: str, tests: dict) -> int:
    conn = _conn()
    now = time.time()
    fix_id = conn.execute("INSERT INTO agent_fixes (issue_id, branch, tier, diff, tests_json, status, created_at, "
                          "updated_at) VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)",
                          (issue_id, branch, tier, diff, json.dumps(tests), now, now)).lastrowid
    conn.commit()
    conn.close()
    return fix_id


def get_fix(fix_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM agent_fixes WHERE id = ?", (fix_id,)).fetchone()
    conn.close()
    return _row(row, {"tests_json": "tests"}) if row else None


def list_fixes(status: str | None = None) -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM agent_fixes" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC",
                        (status,) if status else ()).fetchall()
    conn.close()
    return [_row(r, {"tests_json": "tests"}) for r in rows]


def update_fix(fix_id: int, **fields) -> None:
    unknown = set(fields) - _FIX_FIELDS
    if unknown:
        raise ValueError(f"unknown fix fields: {sorted(unknown)}")
    if "tests" in fields:
        fields["tests_json"] = json.dumps(fields.pop("tests"))
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = _conn()
    conn.execute(f"UPDATE agent_fixes SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), time.time(), fix_id))
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_repository.py agent/tests/test_auth_migration.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/app/core/db.py agent/app/core/store.py agent/app/domains/agent/__init__.py agent/app/domains/agent/repository.py
git commit -m "feat(agent): memory, event log, autopilot state, issues and fixes tables"
```

### Task 3: Project memory and the context budget

**Files:**
- Create: `agent/app/domains/agent/memory.py`
- Test: `agent/tests/test_agent_memory.py`

**Interfaces:**
- Consumes (Task 2):
  - `store.set_memory`, `store.list_memory`
  - `store.add_agent_event`, `store.list_agent_events`
- Produces:
  - `MEMORY_KINDS = ("preference", "decision", "fact", "fix")`
  - `remember(project_id: int, kind: str, key: str, value) -> None`. Raises `ValueError` for an unknown kind.
  - `record(project_id: int, actor: str, action: str, detail: dict | None = None, run_id: int | None = None) -> int`.
    - Also broadcasts `{"type": "agent_event", "project_id", "actor", "action", "event_id"}`.
  - `estimate_tokens(text: str) -> int`, defined as `len(text) // 4 + 1`.
  - `context(project_id: int, llm=None, budget: int = PROMPT_BUDGET_TOKENS) -> str`.
    - The result never exceeds `budget` tokens by `estimate_tokens`.
  - `PROMPT_BUDGET_TOKENS = 6000`, `RECENT_EVENTS = 30`

- [ ] **Step 1: Write the failing tests**

```python
"""Memory context stays under budget, keeps preferences, and summarises old events."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.core import store
from agent.app.domains.agent import memory


def setup_module(_):
    store.init_intelligence_db()


class FakeLLM:
    def __init__(self): self.calls = 0
    def is_reachable(self): return True
    def chat(self, messages, **_):
        self.calls += 1
        return "Summary: scope approved, strategy approved, two runs failed at ingest."


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        memory.remember(9101, "secret", "k", 1)


def test_context_includes_preferences_and_recent_events():
    memory.remember(9102, "preference", "palette", "calm blues")
    memory.record(9102, "autopilot", "approve_scope", {"ok": True})
    text = memory.context(9102)
    assert "palette" in text and "calm blues" in text and "approve_scope" in text


def test_context_respects_budget_and_summarises_old_events():
    for k in range(400):
        memory.record(9103, "autopilot", f"step_{k}", {"note": "x" * 80})
    llm = FakeLLM()
    text = memory.context(9103, llm=llm, budget=1500)
    assert memory.estimate_tokens(text) <= 1500
    assert "Summary: scope approved" in text and "step_399" in text and llm.calls == 1
    memory.context(9103, llm=llm, budget=1500)          # summary reused until new events pile up
    assert llm.calls == 1


def test_context_without_llm_uses_counts():
    for k in range(400):
        memory.record(9104, "autopilot", "run_deliverable" if k % 2 else "read_run", {"note": "y" * 80})
    text = memory.context(9104, llm=None, budget=1200)
    assert memory.estimate_tokens(text) <= 1200 and "run_deliverable" in text and "earlier events" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_agent_memory.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'memory'`.

- [ ] **Step 3: Write `memory.py`**

```python
"""Per-project memory shared by the autopilot and the copilot, and the prompt context built from it.
The context stays under a fixed token budget: memory rows, then a rolling summary of older events, then the most
recent events."""
from __future__ import annotations

import json
import logging
from collections import Counter

from ...core import store
from ...core.events import broadcast

logger = logging.getLogger(__name__)
MEMORY_KINDS = ("preference", "decision", "fact", "fix")
PROMPT_BUDGET_TOKENS = 6000
RECENT_EVENTS = 30
SUMMARY_KEY = "events"
SUMMARY_SHARE = 0.25          # at most a quarter of the budget goes to the rolling summary
_SUMMARY_PROMPT = ("Summarise this project's agent activity log in at most 120 words: what was done, what failed and "
                   "why, what the user asked for. Plain sentences, no lists.")


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def remember(project_id: int, kind: str, key: str, value) -> None:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind {kind!r}")
    store.set_memory(project_id, kind, key, value)


def record(project_id: int, actor: str, action: str, detail: dict | None = None, run_id: int | None = None) -> int:
    event_id = store.add_agent_event(project_id, actor, action, detail, run_id)
    broadcast({"type": "agent_event", "project_id": project_id, "actor": actor, "action": action, "event_id": event_id})
    return event_id


def _line(e: dict) -> str:
    detail = json.dumps(e["detail"], default=str)[:300] if e.get("detail") else ""
    return f"[{e['id']}] {e['actor']} {e['action']} {detail}".strip()


def _clip(text: str, budget: int) -> str:
    return text if estimate_tokens(text) <= budget else text[: max(0, budget * 4 - 8)] + " …"


def _summary(project_id: int, older: list[dict], llm) -> str:
    upto = older[0]["id"]                       # older is newest-first
    saved = next((m["value"] for m in store.list_memory(project_id, "summary") if m["key"] == SUMMARY_KEY), None)
    if saved and saved.get("upto") == upto:
        return saved["text"]
    text = ""
    if llm is not None and getattr(llm, "is_reachable", lambda: False)():
        try:
            log = "\n".join(_line(e) for e in reversed(older))[-24000:]
            text = (llm.chat([{"role": "system", "content": _SUMMARY_PROMPT},
                              {"role": "user", "content": log}]) or "").strip()
        except Exception as e:      # the deterministic summary below still fits the budget
            logger.warning("memory summary skipped: %s", type(e).__name__)
    if not text:
        counts = Counter(e["action"] for e in older)
        text = f"{len(older)} earlier events: " + ", ".join(f"{a} x{n}" for a, n in counts.most_common(12))
    store.set_memory(project_id, "summary", SUMMARY_KEY, {"upto": upto, "text": text})
    return text


def context(project_id: int, llm=None, budget: int = PROMPT_BUDGET_TOKENS) -> str:
    rows = [m for m in store.list_memory(project_id) if m["kind"] in MEMORY_KINDS]
    facts = "\n".join(f"{m['kind']}: {m['key']} = {json.dumps(m['value'], default=str)[:400]}" for m in rows)
    head = _clip("Project memory:\n" + (facts or "(none)"), budget // 3)
    events = store.list_agent_events(project_id, limit=5000)
    recent, older = events[:RECENT_EVENTS], events[RECENT_EVENTS:]
    summary = _clip("Earlier activity: " + _summary(project_id, older, llm), int(budget * SUMMARY_SHARE)) if older else ""
    room = budget - estimate_tokens(head) - estimate_tokens(summary) - 8
    lines: list[str] = []
    for e in recent:                            # newest first, so the latest always fit
        line = _line(e)
        if estimate_tokens("\n".join(lines + [line])) > room:
            break
        lines.append(line)
    tail = "Recent activity (newest first):\n" + "\n".join(lines)
    return "\n\n".join(part for part in (head, summary, tail) if part)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_memory.py -q -p no:cacheprovider`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/agent/memory.py
git commit -m "feat(agent): project memory with a token-budgeted context and rolling summary"
```

### Task 4: Tool calling on the Azure OpenAI client

**Files:**
- Modify: `agent/app/core/azure_openai_client.py` (add `chat_tools`)
- Modify: `agent/app/core/llm_provider.py` (add `HybridLLMClient.chat_tools`)
- Test: `agent/tests/test_llm_tool_calls.py`

**Interfaces:**
- Produces:
  - `AzureOpenAIClient.chat_tools(messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict`
    - Returns `{"content": str | None, "tool_calls": [{"id": str, "name": str, "arguments": dict}], "message": dict}`.
    - `message` is the raw assistant message, ready to append back into the conversation.
    - Arguments that are not valid JSON become `{"_raw": "<text>"}`.
  - `HybridLLMClient.chat_tools(...)`: same signature. Raises `NoChatProviderError` when no chat backend is configured.

- [ ] **Step 1: Write the failing tests**

```python
"""Azure OpenAI tool calling: request carries tools; tool calls come back parsed."""
from __future__ import annotations
import json
import pytest
from agent.app.core.azure_openai_client import AzureOpenAIClient, AzureOpenAIError


class Resp:
    def __init__(self, status, body): self.status_code, self._body, self.text = status, body, json.dumps(body)
    def json(self): return self._body


def _client():
    return AzureOpenAIClient(api_key="k", endpoint="https://x.openai.azure.com", deployment="d", api_version="v")


def test_chat_tools_sends_tools_and_parses_calls(monkeypatch):
    seen = {}
    def fake_post(url, headers, json, timeout):
        seen.update(json)
        return Resp(200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "approve_scope", "arguments": "{\"note\": \"ok\"}"}},
            {"id": "c2", "type": "function", "function": {"name": "read_run", "arguments": "not json"}}]}}]})
    monkeypatch.setattr("agent.app.core.azure_openai_client.requests.post", fake_post)
    tools = [{"type": "function", "function": {"name": "approve_scope", "parameters": {"type": "object"}}}]
    out = _client().chat_tools([{"role": "user", "content": "go"}], tools)
    assert seen["tools"] == tools and seen["tool_choice"] == "auto"
    assert out["tool_calls"] == [{"id": "c1", "name": "approve_scope", "arguments": {"note": "ok"}},
                                 {"id": "c2", "name": "read_run", "arguments": {"_raw": "not json"}}]
    assert out["message"]["tool_calls"][0]["id"] == "c1" and out["content"] is None


def test_chat_tools_error_status_raises(monkeypatch):
    monkeypatch.setattr("agent.app.core.azure_openai_client.requests.post",
                        lambda *a, **k: Resp(429, {"error": "busy"}))
    with pytest.raises(AzureOpenAIError):
        _client().chat_tools([{"role": "user", "content": "go"}], [])


def test_hybrid_without_backend_raises():
    from agent.app.core.llm_provider import HybridLLMClient, NoChatProviderError
    client = HybridLLMClient.__new__(HybridLLMClient)
    client._chat_backend = None
    with pytest.raises(NoChatProviderError):
        client.chat_tools([{"role": "user", "content": "x"}], [])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_llm_tool_calls.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: 'AzureOpenAIClient' object has no attribute 'chat_tools'`.

- [ ] **Step 3: Add `chat_tools` to `AzureOpenAIClient`** (after `chat`)

```python
    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        """One tool-calling turn: the reply's text and the tool calls it asks for, arguments parsed."""
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload: dict = {"messages": messages, "max_tokens": 4096}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        r = requests.post(self._url(), headers=headers, json=payload, timeout=180)
        if r.status_code != 200:
            raise AzureOpenAIError(f"Azure OpenAI tool call failed: {r.status_code} {r.text[:300]}")
        message = r.json()["choices"][0]["message"]
        calls = []
        for c in message.get("tool_calls") or []:
            raw = c.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append({"id": c.get("id", ""), "name": c.get("function", {}).get("name", ""),
                          "arguments": args if isinstance(args, dict) else {"_raw": raw}})
        return {"content": message.get("content"), "tool_calls": calls, "message": message}
```

- [ ] **Step 4: Add `chat_tools` to `HybridLLMClient`** (after `chat`)

```python
    def chat_tools(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        if self._chat_backend is None:
            raise NoChatProviderError(
                "No chat LLM configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL"
            )
        return self._chat_backend.chat_tools(messages, tools, tool_choice=tool_choice)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_llm_tool_calls.py -q -p no:cacheprovider`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/app/core/azure_openai_client.py agent/app/core/llm_provider.py
git commit -m "feat(llm): Azure OpenAI tool-calling turn"
```

### Task 5: Project status and the deterministic next step

**Files:**
- Create: `agent/app/domains/agent/status.py`
- Test: `agent/tests/test_agent_status.py`

**Interfaces:**
- Consumes existing store getters:
  - `get_project`
  - `get_latest_spec`: `id`, `approval_status`
  - `get_latest_research`: `status`
  - `get_latest_brief`: `id`, `approval_status`
  - `get_latest_strategy`: `id`, `approval_status`
  - `get_datasets_by_project`: `id`, `processing_status`, `enrichment_status`, `record_count`, `approval_status`
  - `get_latest_deliverable_run`: `id`, `status`, `stage`, `error`
  - `list_jobs(project_id)`: `job_type`, `status`
- Produces:
  - `STEP_KEYS = ("scope", "research", "brief", "strategy", "datasets", "deliverable")`
  - `project_status(project_id: int) -> dict`.
    - Returns `{"project_id", "name", "steps": [{"key", "label", "state", "detail"}], "next": str | None, "datasets": [...], "run": dict | None}`.
    - `state` is one of `done | ready | waiting | failed | todo`.
  - `next_step(status: dict) -> str | None`.
    - Returns a Task 6 tool name, or `"wait"`, or `None` once the deck is delivered.
    - Tool names: `generate_scope`, `approve_scope`, `run_research`, `approve_brief`, `generate_strategy`, `approve_strategy`, `upload_datasets`, `enrich_dataset`, `approve_dataset`, `run_deliverable`.
  - `ENRICH_MAX_RECORDS = 2000`. Larger datasets are approved without enrichment (the 2026-10-07 onboarding precedent).

- [ ] **Step 1: Read the getter return shapes**

Run:

```bash
$PY -c "from agent.app.core import store; import json; p=262; print(json.dumps({k: sorted((getattr(store,k)(p) or {}).keys()) for k in ('get_latest_spec','get_latest_research','get_latest_brief','get_latest_strategy','get_latest_deliverable_run')}, indent=1)); print(sorted(store.get_datasets_by_project(p)[0].keys()))"
```

Expected: key lists that include the fields named in Interfaces. If a name differs, use the printed name in Step 3 and ledger a ruling.

- [ ] **Step 2: Write the failing tests** (pure: status dicts are built directly)

```python
"""Deterministic next step from project status."""
from __future__ import annotations
from agent.app.domains.agent.status import next_step, ENRICH_MAX_RECORDS


def S(**states):
    steps = [{"key": k, "label": k, "state": states.get(k, "todo"), "detail": ""}
             for k in ("scope", "research", "brief", "strategy", "datasets", "deliverable")]
    return {"project_id": 1, "steps": steps, "datasets": states.get("_datasets", []), "run": states.get("_run")}


DONE4 = dict(scope="done", research="done", brief="done", strategy="done")


def test_fresh_project_generates_scope():
    assert next_step(S()) == "generate_scope"


def test_ready_scope_is_approved():
    assert next_step(S(scope="ready")) == "approve_scope"


def test_waiting_step_waits():
    assert next_step(S(scope="done", research="waiting")) == "wait"


def test_research_then_brief_then_strategy():
    assert next_step(S(scope="done")) == "run_research"
    assert next_step(S(scope="done", research="done", brief="ready")) == "approve_brief"
    assert next_step(S(scope="done", research="done", brief="done")) == "generate_strategy"
    assert next_step(S(scope="done", research="done", brief="done", strategy="ready")) == "approve_strategy"


def test_no_datasets_uploads():
    assert next_step(S(**DONE4)) == "upload_datasets"


def test_small_dataset_enriched_before_approval_big_one_approved_directly():
    small = {"id": 5, "processing_status": "done", "enrichment_status": None, "record_count": 200, "approval_status": "pending"}
    big = {**small, "id": 6, "record_count": ENRICH_MAX_RECORDS + 1}
    assert next_step(S(**DONE4, datasets="ready", _datasets=[small])) == "enrich_dataset"
    assert next_step(S(**DONE4, datasets="ready", _datasets=[{**small, "enrichment_status": "done"}])) == "approve_dataset"
    assert next_step(S(**DONE4, datasets="ready", _datasets=[big])) == "approve_dataset"


def test_failed_or_missing_run_reruns_and_completed_is_done():
    base = dict(DONE4, datasets="done")
    assert next_step(S(**base)) == "run_deliverable"
    assert next_step(S(**base, deliverable="failed")) == "run_deliverable"
    assert next_step(S(**base, deliverable="waiting")) == "wait"
    assert next_step(S(**base, deliverable="done")) is None
```

Run: `$PY -m pytest agent/tests/test_agent_status.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `status.py`**

```python
"""Where a project is in the pipeline, step by step, and the next step a deterministic driver would take."""
from __future__ import annotations

from ...core import store

STEP_KEYS = ("scope", "research", "brief", "strategy", "datasets", "deliverable")
LABELS = {"scope": "Scope", "research": "Background research", "brief": "Analyst brief", "strategy": "Search strategy",
          "datasets": "Datasets", "deliverable": "Deck"}
ENRICH_MAX_RECORDS = 2000
_RUNNING_JOB = ("pending", "running", "queued")
_JOB_FOR = {"scope": "spec", "research": "research", "strategy": "strategy"}
_RESEARCH_DONE = ("completed", "enriched")


def _approved(row: dict | None) -> bool:
    return bool(row) and row.get("approval_status") == "approved"


def _job_running(jobs: list[dict], step: str) -> bool:
    kind = _JOB_FOR.get(step)
    return bool(kind) and any(kind in (j.get("job_type") or "") and j.get("status") in _RUNNING_JOB for j in jobs)


def _state(row: dict | None, running: bool) -> str:
    if running:
        return "waiting"
    if _approved(row):
        return "done"
    return "ready" if row else "todo"


def _datasets_state(datasets: list[dict]) -> str:
    if not datasets:
        return "todo"
    if any(d.get("processing_status") not in ("done", "error") or d.get("enrichment_status") == "running" for d in datasets):
        return "waiting"
    usable = [d for d in datasets if d.get("processing_status") == "done"]
    if usable and all(_approved(d) for d in usable):
        return "done"
    return "ready" if usable else "failed"


def _run_state(run: dict | None) -> str:
    if not run:
        return "todo"
    return {"running": "waiting", "completed": "done", "failed": "failed"}.get(run.get("status"), "todo")


def project_status(project_id: int) -> dict:
    project = store.get_project(project_id) or {}
    jobs = store.list_jobs(project_id)
    spec, research = store.get_latest_spec(project_id), store.get_latest_research(project_id)
    brief, strategy = store.get_latest_brief(project_id), store.get_latest_strategy(project_id)
    datasets, run = store.get_datasets_by_project(project_id), store.get_latest_deliverable_run(project_id)
    research_done = bool(research) and (research.get("status") in _RESEARCH_DONE or _approved(research))
    states = {
        "scope": _state(spec, _job_running(jobs, "scope")),
        "research": "waiting" if _job_running(jobs, "research") else ("done" if research_done else "todo"),
        "brief": _state(brief, False),
        "strategy": _state(strategy, _job_running(jobs, "strategy")),
        "datasets": _datasets_state(datasets),
        "deliverable": _run_state(run),
    }
    details = {"deliverable": (run or {}).get("error") or (run or {}).get("stage") or "",
               "datasets": f"{len(datasets)} uploaded"}
    status = {"project_id": project_id, "name": project.get("name") or project.get("project_name") or "",
              "steps": [{"key": k, "label": LABELS[k], "state": states[k], "detail": details.get(k, "")} for k in STEP_KEYS],
              "datasets": datasets, "run": run}
    status["next"] = next_step(status)
    return status


def next_step(status: dict) -> str | None:
    states = {s["key"]: s["state"] for s in status["steps"]}
    for key in STEP_KEYS:
        state = states[key]
        if state == "waiting":
            return "wait"
        if state == "done":
            continue
        if key == "scope":
            return "approve_scope" if state == "ready" else "generate_scope"
        if key == "research":
            return "run_research"
        if key == "brief":
            return "approve_brief"
        if key == "strategy":
            return "approve_strategy" if state == "ready" else "generate_strategy"
        if key == "datasets":
            pending = [d for d in status["datasets"] if d.get("processing_status") == "done" and not _approved(d)]
            if not pending:
                return "upload_datasets"
            d = pending[0]
            small = (d.get("record_count") or 0) <= ENRICH_MAX_RECORDS
            return "enrich_dataset" if small and d.get("enrichment_status") not in ("done", "error") else "approve_dataset"
        return "run_deliverable"
    return None
```

- [ ] **Step 4: Run the tests, then a read-only check on real projects**

Run: `$PY -m pytest agent/tests/test_agent_status.py -q -p no:cacheprovider`
Expected: PASS (7 passed).

Run: `$PY -c "from agent.app.domains.agent.status import project_status as s; [print(p, [(x['key'], x['state']) for x in s(p)['steps']], s(p)['next']) for p in (262, 263, 264)]"`
Expected:
- 262: every step is `done` and `next` is `None`.
- 263 and 264: deliverable is `failed` and `next` is `run_deliverable`.

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/agent/status.py
git commit -m "feat(agent): project status and deterministic next step"
```

### Task 6: In-process API client and the tool registry

**Files:**
- Modify: `agent/app/core/config.py`. Add after `DELIVERABLE_DIR`:
  - `REPO_ROOT = AGENT_DIR.parent`
  - `AGENT_INPUT_ROOTS = [Path(p) for p in (os.getenv("HUNTER_AGENT_INPUT_ROOTS") or str(AGENT_DIR.parent)).split(";") if p]`
- Create:
  - `agent/app/domains/agent/api_client.py`
  - `agent/app/domains/agent/tools.py`
- Test: `agent/tests/test_agent_tools.py`

**Interfaces:**
- Consumes:
  - Task 3: `memory.record`, `memory.remember`.
  - Task 5: `status.project_status`.
  - Existing:
    - `store.create_session(user_id) -> (token, expires_at)`
    - `store.delete_session(token)`
    - `store.get_user_by_id`
    - `core.auth.SESSION_COOKIE_NAME`
    - `store.get_dataset_by_id`
    - `store.get_deliverable_run`
    - `store.get_latest_deliverable_run`
    - `deliverable.engine.run_payload`
- Produces:
  - `api_client.ToolError(RuntimeError)`, re-exported by `tools`.
  - `api_client.ApiClient(user_id: int)`:
    - `.call(method: str, path: str, **kw) -> dict`. `path` is under `/api/intel`. A status of 400 or more raises `ToolError`.
    - `.wait_job(job_id: str, timeout: float) -> dict`
    - `.close()`
  - `tools.ToolContext(project_id: int, user_id: int, actor: str, api, llm=None)`, a dataclass.
  - `tools.Tool(name, description, parameters: dict, handler, costly: bool = False)`, a frozen dataclass.
  - `tools.TOOLS: dict[str, Tool]`, and `tools.register(tool) -> None` (used again by Tasks 8, 12 and 13).
  - `tools.tool_specs(names: list[str] | None = None) -> list[dict]`, in OpenAI `{"type": "function", "function": {...}}` format.
  - `tools.run_tool(ctx, name: str, args: dict) -> dict`.
    - Always returns a dict with `ok: bool`.
    - Records exactly one `agent_events` row.
  - `tools.list_input_files(folder: str) -> list[str]`. Raises `ToolError` outside `config.AGENT_INPUT_ROOTS`.
  - `tools.suggest_mapping(files: list[str], rqs: list[dict]) -> dict[str, list[str]]`.
  - `tools.MANUAL_GATES_KEY = "manual_gates"`. This `preference` memory key holds a list of step keys the autopilot must leave to a human.

- [ ] **Step 1: Write the failing tests**

```python
"""Agent tools: registry shape, safety, auth via a real session, events recorded."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.core import config, store
from agent.app.domains.agent import memory, tools
from agent.app.domains.agent.api_client import ApiClient


def setup_module(_):
    store.init_intelligence_db()


def _user():
    from agent.app.core.auth import seed_super_admin_if_missing
    seed_super_admin_if_missing()
    return next(u["id"] for u in store.list_users() if u["role"] == "super_admin")


def test_no_destructive_tools():
    assert not [n for n in tools.TOOLS if any(w in n for w in ("delete", "remove", "drop", "archive"))]


def test_specs_are_openai_functions():
    specs = tools.tool_specs()
    assert all(s["type"] == "function" and s["function"]["name"] in tools.TOOLS for s in specs)
    assert all(s["function"]["parameters"]["type"] == "object" for s in specs)


def test_input_files_restricted_to_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "Client"
    allowed.mkdir()
    (allowed / "a.csv").write_text("URL\n")
    (allowed / "notes.txt").write_text("x")
    monkeypatch.setattr(config, "AGENT_INPUT_ROOTS", [tmp_path])
    assert tools.list_input_files(str(allowed)) == [str(allowed / "a.csv")]
    with pytest.raises(tools.ToolError):
        tools.list_input_files("C:/Windows")
    with pytest.raises(tools.ToolError):
        tools.list_input_files(str(allowed / ".." / ".."))


def test_suggest_mapping_covers_every_file():
    rqs = [{"id": "RQ1", "question": "Which soccer injuries dominate?"},
           {"id": "RQ2", "question": "How do running brands talk about care?"}]
    m = tools.suggest_mapping(["D:/x/Band_Aid_Soccer.csv", "D:/x/Running.xlsx", "D:/x/Overall.csv"], rqs)
    assert m == {"D:/x/Band_Aid_Soccer.csv": ["RQ1"], "D:/x/Running.xlsx": ["RQ2"], "D:/x/Overall.csv": ["RQ1"]}


def test_api_client_uses_real_session_and_enforces_auth():
    uid = _user()
    api = ApiClient(uid)
    try:
        pid = store.get_or_create_project({"commissioning_brand": {"name": "Tool Auth Co"}})
        assert api.call("GET", f"/projects/{pid}")["id"] == pid
    finally:
        api.close()
    with pytest.raises(tools.ToolError):
        ApiClient(999999)        # no such user: never builds an unauthenticated client


def test_run_tool_records_event_and_reports_errors():
    uid = _user()
    pid = store.get_or_create_project({"commissioning_brand": {"name": "Tool Event Co"}})
    ctx = tools.ToolContext(project_id=pid, user_id=uid, actor="copilot", api=ApiClient(uid))
    ok = tools.run_tool(ctx, "project_status", {})
    bad = tools.run_tool(ctx, "no_such_tool", {})
    ctx.api.close()
    assert ok["ok"] and ok["result"]["project_id"] == pid
    assert not bad["ok"] and "unknown tool" in bad["error"]
    assert [e["action"] for e in store.list_agent_events(pid)][:2] == ["no_such_tool", "project_status"]


def test_manual_gate_blocks_approval():
    uid = _user()
    pid = store.get_or_create_project({"commissioning_brand": {"name": "Gate Co"}})
    memory.remember(pid, "preference", tools.MANUAL_GATES_KEY, ["scope"])
    ctx = tools.ToolContext(project_id=pid, user_id=uid, actor="autopilot", api=None)
    assert tools.run_tool(ctx, "approve_scope", {}) == {
        "ok": False, "needs_human": True, "error": "scope approval is kept manual for this project"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_agent_tools.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError` (no `tools`/`api_client`).

- [ ] **Step 3: Check the helper names this task imports**

Run: `$PY -c "from agent.app.core import store; from agent.app.core.auth import SESSION_COOKIE_NAME; from agent.app.core.api import get_app_settings; [getattr(store, n) for n in ('get_user_by_id','create_session','delete_session','get_dataset_by_id','get_deliverable_run','list_users','get_or_create_project','list_jobs')]; print('ok')"`
Expected: `ok`.

If an import fails, find the real name with `grep -rn "def <name>" agent/app` and use it in Steps 4–5. Record that as a ledger ruling.

- [ ] **Step 4: Write `api_client.py`**

```python
"""The app's own /api/intel routes, called in-process as a real user. Stage logic lives in the routers, so the agent
goes through them: the same validation and the same project access checks as the UI (Ruling R1)."""
from __future__ import annotations

import time

from ...core import store
from ...core.auth import SESSION_COOKIE_NAME

JOB_POLL_SECONDS = 3
_DONE = ("completed", "failed", "cancelled")


class ToolError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, user_id: int):
        if not store.get_user_by_id(user_id):
            raise ToolError(f"user {user_id} does not exist")
        from fastapi.testclient import TestClient
        from ...core.api import get_app_settings
        from ...main import app                   # lazy: main imports the domains package
        token, _expires = store.create_session(user_id)
        self._token = token
        self._client = TestClient(app, raise_server_exceptions=False)
        self._client.cookies.set(SESSION_COOKIE_NAME, token)
        key = get_app_settings().api_key
        self._headers = {"X-API-Key": key} if key else {}

    def call(self, method: str, path: str, **kw) -> dict:
        r = self._client.request(method, "/api/intel" + path, headers=self._headers, **kw)
        if r.status_code >= 400:
            raise ToolError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def wait_job(self, job_id: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.call("GET", f"/job/{job_id}")
            if job.get("status") in _DONE:
                return job
            time.sleep(JOB_POLL_SECONDS)
        raise ToolError(f"job {job_id} still running after {int(timeout)}s")

    def close(self) -> None:
        store.delete_session(self._token)
        self._client.close()
```

- [ ] **Step 5: Write `tools.py`**

```python
"""Typed tools the autopilot and copilot call. Writes go through the app's routes (ApiClient); reads come from the
store. Every call records one agent_events row. Nothing here deletes anything."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...core import config, store
from . import memory
from .api_client import ApiClient, ToolError  # noqa: F401  (ToolError re-exported)
from .status import project_status

logger = logging.getLogger(__name__)
MANUAL_GATES_KEY = "manual_gates"
INPUT_SUFFIXES = (".csv", ".xlsx", ".xls", ".docx", ".pdf")
DATASET_SUFFIXES = (".csv", ".xlsx", ".xls")
JOB_TIMEOUT = 1800
RUN_TIMEOUT = 5400
RUN_POLL_SECONDS = 10
_WORD = re.compile(r"[a-z]{4,}")
_CONTENT_TYPES = {".csv": "text/csv", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  ".xls": "application/vnd.ms-excel"}
_NO_ARGS = {"type": "object", "properties": {}}
_STR = {"type": "string"}


@dataclass
class ToolContext:
    project_id: int
    user_id: int
    actor: str
    api: object
    llm: object = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], dict]
    costly: bool = False


TOOLS: dict[str, Tool] = {}


class _NeedsHuman(RuntimeError):
    pass


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


def tool_specs(names: list[str] | None = None) -> list[dict]:
    chosen = [TOOLS[n] for n in names] if names else list(TOOLS.values())
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in chosen]


def _short(args: dict | None) -> dict:
    return {k: (v if len(str(v)) < 200 else str(v)[:200] + "…") for k, v in (args or {}).items()}


def run_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    started = time.time()
    tool = TOOLS.get(name)
    try:
        if tool is None:
            raise ToolError(f"unknown tool {name!r}")
        out = {"ok": True, "result": tool.handler(ctx, args or {})}
    except _NeedsHuman as e:
        out = {"ok": False, "needs_human": True, "error": str(e)}
    except Exception as e:      # a failed tool is reported to the model, never raised into the loop
        logger.warning("tool %s failed: %s", name, e)
        out = {"ok": False, "error": str(e)[:500]}
    memory.record(ctx.project_id, ctx.actor, name, {"args": _short(args), "ok": out["ok"], "error": out.get("error"),
                                                   "seconds": round(time.time() - started, 1)})
    return out


def _gate(ctx: ToolContext, step: str) -> None:
    gates = next((m["value"] for m in store.list_memory(ctx.project_id, "preference") if m["key"] == MANUAL_GATES_KEY), [])
    if ctx.actor == "autopilot" and step in (gates or []):
        raise _NeedsHuman(f"{step} approval is kept manual for this project")


def _reviewer(ctx: ToolContext) -> str:
    return f"hunter-agent:{ctx.user_id}"


def _job(ctx: ToolContext, started: dict) -> dict:
    job = ctx.api.wait_job(started["job_id"], JOB_TIMEOUT)
    if job["status"] != "completed":
        raise ToolError(f"job {job['status']}: {job.get('error') or ''}"[:300])
    return job.get("result") or {}


# ── inputs ────────────────────────────────────────────────────────────────────────────────────────────────────────
def list_input_files(folder: str) -> list[str]:
    target = Path(folder).resolve()
    if not any(target == r.resolve() or r.resolve() in target.parents for r in config.AGENT_INPUT_ROOTS):
        raise ToolError(f"{folder} is outside the allowed input folders")
    if not target.is_dir():
        raise ToolError(f"{folder} is not a folder")
    return sorted(str(p) for p in target.iterdir() if p.is_file() and p.suffix.lower() in INPUT_SUFFIXES)


def suggest_mapping(files: list[str], rqs: list[dict]) -> dict[str, list[str]]:
    """Each dataset to the research question whose words its file name shares most; no overlap goes to the first
    question (an 'overall' export usually serves the headline question)."""
    words = {q["id"]: set(_WORD.findall((q.get("question") or "").lower())) for q in rqs}
    out = {}
    for f in files:
        stem = set(_WORD.findall(Path(f).stem.lower().replace("_", " ").replace("-", " ")))
        best = max(rqs, key=lambda q: len(stem & words[q["id"]]))
        out[f] = [best["id"] if stem & words[best["id"]] else rqs[0]["id"]]
    return out


def _strategy_questions(ctx) -> list[dict]:
    s = ctx.api.call("GET", f"/strategy/{ctx.project_id}")
    return [{"id": q.get("question_id"), "question": q.get("question")}
            for q in s["strategy"].get("research_question_queries") or []]


# ── handlers ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _status(ctx, _args):
    s = project_status(ctx.project_id)
    keep = ("id", "file_name", "record_count", "processing_status", "enrichment_status", "approval_status")
    return {**s, "datasets": [{k: d.get(k) for k in keep} for d in s["datasets"]]}


def _generate_scope(ctx, _args):
    project = ctx.api.call("GET", f"/projects/{ctx.project_id}")
    brief = (project.get("spec") or {}).get("raw_brief") or ""
    if not brief:
        raise ToolError("the project has no brief text")
    started = ctx.api.call("POST", "/spec/generate", json={"project_id": ctx.project_id, "raw_brief_text": brief,
                                                           "use_llm": True})
    return {"spec_id": _job(ctx, started).get("spec_id")}


def _approve_scope(ctx, _args):
    _gate(ctx, "scope")
    spec = store.get_latest_spec(ctx.project_id) or {}
    if not spec:
        raise ToolError("no scope to approve")
    ready = ctx.api.call("GET", f"/spec/{spec['id']}/readiness")
    if ready.get("blocking_issues"):
        raise _NeedsHuman(f"scope has blocking issues: {ready['blocking_issues']}")
    return ctx.api.call("POST", f"/spec/{spec['id']}/approve", json={"reviewer": _reviewer(ctx)})


def _run_research(ctx, _args):
    project = ctx.api.call("GET", f"/projects/{ctx.project_id}")
    _job(ctx, ctx.api.call("POST", "/research/start", json={"spec": project["spec"], "project_id": ctx.project_id}))
    return {"research": "completed"}


def _approve_brief(ctx, _args):
    _gate(ctx, "brief")
    made = ctx.api.call("POST", "/brief/generate", json={"project_id": ctx.project_id})
    ctx.api.call("POST", f"/brief/{made['brief_id']}/approve", json={"reviewer": _reviewer(ctx)})
    return {"brief_id": made["brief_id"]}


def _generate_strategy(ctx, _args):
    _job(ctx, ctx.api.call("POST", "/strategy/generate", json={"project_id": ctx.project_id}))
    return {"questions": _strategy_questions(ctx)}


def _approve_strategy(ctx, _args):
    _gate(ctx, "strategy")
    strategy = store.get_latest_strategy(ctx.project_id) or {}
    if not strategy:
        raise ToolError("no strategy to approve")
    return ctx.api.call("POST", f"/strategy/{strategy['id']}/approve", json={"reviewer": _reviewer(ctx)})


def _list_inputs(ctx, args):
    folder = args.get("folder") or next((m["value"] for m in store.list_memory(ctx.project_id, "fact")
                                         if m["key"] == "input_folder"), "")
    return {"folder": folder, "files": list_input_files(folder)}


def _upload_datasets(ctx, args):
    listing = _list_inputs(ctx, args)
    files = [f for f in listing["files"] if Path(f).suffix.lower() in DATASET_SUFFIXES]
    if not files:
        raise ToolError(f"no dataset files in {listing['folder']}")
    mapping = args.get("mapping") or suggest_mapping(files, _strategy_questions(ctx))
    uploaded = []
    for f, rq_ids in mapping.items():
        if f not in files:
            raise ToolError(f"{f} is not one of the input files")
        for rq in rq_ids:
            with open(f, "rb") as fh:
                r = ctx.api.call("POST", f"/dataset/upload?project_id={ctx.project_id}&research_question_id={rq}",
                                 files={"file": (Path(f).name, fh, _CONTENT_TYPES[Path(f).suffix.lower()])})
            uploaded.append({"file": Path(f).name, "rq": rq, "dataset_id": r["dataset_id"]})
    memory.remember(ctx.project_id, "decision", "dataset_mapping", {Path(f).name: v for f, v in mapping.items()})
    return {"uploaded": uploaded}


def _pending_dataset(ctx, args) -> int:
    if args.get("dataset_id"):
        return int(args["dataset_id"])
    pending = [d for d in store.get_datasets_by_project(ctx.project_id)
               if d.get("processing_status") == "done" and d.get("approval_status") != "approved"]
    if not pending:
        raise ToolError("no dataset is waiting for approval")
    return pending[0]["id"]


def _enrich_dataset(ctx, args):
    did = _pending_dataset(ctx, args)
    ctx.api.call("POST", f"/dataset/{did}/enrich")
    deadline = time.time() + JOB_TIMEOUT
    while time.time() < deadline:
        d = store.get_dataset_by_id(did)
        if d.get("enrichment_status") in ("done", "error"):
            return {"dataset_id": did, "enrichment_status": d["enrichment_status"]}
        time.sleep(RUN_POLL_SECONDS)
    raise ToolError(f"dataset {did} enrichment still running")


def _approve_dataset(ctx, args):
    _gate(ctx, "datasets")
    did = _pending_dataset(ctx, args)
    ctx.api.call("POST", f"/dataset/{did}/approve")
    return {"dataset_id": did}


def run_summary(run_id: int) -> dict:
    from ..deliverable.engine import run_payload
    payload = run_payload(run_id)
    run, sections = payload["run"], {s["id"]: s for s in payload["sections"]}
    studio = sections.get("studio") or {}
    log = (sections.get("log") or {}).get("lines") or []
    return {"run_id": run_id, "status": run["status"], "stage": run.get("stage"), "error": run.get("error"),
            "scorecard": studio.get("scorecard"), "checklist": studio.get("checklist"),
            "qc": [ln["message"] for ln in log if ln["message"].startswith("QC flag")][-20:],
            "log_tail": [ln["message"] for ln in log][-25:]}


def _run_deliverable(ctx, _args):
    run_id = ctx.api.call("POST", f"/deliverable/{ctx.project_id}/run", json={})["run_id"]
    deadline = time.time() + RUN_TIMEOUT
    while time.time() < deadline:
        if (store.get_deliverable_run(run_id) or {}).get("status") in ("completed", "failed"):
            return run_summary(run_id)
        time.sleep(RUN_POLL_SECONDS)
    raise ToolError(f"deliverable run {run_id} still running")


def _read_run(ctx, args):
    run = store.get_deliverable_run(int(args["run_id"])) if args.get("run_id") else store.get_latest_deliverable_run(ctx.project_id)
    if not run or run.get("project_id") != ctx.project_id:
        raise ToolError("no deliverable run for this project")
    return run_summary(run["id"])


def _remember(ctx, args):
    memory.remember(ctx.project_id, args["kind"], args["key"], args["value"])
    return {"saved": args["key"]}


for _tool in (
    Tool("project_status", "Where the project is: each pipeline step's state and the suggested next step.", _NO_ARGS, _status),
    Tool("generate_scope", "Generate the research scope from the project's brief (LLM, ~2 min).", _NO_ARGS,
         _generate_scope, costly=True),
    Tool("approve_scope", "Approve the latest scope when it has no blocking issues.", _NO_ARGS, _approve_scope),
    Tool("run_research", "Run background research for the project (~5-10 min).", _NO_ARGS, _run_research, costly=True),
    Tool("approve_brief", "Generate and approve the analyst brief (also approves background research).", _NO_ARGS,
         _approve_brief),
    Tool("generate_strategy", "Generate the search strategy and research questions (~5 min).", _NO_ARGS,
         _generate_strategy, costly=True),
    Tool("approve_strategy", "Approve the latest search strategy.", _NO_ARGS, _approve_strategy),
    Tool("list_input_files", "List the client's input files (brief, Meltwater exports) in the project's input folder.",
         {"type": "object", "properties": {"folder": _STR}}, _list_inputs),
    Tool("upload_datasets", "Upload the input folder's dataset files, each to the research questions it serves. "
         "mapping: {file path: [question ids]}; omitted means match by file name.",
         {"type": "object", "properties": {"folder": _STR, "mapping": {
             "type": "object", "additionalProperties": {"type": "array", "items": _STR}}}}, _upload_datasets, costly=True),
    Tool("enrich_dataset", "Enrich a parsed dataset with the LLM (small datasets only).",
         {"type": "object", "properties": {"dataset_id": {"type": "integer"}}}, _enrich_dataset, costly=True),
    Tool("approve_dataset", "Approve a parsed dataset.",
         {"type": "object", "properties": {"dataset_id": {"type": "integer"}}}, _approve_dataset),
    Tool("run_deliverable", "Build the deliverable: analyses, insights and the deck (~6-30 min).", _NO_ARGS,
         _run_deliverable, costly=True),
    Tool("read_run", "Read a deliverable run: status, error, scorecard, brief checklist, QC flags, log tail.",
         {"type": "object", "properties": {"run_id": {"type": "integer"}}}, _read_run),
    Tool("remember", "Save a project preference, decision, fact or fix to memory.",
         {"type": "object", "required": ["kind", "key", "value"], "properties": {
             "kind": {"type": "string", "enum": list(memory.MEMORY_KINDS)}, "key": _STR, "value": {}}}, _remember),
):
    register(_tool)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_tools.py -q -p no:cacheprovider`
Expected: PASS (7 passed).

- [ ] **Step 7: Commit**

```bash
git add agent/app/core/config.py agent/app/domains/agent/api_client.py agent/app/domains/agent/tools.py
git commit -m "feat(agent): authenticated in-process API client and pipeline tools"
```

### Task 7: Autopilot loop, resume, router and health route

**Files:**
- Create:
  - `agent/app/domains/agent/autopilot.py`
  - `agent/app/domains/agent/router.py`
  - `agent/app/domains/agent/schemas.py`
- Modify: `agent/app/domains/__init__.py`. Import `from .agent.router import router as agent_router` and append `agent_router` to the include tuple.
- Modify: `agent/app/main.py`:
  - `GET /api/health` in `create_app`, unauthenticated;
  - in `lifespan`, `autopilot.resume_all()` after `events.bind_loop(...)`.
- Test: `agent/tests/test_agent_autopilot.py`

**Interfaces:**
- Consumes:
  - Task 3: `memory.context`, `memory.remember`, `memory.record`.
  - Task 4: `llm.chat_tools`.
  - Task 5: `status.project_status`, `status.next_step`.
  - Task 6: `tools.TOOLS`, `tools.run_tool`, `tools.tool_specs`, `tools.ToolContext`, `ApiClient`, `ToolError`.
- Produces:
  - `autopilot.MAX_STEPS = 60`, `MAX_FAILURES_PER_STEP = 3`, `WAIT_SECONDS = 20`
  - `autopilot.decide(project_id: int, llm, status: dict) -> tuple[str, dict, str]`, meaning (tool name, args, why).
  - `autopilot.drive(project_id: int, user_id: int, llm=None, sleep=time.sleep) -> str`. Returns `"done" | "blocked" | "stopped"`.
  - `autopilot.start(project_id: int, user_id: int, input_folder: str | None = None) -> dict`
  - `autopilot.stop(project_id: int) -> None`
  - `autopilot.resume_all() -> list[int]`
  - `autopilot._llm()`, the shared LLM factory.
  - Routes under `/api/intel`, guarded by `require_project_access`:
    - `GET /agent/{project_id}` returns `{"autopilot", "status"}`.
    - `POST /agent/{project_id}/autopilot/start` takes `{"input_folder"}`.
    - `POST /agent/{project_id}/autopilot/stop`.
    - `GET /agent/{project_id}/events?limit=&after_id=`.
    - `GET /agent/{project_id}/memory`.
  - `GET /api/health` returns `{"ok": true}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Autopilot: deterministic progress without an LLM, LLM tool choice when available, resume after restart."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.core import store
from agent.app.domains.agent import autopilot, status as status_mod

ORDER = ["scope", "research", "brief", "strategy", "datasets", "deliverable"]
# what each tool does to the fake pipeline: (step, new state)
EFFECT = {"generate_scope": ("scope", "ready"), "approve_scope": ("scope", "done"), "run_research": ("research", "done"),
          "approve_brief": ("brief", "done"), "generate_strategy": ("strategy", "ready"),
          "approve_strategy": ("strategy", "done"), "approve_dataset": ("datasets", "done"),
          "run_deliverable": ("deliverable", "done")}


def setup_module(_):
    store.init_intelligence_db()


class Pipeline:
    """A fake pipeline whose status follows the tools the autopilot runs."""
    def __init__(self, monkeypatch, cancel_once=None):
        self.states, self.calls, self.cancel_once = {k: "todo" for k in ORDER}, [], cancel_once
        monkeypatch.setattr(autopilot, "project_status", self.status)
        monkeypatch.setattr(autopilot, "run_tool", self.run)
        monkeypatch.setattr(autopilot, "_api", lambda uid: None)

    def status(self, pid):
        approved = "approved" if self.states["datasets"] == "done" else "pending"
        s = {"project_id": pid, "steps": [{"key": k, "label": k, "state": self.states[k], "detail": ""} for k in ORDER],
             "datasets": [{"id": 1, "processing_status": "done", "enrichment_status": "done", "record_count": 5,
                           "approval_status": approved}], "run": None}
        s["next"] = status_mod.next_step(s)
        return s

    def run(self, ctx, name, args):
        self.calls.append(name)
        if name == self.cancel_once:
            self.cancel_once = None
            return {"ok": False, "error": "job cancelled: stale running job from prior session"}
        step, state = EFFECT.get(name, (None, None))
        if step:
            self.states[step] = state
        return {"ok": True, "result": {}}


def _pid(name):
    return store.get_or_create_project({"commissioning_brand": {"name": name}})


def test_autopilot_progresses_without_llm(monkeypatch):
    p = Pipeline(monkeypatch)
    pid = _pid("Autopilot NoLLM")
    assert autopilot.drive(pid, 1, llm=None, sleep=lambda _s: None) == "done"
    assert p.calls == ["generate_scope", "approve_scope", "run_research", "approve_brief", "generate_strategy",
                       "approve_strategy", "approve_dataset", "run_deliverable"]
    assert store.get_autopilot(pid)["status"] == "done"


def test_resume_reruns_cancelled_step(monkeypatch):
    p = Pipeline(monkeypatch, cancel_once="run_research")
    assert autopilot.drive(_pid("Autopilot Resume"), 1, llm=None, sleep=lambda _s: None) == "done"
    assert p.calls.count("run_research") == 2


def test_repeated_failure_blocks(monkeypatch):
    Pipeline(monkeypatch)
    monkeypatch.setattr(autopilot, "run_tool", lambda ctx, name, args: {"ok": False, "error": "boom"})
    pid = _pid("Autopilot Blocked")
    assert autopilot.drive(pid, 1, llm=None, sleep=lambda _s: None) == "blocked"
    ap = store.get_autopilot(pid)
    assert ap["status"] == "blocked" and "generate_scope" in ap["note"] and "boom" in ap["note"]


class ToolLLM:
    def __init__(self, name): self.name = name
    def is_reachable(self): return True
    def chat_tools(self, messages, tools, tool_choice="auto"):
        assert any("Project memory" in m["content"] for m in messages if m["role"] == "user")
        return {"content": "because", "tool_calls": [{"id": "1", "name": self.name, "arguments": {}}], "message": {}}


def test_decide_uses_llm_choice_and_falls_back_on_unknown_tool():
    st = {"project_id": 1, "steps": [{"key": k, "label": k, "state": "todo", "detail": ""} for k in ORDER],
          "datasets": [], "run": None, "next": "generate_scope"}
    assert autopilot.decide(1, ToolLLM("read_run"), st)[0] == "read_run"
    assert autopilot.decide(1, ToolLLM("delete_everything"), st)[0] == "generate_scope"


def test_resume_all_restarts_running_autopilots(monkeypatch):
    started = []
    monkeypatch.setattr(autopilot, "_spawn", lambda pid, uid: started.append(pid))
    pid = _pid("Autopilot Restart")
    store.upsert_autopilot(pid, 1, "running", "step 3")
    assert pid in autopilot.resume_all() and pid in started


def test_routes_and_health(monkeypatch):
    from fastapi.testclient import TestClient
    from agent.app.core.auth import get_current_user, require_project_access
    from agent.app.main import app
    admin = {"id": 1, "role": "super_admin", "org_id": None}
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_project_access] = lambda: admin
    monkeypatch.setattr(autopilot, "_spawn", lambda pid, uid: None)
    try:
        c = TestClient(app)
        pid = _pid("Autopilot Routes")
        assert c.get("/api/health").json() == {"ok": True}
        assert c.post(f"/api/intel/agent/{pid}/autopilot/start", json={}).json()["status"] == "running"
        assert c.get(f"/api/intel/agent/{pid}").json()["autopilot"]["status"] == "running"
        assert c.get(f"/api/intel/agent/{pid}/events").json()[0]["action"] == "start"
        assert c.post(f"/api/intel/agent/{pid}/autopilot/start", json={"input_folder": "C:/Windows"}).status_code == 400
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_agent_autopilot.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'autopilot'`.

- [ ] **Step 3: Write `autopilot.py`**

```python
"""The autopilot: drives one project from brief to delivered deck. Each turn reads status + memory, picks the next
tool (Azure OpenAI tool calling, or the deterministic next step), runs it and records it. State lives in the database,
so a restart resumes the loop (resume_all at startup)."""
from __future__ import annotations

import logging
import threading
import time

from ...core import store
from . import memory
from .api_client import ApiClient
from .status import project_status
from .tools import TOOLS, ToolContext, list_input_files, run_tool, tool_specs

logger = logging.getLogger(__name__)
MAX_STEPS = 60
MAX_FAILURES_PER_STEP = 3
WAIT_SECONDS = 20
_worker = threading.Semaphore(1)          # one project at a time per worker (spec 3.3)
_stop: set[int] = set()
_SYSTEM = ("You are Hunter's autopilot. You move a research project from client brief to delivered deck by calling one "
           "tool per turn. Prefer the suggested next step unless memory says the user wants something else. Never "
           "approve a step whose state is not 'ready'. If a step failed, read why (read_run) before retrying.")


def _api(user_id: int):
    return ApiClient(user_id)


def _llm():
    try:
        from ...core.anthropic_client import get_llm_client
        return get_llm_client()
    except Exception as e:
        logger.warning("autopilot runs deterministically: %s", type(e).__name__)
        return None


def decide(project_id: int, llm, status: dict) -> tuple[str, dict, str]:
    fallback = status["next"] or "wait"
    if llm is None or not getattr(llm, "is_reachable", lambda: False)() or fallback == "wait":
        return fallback, {}, "deterministic next step"
    steps = "\n".join(f"- {s['label']}: {s['state']} {s['detail']}".rstrip() for s in status["steps"])
    prompt = (f"{memory.context(project_id, llm)}\n\nPipeline:\n{steps}\nSuggested next step: {fallback}\n"
              "Call exactly one tool.")
    try:
        reply = llm.chat_tools([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}], tool_specs())
        call = (reply.get("tool_calls") or [None])[0]
        if call and call["name"] in TOOLS and "_raw" not in call["arguments"]:
            return call["name"], call["arguments"], (reply.get("content") or "model choice")[:200]
    except Exception as e:      # an LLM failure never stops the project: take the deterministic step
        logger.warning("autopilot decision fell back: %s", type(e).__name__)
    return fallback, {}, "deterministic next step (model unavailable or chose an unknown tool)"


def drive(project_id: int, user_id: int, llm=None, sleep=time.sleep) -> str:
    failures: dict[str, int] = {}
    api = _api(user_id)
    ctx = ToolContext(project_id=project_id, user_id=user_id, actor="autopilot", api=api, llm=llm)
    try:
        for n in range(1, MAX_STEPS + 1):
            if project_id in _stop:
                _stop.discard(project_id)
                store.upsert_autopilot(project_id, user_id, "stopped", "stopped by user")
                return "stopped"
            status = project_status(project_id)
            if status["next"] is None:
                store.upsert_autopilot(project_id, user_id, "done", "deck delivered")
                memory.record(project_id, "autopilot", "done", {"steps": n - 1})
                return "done"
            name, args, why = decide(project_id, llm, status)
            store.upsert_autopilot(project_id, user_id, "running", f"step {n}: {name}")
            if name == "wait":
                sleep(WAIT_SECONDS)
                continue
            out = run_tool(ctx, name, args)
            if out.get("needs_human"):
                store.upsert_autopilot(project_id, user_id, "blocked", f"{name}: {out['error']}")
                return "blocked"
            if out["ok"]:
                failures.pop(name, None)
                memory.remember(project_id, "decision", f"step_{n}", {"tool": name, "why": why})
                continue
            failures[name] = failures.get(name, 0) + 1
            if failures[name] >= MAX_FAILURES_PER_STEP:
                note = f"{name} failed {failures[name]} times: {out['error']}"[:500]
                store.upsert_autopilot(project_id, user_id, "blocked", note)
                memory.remember(project_id, "fix", f"blocked_{name}", {"error": out["error"]})
                return "blocked"
        store.upsert_autopilot(project_id, user_id, "blocked", f"no delivery after {MAX_STEPS} steps")
        return "blocked"
    finally:
        if api is not None:
            api.close()


def _run(project_id: int, user_id: int) -> None:
    with _worker:
        try:
            drive(project_id, user_id, llm=_llm())
        except Exception as e:      # a crash is recorded so the UI shows it; the thread never dies silently
            logger.exception("autopilot crashed for project %s", project_id)
            store.upsert_autopilot(project_id, user_id, "blocked", f"autopilot error: {e}"[:500])


def _spawn(project_id: int, user_id: int) -> None:
    threading.Thread(target=_run, args=(project_id, user_id), daemon=True, name=f"autopilot-{project_id}").start()


def start(project_id: int, user_id: int, input_folder: str | None = None) -> dict:
    if input_folder:
        list_input_files(input_folder)               # raises ToolError outside the allowed roots
        memory.remember(project_id, "fact", "input_folder", input_folder)
    _stop.discard(project_id)
    store.upsert_autopilot(project_id, user_id, "running", "starting", attempts=0)
    memory.record(project_id, "autopilot", "start", {"input_folder": input_folder})
    _spawn(project_id, user_id)
    return store.get_autopilot(project_id)


def stop(project_id: int) -> None:
    _stop.add(project_id)


def resume_all() -> list[int]:
    resumed = []
    for ap in store.list_autopilots("running"):
        memory.record(ap["project_id"], "autopilot", "resume", {"after": ap["note"]})
        _spawn(ap["project_id"], ap["user_id"])
        resumed.append(ap["project_id"])
    return resumed
```

- [ ] **Step 4: Write `schemas.py` and `router.py`**

```python
"""Request bodies for the agent routes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AutopilotStart(BaseModel):
    input_folder: str | None = Field(default=None, max_length=500)


class CopilotMessage(BaseModel):
    message: str = Field(default="", max_length=4000)
    confirm: str | None = Field(default=None, max_length=64)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
```

```python
"""Agent routes: autopilot control, activity, memory, the copilot, and (super admin) issues and fixes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...core import store
from ...core.auth import get_current_user, require_project_access
from . import autopilot
from .api_client import ToolError
from .schemas import AutopilotStart
from .status import project_status

router = APIRouter()
ProjectId = Annotated[int, Path(ge=1)]


@router.get("/agent/{project_id}")
def agent_state(project_id: ProjectId, _u=Depends(require_project_access)):
    s = project_status(project_id)
    return {"autopilot": store.get_autopilot(project_id),
            "status": {k: s[k] for k in ("project_id", "name", "steps", "next")}}


@router.post("/agent/{project_id}/autopilot/start")
def autopilot_start(project_id: ProjectId, body: AutopilotStart, user=Depends(get_current_user),
                    _u=Depends(require_project_access)):
    try:
        return autopilot.start(project_id, user["id"], body.input_folder)
    except ToolError as e:
        raise HTTPException(400, str(e))


@router.post("/agent/{project_id}/autopilot/stop")
def autopilot_stop(project_id: ProjectId, _u=Depends(require_project_access)):
    autopilot.stop(project_id)
    return {"ok": True}


@router.get("/agent/{project_id}/events")
def agent_events(project_id: ProjectId, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                 after_id: Annotated[int, Query(ge=0)] = 0, _u=Depends(require_project_access)):
    return store.list_agent_events(project_id, limit=limit, after_id=after_id)


@router.get("/agent/{project_id}/memory")
def agent_memory(project_id: ProjectId, _u=Depends(require_project_access)):
    return [m for m in store.list_memory(project_id) if m["kind"] != "pending"]
```

- [ ] **Step 5: Wire the router, health and resume**

In `domains/__init__.py`, add `from .agent.router import router as agent_router` and change the tuple's last line to `datasources, deliverable, agent_router,`.

In `main.py`, inside `create_app()` before `_mount_spa(app)`:

```python
    @app.get("/api/health", include_in_schema=False)
    def health():
        conn = store._conn()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return {"ok": True}
```

In `lifespan`, after `events.bind_loop(asyncio.get_running_loop())`:

```python
    from .domains.agent import autopilot
    autopilot.resume_all()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_autopilot.py agent/tests/test_agent_tools.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/agent/autopilot.py agent/app/domains/agent/router.py agent/app/domains/agent/schemas.py agent/app/domains/__init__.py agent/app/main.py
git commit -m "feat(agent): resumable autopilot with Azure tool choice and deterministic fallback; health route"
```

### Task 8: Copilot

**Files:**
- Create: `agent/app/domains/agent/copilot.py`
- Modify: `agent/app/domains/agent/router.py`. Add `POST /agent/{project_id}/copilot`.
- Modify: `agent/app/domains/agent/tools.py`. Register `report_issue`. It is memory-backed here and switched to the issue table in Task 13 Step 5.
- Test: `agent/tests/test_agent_copilot.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 6 and 7 (`autopilot._llm`).
- Produces:
  - `copilot.MAX_TOOL_TURNS = 4` and `PENDING_TTL = 1800`.
  - `copilot.reply(project_id: int, user_id: int, message: str, llm, confirm: str | None = None, api=None) -> dict`
    - Returns `{"reply": str, "actions": [{"tool", "ok", "error"?}], "pending": {"id", "tool", "args", "summary"} | None}`.
  - Pending actions are stored as memory kind `"pending"`, with the id as the key.
  - Chat text is never stored. Events `copilot_message` and `copilot_reply` carry `{"chars": n}` only.

- [ ] **Step 1: Write the failing tests**

```python
"""Copilot: answers from tools, confirms costly actions, cannot delete, degrades without an LLM."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.core import store
from agent.app.domains.agent import copilot


def setup_module(_):
    store.init_intelligence_db()


def _pid(n):
    return store.get_or_create_project({"commissioning_brand": {"name": n}})


class LLM:
    """Scripted: first turn asks for a tool (if given), second turn answers."""
    def __init__(self, first_call):
        self.first, self.turn, self.seen_tools = first_call, 0, None
    def is_reachable(self): return True
    def chat_tools(self, messages, tools, tool_choice="auto"):
        self.turn += 1
        self.seen_tools = {t["function"]["name"] for t in tools}
        if self.turn == 1 and self.first:
            return {"content": None, "tool_calls": [{"id": "t1", "name": self.first[0], "arguments": self.first[1]}],
                    "message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "t1", "type": "function", "function": {"name": self.first[0], "arguments": "{}"}}]}}
        return {"content": "RQ4 is partial because affiliation is not stated.", "tool_calls": [], "message": {}}


def test_answers_question_with_read_tool(monkeypatch):
    ran = []
    monkeypatch.setattr(copilot, "run_tool", lambda ctx, n, a: ran.append(n) or {"ok": True, "result": {"checklist": []}})
    out = copilot.reply(_pid("Copilot Q"), 1, "why is RQ4 partial?", LLM(("read_run", {})), api=object())
    assert ran == ["read_run"] and "partial" in out["reply"] and out["pending"] is None


def test_copilot_cannot_delete(monkeypatch):
    ran = []
    monkeypatch.setattr(copilot, "run_tool", lambda ctx, n, a: ran.append(n) or {"ok": True, "result": {}})
    llm = LLM(("delete_dataset", {"dataset_id": 3}))
    out = copilot.reply(_pid("Copilot Del"), 1, "delete this dataset", llm, api=object())
    assert ran == [] and not any("delete" in t for t in llm.seen_tools)
    assert out["actions"] == [{"tool": "delete_dataset", "ok": False, "error": "no such tool"}]


def test_costly_action_needs_confirm(monkeypatch):
    ran = []
    monkeypatch.setattr(copilot, "run_tool", lambda ctx, n, a: ran.append(n) or {"ok": True, "result": {"run_id": 9}})
    pid = _pid("Copilot Costly")
    out = copilot.reply(pid, 1, "rebuild the deck", LLM(("run_deliverable", {})), api=object())
    assert ran == [] and out["pending"]["tool"] == "run_deliverable"
    done = copilot.reply(pid, 1, "", None, confirm=out["pending"]["id"], api=object())
    assert ran == ["run_deliverable"] and done["actions"][0]["ok"]
    again = copilot.reply(pid, 1, "", None, confirm=out["pending"]["id"], api=object())
    assert "no pending action" in again["reply"]


def test_copilot_without_llm(monkeypatch):
    monkeypatch.setattr(copilot, "run_tool", lambda ctx, n, a: {"ok": True, "result": {
        "steps": [{"label": "Scope", "state": "done"}, {"label": "Deck", "state": "failed"}], "next": "run_deliverable"}})
    out = copilot.reply(_pid("Copilot NoLLM"), 1, "status?", None, api=object())
    assert "model is unavailable" in out["reply"] and "Deck: failed" in out["reply"]


def test_chat_text_never_stored_in_events(monkeypatch):
    monkeypatch.setattr(copilot, "run_tool", lambda ctx, n, a: {"ok": True, "result": {}})
    pid = _pid("Copilot Privacy")
    copilot.reply(pid, 1, "my secret plan", LLM(None), api=object())
    assert "secret" not in str(store.list_agent_events(pid))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_agent_copilot.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'copilot'`.

- [ ] **Step 3: Write `copilot.py`**

```python
"""The copilot: a project chat that answers from run data and can act with the autopilot's tools. Costly actions come
back as a pending action the user confirms; nothing destructive exists to call."""
from __future__ import annotations

import json
import secrets
import time

from ...core import store
from . import memory
from .api_client import ApiClient
from .tools import TOOLS, ToolContext, run_tool, tool_specs

MAX_TOOL_TURNS = 4
PENDING_TTL = 1800
_SYSTEM = ("You are Hunter's copilot for one research project. Answer from tool results, briefly and concretely. "
           "Use read_run to explain scorecards and failures. To change the deck, call the matching tool. You cannot "
           "delete projects or datasets; say so if asked. If the user reports a problem, file it with report_issue.")


def _action(tool: str, out: dict) -> dict:
    return {"tool": tool, "ok": out["ok"], **({"error": out.get("error")} if not out["ok"] else {})}


def _pending(project_id: int, tool: str, args: dict) -> dict:
    pid = secrets.token_hex(8)
    item = {"id": pid, "tool": tool, "args": args, "summary": f"{tool} {json.dumps(args)[:120]}", "at": time.time()}
    store.set_memory(project_id, "pending", pid, item)
    return {k: item[k] for k in ("id", "tool", "args", "summary")}


def _confirm(ctx: ToolContext, pending_id: str) -> dict:
    item = next((m["value"] for m in store.list_memory(ctx.project_id, "pending") if m["key"] == pending_id), None)
    store.delete_memory(ctx.project_id, "pending", pending_id)
    if not item or time.time() - item["at"] > PENDING_TTL:
        return {"reply": "There is no pending action with that id (it may have expired).", "actions": [], "pending": None}
    out = run_tool(ctx, item["tool"], item["args"])
    return {"reply": "Done." if out["ok"] else f"That failed: {out.get('error')}", "actions": [_action(item["tool"], out)],
            "pending": None}


def _no_llm(ctx: ToolContext) -> dict:
    result = run_tool(ctx, "project_status", {}).get("result") or {}
    steps = ", ".join(f"{x['label']}: {x['state']}" for x in result.get("steps", []))
    return {"reply": f"The model is unavailable, so I can only report status. {steps}. "
                     f"Next step: {result.get('next') or 'none'}.", "actions": [], "pending": None}


def reply(project_id: int, user_id: int, message: str, llm, confirm: str | None = None, api=None) -> dict:
    ctx = ToolContext(project_id=project_id, user_id=user_id, actor="copilot", api=api or ApiClient(user_id), llm=llm)
    if confirm:
        return _confirm(ctx, confirm)
    memory.record(project_id, "copilot", "copilot_message", {"chars": len(message)})
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return _no_llm(ctx)
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": memory.context(project_id, llm)},
                {"role": "user", "content": message}]
    actions: list[dict] = []
    for _ in range(MAX_TOOL_TURNS):
        out = llm.chat_tools(messages, tool_specs())
        calls = out.get("tool_calls") or []
        if not calls:
            text = (out.get("content") or "").strip() or "I have nothing to add."
            memory.record(project_id, "copilot", "copilot_reply", {"chars": len(text)})
            return {"reply": text, "actions": actions, "pending": None}
        messages.append(out["message"])
        for call in calls:
            tool = TOOLS.get(call["name"])
            if tool is None:
                actions.append({"tool": call["name"], "ok": False, "error": "no such tool"})
                result = {"ok": False, "error": "no such tool; this cannot be done"}
            elif tool.costly:
                pending = _pending(project_id, call["name"], call["arguments"])
                return {"reply": f"This will run {call['name'].replace('_', ' ')}, which takes a while. Confirm to go ahead.",
                        "actions": actions, "pending": pending}
            else:
                result = run_tool(ctx, call["name"], call["arguments"])
                actions.append(_action(call["name"], result))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)[:12000]})
    return {"reply": "I ran out of steps for this question; please narrow it.", "actions": actions, "pending": None}
```

- [ ] **Step 4: Add the route** (`router.py`)

```python
from . import copilot
from .schemas import AutopilotStart, CopilotMessage


@router.post("/agent/{project_id}/copilot")
def copilot_reply(project_id: ProjectId, body: CopilotMessage, user=Depends(get_current_user),
                  _u=Depends(require_project_access)):
    return copilot.reply(project_id, user["id"], body.message, autopilot._llm(), confirm=body.confirm)
```

- [ ] **Step 5: Register `report_issue`** (`tools.py`; Task 13 Step 5 replaces the body)

```python
def _report_issue(ctx, args):
    key = f"user_report_{int(time.time())}"
    memory.remember(ctx.project_id, "fix", key, {"title": args["title"], "page": args.get("page", ""),
                                                "detail": args.get("detail", "")})
    return {"reported": key}


register(Tool("report_issue", "File a problem the user reports (a bug, an ugly slide, a wrong label, a faded page).",
              {"type": "object", "required": ["title"], "properties": {"title": _STR, "page": _STR, "detail": _STR}},
              _report_issue))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_copilot.py agent/tests/test_agent_tools.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/agent/copilot.py agent/app/domains/agent/router.py agent/app/domains/agent/tools.py
git commit -m "feat(agent): project copilot with confirm-before-costly actions"
```

---

## Phase 2: screenshots, verbatim slides, in-run repair, slide revision

### Task 9: Article and post screenshots

**Files:**
- Create: `agent/app/domains/deckstudio/verbatims.py`
- Test: `agent/tests/test_deckstudio_verbatims.py`

**Interfaces:**
- Consumes: `deliverable.engine_types.EngineRow`, whose `.article` has `url, norm_url, outlet, title, date, reach, text`.
- Produces:
  - Constants: `GRID = 9`, `VIEW_W, VIEW_H = 1280, 800`, `CAPTURE_TIMEOUT_MS = 20000`.
  - `pick(rows, cited_urls: list[str], limit: int = GRID) -> list[dict]`
    - Returns items `{"url", "outlet", "title", "date", "text"}`.
    - Order: cited URLs first, then by highest reach, preferring distinct outlets.
    - No duplicate `norm_url`.
  - `embed_url(url: str) -> str | None` for X/Twitter, Instagram, TikTok and YouTube.
  - `is_public_http(url: str) -> bool`. It uses the module-level `_resolve = socket.getaddrinfo`, which is the test seam.
  - `collect(items: list[dict], folder: Path, page_factory=None) -> list[dict]`
    - Adds `"image"` (a PNG path) and `"kind": "screenshot" | "card"` to each item.
    - Results are cached in `folder` by `sha1(url)`.
    - `page_factory` is a test seam: a context manager yielding a Playwright-like page.

- [ ] **Step 1: Write the failing tests**

```python
"""Verbatim screenshots: choice of articles, embeds, URL safety, fallback cards, cache."""
from __future__ import annotations
import os, tempfile, socket
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import pytest
from agent.app.domains.deckstudio import verbatims as V
from agent.app.domains.deliverable.engine_types import EngineRow
from agent.app.domains.deliverable.ingest import Article

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    """example.com resolves to a public address without the network; everything else resolves for real."""
    real = socket.getaddrinfo
    monkeypatch.setattr(V, "_resolve", lambda host, port: [(None, None, None, None, (PUBLIC_IP, 0))]
                        if host.endswith("example.com") else real(host, port))


def _row(url, outlet, reach):
    a = Article(url=url, norm_url=url.lower(), title=f"T {url}", date=date(2026, 3, 1), outlet=outlet,
                text="First sentence. Second.", sentiment=None, reach=reach)
    return EngineRow(article=a, rq_ids={"RQ1"})


def test_pick_cited_first_then_reach_distinct_outlets():
    rows = [_row("https://a.com/1", "A", 10), _row("https://b.com/1", "B", 500), _row("https://b.com/2", "B", 400),
            _row("https://c.com/1", "C", 300)]
    assert [x["url"] for x in V.pick(rows, ["https://a.com/1"], limit=3)] == \
        ["https://a.com/1", "https://b.com/1", "https://c.com/1"]


def test_embed_urls():
    assert V.embed_url("https://x.com/nasa/status/123") == "https://platform.twitter.com/embed/Tweet.html?id=123"
    assert V.embed_url("https://www.instagram.com/p/AbC12/") == "https://www.instagram.com/p/AbC12/embed"
    assert V.embed_url("https://www.tiktok.com/@u/video/987") == "https://www.tiktok.com/embed/v2/987"
    assert V.embed_url("https://www.youtube.com/watch?v=xyz") == "https://www.youtube.com/embed/xyz"
    assert V.embed_url("https://news.com/a") is None


def test_capture_refuses_private_and_non_http_urls():
    for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)", "http://127.0.0.1:8002/api/health",
                "http://localhost/x", "http://10.0.0.5/a", "http://169.254.169.254/latest", "http://[::1]/"):
        assert not V.is_public_http(url), url
    assert V.is_public_http("https://www.example.com/a")


class FakePage:
    def __init__(self, fail): self.fail, self.visited, self.contents = fail, [], []
    def goto(self, url, **_):
        self.visited.append(url)
        if self.fail:
            raise TimeoutError("blocked")
    def set_content(self, html, **_): self.contents.append(html)
    def evaluate(self, js): return "" if "innerText" in js else {"top": 0, "found": True}
    def wait_for_timeout(self, ms): pass
    def screenshot(self, path, **_): Path(path).write_bytes(b"\x89PNG fake")
    def locator(self, sel):
        class L:
            def count(self): return 0
        return L()


def _factory(page):
    @contextmanager
    def make():
        yield page
    return make


def test_failed_capture_falls_back_to_card(tmp_path):
    page = FakePage(fail=True)
    out = V.collect([{"url": "https://www.example.com/a", "outlet": "Ex", "title": "Head", "date": "2026-03-01",
                      "text": "Lead."}], tmp_path, page_factory=_factory(page))
    assert out[0]["kind"] == "card" and Path(out[0]["image"]).exists() and "Head" in page.contents[0]


def test_private_url_never_visited(tmp_path):
    page = FakePage(fail=False)
    out = V.collect([{"url": "http://127.0.0.1/x", "outlet": "L", "title": "H", "date": "", "text": ""}], tmp_path,
                    page_factory=_factory(page))
    assert page.visited == [] and out[0]["kind"] == "card"


def test_cache_hit_skips_browser(tmp_path):
    item = {"url": "https://www.example.com/b", "outlet": "Ex", "title": "H", "date": "", "text": ""}
    V.collect([item], tmp_path, page_factory=_factory(FakePage(fail=False)))
    page = FakePage(fail=False)
    out = V.collect([item], tmp_path, page_factory=_factory(page))
    assert page.visited == [] and out[0]["kind"] == "screenshot"


def test_card_html_escapes_text(tmp_path):
    page = FakePage(fail=True)
    V.collect([{"url": "https://www.example.com/c", "outlet": "<b>x</b>", "title": "<script>1</script>", "date": "",
                "text": ""}], tmp_path, page_factory=_factory(page))
    assert "<script>1" not in page.contents[0] and "&lt;script&gt;" in page.contents[0]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest agent/tests/test_deckstudio_verbatims.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'verbatims'`.

- [ ] **Step 3: Write `verbatims.py`**

```python
"""Screenshots of the articles and posts behind each research question, for the verbatim slides and the insight-card
thumbnails. Pages that block automation, paywalls and non-public URLs get a generated article card instead."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import re
import socket
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)
GRID = 9
VIEW_W, VIEW_H = 1280, 800
CAPTURE_TIMEOUT_MS = 20000
SETTLE_MS = 1200
CROP_ABOVE_HEADLINE = 40
MAX_CONSENT_BUTTONS = 40
_resolve = socket.getaddrinfo
_CONSENT = re.compile(r"^(accept|accept all|agree|i agree|ok|got it|allow all|i accept|continue)$", re.I)
_PAYWALL = re.compile(r"subscribe to (continue|read)|to continue reading|already a subscriber", re.I)
_TWEET = re.compile(r"(?:twitter|x)\.com/[^/]+/status/(\d+)")
_INSTA = re.compile(r"instagram\.com/(p|reel)/([\w-]+)")
_TIKTOK = re.compile(r"tiktok\.com/@[^/]+/video/(\d+)")
_BODY_TEXT_JS = "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
_HEADLINE_JS = """() => { const h = document.querySelector('h1') || document.querySelector('article h2');
  if (!h) return {found: false, top: 0}; h.scrollIntoView({block: 'start'});
  return {found: true, top: Math.max(0, h.getBoundingClientRect().top)}; }"""
_CARD = """<html><body style="margin:0;width:{w}px;height:{h}px;font-family:Arial;background:#fff">
<div style="padding:56px 64px"><div style="font:700 26px Arial;color:#555;letter-spacing:.08em;text-transform:uppercase">
{outlet}</div><div style="font:700 54px/1.15 Georgia;color:#111;margin-top:28px">{title}</div>
<div style="font:400 26px Arial;color:#666;margin-top:24px">{date}</div>
<div style="font:400 30px/1.45 Arial;color:#222;margin-top:36px">{lead}</div></div></body></html>"""


def pick(rows, cited_urls: list[str], limit: int = GRID) -> list[dict]:
    by_url = {r.article.url: r for r in rows}
    chosen, seen, outlets = [], set(), set()

    def take(row) -> None:
        a = row.article
        if a.norm_url in seen or len(chosen) >= limit:
            return
        seen.add(a.norm_url)
        outlets.add(a.outlet)
        chosen.append({"url": a.url, "outlet": a.outlet, "title": a.title,
                       "date": a.date.isoformat() if a.date else "", "text": (a.text or "")[:400]})

    for url in cited_urls:
        if url in by_url:
            take(by_url[url])
    ranked = sorted(rows, key=lambda r: -r.article.reach)
    for row in ranked:                        # distinct outlets first
        if row.article.outlet not in outlets:
            take(row)
    for row in ranked:
        take(row)
    return chosen


def embed_url(url: str) -> str | None:
    if m := _TWEET.search(url):
        return f"https://platform.twitter.com/embed/Tweet.html?id={m.group(1)}"
    if m := _INSTA.search(url):
        return f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/embed"
    if m := _TIKTOK.search(url):
        return f"https://www.tiktok.com/embed/v2/{m.group(1)}"
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("youtube.com") and (v := parse_qs(parsed.query).get("v")):
        return f"https://www.youtube.com/embed/{v[0]}"
    if parsed.hostname == "youtu.be" and parsed.path.strip("/"):
        return f"https://www.youtube.com/embed/{parsed.path.strip('/')}"
    return None


def is_public_http(url: str) -> bool:
    """Only public http(s) pages are opened: dataset URLs are client data, never trusted to point inside the network."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = _resolve(parsed.hostname, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


@contextmanager
def _browser_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H})
        finally:
            browser.close()


def _dismiss_consent(page) -> None:
    buttons = page.locator("button")
    for i in range(min(buttons.count(), MAX_CONSENT_BUTTONS)):
        b = buttons.nth(i)
        if _CONSENT.match((b.inner_text() or "").strip()):
            b.click(timeout=2000)
            return


def _capture(page, url: str, out: Path) -> bool:
    target = embed_url(url) or url
    if not is_public_http(target):
        return False
    try:
        page.goto(target, timeout=CAPTURE_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(SETTLE_MS)
        _dismiss_consent(page)
        if _PAYWALL.search(page.evaluate(_BODY_TEXT_JS) or ""):
            return False
        head = page.evaluate(_HEADLINE_JS)
        if not embed_url(url) and not head.get("found"):
            return False
        top = max(0, int(head.get("top", 0)) - CROP_ABOVE_HEADLINE)
        page.screenshot(path=str(out), clip={"x": 0, "y": top, "width": VIEW_W, "height": VIEW_H - top} if top else None)
        return out.exists()
    except Exception as e:      # blocked, timed out, crashed: the article card stands in
        logger.info("screenshot fell back to a card for %s: %s", urlparse(url).hostname, type(e).__name__)
        return False


def _card(page, item: dict, out: Path) -> None:
    lead = re.split(r"(?<=[.!?])\s", (item.get("text") or "").strip(), maxsplit=1)[0][:220]
    page.set_content(_CARD.format(w=VIEW_W, h=VIEW_H, outlet=html.escape(item.get("outlet") or ""),
                                  title=html.escape(item.get("title") or ""), date=html.escape(item.get("date") or ""),
                                  lead=html.escape(lead)))
    page.screenshot(path=str(out))


def collect(items: list[dict], folder: Path, page_factory=None) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    out: list[dict | None] = []
    todo = []
    for item in items:
        stem = hashlib.sha1(item["url"].encode("utf-8")).hexdigest()[:16]
        meta = folder / f"{stem}.json"
        if meta.exists() and Path(json.loads(meta.read_text("utf-8"))["image"]).exists():
            out.append({**item, **json.loads(meta.read_text("utf-8"))})
            continue
        out.append(None)
        todo.append((len(out) - 1, item, folder / f"{stem}.png", folder / f"{stem}-card.png", meta))
    if todo:
        with (page_factory or _browser_page)() as page:
            for idx, item, shot, card, meta in todo:
                if _capture(page, item["url"], shot):
                    found = {"image": str(shot), "kind": "screenshot"}
                else:
                    _card(page, item, card)
                    found = {"image": str(card), "kind": "card"}
                meta.write_text(json.dumps(found), encoding="utf-8")
                out[idx] = {**item, **found}
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_deckstudio_verbatims.py -q -p no:cacheprovider`
Expected: PASS (7 passed).

- [ ] **Step 5: Live smoke (needs network)**

Run: `$PY -c "from pathlib import Path; import tempfile; from agent.app.domains.deckstudio import verbatims as V; d=Path(tempfile.mkdtemp()); print([(x['kind'], Path(x['image']).stat().st_size) for x in V.collect([{'url':'https://www.bbc.com/news','outlet':'BBC','title':'News','date':'','text':''}], d)])"`
Expected: one tuple whose kind is `screenshot` or `card`, with a size above 10000 bytes.

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/deckstudio/verbatims.py
git commit -m "feat(deckstudio): article and post screenshots with safe-URL check and article-card fallback"
```

### Task 10: Verbatim slides, card thumbnails, PPTX notes

**Files:**
- Modify: `agent/app/domains/deckstudio/planner.py`
  - Add `PlanInput.verbatims_by_rq`.
  - Add a `verbatim_wall` slide after each question's evidence.
- Modify: `agent/app/domains/deckstudio/renderer.py:31-38` (`render_slide`). Copy card `image`/`thumb` files into `assets/`.
- Modify: `agent/app/domains/deckstudio/templates/slide.html.j2`. Add a `verbatim_wall` branch and thumbs on cards.
- Modify: `agent/app/domains/deckstudio/templates/deck.html.j2`. Add the wall and thumb styles.
- Modify: `agent/app/domains/deckstudio/exporter.py:34-46` (`build_pptx`). Put the URLs from `s.notes` into the notes for `verbatim_wall`/`citations` slides.
- Modify: `agent/app/domains/deckstudio/pipeline.py`. During the `assets` stage, capture the screenshots, fill the wall images and card thumbs, and log the source URLs.
- Modify: `agent/app/domains/deliverable/engine.py`. Build `verbatims_by_rq` with `verbatims.pick` and pass it through `_plan_input`.
- Test: `agent/tests/test_deckstudio_verbatim_slides.py`

**Interfaces:**
- Consumes (Task 9): `verbatims.pick`, `verbatims.collect`.
- Produces:
  - `PlanInput.verbatims_by_rq: dict[str, list[dict]]`, defaulting to `{}`.
  - Slide type `"verbatim_wall"`:
    - id `f"{rq.id.lower()}-verbatims"`, treatment `"plain"`, title `VERBATIM_TITLE = "Supporting verbatims"`;
    - cards `[{"headline": outlet, "text": date, "url": url, "image": path | None}]`;
    - `notes` holds the URLs, one per line.
  - Card key `"thumb"`: the screenshot or card PNG of the card's first citation.

- [ ] **Step 1: Find the existing planner fixture**

Run: `grep -n "^def _" agent/tests/test_deckstudio_planner.py`
Expected: a helper that returns a `PlanInput`. Use its real name in Step 2 where the test says `_plan_input`. If you rename it, record a ruling.

- [ ] **Step 2: Write the failing tests**

```python
"""Verbatim wall per question, thumbnails on insight cards, URLs in PPTX notes."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.domains.deckstudio import planner, renderer
from agent.app.domains.deckstudio.spec import DeckSpec, DeckTokens, SlideSpec
from agent.tests.test_deckstudio_planner import _plan_input      # name confirmed in Step 1


def _vb(n=9):
    return [{"url": f"https://ex{i}.com/a", "outlet": f"Ex{i}", "title": f"T{i}", "date": "2026-03-01", "text": ""}
            for i in range(n)]


def test_one_verbatim_wall_per_question_after_its_evidence():
    inp = _plan_input()
    inp.verbatims_by_rq = {q.id: _vb() for q in inp.rqs}
    spec = planner.build_deck_spec(inp)
    ids = [s.id for s in spec.slides]
    for q in inp.rqs:
        wall = ids.index(f"{q.id.lower()}-verbatims")
        later_dividers = [i for i, sid in enumerate(ids) if sid.endswith("-divider") and i > wall]
        assert ids.index(f"{q.id.lower()}-divider") < wall and (not later_dividers or wall < later_dividers[0])
        slide = spec.slides[wall]
        assert slide.type == "verbatim_wall" and len(slide.cards) == 9
        assert slide.notes.splitlines()[0] == "https://ex0.com/a" and "RQ" not in slide.title


def test_no_verbatims_no_wall():
    assert not [s for s in planner.build_deck_spec(_plan_input()).slides if s.type == "verbatim_wall"]


def test_wall_renders_images_and_card_thumbs(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG")
    wall = SlideSpec(id="rq1-verbatims", type="verbatim_wall", title="Supporting verbatims",
                     cards=[{"headline": "Ex", "text": "2026-03-01", "url": "https://ex.com", "image": str(img)}])
    card = SlideSpec(id="e-0", type="bar_with_cards", treatment="A", title="t", question="q",
                     cards=[{"headline": "h", "text": "x", "thumb": str(img)}])
    html_wall = renderer.render_slide(wall, DeckTokens(), 1, 2, 10, "P", "Meltwater", tmp_path)
    html_card = renderer.render_slide(card, DeckTokens(), 2, 2, 10, "P", "Meltwater", tmp_path)
    assert html_wall.count('class="vshot"') == 1 and "assets/shot.png" in html_wall and "Ex" in html_wall
    assert 'class="thumb"' in html_card and "assets/shot.png" in html_card
    assert wall.cards[0]["image"] == str(img)          # the spec is not mutated by rendering


def test_pptx_notes_carry_wall_urls(tmp_path):
    from agent.app.domains.deckstudio import exporter
    from pptx import Presentation
    from PIL import Image
    png = tmp_path / "1.png"
    Image.new("RGB", (192, 108)).save(png)
    s = SlideSpec(id="rq1-verbatims", type="verbatim_wall", title="Supporting verbatims", notes="https://ex.com/a")
    spec = DeckSpec(1, "T", "S", "P", 1, "topic_map", "", DeckTokens(), [s])
    out = exporter.build_pptx([png], spec, tmp_path / "d.pptx")
    assert "https://ex.com/a" in Presentation(str(out)).slides[0].notes_slide.notes_text_frame.text
```

Run: `$PY -m pytest agent/tests/test_deckstudio_verbatim_slides.py -q -p no:cacheprovider`
Expected: FAIL with `ValueError: 'rq1-verbatims' is not in list`.

- [ ] **Step 3: Planner**

In `planner.py`:
- add the last `PlanInput` field: `verbatims_by_rq: dict[str, list[dict]] = field(default_factory=dict)`;
- add the module constant `VERBATIM_TITLE = "Supporting verbatims"`;
- in `build_deck_spec`, right after `slides += _evidence(...)`, add:

```python
        items = inp.verbatims_by_rq.get(rq.id) or []
        if items:
            slides.append(SlideSpec(
                id=f"{rq.id.lower()}-verbatims", type="verbatim_wall", treatment="plain", kicker=kicker,
                title=VERBATIM_TITLE, question=rq.question,
                cards=[{"headline": v["outlet"], "text": v["date"], "url": v["url"], "image": v.get("image")} for v in items],
                facts_allowed=_facts(sections) + [v["date"] for v in items], notes="\n".join(v["url"] for v in items)))
```

- [ ] **Step 4: Renderer and templates**

In `renderer.py`, add `from dataclasses import replace`. Then at the top of `render_slide`:

```python
    slide = replace(slide, cards=[{**c, **({"image": _asset(c["image"], out_dir)} if c.get("image") else {}),
                                   **({"thumb": _asset(c["thumb"], out_dir)} if c.get("thumb") else {})}
                                  for c in slide.cards])
```

In `slide.html.j2`, add a branch before the final `{% else %}`:

```jinja
{% elif s.type == "verbatim_wall" %}
  <div style="position:absolute;left:70px;right:70px;top:48px">
    {% if s.kicker %}<div class="kicker">{{ s.kicker }}</div>{% endif %}
    <div class="title clamp" style="margin-top:8px;font-size:40px">{{ s.title }}</div>
  </div>
  <div class="vwall reveal">
    {% for c in s.cards[:9] %}<figure class="vcell">{% if c.image %}<img class="vshot" src="{{ c.image }}" alt="">{% endif %}
      <figcaption><b>{{ c.headline }}</b> · {{ c.text }}</figcaption></figure>{% endfor %}
  </div>
```

In both A-treatment card loops (`{% for c in s.cards[:6] %}` and `{% for c in s.cards[:3] %}`), make `{% if c.thumb %}<img class="thumb" src="{{ c.thumb }}" alt="">{% endif %}` the first child of `<div class="card"...>`.

In `deck.html.j2`, inside `<style>`:

```css
.vwall{position:absolute;left:70px;right:70px;top:190px;bottom:70px;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:18px}
.vcell{margin:0;background:var(--surface);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.vshot{width:100%;flex:1;min-height:0;object-fit:cover;object-position:top}
.vcell figcaption{font:400 15px/1.3 var(--body);color:var(--text);padding:8px 12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.thumb{float:right;width:48px;height:48px;object-fit:cover;object-position:top;border-radius:8px;margin:0 0 6px 10px}
```

- [ ] **Step 5: PPTX notes**

In `exporter.build_pptx`, after `lines = [...]`:

```python
        if s.type in ("verbatim_wall", "citations") and s.notes:
            lines.append(s.notes)
```

- [ ] **Step 6: Engine and pipeline**

In `engine.py`:
- add `from ..deckstudio import verbatims`;
- add a keyword parameter `verbatims_by_rq: dict | None = None` to `_plan_input` and forward it as `PlanInput(..., verbatims_by_rq=verbatims_by_rq or {})`;
- at the `_plan_input(...)` call site, where `rows_by_rq`, `registry` and `insights_by_rq` are in scope, pass:

```python
        cited = {c["n"]: c["url"] for c in registry.entries()}
        verbatims_by_rq = {q.id: verbatims.pick(rows_by_rq[q.id], [cited[n] for i in insights_by_rq[q.id]
                                                                   for n in i.get("citations", []) if n in cited])
                           for q in rqs}
```

In `deckstudio/pipeline.py`:
- add `verbatims` to the `from . import ...` line, and add `from ...core import config`;
- in the `assets` stage, after the photo loop and before `run.stage("assets", "done", ...)`, add:

```python
    walls = [s for s in spec.slides if s.type == "verbatim_wall"]
    shots: dict[str, str] = {}
    for k, s in enumerate(walls, start=1):
        run.within("assets", 0.9 + 0.1 * k / len(walls), f"Capturing article screenshots for question {k} of {len(walls)}")
        rq_id = s.id.rsplit("-verbatims", 1)[0].upper()
        got = verbatims.collect(plan_input.verbatims_by_rq.get(rq_id, []), config.DATA_DIR / "verbatims")
        s.cards = [{**c, "image": g["image"]} for c, g in zip(s.cards, got)]
        shots.update({g["url"]: g["image"] for g in got})
        run.log(f"Verbatims for {s.kicker or rq_id}: {sum(g['kind'] == 'screenshot' for g in got)} screenshots, "
                f"{sum(g['kind'] == 'card' for g in got)} article cards")
        for g in got:
            run.log(f"Verbatim source: {g['url']}")
    by_n = {c["n"]: c["url"] for c in plan_input.citations}
    for s in spec.slides:
        if s.type == "verbatim_wall":
            continue
        for c in s.cards:
            first = next((by_n[n] for n in c.get("citations", []) if by_n.get(n) in shots), None)
            if first:
                c["thumb"] = shots[first]
```

Source URLs in the log are addresses, not article content. The spec asks for them ("their source URLs go in the run log"), the same as the existing photo `source <url>` lines.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_deckstudio_verbatim_slides.py agent/tests/test_deckstudio_planner.py agent/tests/test_deckstudio_render.py agent/tests/test_deckstudio_export.py agent/tests/test_deckstudio_pipeline.py agent/tests/test_deliverable_engine.py -q -p no:cacheprovider`
Expected: PASS (all).

If `test_deckstudio_pipeline.py` drives the assets stage, monkeypatch `verbatims.collect` there to return card items (`{**item, "image": <tmp png>, "kind": "card"}`), and record a ruling.

- [ ] **Step 8: Commit**

```bash
git add agent/app/domains/deckstudio/planner.py agent/app/domains/deckstudio/pipeline.py agent/app/domains/deckstudio/renderer.py agent/app/domains/deckstudio/templates/slide.html.j2 agent/app/domains/deckstudio/templates/deck.html.j2 agent/app/domains/deckstudio/exporter.py agent/app/domains/deliverable/engine.py
git commit -m "feat(deckstudio): verbatim slide per question, screenshot thumbnails on insight cards, URLs in notes"
```

### Task 11: In-run slide repair

**Files:**
- Create: `agent/app/domains/deckstudio/repair.py`
- Modify: `agent/app/domains/deckstudio/creative.py`. `compose(..., on_fix=None)` runs `repair.repair_deck` after `_final_check` and saves the kept creative HTML to `out_dir/"creative.json"` (Task 12 reads it).
- Modify: `agent/app/domains/deckstudio/pipeline.py`:
  - `run_studio(..., on_fix=None)` passes `on_fix` to `compose`;
  - a slide with a missing photo gets one retry, using the slide's kicker as the query.
- Modify: `agent/app/domains/deliverable/engine.py`. Pass an `on_fix` that records each fix in agent memory.
- Test: `agent/tests/test_deckstudio_repair.py`

**Interfaces:**
- Consumes:
  - `guards.layout_issues(path)`, which returns `[{"slide_id", "kind", "detail"}]`;
  - `renderer.render_deck(spec, out_dir, candidates)`.
- Produces:
  - Constants: `repair.MAX_ATTEMPTS = 2`, `SO_WHAT_MAX = 140`, `CARD_TEXT_MAX = 160`, `CARDS_MAX = 3`, `TABLE_ROWS_PER_SLIDE = 8`.
  - `repair.action_for(kind: str) -> str`, returning one of `"shorten" | "drop_photo"`. `"split_table"` is chosen in `_apply` when the slide has a long table.
  - `repair.repair_deck(spec, out_dir: Path, candidates: dict[str, str], report: list[dict], on_fix=None, layout=guards.layout_issues, path: Path | None = None) -> tuple[Path, list[dict]]`
    - Only template slides (those not in `candidates`) with `qc` flags are repaired.
    - After a fix, the slide's `qc` holds the flags that remain, or `[]`.
    - Each fixed slide gains `"repaired": [actions]`.
    - `on_fix(slide_id, action, kind)` is called once per fix.
  - `creative.compose(spec, out_dir, llm, shingles, progress=None, workers=4, on_fix=None) -> tuple[Path, list[dict]]`

- [ ] **Step 1: Write the failing tests**

```python
"""In-run repair: shorten overflowing text, drop photos behind unreadable text, split long tables; at most 2 tries."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.domains.deckstudio import repair
from agent.app.domains.deckstudio.spec import DeckSpec, DeckTokens, SlideSpec


def _spec(*slides):
    return DeckSpec(1, "T", "S", "P", 10, "topic_map", "", DeckTokens(), list(slides))


def _report(spec, flags):
    return [{"slide_id": s.id, "source": "template", "reasons": [], "qc": flags.get(s.id, [])} for s in spec.slides]


def test_actions_by_flag():
    assert repair.action_for("overflow") == "shorten" and repair.action_for("overlap") == "shorten"
    assert repair.action_for("low_contrast") == "drop_photo" and repair.action_for("off_slide") == "shorten"


def test_overflow_fixed_by_shortening(tmp_path):
    s = SlideSpec(id="a", type="takeaways", treatment="A", so_what="x " * 200,
                  cards=[{"headline": "h", "text": "y " * 250} for _ in range(6)])
    spec = _spec(s)
    fixes = []
    _, report = repair.repair_deck(spec, tmp_path, {}, _report(spec, {"a": ["overflow: cards"]}),
                                   on_fix=lambda *a: fixes.append(a), layout=lambda p: [])
    assert len(s.so_what) <= repair.SO_WHAT_MAX + 1 and len(s.cards) == repair.CARDS_MAX
    assert all(len(c["text"]) <= repair.CARD_TEXT_MAX + 1 for c in s.cards)
    assert report[0]["qc"] == [] and report[0]["repaired"] == ["shorten"] and fixes == [("a", "shorten", "overflow")]


def test_low_contrast_drops_photo(tmp_path):
    s = SlideSpec(id="b", type="divider", treatment="full", image={"query": "q", "path": "x.jpg"})
    spec = _spec(s)
    repair.repair_deck(spec, tmp_path, {}, _report(spec, {"b": ["low_contrast: t"]}), layout=lambda p: [])
    assert s.image.get("path") is None


def test_long_table_split_into_continuation(tmp_path):
    rows = [[str(i), "x"] for i in range(20)]
    s = SlideSpec(id="c", type="checklist", treatment="plain", title="Brief checklist",
                  tables=[{"header": ["a", "b"], "rows": rows}])
    spec = _spec(s, SlideSpec(id="z", type="closing", treatment="full"))
    repair.repair_deck(spec, tmp_path, {}, _report(spec, {"c": ["overflow: table"]}), layout=lambda p: [])
    assert [x.id for x in spec.slides][:3] == ["c", "c-cont-1", "c-cont-2"]
    assert len(spec.slides[0].tables[0]["rows"]) == repair.TABLE_ROWS_PER_SLIDE
    assert sum(len(x.tables[0]["rows"]) for x in spec.slides[:3]) == 20


def test_gives_up_after_two_attempts(tmp_path):
    s = SlideSpec(id="d", type="takeaways", treatment="A", so_what="short")
    spec = _spec(s)
    seen = []
    def always(p):
        seen.append(1)
        return [{"slide_id": "d", "kind": "overlap", "detail": "chart"}]
    _, report = repair.repair_deck(spec, tmp_path, {}, _report(spec, {"d": ["overlap: chart"]}), layout=always)
    assert len(seen) == repair.MAX_ATTEMPTS and report[0]["qc"] == ["overlap: chart"]


def test_creative_slides_are_left_alone(tmp_path):
    s = SlideSpec(id="e", type="takeaways", treatment="A", so_what="x" * 400)
    spec = _spec(s)
    rep = _report(spec, {"e": ["overflow: x"]})
    rep[0]["source"] = "creative"
    repair.repair_deck(spec, tmp_path, {"e": "<section>"}, rep, layout=lambda p: [])
    assert len(s.so_what) == 400
```

Run: `$PY -m pytest agent/tests/test_deckstudio_repair.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'repair'`.

- [ ] **Step 2: Write `repair.py`**

```python
"""In-run repair of template slides that still fail layout QC: shorten text, drop a photo that makes text unreadable,
split a long table onto continuation slides. Up to MAX_ATTEMPTS re-renders; every fix is reported."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import guards
from .renderer import render_deck

MAX_ATTEMPTS = 2
SO_WHAT_MAX = 140
CARD_TEXT_MAX = 160
CARDS_MAX = 3
TABLE_ROWS_PER_SLIDE = 8
_ACTIONS = {"low_contrast": "drop_photo"}
_TABLE_KINDS = ("overflow", "off_slide")


def action_for(kind: str) -> str:
    return _ACTIONS.get(kind, "shorten")


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _shorten(slide) -> None:
    slide.so_what = _cut(slide.so_what, SO_WHAT_MAX)
    slide.cards = [{**c, "text": _cut(c.get("text", ""), CARD_TEXT_MAX)} for c in slide.cards[:CARDS_MAX]]


def _split(spec, slide) -> bool:
    rows = slide.tables[0]["rows"] if slide.tables else []
    if len(rows) <= TABLE_ROWS_PER_SLIDE:
        return False
    at = spec.slides.index(slide)
    chunks = [rows[i:i + TABLE_ROWS_PER_SLIDE] for i in range(0, len(rows), TABLE_ROWS_PER_SLIDE)]
    table = slide.tables[0]
    slide.tables = [{**table, "rows": chunks[0]}]
    for k, chunk in enumerate(chunks[1:], start=1):
        spec.slides.insert(at + k, replace(slide, id=f"{slide.id}-cont-{k}", title=f"{slide.title} (continued)",
                                           tables=[{**table, "rows": chunk}]))
    return True


def _apply(spec, slide, kind: str) -> str:
    if kind in _TABLE_KINDS and _split(spec, slide):
        return "split_table"
    if action_for(kind) == "drop_photo":
        slide.image = {**slide.image, "path": None}
        return "drop_photo"
    _shorten(slide)
    return "shorten"


def repair_deck(spec, out_dir: Path, candidates: dict[str, str], report: list[dict], on_fix=None,
                layout=guards.layout_issues, path: Path | None = None) -> tuple[Path, list[dict]]:
    by_id = {r["slide_id"]: r for r in report}
    flagged = {r["slide_id"]: r["qc"] for r in report if r["qc"] and r["slide_id"] not in candidates}
    for _attempt in range(MAX_ATTEMPTS):
        if not flagged:
            break
        for sid, flags in flagged.items():
            slide = next((s for s in spec.slides if s.id == sid), None)
            if slide is None:
                continue
            kind = flags[0].split(":", 1)[0]
            action = _apply(spec, slide, kind)
            by_id[sid].setdefault("repaired", []).append(action)
            if on_fix:
                on_fix(sid, action, kind)
        path = render_deck(spec, out_dir, candidates)
        still: dict[str, list[str]] = {}
        for issue in layout(path):
            if issue["slide_id"] in flagged:
                still.setdefault(issue["slide_id"], []).append(f"{issue['kind']}: {issue['detail']}")
        for sid in flagged:
            by_id[sid]["qc"] = still.get(sid, [])
        flagged = still
    rows = [by_id.get(s.id) or {"slide_id": s.id, "source": "template", "reasons": [], "qc": []} for s in spec.slides]
    return path or out_dir / "deck.html", rows
```

- [ ] **Step 3: Wire into `compose`, the pipeline and the engine**

In `creative.py`:
- add `import json` and `from . import repair`;
- add `on_fix=None` to `compose`'s parameters;
- add this helper:

```python
def _finish(path: Path, spec: DeckSpec, out_dir: Path, candidates: dict[str, str], report: dict, on_fix):
    path, rows = _final_check(path, spec, out_dir, candidates, report)
    (out_dir / "creative.json").write_text(json.dumps(candidates), encoding="utf-8")
    return repair.repair_deck(spec, out_dir, candidates, rows, on_fix=on_fix, path=path)
```

Then route both returns through it:
- the early return becomes `return _finish(template_path, spec, out_dir, {}, report, on_fix)`;
- the final return becomes `return _finish(render_deck(spec, out_dir, candidates), spec, out_dir, candidates, report, on_fix)`.

In `pipeline.py`:
- add the parameter `on_fix=None` to `run_studio` and pass `on_fix=on_fix` to `creative.compose`;
- after the report loop, log each repair:

```python
    for r in report:
        if r.get("repaired"):
            run.log(f"Repaired {r['slide_id']}: {', '.join(r['repaired'])}")
```

- in the photo loop, right after `photo = assets.find_photo(...)`, retry with the kicker:

```python
            if not photo.path and s.kicker:
                photo = assets.find_photo(s.kicker, role, deck_dir / "photos", used, None)
```

In `engine.py`, add `from ..agent import memory as agent_memory`. Pass this to `run_studio(...)`:

```python
            on_fix=lambda sid, action, kind: agent_memory.remember(project_id, "fix", f"run{run_id}_{sid}",
                                                                   {"action": action, "flag": kind}),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_deckstudio_repair.py agent/tests/test_deckstudio_creative.py agent/tests/test_deckstudio_pipeline.py agent/tests/test_deliverable_engine.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/deckstudio/repair.py agent/app/domains/deckstudio/creative.py agent/app/domains/deckstudio/pipeline.py agent/app/domains/deliverable/engine.py
git commit -m "feat(deckstudio): in-run repair of slides that fail layout QC, recorded in project memory"
```

### Task 12: Copilot slide revision and design changes

**Files:**
- Create: `agent/app/domains/deckstudio/revise.py`
- Modify: `agent/app/domains/deckstudio/creative.py`. `creative_slide(..., instructions: str = "")` adds the user's instructions to the prompt.
- Modify: `agent/app/domains/agent/tools.py`. Register `revise_slide` and `set_design`, both costly.
- Test: `agent/tests/test_deckstudio_revise.py`

**Interfaces:**
- Consumes:
  - Task 11: `deck_dir/creative.json`.
  - Existing: `deck_dir/spec.json`, `creative.creative_slide`, `creative._safe`, `creative._same_charts`, `guards.*`, `renderer.render_deck`, `renderer.inline_assets`, `exporter.export_all`, `art_director._guard`, `art_director.GOOGLE_FONTS`.
- Produces:
  - `revise.load(deck_dir: Path) -> tuple[DeckSpec, dict[str, str]]`
  - `revise.revise_slide(deck_dir: Path, slide_ref: str, instructions: str, llm, check_layout: bool = True) -> dict`
    - `slide_ref` is a slide id or a 1-based slide number.
    - Returns `{"slide_id", "applied": bool, "reason": str, ...paths}`.
    - A change that fails any guard is not applied, and the reason names the guard.
  - `revise.set_design(deck_dir: Path, changes: dict) -> dict`
    - Accepts only colour fields (6 hex digits) and font fields from `GOOGLE_FONTS`.
    - A value that the contrast guard would change is rejected.
    - Returns `{"applied": [...], "rejected": {field: reason}, ...paths}`.

- [ ] **Step 1: Read the guard and font list signatures**

Run: `grep -n "def _guard\|^GOOGLE_FONTS" -A3 agent/app/domains/deckstudio/art_director.py`
Expected: `def _guard(t: DeckTokens) -> DeckTokens` (or similar) and a `GOOGLE_FONTS` collection. If the shape differs, call the guard the way `choose_tokens` does, and record a ruling.

- [ ] **Step 2: Write the failing tests**

```python
"""Copilot deck edits: one slide with instructions, or design tokens; guarded, then re-exported."""
from __future__ import annotations
import os, tempfile, json
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.domains.deckstudio import guards, renderer, revise
from agent.app.domains.deckstudio.spec import DeckSpec, DeckTokens, SlideSpec


@pytest.fixture
def deck(tmp_path, monkeypatch):
    spec = DeckSpec(1, "Deck", "Sub", "2026", 10, "topic_map", "", DeckTokens(),
                    [SlideSpec(id="cover", type="cover", treatment="full", title="Deck"),
                     SlideSpec(id="takeaways", type="takeaways", treatment="A", title="Key takeaways",
                               cards=[{"headline": "40% said", "text": "x"}], facts_allowed=["40%"])])
    (tmp_path / "spec.json").write_text(json.dumps(spec.to_dict()), encoding="utf-8")
    (tmp_path / "creative.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(revise, "_export", lambda spec, html, deck_dir: {"pptx": "p", "pdf": "d", "html": str(html)})
    return tmp_path


class LLM:
    def __init__(self, html): self.html, self.prompts = html, []
    def is_reachable(self): return True
    def chat(self, messages, **_):
        self.prompts.append(messages[-1]["content"])
        return self.html


def _template(deck, sid):
    spec, _ = revise.load(deck)
    return guards.slide_html_map(renderer.render_deck(spec, deck).read_text("utf-8"))[sid]


def test_revise_by_number_applies_guarded_html(deck):
    html = _template(deck, "takeaways").replace("Key takeaways", "Key takeaways, calmer")
    llm = LLM(html)
    out = revise.revise_slide(deck, "2", "make it calmer", llm, check_layout=False)
    assert out["applied"] and out["slide_id"] == "takeaways" and "make it calmer" in llm.prompts[0]
    assert "calmer" in json.loads((deck / "creative.json").read_text())["takeaways"]


def test_revise_rejects_invented_number(deck):
    html = _template(deck, "takeaways").replace("40% said", "75% said")
    out = revise.revise_slide(deck, "takeaways", "punchier", LLM(html), check_layout=False)
    assert not out["applied"] and "75" in out["reason"]


def test_revise_unknown_slide(deck):
    with pytest.raises(ValueError):
        revise.revise_slide(deck, "99", "x", LLM(""))


def test_set_design_validates(deck):
    out = revise.set_design(deck, {"primary": "1A4D8F", "accent": "zzz", "password": "x", "text": "FFFFFF"})
    assert out["applied"] == ["primary"] and set(out["rejected"]) == {"accent", "password", "text"}
    spec, _ = revise.load(deck)
    assert spec.tokens.primary == "1A4D8F" and spec.tokens.text != "FFFFFF"
```

Run: `$PY -m pytest agent/tests/test_deckstudio_revise.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'revise'`.

- [ ] **Step 3: `creative_slide` instructions**

```python
def creative_slide(llm, slide_html: str, slide: SlideSpec, tokens: DeckTokens, reference: dict,
                   instructions: str = "") -> str | None:
    extra = f"\nUser instructions: {instructions}" if instructions else ""
    try:
        reply = llm.chat([{"role": "system", "content": _PROMPT},
                          {"role": "user", "content": f"Reference layout: {reference or 'none'}{extra}\nSlide:\n{slide_html}"}])
```

The rest of the function is unchanged.

- [ ] **Step 4: Write `revise.py`**

```python
"""Copilot edits to a finished deck: restyle one slide with the user's instructions, or change design tokens. Every
change passes the same guards as the creative pass, then the deck is re-rendered and re-exported in place."""
from __future__ import annotations

import json
import re
from dataclasses import fields, replace
from pathlib import Path

from . import art_director, creative, exporter, guards, renderer
from .spec import DeckSpec, DeckTokens

_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_COLOR_FIELDS = {"background", "surface", "primary", "accent", "text", "muted", "on_dark"}
_FONT_FIELDS = {"title_font", "body_font"}


def load(deck_dir: Path) -> tuple[DeckSpec, dict[str, str]]:
    spec = DeckSpec.from_dict(json.loads((deck_dir / "spec.json").read_text(encoding="utf-8")))
    cpath = deck_dir / "creative.json"
    return spec, (json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {})


def _save(deck_dir: Path, spec: DeckSpec, candidates: dict[str, str]) -> None:
    (deck_dir / "spec.json").write_text(json.dumps(spec.to_dict(), default=str), encoding="utf-8")
    (deck_dir / "creative.json").write_text(json.dumps(candidates), encoding="utf-8")


def _export(spec: DeckSpec, html: Path, deck_dir: Path) -> dict:
    out = exporter.export_all(html, spec, deck_dir, spec.title)
    return {"pptx": str(out["pptx"]), "pdf": str(out["pdf"]), "html": str(html)}


def _slide(spec: DeckSpec, ref: str):
    if ref.isdigit() and 1 <= int(ref) <= len(spec.slides):
        return spec.slides[int(ref) - 1]
    found = next((s for s in spec.slides if s.id == ref), None)
    if not found:
        raise ValueError(f"no slide {ref!r}")
    return found


def _rejection(html: str | None, template: str, slide, spec: DeckSpec) -> str:
    if not html:
        return "the model returned no usable slide"
    if not creative._safe(html):
        return "unsafe or malformed html"
    if not creative._same_charts(template, html):
        return "the chart changed"
    allowed = slide.facts_allowed + [str(spec.base_n), slide.question, slide.kicker, slide.title, spec.period]
    bad = guards.number_issues(guards.slide_visible_text(html), allowed)
    return f"numbers not in the data: {', '.join(bad)}" if bad else ""


def revise_slide(deck_dir: Path, slide_ref: str, instructions: str, llm, check_layout: bool = True) -> dict:
    spec, candidates = load(deck_dir)
    slide = _slide(spec, str(slide_ref))
    template = guards.slide_html_map(renderer.render_deck(spec, deck_dir, {}).read_text(encoding="utf-8"))[slide.id]
    html = creative.creative_slide(llm, candidates.get(slide.id, template), slide, spec.tokens or DeckTokens(),
                                   slide.reference, instructions=instructions)
    reason = _rejection(html, template, slide, spec)
    if reason:
        return {"slide_id": slide.id, "applied": False, "reason": reason}
    candidates[slide.id] = html
    path = renderer.render_deck(spec, deck_dir, candidates)
    issues = [i for i in guards.layout_issues(path) if i["slide_id"] == slide.id] if check_layout else []
    if issues:
        return {"slide_id": slide.id, "applied": False, "reason": f"layout: {issues[0]['kind']}"}
    _save(deck_dir, spec, candidates)
    renderer.inline_assets(path)
    return {"slide_id": slide.id, "applied": True, "reason": "", **_export(spec, path, deck_dir)}


def set_design(deck_dir: Path, changes: dict) -> dict:
    spec, candidates = load(deck_dir)
    tokens = spec.tokens or DeckTokens()
    allowed = {f.name for f in fields(DeckTokens)} & (_COLOR_FIELDS | _FONT_FIELDS)
    rejected, updates = {}, {}
    for key, value in changes.items():
        if key not in allowed:
            rejected[key] = "not a design token"
        elif key in _COLOR_FIELDS and not _HEX.match(str(value)):
            rejected[key] = "colours are 6 hex digits"
        elif key in _FONT_FIELDS and str(value) not in art_director.GOOGLE_FONTS:
            rejected[key] = "font not available"
        else:
            updates[key] = str(value).upper() if key in _COLOR_FIELDS else str(value)
    guarded = art_director._guard(replace(tokens, **updates))
    applied = [k for k, v in updates.items() if getattr(guarded, k) == v]
    rejected.update({k: "fails the contrast guard" for k in updates if k not in applied})
    spec.tokens = replace(tokens, **{k: updates[k] for k in applied})
    path = renderer.render_deck(spec, deck_dir, candidates)
    _save(deck_dir, spec, candidates)
    renderer.inline_assets(path)
    return {"applied": applied, "rejected": rejected, **_export(spec, path, deck_dir)}
```

- [ ] **Step 5: Register the tools** (`tools.py`)

```python
def _deck_dir(ctx) -> Path:
    run = store.get_latest_deliverable_run(ctx.project_id) or {}
    if run.get("status") != "completed" or not run.get("deck_dir"):
        raise ToolError("there is no finished deck to change yet")
    return Path(run["deck_dir"])


def _revise(ctx, args):
    from ..deckstudio import revise
    out = revise.revise_slide(_deck_dir(ctx), str(args["slide"]), args["instructions"], ctx.llm)
    if out["applied"]:
        memory.remember(ctx.project_id, "preference", f"slide_{out['slide_id']}", args["instructions"])
    return out


def _design(ctx, args):
    from ..deckstudio import revise
    out = revise.set_design(_deck_dir(ctx), args["changes"])
    if out["applied"]:
        memory.remember(ctx.project_id, "preference", "design_tokens", {k: args["changes"][k] for k in out["applied"]})
    return out


register(Tool("revise_slide", "Restyle one slide of the finished deck following the user's instructions "
              "(slide = number or id). Numbers must stay those in the data.",
              {"type": "object", "required": ["slide", "instructions"], "properties": {"slide": _STR, "instructions": _STR}},
              _revise, costly=True))
register(Tool("set_design", "Change the deck's colours (6-hex) or fonts and re-export it.",
              {"type": "object", "required": ["changes"], "properties": {"changes": {"type": "object"}}},
              _design, costly=True))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_deckstudio_revise.py agent/tests/test_deckstudio_creative.py agent/tests/test_agent_tools.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/deckstudio/revise.py agent/app/domains/deckstudio/creative.py agent/app/domains/agent/tools.py
git commit -m "feat(deckstudio): guarded single-slide revision and design-token changes for the copilot"
```

### Task 12A: Photos that match the brand, the products and the slide

The user reported (2026-10-07) that deck images are irrelevant to the brand, the products and the slide label. Diagnosis from project 262, run 17 (`deck/spec.json`):
- **Queries are analysis labels, not subjects.** Examples: "Deal-Led Editorial Coverage Share Coverage over time" and "… Top Outlets for Deal-Led Content".
- **Brands and products are never in the query.**
- **Nothing gates relevance.** `find_photo` accepts the best of whatever Pexels returns, even with zero matching words.
- **SerpAPI is unavailable.** It returns HTTP 429 "Your account has run out of searches", so brand and product shots never arrive.

**Files:**
- Create:
  - `agent/app/domains/deckstudio/image_brief.py`: subjects, jargon stripping, tiered queries and the text relevance gate.
  - `agent/app/domains/deckstudio/vision.py`: Azure `gpt-4.1` image check.
- Modify `agent/app/domains/deckstudio/assets.py`:
  - add a DuckDuckGo image source;
  - add article lead images (`og:image`);
  - add a SerpAPI quota circuit breaker;
  - make `find_photo` subject-aware with a judge;
  - return no photo rather than an irrelevant one.
- Modify `agent/app/domains/deckstudio/planner.py`: add `PlanInput.products`, `PlanInput.category`.
- Modify `agent/app/domains/deckstudio/pipeline.py`: build a brief per slide, ask for one batched LLM scene line, and log query, source and verdict for each slide.
- Modify `agent/app/domains/deliverable/engine.py` `_plan_input`: pass products (spec `validated_entities` of type product/sub-brand) and the category phrase.
- Test: `agent/tests/test_deckstudio_image_relevance.py`

**Interfaces:**
- Consumes:
  - Task 9: `verbatims.is_public_http`.
  - Task 10: `PlanInput.verbatims_by_rq`.
  - Task 4: none. Vision uses plain `llm.chat` with an image content part, which `AzureOpenAIClient.chat` passes through unchanged.
- Produces:
  - `image_brief.Subjects(brands: list[str], products: list[str], category: str, scene: str)`, a frozen dataclass.
  - `image_brief.JARGON`, a frozenset of analysis words dropped from queries.
  - `image_brief.subjects_for(slide, brands: list[str], products: list[str], category: str, scene: str = "") -> Subjects`. The brands are those in the slide's chart categories or logos, else none.
  - `image_brief.queries(s: Subjects) -> list[str]`: most specific first, at most 4, no duplicates.
  - `image_brief.text_relevant(text: str, s: Subjects) -> bool`: shares at least one brand, product or category word.
  - `vision.matches(llm, image_bytes: bytes, s: Subjects, slide_label: str) -> bool | None`. `None` means it could not judge (no LLM, or an error).
  - `assets.article_image(url: str) -> str | None`: the page's `og:image` / `twitter:image`. Public URLs only.
  - `assets.find_photo(query, role, folder, used, brand_image=None, *, subjects: Subjects | None = None, article_urls: list[str] = (), judge=None) -> Photo`. The original positional use stays valid. `Photo` gains `why: str`.
  - `assets.MAX_VISION_CHECKS = 60` per run, counted by the caller-provided `judge`.
  - Global rule: **no photo is better than an irrelevant photo.** If nothing passes the gate, the slide keeps its brand-colour gradient.

- [ ] **Step 1: Write the failing tests**

```python
"""Slide photos must match the brand, products, category and the slide's subject; otherwise no photo."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from io import BytesIO
from PIL import Image
from agent.app.domains.deckstudio import assets, image_brief as IB, vision
from agent.app.domains.deckstudio.spec import SlideSpec

BRANDS, PRODUCTS, CATEGORY = ["Aveeno", "Cetaphil", "Johnson's"], ["baby wash", "baby lotion"], "baby skincare"


def _jpeg(w=2000, h=1200) -> bytes:
    b = BytesIO()
    Image.new("RGB", (w, h), (200, 180, 160)).save(b, "JPEG")
    return b.getvalue()


def test_jargon_never_reaches_a_query():
    slide = SlideSpec(id="rq1-volume_trend-0", type="trend_with_peaks", kicker="Deal-Led Editorial Coverage Share",
                      title="Coverage over time")
    qs = IB.queries(IB.subjects_for(slide, BRANDS, PRODUCTS, CATEGORY))
    assert qs and all(not (set(q.lower().split()) & {"coverage", "share", "editorial", "over", "time", "top", "outlets"})
                      for q in qs)
    assert all("baby" in q.lower() for q in qs)


def test_brand_slide_queries_name_the_brand_and_product():
    slide = SlideSpec(id="rq4-brand_sov-2", type="bar_with_cards", kicker="Expert Brand Affiliation",
                      title="Brand Share of Voice", charts=[{"kind": "bar", "categories": ["Aveeno", "Cetaphil", "Other"]}])
    s = IB.subjects_for(slide, BRANDS, PRODUCTS, CATEGORY)
    assert s.brands == ["Aveeno", "Cetaphil"]
    assert IB.queries(s)[0].startswith("Aveeno") and "baby" in IB.queries(s)[0].lower()


def test_text_gate():
    s = IB.Subjects(brands=["Aveeno"], products=["baby lotion"], category="baby skincare", scene="")
    assert IB.text_relevant("Mother applying lotion to her baby", s)
    assert IB.text_relevant("Aveeno Baby Daily Moisture", s)
    assert not IB.text_relevant("Business people in a meeting room", s)


def test_irrelevant_candidates_give_no_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [{"url": "https://img.example.com/office.jpg", "width": 3000,
                                                       "title": "Business people in a meeting room"}])
    monkeypatch.setattr(assets, "_ddg_images", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg())
    s = IB.Subjects(brands=[], products=[], category="baby skincare", scene="")
    photo = assets.find_photo("baby skincare", "panel", tmp_path, set(), subjects=s)
    assert photo.path is None and "no relevant" in photo.why


def test_vision_judge_overrides_text(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_pexels", lambda q: [
        {"url": "https://img.example.com/a.jpg", "width": 3000, "title": "baby lotion"},
        {"url": "https://img.example.com/b.jpg", "width": 3000, "title": "baby lotion bottle"}])
    monkeypatch.setattr(assets, "_ddg_images", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg())
    verdicts = iter([False, True])
    s = IB.Subjects(brands=[], products=["baby lotion"], category="baby skincare", scene="")
    photo = assets.find_photo("baby lotion", "panel", tmp_path, set(), subjects=s, judge=lambda data: next(verdicts))
    assert photo.source_url.endswith("b.jpg") and "vision" in photo.why


def test_article_lead_image_preferred_for_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "article_image", lambda url: "https://news.example.com/lead.jpg")
    monkeypatch.setattr(assets, "_pexels", lambda q: [])
    monkeypatch.setattr(assets, "_ddg_images", lambda q: [])
    monkeypatch.setattr(assets, "_serpapi", lambda q: [])
    monkeypatch.setattr(assets, "_download", lambda url: _jpeg())
    s = IB.Subjects(brands=[], products=[], category="baby skincare", scene="")
    photo = assets.find_photo("baby skincare", "panel", tmp_path, set(), subjects=s,
                              article_urls=["https://news.example.com/a"], judge=lambda data: True)
    assert photo.source_url == "https://news.example.com/lead.jpg" and photo.licence == "article"


def test_article_image_parses_og_tag_and_refuses_private(monkeypatch):
    html = '<html><head><meta property="og:image" content="https://cdn.example.com/x.jpg"></head></html>'
    class R:
        status_code, text, headers = 200, html, {"content-type": "text/html"}
    monkeypatch.setattr(assets.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(assets, "is_public_http", lambda u: "127.0.0.1" not in u)
    assert assets.article_image("https://news.example.com/a") == "https://cdn.example.com/x.jpg"
    assert assets.article_image("http://127.0.0.1/a") is None


def test_serpapi_quota_trips_breaker(monkeypatch):
    calls = []
    class R:
        status_code = 429
        def json(self): return {"error": "Your account has run out of searches."}
    monkeypatch.setenv("SERP_API_KEY", "k" * 64)
    monkeypatch.setattr(assets, "_serp_disabled", False)
    monkeypatch.setattr(assets.requests, "get", lambda *a, **k: calls.append(1) or R())
    assert assets._serpapi("a") == [] and assets._serpapi("b") == [] and len(calls) == 1


def test_vision_parses_yes_no_and_degrades():
    class L:
        def __init__(self, reply): self.reply = reply
        def is_reachable(self): return True
        def chat(self, messages, **_):
            assert messages[-1]["content"][1]["type"] == "image_url"
            return self.reply
    s = IB.Subjects(brands=["Aveeno"], products=[], category="baby skincare", scene="")
    assert vision.matches(L("YES - a baby lotion bottle"), _jpeg(), s, "Brand share") is True
    assert vision.matches(L("no, an office"), _jpeg(), s, "Brand share") is False
    assert vision.matches(None, _jpeg(), s, "Brand share") is None
```

Run: `$PY -m pytest agent/tests/test_deckstudio_image_relevance.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'image_brief'`.

- [ ] **Step 2: Write `image_brief.py`**

```python
"""What a slide's photo should show: the brands on the slide, the project's products and category, and the slide's
subject with analysis jargon removed. Queries go from most specific (brand + product) to most general (category)."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUERIES = 4
_WORD = re.compile(r"[A-Za-z][A-Za-z'&-]+")
JARGON = frozenset("""coverage share voice editorial earned media analysis overview top key trend trends over time
sentiment split themes theme cluster clusters outlets outlet ranking volume named mentions mention most cited
led citations affiliation affiliated across among featured associated centered with in of the and for on to by
question questions research brief takeaways summary objectives scope methodology sources thank you""".split())


@dataclass(frozen=True)
class Subjects:
    brands: list[str]
    products: list[str]
    category: str
    scene: str


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text or "") if w.lower() not in JARGON and len(w) > 2]


def subjects_for(slide, brands: list[str], products: list[str], category: str, scene: str = "") -> Subjects:
    on_slide = {c for ch in slide.charts for c in ch.get("categories", [])} | set(slide.logos)
    named = [b for b in brands if b in on_slide]
    topic = " ".join(dict.fromkeys(_words(f"{slide.kicker} {slide.title}")))[:60]
    return Subjects(brands=named, products=list(products), category=category, scene=scene or topic)


def queries(s: Subjects) -> list[str]:
    product = s.products[0] if s.products else s.category
    out = [f"{b} {product}" for b in s.brands[:2]]
    if s.scene:
        out.append(f"{s.category} {s.scene}" if s.category.split()[0].lower() not in s.scene.lower() else s.scene)
    out += [f"{s.category} {p}" for p in s.products[:1]] + [s.category]
    clean = []
    for q in out:
        q = " ".join(w for w in q.split() if w.lower() not in JARGON)
        if q and q.lower() not in {c.lower() for c in clean}:
            clean.append(q)
    return clean[:MAX_QUERIES]


def text_relevant(text: str, s: Subjects) -> bool:
    have = {w.lower() for w in _WORD.findall(text or "")}
    want = {w.lower() for term in (*s.brands, *s.products, s.category) for w in _WORD.findall(term) if len(w) > 3}
    return bool(have & want)
```

- [ ] **Step 3: Write `vision.py`**

```python
"""Ask Azure OpenAI (gpt-4.1, image input) whether a candidate photo fits the slide. None = could not judge."""
from __future__ import annotations

import base64
import logging
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)
THUMB_PX = 512
_PROMPT = ("Answer YES or NO first. Is this photo a good, on-topic image for a presentation slide about {label}, "
           "for the {category} category{brands}{products}? Say NO for logos alone, charts, screenshots of text, "
           "watermarked stock, unrelated scenes, or a different brand's product.")


def _thumb(data: bytes) -> str:
    with Image.open(BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX))
        out = BytesIO()
        im.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode("ascii")


def matches(llm, image_bytes: bytes, s, slide_label: str) -> bool | None:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return None
    text = _PROMPT.format(label=slide_label, category=s.category,
                          brands=f", brands {', '.join(s.brands)}" if s.brands else "",
                          products=f", products {', '.join(s.products[:3])}" if s.products else "")
    try:
        reply = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_thumb(image_bytes)}"}}]}])
    except Exception as e:      # the text gate still applies when vision is unavailable
        logger.warning("vision check skipped: %s", type(e).__name__)
        return None
    head = (reply or "").strip().upper()
    return True if head.startswith("YES") else False if head.startswith("NO") else None
```

- [ ] **Step 4: Change `assets.py`**

Add imports: `from .image_brief import Subjects, text_relevant` and `from .verbatims import is_public_http`. Add a module flag `_serp_disabled = False` and the constants `ARTICLE_TIMEOUT_S = 10` and `MAX_VISION_CHECKS = 60`.

`_serpapi`: before the request, `if _serp_disabled: return []`. After the request, add:

```python
        if r.status_code == 429:
            global _serp_disabled
            _serp_disabled = True
            logger.warning("serpapi quota exhausted; image search falls back to DuckDuckGo and Pexels for this process")
            return []
```

New sources:

```python
def _ddg_images(query: str) -> list[dict]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as d:
            found = list(d.images(query, safesearch="moderate", size="Large", max_results=15))
        return [{"url": i.get("image"), "width": int(i.get("width") or 0), "title": i.get("title") or ""} for i in found]
    except Exception as e:      # rate limits and network errors: the next source is tried
        logger.warning("duckduckgo image search failed: %s", type(e).__name__)
        return []


_OG = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', re.I)


def article_image(url: str) -> str | None:
    """The lead image an article declares for sharing: on-topic by construction."""
    if not is_public_http(url):
        return None
    try:
        r = requests.get(url, timeout=ARTICLE_TIMEOUT_S, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        m = _OG.search(r.text[:200000])
        found = m.group(1) if m else None
        return found if found and is_public_http(found) else None
    except requests.RequestException:
        return None
```

`Photo` gains `why: str = ""`. The new `find_photo` keeps the old positional parameters:

```python
def _accept(data: bytes, role: str, title: str, subjects: Subjects | None, judge) -> tuple[bool, str]:
    try:
        with Image.open(BytesIO(data)) as im:
            if im.width < MIN_WIDTH[role]:
                return False, "too small"
    except Exception:
        return False, "not an image"
    if subjects is None:
        return True, "no subject check"
    verdict = judge(data) if judge else None
    if verdict is not None:
        return verdict, "vision: " + ("matches" if verdict else "off-topic")
    ok = text_relevant(title, subjects)
    return ok, "text: " + ("names the subject" if ok else "does not name the subject")


def find_photo(query: str, role: str, folder: Path, used: set[str], brand_image: Path | None = None, *,
               subjects: Subjects | None = None, article_urls=(), judge=None) -> Photo:
    slug = hashlib.sha1(f"{query}|{role}".encode()).hexdigest()[:12]
    if brand_image and brand_image.exists() and str(brand_image) not in used:
        with Image.open(brand_image) as im:
            wide_enough = im.width >= MIN_WIDTH[role]
        if wide_enough:
            used.add(str(brand_image))
            return Photo(crop_to(brand_image, role, folder / f"{slug}.jpg"), str(brand_image), "brand", "brand imagery")
    from .image_brief import queries as brief_queries
    plan = [("article", [{"url": u, "width": 10**6, "title": ""} for u in filter(None, map(article_image, article_urls[:4]))])]
    for q in (brief_queries(subjects) if subjects else [query]):
        plan += [("web", _ddg_images(q) if subjects and subjects.brands else []), ("licensed", _pexels(q)), ("web", _serpapi(q))]
    rejected = 0
    for licence, results in plan:
        for cand in [c for c in results if c["url"] and c["url"] not in used][:MAX_TRIES]:
            data = _download(cand["url"])
            if not data:
                continue
            title = cand["title"] or (" ".join(subjects.brands + [subjects.category]) if subjects and licence == "article" else "")
            ok, why = _accept(data, role, title, subjects, judge)
            if not ok:
                rejected += 1
                continue
            folder.mkdir(parents=True, exist_ok=True)
            raw = folder / f"{slug}.src"
            raw.write_bytes(data)
            used.add(cand["url"])
            return Photo(crop_to(raw, role, folder / f"{slug}.jpg"), cand["url"], licence, why)
    return Photo(None, "", "none", f"no relevant photo ({rejected} candidates rejected)")
```

Under the text gate, article lead images count as relevant: the article was routed to the slide's question, so its title is replaced by the slide's subjects. Under vision, they are judged like any other candidate.

- [ ] **Step 5: Pipeline and engine**

1. In `planner.PlanInput`, add `products: list[str] = field(default_factory=list)` and `category: str = ""`.
2. In `engine._plan_input`:
   - `products`: names of `spec["validated_entities"]` whose `type` is in `("product", "sub_brand", "product_line")`. Read from `store.get_latest_spec(project_id)`.
   - `category`: the project's category phrase. Use `spec.get("research_subject", {}).get("category")`, else the project title with "Category", "Analysis", "Media" and "Earned" removed, lower-cased (for example "baby skincare").
3. In `pipeline.run_studio`, `assets` stage:
   - One batched scene call. Ask the LLM, in a single JSON-mode `chat`, for `{slide_id: "concrete photo scene, max 8 words"}` covering every slide with an image, given the slide titles, brands, products and category.
   - Keep a scene only if `text_relevant(scene, Subjects(brands, products, category, ""))` is true. Any error falls back to an empty scene, which means the deterministic topic.
   - Per slide:
     - `subjects = image_brief.subjects_for(s, plan_input.brands, plan_input.products, plan_input.category, scenes.get(s.id, ""))`.
     - `article_urls` are the URLs of the slide's card citations. When there are none, use the first 4 `verbatims_by_rq` URLs of the slide's question; the question id is the prefix of `s.id`, upper-cased.
     - `judge` is a closure that calls `vision.matches(llm, data, subjects, s.question or s.title or s.kicker)` while a run-level counter is below `assets.MAX_VISION_CHECKS`. After that it returns `None`, so the text gate applies.
   - Replace the existing `find_photo` call with `assets.find_photo(" ".join(image_brief.queries(subjects)[:1]) or s.image["query"], role, deck_dir / "photos", used, brand_image if s.type == "cover" else None, subjects=subjects, article_urls=article_urls, judge=judge)`. Delete the Task 11 kicker retry; the tiered queries replace it.
   - Log per slide: `Photo for {s.id}: {photo.licence} — {photo.why} — {photo.source_url[:90]}`, or `No relevant photo for {s.id} ({photo.why}); brand gradient kept`.
   - Store `s.image["why"] = photo.why`.

- [ ] **Step 6: Run the tests**

Run: `$PY -m pytest agent/tests/test_deckstudio_image_relevance.py agent/tests/test_deckstudio_assets.py agent/tests/test_deckstudio_pipeline.py agent/tests/test_deliverable_engine.py -q -p no:cacheprovider`
Expected: PASS (all). Existing `test_deckstudio_assets.py` cases call `find_photo` positionally without `subjects`, which keeps the old behaviour.

- [ ] **Step 7: Live check on project 262**

1. Regenerate project 262's deck from the Deliverables page.
2. Run: `$PY -c "import json; s=json.load(open(r'agent/data/deliverables/project_262/run_<new>/deck/spec.json',encoding='utf-8')); [print(x['id'][:24].ljust(24), (x['image'].get('why') or '')[:70]) for x in s['slides'] if x.get('image')]"`
3. Expected:
   - Every photo's `why` reads `vision: matches` (Azure configured), or `brand imagery`, or the slide says `no relevant photo`.
   - No photo was chosen by `text: does not name the subject`.
4. Open the deck and look at the brand slides (brand share of voice, experts affiliated with brands). They should show those brands' products, or article lead images about them, never generic stock. Record what you see in the ledger.

- [ ] **Step 8: Commit**

```bash
git add agent/app/domains/deckstudio/image_brief.py agent/app/domains/deckstudio/vision.py agent/app/domains/deckstudio/assets.py agent/app/domains/deckstudio/planner.py agent/app/domains/deckstudio/pipeline.py agent/app/domains/deliverable/engine.py
git commit -m "fix(deckstudio): slide photos chosen for brand, product and slide subject, vision-checked; no photo rather than an off-topic one"
```

### Task 12B: Rotate across several SerpAPI keys

The user has several SerpAPI keys (2026-10-07). Today only `SERP_API_KEY` is read, and that key's account is out of searches (HTTP 429). It is read in four places: `deckstudio/assets.py:51`, `research/brandfetch.py:128`, `research/news_search.py:155` and `research/video_search.py:141`.

**Files:**
- Create: `agent/app/core/serp_keys.py`
- Modify these call sites to use it: `deckstudio/assets.py`, `research/brandfetch.py`, `research/news_search.py`, `research/video_search.py`. Each passes the `api_key` it is given; on a 429 or quota error it calls `serp_keys.exhausted(key)` and retries once with the next key.
- Modify: `.env.example`, if present. Document `SERP_API_KEYS=key1,key2,key3` (comma-separated; `SERP_API_KEY` still works).
- Test: `agent/tests/test_serp_keys.py`

**Interfaces:**
- Produces:
  - `serp_keys.current() -> str | None`: the first key not marked exhausted. Keys come from `SERP_API_KEYS` (comma-separated), then `SERP_API_KEY`, de-duplicated and in order.
  - `serp_keys.exhausted(key: str) -> None`: marks a key exhausted for `COOLDOWN_SECONDS = 3600`. Only the key's position is logged ("SerpAPI key 2 of 3 exhausted"), never its value.
  - `serp_keys.is_quota_error(status: int, body: dict | None) -> bool`: true for 429, or for a body `error` mentioning "run out of searches" or "limit".
  - Task 12A's `_serp_disabled` breaker becomes "every key exhausted" (`current() is None`).

- [ ] **Step 1: Write the failing tests**

```python
"""SerpAPI keys rotate on quota errors; key values never appear in logs."""
from __future__ import annotations
import logging
from agent.app.core import serp_keys


def test_rotation_and_cooldown(monkeypatch):
    monkeypatch.setenv("SERP_API_KEYS", "aaa111,bbb222, ccc333")
    monkeypatch.setenv("SERP_API_KEY", "aaa111")
    serp_keys._reset()
    assert serp_keys.current() == "aaa111"
    serp_keys.exhausted("aaa111")
    assert serp_keys.current() == "bbb222"
    serp_keys.exhausted("bbb222"); serp_keys.exhausted("ccc333")
    assert serp_keys.current() is None
    monkeypatch.setattr(serp_keys.time, "time", lambda: 10**12)        # an hour later
    assert serp_keys.current() == "aaa111"


def test_single_key_still_works(monkeypatch):
    monkeypatch.delenv("SERP_API_KEYS", raising=False)
    monkeypatch.setenv("SERP_API_KEY", "only1")
    serp_keys._reset()
    assert serp_keys.current() == "only1"


def test_quota_error_detection():
    assert serp_keys.is_quota_error(429, None)
    assert serp_keys.is_quota_error(200, {"error": "Your account has run out of searches."})
    assert not serp_keys.is_quota_error(200, {"images_results": []})


def test_key_value_never_logged(monkeypatch, caplog):
    monkeypatch.setenv("SERP_API_KEYS", "secretvalue1,secretvalue2")
    serp_keys._reset()
    with caplog.at_level(logging.WARNING):
        serp_keys.exhausted("secretvalue1")
    assert "secretvalue1" not in caplog.text and "1 of 2" in caplog.text
```

Run: `$PY -m pytest agent/tests/test_serp_keys.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError`.

- [ ] **Step 2: Write `core/serp_keys.py`**

```python
"""Several SerpAPI keys, used in order; a key that hits its quota rests for an hour. Key values are never logged."""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)
COOLDOWN_SECONDS = 3600
_QUOTA_WORDS = ("run out of searches", "limit")
_lock = threading.Lock()
_resting: dict[str, float] = {}


def _keys() -> list[str]:
    raw = (os.environ.get("SERP_API_KEYS") or "").split(",") + [os.environ.get("SERP_API_KEY") or ""]
    return list(dict.fromkeys(k.strip() for k in raw if k.strip()))


def _reset() -> None:
    with _lock:
        _resting.clear()


def current() -> str | None:
    now = time.time()
    with _lock:
        return next((k for k in _keys() if _resting.get(k, 0) <= now), None)


def exhausted(key: str) -> None:
    keys = _keys()
    with _lock:
        _resting[key] = time.time() + COOLDOWN_SECONDS
    position = keys.index(key) + 1 if key in keys else "?"
    logger.warning("SerpAPI key %s of %s exhausted; resting %ss", position, len(keys), COOLDOWN_SECONDS)


def is_quota_error(status: int, body: dict | None) -> bool:
    err = str((body or {}).get("error") or "").lower()
    return status == 429 or any(w in err for w in _QUOTA_WORDS)
```

- [ ] **Step 3: Use it at the four call sites**

Apply the same shape at each site. For example, in `assets._serpapi`:

```python
def _serpapi(query: str) -> list[dict]:
    for _ in range(len(serp_keys._keys()) or 1):
        key = serp_keys.current()
        if not key:
            return []
        try:
            r = requests.get(SERP_URL, params={"engine": "google_images", "q": query, "api_key": key, "safe": "active"},
                             timeout=TIMEOUT_S)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            if serp_keys.is_quota_error(r.status_code, body):
                serp_keys.exhausted(key)
                continue
            r.raise_for_status()
            return [{"url": i.get("original"), "width": i.get("original_width") or 0, "title": i.get("title") or ""}
                    for i in (body or {}).get("images_results") or [] if i.get("original")]
        except (requests.RequestException, ValueError, AttributeError, TypeError) as e:
            logger.warning("serpapi image search failed: %s", type(e).__name__)
            return []
    return []
```

At the other sites:
- `brandfetch.py:128`: replace `_env("SERP_API_KEY")` with `serp_keys.current()`.
- `news_search.py:155`: `api_key_override or os.getenv("SERP_API_KEY", "")` becomes `api_key_override or serp_keys.current() or ""`.
- `video_search.py:141`: replace `os.getenv("SERP_API_KEY", "")` with `serp_keys.current() or ""`.

Each site also adds the quota check and a one-retry loop around its request, in the same shape as above. Remove Task 12A's `_serp_disabled` flag and its test (`test_serpapi_quota_trips_breaker`). Replace that test with an `assets` test: two keys, the first returns 429 and the second returns results, so results come back from the second key.

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest agent/tests/test_serp_keys.py agent/tests/test_deckstudio_image_relevance.py agent/tests/test_brand_logos.py agent/tests/test_news_search.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add agent/app/core/serp_keys.py agent/app/domains/deckstudio/assets.py agent/app/domains/research/brandfetch.py agent/app/domains/research/news_search.py agent/app/domains/research/video_search.py
git commit -m "feat: rotate across several SerpAPI keys on quota errors"
```

---

## Phase 3: detection, fixer, tiered apply

### Task 13: Issue intake and secret redaction

**Files:**
- Create:
  - `agent/app/domains/agent/redact.py`
  - `agent/app/domains/agent/repair/__init__.py` (docstring only)
  - `agent/app/domains/agent/repair/issues.py`
- Modify: `agent/app/domains/deliverable/engine.py`:
  - `_Run` records per-stage timings (section `"timings"`);
  - a failure files an issue;
  - a completed run gets a calibration check;
  - the studio's surviving QC flags file issues through an `on_issue` callback.
- Modify: `agent/app/domains/deckstudio/pipeline.py`. Add `run_studio(..., on_issue=None)`.
- Modify: `agent/app/domains/agent/tools.py`. `_report_issue` files a real issue.
- Test: `agent/tests/test_agent_issues.py`

**Interfaces:**
- Produces:
  - `redact.redact(text: str) -> str`. It replaces two things:
    - the value of any environment variable whose name contains `KEY`, `SECRET`, `TOKEN`, `PASSWORD` or `ENDPOINT`, when the value is 6 or more characters, becomes `[REDACTED:<NAME>]`;
    - `api-key:`, `Bearer` and `X-API-Key:` header values.
  - `issues.fingerprint(*parts: str) -> str`: a 16-hex sha1 of the parts, with digits replaced by `#`.
  - `issues.file_issue(source: str, kind: str, title: str, detail: dict, project_id: int | None = None) -> tuple[int, bool]`. Redacts the title and every string in the detail.
  - `issues.from_exception(stage: str, exc: BaseException, project_id: int | None) -> int`
  - `issues.check_progress_calibration(run_id: int, tolerance: float = 0.5, weights: dict | None = None) -> int | None`
    - Files `kind="progress_calibration"` when the summed absolute difference between measured stage-time shares and weight shares exceeds `tolerance`.
    - `weights` defaults to `engine.STAGE_WEIGHTS`.
  - `_Run.timings: dict[str, list[float]]`, persisted as section `{"id": "timings", "module": "timings", "rq_id": None, "title": "Timings", "stages": {...}}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Issue intake: dedupe, redaction, engine failures, progress calibration."""
from __future__ import annotations
import os, tempfile, time
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from agent.app.core import store
from agent.app.domains.agent.redact import redact
from agent.app.domains.agent.repair import issues


def setup_module(_):
    store.init_intelligence_db()


def test_redact_env_values_and_headers(monkeypatch):
    monkeypatch.setenv("SERP_API_KEY", "serp-secret-123456")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://my-ai.openai.azure.com")
    text = "GET https://my-ai.openai.azure.com?q=1 key=serp-secret-123456 api-key: abc123 Authorization: Bearer tok_987"
    out = redact(text)
    assert "serp-secret" not in out and "my-ai.openai" not in out and "abc123" not in out and "tok_987" not in out
    assert "[REDACTED:SERP_API_KEY]" in out


def test_fingerprint_ignores_numbers():
    assert issues.fingerprint("ingest", "Run 18 failed") == issues.fingerprint("ingest", "Run 19 failed")


def test_from_exception_dedupes_and_redacts(monkeypatch):
    monkeypatch.setenv("PEXEL_API_KEY", "pexel-very-secret")
    try:
        raise AttributeError("'NoneType' object has no attribute 'lower' pexel-very-secret")
    except AttributeError as e:
        a = issues.from_exception("ingest", e, 263)
        b = issues.from_exception("ingest", e, 264)
    issue = store.get_issue(a)
    assert a == b and issue["seen"] == 2 and issue["kind"] == "exception"
    assert "pexel-very-secret" not in str(issue) and "lower" in issue["title"]


def _timed_run(stages: dict[str, int]) -> int:
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Calib {time.time()}"}})
    rid = store.create_deliverable_run(pid)
    t, out = 1000.0, {}
    for name, secs in stages.items():
        out[name] = [t, t + secs]
        t += secs
    store.save_deliverable_section(rid, {"id": "timings", "rq_id": None, "module": "timings", "title": "Timings",
                                         "stages": out})
    return rid


def test_progress_calibration_flags_skewed_weights():
    rid = _timed_run({"classify": 2, "compose": 130, "assets": 85})
    skewed = {"classify": 80, "compose": 10, "assets": 10}
    assert issues.check_progress_calibration(rid, weights=skewed) is not None
    matching = {"classify": 1, "compose": 60, "assets": 39}
    assert issues.check_progress_calibration(rid, weights=matching) is None
```

Run: `$PY -m pytest agent/tests/test_agent_issues.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 2: Write `redact.py`**

```python
"""Remove secrets from any text that may reach a prompt, an issue or a log line."""
from __future__ import annotations

import os
import re

_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|ENDPOINT", re.I)
_MIN_LEN = 6
_PATTERNS = (re.compile(r"(api-key\s*[:=]\s*)\S+", re.I), re.compile(r"(Bearer\s+)\S+", re.I),
             re.compile(r"(X-API-Key\s*[:=]\s*)\S+", re.I))


def redact(text: str) -> str:
    out = text or ""
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and value and len(value) >= _MIN_LEN:
            out = out.replace(value, f"[REDACTED:{name}]")
    for pattern in _PATTERNS:
        out = pattern.sub(r"\1[REDACTED]", out)
    return out
```

- [ ] **Step 3: Write `repair/issues.py`**

```python
"""Where problems become issues: engine failures, QC flags that survived repair, browser QA findings, progress
calibration and user reports from the copilot. Issues are deduplicated by fingerprint and always redacted."""
from __future__ import annotations

import hashlib
import re
import traceback

from ....core import store
from ..redact import redact

TRACE_LINES = 40
_DIGITS = re.compile(r"\d+")


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(_DIGITS.sub("#", p or "") for p in parts).encode("utf-8")).hexdigest()[:16]


def _clean(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def file_issue(source: str, kind: str, title: str, detail: dict, project_id: int | None = None) -> tuple[int, bool]:
    title = redact(title)[:300]
    return store.file_issue_row(fingerprint(source, kind, title), source, kind, title, _clean(detail), project_id)


def from_exception(stage: str, exc: BaseException, project_id: int | None) -> int:
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).splitlines()[-TRACE_LINES:]
    first = str(exc).splitlines()[0] if str(exc) else ""
    issue_id, _new = file_issue("engine", "exception", f"{stage}: {type(exc).__name__}: {first}",
                                {"stage": stage, "type": type(exc).__name__, "message": str(exc)[:1000],
                                 "trace": "\n".join(trace)}, project_id)
    return issue_id


def check_progress_calibration(run_id: int, tolerance: float = 0.5, weights: dict | None = None) -> int | None:
    if weights is None:
        from ...deliverable.engine import STAGE_WEIGHTS
        weights = STAGE_WEIGHTS
    timings = next((s for s in store.list_deliverable_sections(run_id) if s["id"] == "timings"), None)
    if not timings or not timings.get("stages"):
        return None
    spent = {k: max(0.0, v[1] - v[0]) for k, v in timings["stages"].items() if v and len(v) == 2}
    total_t, total_w = sum(spent.values()), sum(weights.get(k, 0) for k in spent)
    if not total_t or not total_w:
        return None
    share = {k: (spent[k] / total_t, weights.get(k, 0) / total_w) for k in spent}
    gap = sum(abs(m - w) for m, w in share.values())
    if gap <= tolerance:
        return None
    worst = sorted(share, key=lambda k: -abs(share[k][0] - share[k][1]))[:3]
    issue_id, _ = file_issue("engine", "progress_calibration", "Progress bar weights do not match real stage times",
                             {"run_id": run_id, "gap": round(gap, 2), "worst": worst,
                              "measured_share": {k: round(m, 3) for k, (m, _w) in share.items()}})
    return issue_id
```

- [ ] **Step 4: Wire the engine and the pipeline**

In `engine.py` `_Run.__init__`, add `self.timings: dict[str, list[float]] = {}`. In `stage()`, before the existing `if status == "running":`, add:

```python
        now = time.time()
        if status == "running":
            self.timings[name] = [now, now]
        elif name in self.timings:
            self.timings[name][1] = now
            store.replace_deliverable_section(self.run_id, {"id": "timings", "rq_id": None, "module": "timings",
                                                            "title": "Timings", "stages": self.timings})
```

In `run_engine`'s failure `except`, after `store.update_deliverable_run(...)`, add:

```python
        try:
            from ..agent.repair import issues
            issues.from_exception(stage, e, project_id)
        except Exception:       # filing an issue must never mask the run's own failure
            logger.exception("[deliverable:%s] could not file the failure as an issue", run_id)
```

After `run.progress(100, "Deliverable ready")`, add:

```python
        try:
            from ..agent.repair import issues
            issues.check_progress_calibration(run_id)
        except Exception:
            logger.exception("[deliverable:%s] progress calibration check failed", run_id)
```

In `run_studio`:
- add the parameter `on_issue=None`;
- after the report loop, add:

```python
    if on_issue:
        for r in report:
            if r["qc"]:
                on_issue(r["slide_id"], r["qc"])
```

The engine passes:

```python
            on_issue=lambda sid, qc: issues.file_issue(
                "deck_qc", "layout", f"Slide layout problem survives repair: {qc[0].split(':')[0]}",
                {"run_id": run_id, "slide_id": sid, "qc": qc}, project_id),
```

Import `issues` at the top of `run_engine`'s studio block: `from ..agent.repair import issues`.

- [ ] **Step 5: Real `report_issue`** (`tools.py`)

```python
def _report_issue(ctx, args):
    from .repair import issues
    issue_id, new = issues.file_issue("user", "user_report", args["title"],
                                      {"page": args.get("page", ""), "detail": args.get("detail", "")}, ctx.project_id)
    return {"issue_id": issue_id, "new": new}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_issues.py agent/tests/test_deliverable_engine.py agent/tests/test_deliverable_progress.py agent/tests/test_deckstudio_pipeline.py agent/tests/test_agent_copilot.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/agent/redact.py agent/app/domains/agent/repair agent/app/domains/deliverable/engine.py agent/app/domains/deckstudio/pipeline.py agent/app/domains/agent/tools.py
git commit -m "feat(agent): redacted issue intake from engine failures, surviving QC flags, progress calibration and user reports"
```

### Task 14: Browser QA agent

**Files:**
- Create: `agent/app/domains/agent/qa_browser.py` (module plus `__main__` CLI)
- Create fixture pages: `agent/tests/fixtures/qa/faded.html`, `codes.html`, `contrast.html`, `pills.html`, `clean.html`
- Test: `agent/tests/test_agent_qa_browser.py`

**Interfaces:**
- Consumes:
  - Task 13: `issues.file_issue`.
  - Existing: `store.create_session`, `store.delete_session`, `SESSION_COOKIE_NAME`.
- Produces:
  - `Finding(page, kind, detail, screenshot=None)`, a frozen dataclass.
  - `WALK = ("landing", "projects", "dashboard", "background-research", "search-strategy", "data-sources", "deliverables")`
  - Generic finding kinds:
    - `faded_on_load`: root content opacity below 0.6 at 150 ms;
    - `internal_code`: visible `RQn` text without the question beside it;
    - `low_contrast`: below 4.5:1, or below 3:1 for large text;
    - `overflow_x`.
  - Page-specific finding kinds:
    - `stage_pills_wrap` (deliverables);
    - `stat_mismatch` and `empty_activity` (dashboard);
    - `url_project_mismatch` (projects, needs `data-project-id` on the cards, Task 21 Step 1).
  - From the network log: `console_error`, `failed_request` (any 400+ response).
  - `check_page(page, name: str, project_id: int | None) -> list[Finding]`
  - `walk(base_url: str, user_id: int, project_id: int, out_dir: Path, pages=WALK) -> list[Finding]`
  - `file_findings(findings, project_id) -> list[int]`
  - CLI: `python -m agent.app.domains.agent.qa_browser --user 1 --project 262 [--base URL] [--pages a,b] [--file]`. It prints `page kind detail` lines.

- [ ] **Step 1: Fixture pages**

`faded.html`:
```html
<!doctype html><html><head><style>@keyframes f{from{opacity:0}to{opacity:1}}#root>div{animation:f 2s both}</style></head>
<body><div id="root"><div><p style="color:#111">Content</p></div></div></body></html>
```
`codes.html`:
```html
<!doctype html><html><body><div id="root"><p>Drafting cited insights for RQ4</p></div></body></html>
```
`contrast.html`:
```html
<!doctype html><html><body style="background:#fff"><div id="root"><p style="color:#ddd;font-size:14px">Hard to read</p></div></body></html>
```
`pills.html`:
```html
<!doctype html><html><body><div id="root" style="width:500px"><ol aria-label="Deliverable stages" style="display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0">
<li style="padding:6px 12px">Checking approvals</li><li style="padding:6px 12px">Ingesting datasets</li><li style="padding:6px 12px">Routing articles</li>
<li style="padding:6px 12px">Planning analyses</li><li style="padding:6px 12px">Classifying entities</li></ol></div></body></html>
```
`clean.html`:
```html
<!doctype html><html><body style="background:#fff"><div id="root"><h1 style="color:#111">Fine</h1><p style="color:#222">RQ4 "Which experts are cited?"</p></div></body></html>
```

- [ ] **Step 2: Write the failing tests**

```python
"""Browser QA checks against fixture pages (real Chromium)."""
from __future__ import annotations
import os, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from pathlib import Path
import pytest
from agent.app.domains.agent import qa_browser as QA

FIX = Path(__file__).parent / "fixtures" / "qa"


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b.new_page(viewport={"width": 1280, "height": 800})
        b.close()


def kinds(page, name, check="any"):
    page.goto((FIX / name).as_uri())
    return {f.kind for f in QA.check_page(page, check, None)}


def test_faded_page_detected(page):
    assert "faded_on_load" in kinds(page, "faded.html")


def test_internal_codes_detected_but_not_with_question(page):
    assert "internal_code" in kinds(page, "codes.html")
    assert "internal_code" not in kinds(page, "clean.html")


def test_low_contrast_detected(page):
    assert "low_contrast" in kinds(page, "contrast.html")


def test_stage_pills_wrap_detected(page):
    assert "stage_pills_wrap" in kinds(page, "pills.html", "deliverables")


def test_clean_page_has_no_findings(page):
    assert kinds(page, "clean.html") == set()


def test_dashboard_helpers():
    assert QA._zeroish("Insights\n0\nacross 3 questions") and QA._zeroish("Downloads\nNone")
    assert not QA._zeroish("Insights\n14")
    assert QA._activity_empty("Recent Activity\nNo activity yet") and QA._activity_empty("Recent Activity")
    assert not QA._activity_empty("Recent Activity\nrun deliverable\nautopilot")
```

Run: `$PY -m pytest agent/tests/test_agent_qa_browser.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'qa_browser'`.

- [ ] **Step 3: Write `qa_browser.py`**

```python
"""The browser QA agent: walks a project's main pages with Playwright, checks what a person would notice (faded pages,
unreadable text, overflowing content, internal codes, console errors, failed requests, wrong counts) and files each
finding as an issue."""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from ...core import config, store
from ...core.auth import SESSION_COOKIE_NAME

logger = logging.getLogger(__name__)
WALK = ("landing", "projects", "dashboard", "background-research", "search-strategy", "data-sources", "deliverables")
FADE_SAMPLE_MS = 150
FADED_BELOW = 0.6
SETTLE_MS = 1500
NAV_TIMEOUT_MS = 30000
_EMPTY_ACTIVITY = ("no activity", "no recent")


@dataclass(frozen=True)
class Finding:
    page: str
    kind: str
    detail: str
    screenshot: str | None = None


GENERIC_CHECKS_JS = r"""() => {
  const out = [];
  const lum = c => { const m = c.match(/[\d.]+/g); if (!m) return null; const [r, g, b] = m.slice(0, 3).map(Number)
    .map(v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    return [.2126 * r + .7152 * g + .0722 * b, m[3]]; };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
    if (s.backgroundImage !== 'none') return null; const m = s.backgroundColor.match(/[\d.]+/g);
    if (m && (m.length < 4 || Number(m[3]) > .5)) return s.backgroundColor; } return 'rgb(255,255,255)'; };
  const root = document.getElementById('root') || document.body;
  const seen = new Set();
  for (const el of root.querySelectorAll('*')) {
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    const r = el.getBoundingClientRect();
    if (!own || r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || Number(s.opacity) === 0) continue;
    const text = el.innerText.trim();
    if (/\bRQ\d+\b/.test(text) && !/\bRQ\d+\b\s*[:"“-]?\s*["“]?\s*\w+.*\?/.test(text) && !seen.has('code')) {
      seen.add('code'); out.push({kind: 'internal_code', detail: text.slice(0, 120)}); }
    const bg = bgOf(el); const f = lum(s.color); const b = bg && lum(bg);
    if (f && b && (f[1] === undefined || Number(f[1]) > .5)) {
      const ratio = (Math.max(f[0], b[0]) + .05) / (Math.min(f[0], b[0]) + .05);
      const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && Number(s.fontWeight) >= 700);
      const key = 'contrast:' + text.slice(0, 30);
      if (ratio < (big ? 3 : 4.5) && !seen.has(key)) {
        seen.add(key); out.push({kind: 'low_contrast', detail: `${ratio.toFixed(2)}:1 "${text.slice(0, 60)}"`}); }
    }
  }
  if (document.documentElement.scrollWidth > innerWidth + 2)
    out.push({kind: 'overflow_x', detail: `${document.documentElement.scrollWidth}px wide in a ${innerWidth}px window`});
  return out;
}"""
FADE_JS = """() => { const r = document.getElementById('root') || document.body; let min = 1;
  for (let e = r.firstElementChild || r; e; e = e.firstElementChild) {
    min = Math.min(min, Number(getComputedStyle(e).opacity)); if (e.children.length !== 1) break; } return min; }"""
PILLS_JS = """() => { const ol = document.querySelector('[aria-label="Deliverable stages"]'); if (!ol) return null;
  return new Set([...ol.children].map(li => Math.round(li.getBoundingClientRect().top))).size; }"""
DASHBOARD_JS = """async (pid) => {
  const r = await fetch(`/api/intel/deliverable/${pid}/latest`, {credentials: 'include'}); if (!r.ok) return null;
  const d = await r.json();
  const ev = await fetch(`/api/intel/agent/${pid}/events?limit=1`, {credentials: 'include'});
  const events = ev.ok ? await ev.json() : [];
  const leaf = label => [...document.querySelectorAll('*')].find(e => e.childElementCount === 0 && e.textContent.trim() === label);
  const card = label => { const el = leaf(label); const box = el && el.closest('div'); return box && box.parentElement ? box.parentElement.innerText : ''; };
  const heading = leaf('Recent Activity'); const panel = heading && heading.closest('section') || (heading && heading.parentElement && heading.parentElement.parentElement);
  return {completed: !!(d.run && d.run.status === 'completed'), insights: card('Insights'), slides: card('Slides'),
          downloads: card('Downloads'), activityText: panel ? panel.innerText : '', hasActivity: events.length > 0 || !!d.run}; }"""


def _zeroish(card_text: str) -> bool:
    return any(line.strip() in ("0", "None") for line in card_text.splitlines())


def _activity_empty(panel_text: str) -> bool:
    lines = [l.strip() for l in panel_text.splitlines() if l.strip() and l.strip() != "Recent Activity"]
    return not lines or any(l.lower().startswith(_EMPTY_ACTIVITY) for l in lines)


def check_page(page, name: str, project_id: int | None) -> list[Finding]:
    found: list[Finding] = []
    page.wait_for_timeout(FADE_SAMPLE_MS)
    opacity = page.evaluate(FADE_JS)
    if opacity < FADED_BELOW:
        found.append(Finding(name, "faded_on_load", f"page content opacity {opacity:.2f} {FADE_SAMPLE_MS}ms after load"))
    page.wait_for_timeout(SETTLE_MS)
    found += [Finding(name, f["kind"], f["detail"]) for f in page.evaluate(GENERIC_CHECKS_JS)]
    if name in ("deliverables", "any"):
        rows = page.evaluate(PILLS_JS)
        if rows and rows > 1:
            found.append(Finding(name, "stage_pills_wrap", f"stage list spans {rows} rows"))
    if name == "dashboard" and project_id:
        d = page.evaluate(DASHBOARD_JS, project_id)
        if d and d["completed"] and any(_zeroish(d[k]) for k in ("insights", "slides", "downloads")):
            found.append(Finding(name, "stat_mismatch", "dashboard shows 0/None while the deliverable run is complete"))
        if d and d["hasActivity"] and _activity_empty(d["activityText"]):
            found.append(Finding(name, "empty_activity", "Recent Activity is empty although the project has runs"))
    return found


def _check_project_switch(page, project_id: int) -> list[Finding]:
    card = page.locator(f"[data-project-id='{project_id}']").first
    if card.count() == 0:
        return []
    card.click()
    page.wait_for_timeout(SETTLE_MS)
    path = page.evaluate("() => location.pathname")
    return [] if path.startswith(f"/{project_id}/") else [
        Finding("projects", "url_project_mismatch", f"after opening project {project_id} the URL is {path}")]


def walk(base_url: str, user_id: int, project_id: int, out_dir: Path, pages=WALK) -> list[Finding]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    token, _ = store.create_session(user_id)
    host = base_url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies([{"name": SESSION_COOKIE_NAME, "value": token, "domain": host, "path": "/"}])
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url.split('?')[0]}") if r.status >= 400 else None)
            for name in pages:
                errors.clear()
                path = f"/{name}" if name in ("landing", "projects") else f"/{project_id}/{name}"
                page.goto(base_url.rstrip("/") + path, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                here = check_page(page, name, project_id)
                if name == "projects":
                    here += _check_project_switch(page, project_id)
                here += [Finding(name, "failed_request" if e.startswith("HTTP") else "console_error", e[:200])
                         for e in dict.fromkeys(errors)]
                if here:
                    shot = out_dir / f"{name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    here = [Finding(f.page, f.kind, f.detail, str(shot)) for f in here]
                findings += here
            browser.close()
    finally:
        store.delete_session(token)
    return findings


def file_findings(findings: list[Finding], project_id: int) -> list[int]:
    from .repair import issues
    return [issues.file_issue("qa_browser", f.kind, f"{f.page}: {f.kind}",
                              {"page": f.page, "kind": f.kind, "detail": f.detail, "screenshot": f.screenshot},
                              project_id)[0] for f in findings]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Walk the app as a user and report what looks broken.")
    ap.add_argument("--base", default="http://127.0.0.1:8002")
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--pages", default=",".join(WALK))
    ap.add_argument("--file", action="store_true", help="file each finding as an issue")
    a = ap.parse_args(argv)
    found = walk(a.base, a.user, a.project, config.DATA_DIR / "qa" / str(a.project), a.pages.split(","))
    for f in found:
        print(f.page, f.kind, f.detail)
    if a.file:
        print("filed", file_findings(found, a.project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_qa_browser.py -q -p no:cacheprovider`
Expected: PASS (6 passed).

- [ ] **Step 5: Detection run on the current (pre-fix) build** (spec acceptance; Ruling R5)

The backend must be running on 8002 with the built SPA. Run: `$PY -m agent.app.domains.agent.qa_browser --user 1 --project 262 --file`

Expected findings include:
- `failed_request` (`/execution/262`);
- `faded_on_load` (data-sources);
- `stage_pills_wrap` (deliverables);
- `stat_mismatch` and `empty_activity` (dashboard).

`internal_code` appears on deliverables when the page shows a run log with `RQn`.

Record the printed lines in the ledger as `Task 14: QA detection on pre-fix build: <kinds>`. If an expected kind is missing, treat it as a defect in the check and debug it with superpowers:systematic-debugging before continuing. The DASHBOARD_JS card lookup is the likeliest place to need adjusting against the real DOM.

- [ ] **Step 6: Commit**

```bash
git add agent/app/domains/agent/qa_browser.py
git commit -m "feat(agent): browser QA agent that walks a project's pages and files findings"
```

### Task 15: Diff tiers

**Files:**
- Create: `agent/app/domains/agent/repair/tiers.py`
- Test: `agent/tests/test_agent_tiers.py`

**Interfaces:**
- Produces:
  - `classify(diff: str, read_source=None) -> tuple[str, str]`, returning `("auto" | "inbox" | "never", reason)`.
  - `parse(diff: str) -> list[dict]`. Each item is `{"path", "deleted", "new", "added", "removed"}`.
  - Path rule constants:
    - `NEVER`: paths that are never auto-applied (env, config, auth, migrations, data, dependency manifests).
    - `AUTO_ANY`: deck templates.
    - `AUTO_CLASSNAME`: `.tsx` files where only `className` strings change.
    - `AUTO_CONSTANTS`: chart and style constants.
    - `IGNORED`: `agent/tests/**`.
  - Prompt-only rule: a `.py` file whose changed lines are all string literals, in a file that contains `_PROMPT =`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tier rules: design-only diffs auto-apply, logic goes to the inbox, protected paths never apply."""
from __future__ import annotations
from agent.app.domains.agent.repair.tiers import classify


def D(path, removed, added, deleted=False):
    head = (f"diff --git a/{path} b/{path}\n" + ("deleted file mode 100644\n" if deleted else "")
            + f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n")
    return head + "".join(f"-{r}\n" for r in removed) + "".join(f"+{a}\n" for a in added)


def test_template_change_is_auto():
    assert classify(D("agent/app/domains/deckstudio/templates/slide.html.j2", ["<div>"], ["<div class='x'>"]))[0] == "auto"


def test_classname_only_tsx_is_auto():
    d = D("web/src/components/deliverable/RunTimeline.tsx",
          ['    <ol className="flex flex-wrap gap-2" aria-label="Deliverable stages">'],
          ['    <ol className="flex flex-nowrap gap-1 overflow-x-auto" aria-label="Deliverable stages">'])
    assert classify(d)[0] == "auto"


def test_tsx_logic_change_goes_to_inbox():
    assert classify(D("web/src/pages/Dashboard.tsx", ["  const n = 0;"], ["  const n = items.length;"]))[0] == "inbox"


def test_chart_constant_is_auto_but_function_is_inbox():
    assert classify(D("agent/app/domains/deckstudio/charts.py", ["LABEL_W = 300"], ["LABEL_W = 340"]))[0] == "auto"
    assert classify(D("agent/app/domains/deckstudio/charts.py", ["    return w"], ["    return w + 1"]))[0] == "inbox"


def test_prompt_wording_is_auto():
    d = D("agent/app/domains/deckstudio/creative.py", ['           "Keep text short.")'], ['           "Keep text short and calm.")'])
    assert classify(d, read_source=lambda p: '_PROMPT = ("x"\n')[0] == "auto"


def test_python_logic_is_inbox():
    assert classify(D("agent/app/domains/deliverable/engine.py", ["x = 1"], ["x = compute()"]))[0] == "inbox"


def test_protected_paths_never():
    for p in (".env", "agent/app/core/auth.py", "agent/app/core/db.py", "requirements.txt", "web/package.json",
              "agent/app/domains/auth/router.py"):
        assert classify(D(p, ["a"], ["b"]))[0] == "never", p


def test_file_deletion_never():
    assert classify(D("agent/app/domains/deckstudio/templates/table.html.j2", ["x"], [], deleted=True))[0] == "never"


def test_mixed_design_and_logic_is_inbox():
    d = D("agent/app/domains/deckstudio/templates/slide.html.j2", ["a"], ["b"]) + D("agent/app/domains/x.py", ["a"], ["b"])
    assert classify(d)[0] == "inbox"


def test_tests_are_ignored_for_tier():
    d = (D("agent/app/domains/deckstudio/templates/slide.html.j2", ["a"], ["b"])
         + D("agent/tests/test_autofix_1.py", [], ["def test(): pass"]))
    assert classify(d)[0] == "auto"


def test_empty_diff_never():
    assert classify("")[0] == "never"
```

Run: `$PY -m pytest agent/tests/test_agent_tiers.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 2: Write `tiers.py`**

```python
"""Which proposed fixes may apply themselves. Design-only changes (deck templates, Tailwind classes, chart styling
constants, prompt wording) auto-apply behind a health check; logic waits in the Fixes inbox; secrets, config, auth,
migrations, dependencies and deletions are never applied."""
from __future__ import annotations

import re
from fnmatch import fnmatch

NEVER = (".env*", "*/.env*", "agent/app/core/auth.py", "agent/app/domains/auth/*", "agent/app/core/db.py",
         "agent/app/core/config.py", "requirements*.txt", "pyproject.toml", "web/package.json", "web/package-lock.json",
         "agent/data/*")
AUTO_ANY = ("agent/app/domains/deckstudio/templates/*",)
AUTO_CLASSNAME = ("web/src/*.tsx",)
AUTO_CONSTANTS = ("agent/app/domains/deckstudio/charts.py", "agent/app/domains/deliverable/style.py")
IGNORED = ("agent/tests/*",)
_CLASSNAME = re.compile(r'className=(\{`[^`]*`\}|"[^"]*"|\'[^\']*\')')
_CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*\s*=\s*[-\w.\"'(), \[\]{}:#]+$")
_STRING_LINE = re.compile(r"""^\s*[rbuf]*["'].*["']\)?,?\s*$""")


def _match(path: str, globs) -> bool:
    return any(fnmatch(path, g) for g in globs)        # fnmatch's * also matches '/'


def parse(diff: str) -> list[dict]:
    files, cur = [], None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            cur = {"path": line.split(" b/", 1)[-1], "deleted": False, "new": False, "added": [], "removed": []}
            files.append(cur)
        elif cur is None or line.startswith(("+++", "---", "@@", "index ")):
            continue
        elif line.startswith("deleted file mode"):
            cur["deleted"] = True
        elif line.startswith("new file mode"):
            cur["new"] = True
        elif line.startswith("+"):
            cur["added"].append(line[1:])
        elif line.startswith("-"):
            cur["removed"].append(line[1:])
    return files


def _classname_only(f: dict) -> bool:
    strip = lambda lines: sorted(_CLASSNAME.sub("className=_", l) for l in lines)
    return bool(f["added"] or f["removed"]) and strip(f["added"]) == strip(f["removed"])


def _constants_only(f: dict) -> bool:
    return all(_CONSTANT.match(l.strip()) for l in f["added"] + f["removed"] if l.strip())


def _prompt_only(f: dict, read_source) -> bool:
    if not f["path"].endswith(".py") or f["new"] or read_source is None:
        return False
    lines = [l for l in f["added"] + f["removed"] if l.strip()]
    return bool(lines) and all(_STRING_LINE.match(l) for l in lines) and "_PROMPT =" in (read_source(f["path"]) or "")


def classify(diff: str, read_source=None) -> tuple[str, str]:
    files = [f for f in parse(diff) if not _match(f["path"], IGNORED)]
    if not files:
        return "never", "empty diff"
    for f in files:
        if f["deleted"]:
            return "never", f"deletes {f['path']}"
        if _match(f["path"], NEVER):
            return "never", f"touches protected {f['path']}"
    for f in files:
        if _match(f["path"], AUTO_ANY):
            continue
        if _match(f["path"], AUTO_CLASSNAME) and _classname_only(f):
            continue
        if f["path"] in AUTO_CONSTANTS and _constants_only(f):
            continue
        if _prompt_only(f, read_source):
            continue
        return "inbox", f"logic change in {f['path']}"
    return "auto", "design-only change: " + ", ".join(f["path"] for f in files)
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_tiers.py -q -p no:cacheprovider`
Expected: PASS (11 passed).

- [ ] **Step 4: Commit**

```bash
git add agent/app/domains/agent/repair/tiers.py
git commit -m "feat(agent): diff tiers - design-only auto, logic to inbox, protected paths never"
```

### Task 16: Git worktrees for fixes

**Files:**
- Create: `agent/app/domains/agent/repair/worktree.py`
- Test: `agent/tests/test_agent_worktree.py`

**Interfaces:**
- Consumes (Task 6): `config.REPO_ROOT` and `config.DATA_DIR`. Both are read at call time.
- Produces:
  - `Worktree(path: Path, branch: str, base: str)`, a frozen dataclass.
  - `create(issue_id: int, repo: Path | None = None) -> Worktree`
    - Branch name: `autofix/<issue_id>-<epoch>`.
    - Path: `DATA_DIR/autofix/<branch with / → ->`.
    - Copies `agent/tests/` into the new worktree (R8).
  - `run(wt, args: list[str], timeout: int = 1800, env_extra: dict | None = None, cwd_rel: str = "") -> tuple[int, str]`
    - Runs with `HUNTER_AGENT_DATA_DIR` pointed at a fresh temp dir (R4).
    - Maps `"python"` to `sys.executable`.
    - Returns the exit code and the last 8000 characters of output.
  - `diff(wt) -> str`: the change against `wt.base`, excluding `agent/tests`.
  - `commit(wt, message: str) -> str`: returns the sha.
  - `tree_clean(repo=None) -> bool`: `git status --porcelain --untracked-files=no` is empty.
  - `merge(branch: str, repo=None) -> str`: `--no-ff --no-edit`; returns the merge sha.
  - `revert(sha: str, repo=None) -> str`: `-m 1 --no-edit`.
  - `remove(wt, repo=None) -> None`: refuses any path outside `DATA_DIR/autofix`.

- [ ] **Step 1: Write the failing tests** (on a throwaway repo)

```python
"""Worktree lifecycle on a temp repo: create, change, diff, commit, merge, revert, clean-tree check."""
from __future__ import annotations
import os, subprocess, tempfile
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.core import config
from agent.app.domains.agent.repair import worktree as W


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    (r / "agent" / "tests").mkdir(parents=True)
    (r / "app.txt").write_text("v1\n")
    (r / ".gitignore").write_text("agent/tests/\n")
    (r / "agent" / "tests" / "test_x.py").write_text("def test_ok(): pass\n")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "a@b"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "a@b")):
        monkeypatch.setenv(k, v)
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "REPO_ROOT", r)
    return r


def test_full_cycle(repo):
    wt = W.create(7, repo)
    assert wt.branch.startswith("autofix/7-") and (wt.path / "agent" / "tests" / "test_x.py").exists()
    (wt.path / "app.txt").write_text("v2\n")
    d = W.diff(wt)
    assert "+v2" in d and "agent/tests" not in d
    W.commit(wt, "fix: v2")
    assert W.tree_clean(repo)
    sha = W.merge(wt.branch, repo)
    assert (repo / "app.txt").read_text() == "v2\n"
    W.revert(sha, repo)
    assert (repo / "app.txt").read_text() == "v1\n"
    W.remove(wt, repo)
    assert not wt.path.exists()


def test_run_isolates_data_dir_and_honours_cwd(repo):
    wt = W.create(8, repo)
    (wt.path / "sub").mkdir()
    code, out = W.run(wt, ["python", "-c", "import os; print(os.environ['HUNTER_AGENT_DATA_DIR']); print(os.getcwd())"],
                      cwd_rel="sub")
    assert code == 0 and str(config.DATA_DIR) not in out.splitlines()[0] and out.strip().endswith("sub")
    W.remove(wt, repo)


def test_dirty_tree_detected(repo):
    (repo / "app.txt").write_text("local edit\n")
    assert not W.tree_clean(repo)


def test_remove_refuses_foreign_path(repo, tmp_path):
    with pytest.raises(RuntimeError):
        W.remove(W.Worktree(path=tmp_path / "elsewhere", branch="x", base=""), repo)
```

Run: `$PY -m pytest agent/tests/test_agent_worktree.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError`.

- [ ] **Step 2: Write `worktree.py`**

```python
"""Git worktrees for proposed fixes: each fix is made on its own branch in its own folder under DATA_DIR/autofix,
tested there against a throwaway data dir, and merged into the main checkout only on apply."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ....core import config

OUTPUT_TAIL = 8000
TESTS_DIR = Path("agent") / "tests"


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base: str


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def create(issue_id: int, repo: Path | None = None) -> Worktree:
    repo = repo or config.REPO_ROOT
    branch = f"autofix/{issue_id}-{int(time.time())}"
    path = config.DATA_DIR / "autofix" / branch.replace("/", "-")
    path.parent.mkdir(parents=True, exist_ok=True)
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    if (repo / TESTS_DIR).is_dir():
        shutil.copytree(repo / TESTS_DIR, path / TESTS_DIR, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    return Worktree(path=path, branch=branch, base=base)


def run(wt: Worktree, args: list[str], timeout: int = 1800, env_extra: dict | None = None,
        cwd_rel: str = "") -> tuple[int, str]:
    data = tempfile.mkdtemp(prefix="autofix_data_")
    env = {**os.environ, "HUNTER_AGENT_DATA_DIR": data, **(env_extra or {})}
    cmd = [sys.executable if args[0] == "python" else args[0], *args[1:]]
    try:
        r = subprocess.run(cmd, cwd=wt.path / cwd_rel, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr)[-OUTPUT_TAIL:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    finally:
        shutil.rmtree(data, ignore_errors=True)


def _stage(wt: Worktree) -> None:
    _git(wt.path, "add", "-A", "--", ".", f":(exclude){TESTS_DIR.as_posix()}")


def diff(wt: Worktree) -> str:
    _stage(wt)
    return _git(wt.path, "diff", "--cached", wt.base)


def commit(wt: Worktree, message: str) -> str:
    _stage(wt)
    _git(wt.path, "commit", "-q", "-m", message)
    return _git(wt.path, "rev-parse", "HEAD")


def tree_clean(repo: Path | None = None) -> bool:
    return _git(repo or config.REPO_ROOT, "status", "--porcelain", "--untracked-files=no") == ""


def merge(branch: str, repo: Path | None = None) -> str:
    repo = repo or config.REPO_ROOT
    _git(repo, "merge", "--no-ff", "--no-edit", branch)
    return _git(repo, "rev-parse", "HEAD")


def revert(sha: str, repo: Path | None = None) -> str:
    repo = repo or config.REPO_ROOT
    _git(repo, "revert", "--no-edit", "-m", "1", sha)
    return _git(repo, "rev-parse", "HEAD")


def remove(wt: Worktree, repo: Path | None = None) -> None:
    if (config.DATA_DIR / "autofix").resolve() not in wt.path.resolve().parents:
        raise RuntimeError(f"refusing to remove {wt.path}: not an autofix worktree")
    _git(repo or config.REPO_ROOT, "worktree", "remove", "--force", str(wt.path))
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_worktree.py -q -p no:cacheprovider`
Expected: PASS (4 passed).

- [ ] **Step 4: Commit**

```bash
git add agent/app/domains/agent/repair/worktree.py
git commit -m "feat(agent): isolated git worktrees for proposed fixes"
```

### Task 17: The fixer

**Files:**
- Create: `agent/app/domains/agent/repair/fixer.py`
- Test: `agent/tests/test_agent_fixer.py`

**Interfaces:**
- Consumes:
  - Task 4: `llm.chat_tools`.
  - Task 13: `redact.redact`, `store.get_issue`, `store.set_issue_status`, `store.create_fix`.
  - Task 15: `tiers.classify`.
  - Task 16: `worktree.*`.
- Produces:
  - `MAX_TURNS = 30`; `SUITE`, the full-suite pytest command (e2e excluded).
  - `_tool(wt, name, args) -> str`. Tools: `read_file`, `list_files`, `search`, `write_file`, `run_test`.
    - Any path outside the worktree, or matching `.env*`, `agent/data/*` or `.git/*`, returns `"refused: ..."`.
  - `propose(issue_id: int, llm, repo: Path | None = None, create_wt=worktree.create) -> dict`, returning `{"status": "proposed" | "discarded" | "needs_llm", "fix_id", "reason"}`.
    - Python issues: `agent/tests/test_autofix_<id>.py` must fail before the change, pass after it, and the suite must pass.
    - UI issues (`source == "qa_browser"`): `npx tsc --noEmit` must pass in `web/`, with `node_modules` reached via a junction to the main checkout (R3).

- [ ] **Step 1: Write the failing tests**

```python
"""Fixer: red-then-green gate, path confinement, no-LLM handling."""
from __future__ import annotations
import os, tempfile, time
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.core import store
from agent.app.domains.agent.repair import fixer, worktree as W
from agent.tests.test_agent_worktree import git, repo  # noqa: F401  (fixture)


def setup_module(_):
    store.init_intelligence_db()


def _issue():
    i, _ = store.file_issue_row(f"fx-{time.time()}", "engine", "exception", "add() returns wrong sum", {"stage": "x"}, None)
    return i


class Scripted:
    """Plays a fixed list of tool calls, one per turn, then stops."""
    def __init__(self, calls): self.calls, self.turn = calls, 0
    def is_reachable(self): return True
    def chat_tools(self, messages, tools, tool_choice="auto"):
        if self.turn >= len(self.calls):
            return {"content": "done", "tool_calls": [], "message": {"role": "assistant", "content": "done"}}
        name, args = self.calls[self.turn]
        self.turn += 1
        return {"content": None, "tool_calls": [{"id": str(self.turn), "name": name, "arguments": args}],
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": str(self.turn), "type": "function", "function": {"name": name, "arguments": "{}"}}]}}


@pytest.fixture
def calc_repo(repo):
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "calc")
    return repo


def test_red_then_green_proposes(calc_repo, monkeypatch):
    monkeypatch.setattr(fixer, "SUITE", ["python", "-m", "pytest", "agent/tests", "-q", "-p", "no:cacheprovider"])
    iid = _issue()
    test = "import sys, os\nsys.path.insert(0, os.getcwd())\nfrom calc import add\ndef test_add():\n    assert add(2, 2) == 4\n"
    llm = Scripted([("write_file", {"path": f"agent/tests/test_autofix_{iid}.py", "content": test}),
                    ("write_file", {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"})])
    out = fixer.propose(iid, llm, repo=calc_repo)
    assert out["status"] == "proposed", out
    fix = store.get_fix(out["fix_id"])
    assert "return a + b" in fix["diff"] and fix["tier"] == "inbox" and "passed" in fix["tests"]["green"]
    assert store.get_issue(iid)["status"] == "proposed"


def test_test_that_passes_before_change_is_discarded(calc_repo):
    iid = _issue()
    llm = Scripted([("write_file", {"path": f"agent/tests/test_autofix_{iid}.py", "content": "def test_x():\n    assert True\n"})])
    out = fixer.propose(iid, llm, repo=calc_repo)
    assert out["status"] == "discarded" and "does not reproduce" in out["reason"]


def test_paths_confined_to_worktree(calc_repo):
    wt = W.create(99, calc_repo)
    try:
        for bad in ("../../outside.txt", "C:/Windows/win.ini", ".env", "agent/data/memory.db"):
            assert fixer._tool(wt, "write_file", {"path": bad, "content": "x"}).startswith("refused"), bad
        assert fixer._tool(wt, "read_file", {"path": ".env"}).startswith("refused")
    finally:
        W.remove(wt, calc_repo)


def test_fixer_without_llm(calc_repo):
    iid = _issue()
    out = fixer.propose(iid, None, repo=calc_repo)
    assert out["status"] == "needs_llm" and store.get_issue(iid)["status"] == "needs_llm"
```

Run: `$PY -m pytest agent/tests/test_agent_fixer.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'fixer'`.

- [ ] **Step 2: Write `fixer.py`**

```python
"""The fixer: an Azure OpenAI tool loop confined to a git worktree. Python issues need a test that fails before the
change and passes after it, plus a green suite; UI issues need a clean type-check here and pass their browser QA
re-check after apply (Ruling R3). Anything else is discarded."""
from __future__ import annotations

import fnmatch
import json
import logging
import re
import subprocess
from pathlib import Path

from ....core import config, store
from ..redact import redact
from . import tiers, worktree

logger = logging.getLogger(__name__)
MAX_TURNS = 30
READ_LIMIT = 60000
SEARCH_HITS = 200
SUITE = ["python", "-m", "pytest", "agent/tests", "-x", "-q", "-p", "no:cacheprovider",
         "--ignore=agent/tests/test_e2e_live_workflow.py"]
_REFUSED = (".env*", "*/.env*", "agent/data/*", ".git/*")
_SYSTEM = ("You fix one problem in the Hunter codebase (FastAPI backend in agent/app, React frontend in web/src). Work "
           "only through the tools. For a backend problem: FIRST write a pytest file at {test} that reproduces the "
           "problem and fails today; THEN change the code so it passes. For a UI problem: change web/src only. Keep "
           "the change minimal and in the style of the surrounding code. Do not touch .env, auth, migrations or "
           "dependencies. Stop calling tools when done.")


def _fn(name: str, desc: str, required: list[str], props: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "required": required, "properties": props}}}


_S = {"type": "string"}
_TOOLS = [_fn("read_file", "Read a repo file", ["path"], {"path": _S}),
          _fn("list_files", "List repo files matching a glob", ["glob"], {"glob": _S}),
          _fn("search", "Regex search in files matching a glob", ["pattern"], {"pattern": _S, "glob": _S}),
          _fn("write_file", "Replace a repo file's full content", ["path", "content"], {"path": _S, "content": _S}),
          _fn("run_test", "Run one pytest file", ["path"], {"path": _S})]


def _inside(wt, rel: str) -> Path | None:
    root = wt.path.resolve()
    target = (wt.path / rel).resolve()
    if root not in target.parents:
        return None
    relpath = target.relative_to(root).as_posix()
    return None if any(fnmatch.fnmatch(relpath, p) for p in _REFUSED) else target


def _tool(wt, name: str, args: dict) -> str:
    if name in ("read_file", "write_file", "run_test"):
        target = _inside(wt, str(args.get("path", "")))
        if target is None:
            return "refused: path is outside the worktree or protected"
        if name == "read_file":
            return redact(target.read_text(encoding="utf-8", errors="replace")[:READ_LIMIT]) if target.is_file() else "no such file"
        if name == "write_file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get("content", ""), encoding="utf-8")
            return "written"
        code, out = worktree.run(wt, ["python", "-m", "pytest", str(args["path"]), "-q", "-p", "no:cacheprovider"])
        return f"exit {code}\n{out[-3000:]}"
    if name == "list_files":
        return "\n".join(p.relative_to(wt.path).as_posix() for p in wt.path.glob(args.get("glob", "**/*"))
                         if p.is_file() and ".git" not in p.parts)[:READ_LIMIT]
    if name == "search":
        rx, hits = re.compile(args.get("pattern", "")), []
        for p in wt.path.glob(args.get("glob") or "**/*.py"):
            if not p.is_file() or ".git" in p.parts or _inside(wt, p.relative_to(wt.path).as_posix()) is None:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(wt.path).as_posix()}:{n}: {line.strip()[:200]}")
        return redact("\n".join(hits[:SEARCH_HITS]))
    return f"unknown tool {name}"


def _converse(wt, llm, issue: dict, test_rel: str, ask: str, stop_when=None) -> None:
    detail = redact(json.dumps(issue.get("detail") or {}, default=str))[:6000]
    messages = [{"role": "system", "content": _SYSTEM.format(test=test_rel)},
                {"role": "user", "content": f"Problem: {redact(issue['title'])}\nSource: {issue['source']}\n"
                                            f"Detail: {detail}\n{ask}"}]
    for _ in range(MAX_TURNS):
        out = llm.chat_tools(messages, _TOOLS)
        if not out.get("tool_calls"):
            return
        messages.append(out["message"])
        for call in out["tool_calls"]:
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": _tool(wt, call["name"], call["arguments"])[:12000]})
            if stop_when and stop_when():
                return


def _discard(issue_id: int, wt, repo: Path, reason: str) -> dict:
    store.set_issue_status(issue_id, "discarded", reason)
    worktree.remove(wt, repo)
    return {"status": "discarded", "fix_id": None, "reason": reason}


def _junction_node_modules(wt, repo: Path) -> None:
    src, dst = repo / "web" / "node_modules", wt.path / "web" / "node_modules"
    if src.is_dir() and (wt.path / "web").is_dir() and not dst.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True)


def _pytest(wt, test_rel: str) -> tuple[int, str]:
    return worktree.run(wt, ["python", "-m", "pytest", test_rel, "-q", "-p", "no:cacheprovider"])


def propose(issue_id: int, llm, repo: Path | None = None, create_wt=worktree.create) -> dict:
    repo = repo or config.REPO_ROOT
    issue = store.get_issue(issue_id)
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        store.set_issue_status(issue_id, "needs_llm", "Azure OpenAI is not reachable")
        return {"status": "needs_llm", "fix_id": None, "reason": "Azure OpenAI is not reachable"}
    store.set_issue_status(issue_id, "fixing")
    wt = create_wt(issue_id, repo)
    ui = issue["source"] == "qa_browser"
    test_rel = f"agent/tests/test_autofix_{issue_id}.py"
    tests: dict[str, str] = {}
    try:
        if not ui:
            _converse(wt, llm, issue, test_rel, "First write only the test.",
                      stop_when=lambda: (wt.path / test_rel).exists())
            if not (wt.path / test_rel).exists():
                return _discard(issue_id, wt, repo, "no reproducing test was written")
            code, tests["red"] = _pytest(wt, test_rel)
            if code == 0:
                return _discard(issue_id, wt, repo, "the test does not reproduce the problem (it passes before the fix)")
        _converse(wt, llm, issue, test_rel, "Now make the change.")
        if not ui:
            code, tests["green"] = _pytest(wt, test_rel)
            if code != 0:
                return _discard(issue_id, wt, repo, "the fix does not make its test pass")
            code, out = worktree.run(wt, SUITE, timeout=3600)
            tests["suite"] = out[-1500:]
            if code != 0:
                return _discard(issue_id, wt, repo, "the full suite fails with the fix")
        else:
            _junction_node_modules(wt, repo)
            code, out = worktree.run(wt, ["cmd", "/c", "npx", "tsc", "--noEmit"], cwd_rel="web") \
                if (wt.path / "web").is_dir() else (0, "no web/ folder")
            tests["typecheck"] = out[-1500:]
            if code != 0:
                return _discard(issue_id, wt, repo, "the frontend no longer type-checks")
            tests["red"] = f"browser QA finding: {issue['kind']} ({(issue.get('detail') or {}).get('detail', '')})"[:500]
        diff = worktree.diff(wt)
        if not diff.strip():
            return _discard(issue_id, wt, repo, "no change was made")
        tier, why = tiers.classify(diff, read_source=lambda p: (wt.path / p).read_text(encoding="utf-8", errors="replace")
                                   if (wt.path / p).is_file() else None)
        worktree.commit(wt, f"fix: {issue['title'][:60]} (autofix #{issue_id})")
        fix_id = store.create_fix(issue_id, wt.branch, tier, diff, {**{k: v[-1500:] for k, v in tests.items()},
                                                                    "tier_reason": why})
        store.set_issue_status(issue_id, "proposed", f"fix {fix_id} ({tier})")
        return {"status": "proposed", "fix_id": fix_id, "reason": why}
    except Exception as e:      # a crashed attempt is recorded, never retried blindly
        logger.exception("fixer failed for issue %s", issue_id)
        return _discard(issue_id, wt, repo, f"fixer error: {type(e).__name__}")
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_fixer.py agent/tests/test_agent_worktree.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add agent/app/domains/agent/repair/fixer.py
git commit -m "feat(agent): worktree-confined fixer with a red-then-green test gate"
```

### Task 18: Supervisor, apply, health check and rollback

**Files:**
- Create:
  - `agent/supervisor.py`
  - `agent/app/domains/agent/repair/apply.py`
- Modify: `agent/app/main.py` lifespan. Call `apply.verify_pending_async()` after `autopilot.resume_all()`.
- Modify: `start.ps1`. Launch the backend through `-m agent.supervisor --port 8002` instead of uvicorn directly.
- Test: `agent/tests/test_agent_apply.py`

**Interfaces:**
- Consumes:
  - Task 14: `qa_browser.walk`.
  - Task 16: `worktree.tree_clean`, `worktree.merge`, `worktree.revert`.
  - Tasks 2 and 3: store fix and issue functions, `memory.remember`.
- Produces:
  - **Supervisor**
    - `supervisor.RESTART_CODE = 75`.
    - `supervisor.main(argv) -> int` re-runs uvicorn while it exits with code 75.
    - It sets `HUNTER_SUPERVISED=1` and `HUNTER_PORT`.
  - **Constants:** `apply.AUTO_APPLY_PER_HOUR = 3`, `MAX_CONSECUTIVE_ROLLBACKS = 2`, `HEALTH_TIMEOUT = 90`, `HEALTH_DELAY = 3`.
  - **`apply.apply_fix(fix_id: int, approved_by: str | None, restart=None, build_web=None) -> dict`**
    - Returns `{"status": "verifying" | "refused", "reason"}`.
    - `approved_by=None` means an auto-apply.
  - **`apply.verify_pending(health=None, qa=None, restart=None, build_web=None) -> list[int]`**
    - Pass: marks the fix applied.
    - Fail: reverts, rebuilds, marks rolled_back, counts the rollback, disables auto-apply on the second consecutive rollback (and files an `auto_apply_disabled` issue), then restarts.
  - `apply.verify_pending_async() -> None`.
  - `apply.auto_apply_enabled() -> bool`.
  - **Global switch:** memory row project 0, kind `"decision"`, key `"auto_apply"`, value `{"enabled", "rollbacks"}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Apply: refusals, merge + verify, rollback on failed health, auto-apply disabled after repeated rollbacks."""
from __future__ import annotations
import os, tempfile, time
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
import pytest
from agent.app.core import store
from agent.app.domains.agent.repair import apply as A, worktree as W
from agent.tests.test_agent_worktree import git, repo  # noqa: F401  (fixture; also points config at the temp repo)


def setup_module(_):
    store.init_intelligence_db()


def _make_fix(repo, content, tier="auto"):
    iid, _ = store.file_issue_row(f"ap-{time.time()}", "qa_browser", "faded_on_load", "data-sources: faded",
                                  {"page": "data-sources"}, None)
    wt = W.create(iid, repo)
    (wt.path / "app.txt").write_text(content)
    W.commit(wt, "fix")
    return store.create_fix(iid, wt.branch, tier, "diff", {})


@pytest.fixture
def fix(repo, monkeypatch):
    monkeypatch.setenv("HUNTER_SUPERVISED", "1")
    store.set_memory(0, "decision", "auto_apply", {"enabled": True, "rollbacks": 0})
    monkeypatch.setattr(A, "_auto_applied_last_hour", lambda: 0)
    for f in store.list_fixes():
        if f["status"] in ("applying", "verifying"):
            store.update_fix(f["id"], status="rolled_back")
    return _make_fix(repo, "v2\n")


NOOP = dict(restart=lambda: None, build_web=lambda: (0, ""))


def test_apply_refuses_dirty_tree(fix, repo):
    (repo / "app.txt").write_text("user edit\n")
    out = A.apply_fix(fix, None, **NOOP)
    assert out["status"] == "refused" and "uncommitted" in out["reason"]
    assert store.get_fix(fix)["status"] == "proposed" and (repo / "app.txt").read_text() == "user edit\n"


def test_never_tier_refused_even_when_approved(fix):
    store.update_fix(fix, tier="never")
    assert A.apply_fix(fix, "admin@x", **NOOP)["status"] == "refused"


def test_inbox_fix_not_auto_applied(fix):
    store.update_fix(fix, tier="inbox")
    assert A.apply_fix(fix, None, **NOOP)["status"] == "refused"


def test_unsupervised_refused(fix, monkeypatch):
    monkeypatch.delenv("HUNTER_SUPERVISED")
    assert "supervisor" in A.apply_fix(fix, "admin@x", **NOOP)["reason"]


def test_hourly_limit(fix, monkeypatch):
    monkeypatch.setattr(A, "_auto_applied_last_hour", lambda: A.AUTO_APPLY_PER_HOUR)
    assert "per hour" in A.apply_fix(fix, None, **NOOP)["reason"]


def test_apply_then_verify_ok(fix, repo):
    restarts = []
    assert A.apply_fix(fix, None, restart=lambda: restarts.append(1), build_web=lambda: (0, ""))["status"] == "verifying"
    assert (repo / "app.txt").read_text() == "v2\n" and restarts == [1]
    assert A.verify_pending(health=lambda: True, qa=lambda f: [], **NOOP) == [fix]
    assert store.get_fix(fix)["status"] == "applied"
    assert store.get_issue(store.get_fix(fix)["issue_id"])["status"] == "fixed"


def test_failed_check_rolls_back_and_second_rollback_disables(fix, repo):
    A.apply_fix(fix, None, **NOOP)
    A.verify_pending(health=lambda: False, qa=lambda f: [], **NOOP)
    assert store.get_fix(fix)["status"] == "rolled_back" and (repo / "app.txt").read_text() == "v1\n"
    assert A.auto_apply_enabled()
    second = _make_fix(repo, "v3\n")
    A.apply_fix(second, None, **NOOP)
    A.verify_pending(health=lambda: True, qa=lambda f: ["still faded"], **NOOP)
    assert store.get_fix(second)["status"] == "rolled_back" and not A.auto_apply_enabled()
    assert any(i["kind"] == "auto_apply_disabled" for i in store.list_issues("open"))


def test_supervisor_restarts_on_code(monkeypatch):
    from agent import supervisor
    codes = iter([supervisor.RESTART_CODE, supervisor.RESTART_CODE, 0])
    seen = []
    monkeypatch.setattr(supervisor.subprocess, "call", lambda cmd, env: seen.append(env["HUNTER_SUPERVISED"]) or next(codes))
    assert supervisor.main(["--port", "8002"]) == 0 and seen == ["1", "1", "1"]
```

Run: `$PY -m pytest agent/tests/test_agent_apply.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError`.

- [ ] **Step 2: Write `agent/supervisor.py`**

```python
"""Runs the backend and restarts it when it exits with RESTART_CODE: how an applied fix (or its rollback) takes effect.
Any other exit code stops the supervisor with that code."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

RESTART_CODE = 75


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", default="8002")
    a = ap.parse_args(argv)
    env = {**os.environ, "HUNTER_SUPERVISED": "1", "HUNTER_PORT": str(a.port)}
    cmd = [sys.executable, "-m", "uvicorn", "agent.app.main:app", "--host", a.host, "--port", str(a.port)]
    while True:
        code = subprocess.call(cmd, env=env)
        if code != RESTART_CODE:
            return code


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write `repair/apply.py`**

```python
"""Apply a proposed fix to the running app: merge, rebuild the frontend if needed, restart under the supervisor, then
verify after startup (API health + the browser QA re-check of the affected page). A failed check reverts the merge and
restarts again. Auto-apply is rate-limited and switches itself off after repeated rollbacks."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

from ....core import config, store
from .. import memory
from . import worktree

logger = logging.getLogger(__name__)
AUTO_APPLY_PER_HOUR = 3
MAX_CONSECUTIVE_ROLLBACKS = 2
HEALTH_TIMEOUT = 90
HEALTH_DELAY = 3
_GLOBAL = 0
_SETTING = "auto_apply"
_ACTIVE = ("applying", "verifying")


def _setting() -> dict:
    return next((m["value"] for m in store.list_memory(_GLOBAL, "decision") if m["key"] == _SETTING),
                {"enabled": True, "rollbacks": 0})


def auto_apply_enabled() -> bool:
    return bool(_setting().get("enabled", True))


def _auto_applied_last_hour() -> int:
    cutoff = time.time() - 3600
    return sum(1 for f in store.list_fixes() if f["note"].startswith("auto") and f["updated_at"] >= cutoff
               and f["status"] in ("applied", "verifying", "rolled_back"))


def _restart() -> None:
    from agent.supervisor import RESTART_CODE
    threading.Timer(1.0, os._exit, args=(RESTART_CODE,)).start()


def _build_web() -> tuple[int, str]:
    r = subprocess.run(["cmd", "/c", "npm", "run", "build"], cwd=config.REPO_ROOT / "web", capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)[-4000:]


def _refuse(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def _precheck(fix: dict | None, approved_by: str | None) -> str:
    if not fix or fix["status"] != "proposed":
        return "fix is not waiting to be applied"
    if fix["tier"] == "never":
        return "this change touches protected files and is never applied automatically or from the inbox"
    if approved_by is None and fix["tier"] != "auto":
        return "only design-only fixes apply without approval"
    if approved_by is None and not auto_apply_enabled():
        return "auto-apply is disabled after repeated rollbacks"
    if approved_by is None and _auto_applied_last_hour() >= AUTO_APPLY_PER_HOUR:
        return f"auto-apply limit of {AUTO_APPLY_PER_HOUR} per hour reached"
    if any(f["status"] in _ACTIVE for f in store.list_fixes()):
        return "another fix is being applied"
    if os.environ.get("HUNTER_SUPERVISED") != "1":
        return "the backend is not running under the supervisor, so it cannot restart itself"
    if not worktree.tree_clean():
        return "the main checkout has uncommitted changes"
    return ""


def apply_fix(fix_id: int, approved_by: str | None, restart=None, build_web=None) -> dict:
    fix = store.get_fix(fix_id)
    reason = _precheck(fix, approved_by)
    if reason:
        if fix and fix["status"] == "proposed" and "uncommitted" in reason:
            store.update_fix(fix_id, note=f"waiting: {reason}")
        return _refuse(reason)
    store.update_fix(fix_id, status="applying", note="auto" if approved_by is None else f"approved by {approved_by}")
    try:
        sha = worktree.merge(fix["branch"])
    except RuntimeError as e:
        store.update_fix(fix_id, status="proposed", note=f"merge failed: {e}"[:300])
        return _refuse(f"merge failed: {e}")
    test_file = (config.DATA_DIR / "autofix" / fix["branch"].replace("/", "-") / "agent" / "tests"
                 / f"test_autofix_{fix['issue_id']}.py")
    if test_file.exists():
        shutil.copy2(test_file, config.REPO_ROOT / "agent" / "tests" / test_file.name)
    if "web/" in fix["diff"]:
        code, out = (build_web or _build_web)()
        if code != 0:
            worktree.revert(sha)
            store.update_fix(fix_id, status="rolled_back", note=f"frontend build failed: {out[-200:]}")
            return _refuse("frontend build failed; reverted")
    store.update_fix(fix_id, status="verifying", commit_sha=sha)
    (restart or _restart)()
    return {"status": "verifying", "reason": "merged; restarting to verify"}


def _health() -> bool:
    import requests
    url = f"http://127.0.0.1:{os.environ.get('HUNTER_PORT', '8002')}/api/health"
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=5).json().get("ok"):
                return True
        except Exception:
            time.sleep(2)
    return False


def _qa_user() -> int:
    return next(u["id"] for u in store.list_users() if u["role"] == "super_admin")


def _qa(fix: dict) -> list[str]:
    issue = store.get_issue(fix["issue_id"]) or {}
    if issue.get("source") != "qa_browser":
        return []
    from ..qa_browser import walk
    page = (issue.get("detail") or {}).get("page") or "dashboard"
    found = walk(f"http://127.0.0.1:{os.environ.get('HUNTER_PORT', '8002')}", _qa_user(), issue.get("project_id") or 0,
                 config.DATA_DIR / "qa" / "verify", [page])
    return [f.detail for f in found if f.kind == issue["kind"]]


def _rolled_back(fix: dict, why: str, setting: dict, build_web) -> None:
    worktree.revert(fix["commit_sha"])
    if "web/" in fix["diff"]:
        (build_web or _build_web)()
    store.update_fix(fix["id"], status="rolled_back", note=f"verify failed: {why[:200]}")
    store.set_issue_status(fix["issue_id"], "open", f"fix {fix['id']} rolled back")
    rollbacks = setting.get("rollbacks", 0) + 1
    store.set_memory(_GLOBAL, "decision", _SETTING, {"enabled": rollbacks < MAX_CONSECUTIVE_ROLLBACKS,
                                                     "rollbacks": rollbacks})
    memory.remember(_GLOBAL, "fix", f"fix_{fix['id']}", {"outcome": "rolled_back", "why": why[:200]})
    if rollbacks >= MAX_CONSECUTIVE_ROLLBACKS:
        from .issues import file_issue
        file_issue("repair", "auto_apply_disabled", "Auto-apply switched off after repeated rollbacks",
                   {"last_fix": fix["id"]})


def verify_pending(health=None, qa=None, restart=None, build_web=None) -> list[int]:
    done = []
    for fix in store.list_fixes("verifying"):
        ok = (health or _health)()
        still = (qa or _qa)(fix) if ok else ["health check failed"]
        setting = _setting()
        if ok and not still:
            store.update_fix(fix["id"], status="applied")
            store.set_issue_status(fix["issue_id"], "fixed", f"fix {fix['id']} applied")
            store.set_memory(_GLOBAL, "decision", _SETTING, {**setting, "rollbacks": 0})
            memory.remember(_GLOBAL, "fix", f"fix_{fix['id']}", {"outcome": "applied", "issue": fix["issue_id"]})
        else:
            _rolled_back(fix, still[0], setting, build_web)
            (restart or _restart)()
        done.append(fix["id"])
    return done


def verify_pending_async() -> None:
    if store.list_fixes("verifying"):
        threading.Timer(HEALTH_DELAY, verify_pending).start()
```

- [ ] **Step 4: Startup and `start.ps1`**

In `main.py` lifespan, after `autopilot.resume_all()`:

```python
    from .domains.agent.repair import apply as repair_apply
    repair_apply.verify_pending_async()
```

In `start.ps1`, find the line that starts uvicorn with `Select-String -Path start.ps1 -Pattern uvicorn`. Replace the uvicorn module and arguments with `"-m", "agent.supervisor", "--port", "8002"`, keeping that line's existing window, working-directory and log arguments.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_apply.py -q -p no:cacheprovider`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/supervisor.py agent/app/domains/agent/repair/apply.py agent/app/main.py start.ps1
git commit -m "feat(agent): supervised restart, verified apply with automatic rollback and auto-apply limits"
```

### Task 19: Fix worker and admin routes

**Files:**
- Create: `agent/app/domains/agent/repair/worker.py`
- Modify: `agent/app/domains/agent/router.py`. Add the super-admin routes and declare them before the `/agent/{project_id}` routes.
- Modify: `agent/app/main.py` lifespan. Start the worker when `HUNTER_AUTOFIX != "0"` and the process is supervised.
- Test: `agent/tests/test_agent_fix_routes.py`

**Interfaces:**
- Consumes:
  - Task 17: `fixer.propose`.
  - Task 18: `apply.apply_fix`.
  - Task 7: `autopilot._llm`.
- Produces:
  - `worker.POLL_SECONDS = 60`.
  - `worker.tick(llm, propose=fixer.propose, apply_fix=apply.apply_fix) -> dict | None`
    - Handles the oldest `open` issue: it proposes a fix, then auto-applies it if the fix's tier is `auto`.
  - `worker.start() -> None`.
  - Routes (super_admin only, `403` otherwise):
    - `GET /agent/admin/issues?status=`
    - `GET /agent/admin/fixes?status=`
    - `POST /agent/admin/fixes/{fix_id}/apply`
    - `POST /agent/admin/fixes/{fix_id}/reject` (body `{"reason"}`)
    - `POST /agent/admin/issues/{issue_id}/retry`

- [ ] **Step 1: Write the failing tests**

```python
"""Fix worker tick and admin routes."""
from __future__ import annotations
import os, tempfile, time
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from fastapi.testclient import TestClient
from agent.app.core import store
from agent.app.core.auth import get_current_user
from agent.app.domains.agent.repair import worker
from agent.app.main import app


def setup_module(_):
    store.init_intelligence_db()


def _only_open(source="engine"):
    for i in store.list_issues("open"):
        store.set_issue_status(i["id"], "discarded")
    i, _ = store.file_issue_row(f"w-{time.time()}", source, "k", "t", {}, None)
    return i


def test_tick_proposes_then_auto_applies_auto_tier():
    iid = _only_open()
    applied = []
    propose = lambda issue_id, llm: {"status": "proposed", "fix_id": store.create_fix(issue_id, "autofix/x", "auto", "d", {}),
                                     "reason": ""}
    out = worker.tick(None, propose=propose, apply_fix=lambda fid, by: applied.append((fid, by)) or {"status": "verifying"})
    assert out["issue_id"] == iid and applied and applied[0][1] is None


def test_tick_leaves_inbox_fixes_waiting():
    _only_open()
    applied = []
    propose = lambda issue_id, llm: {"status": "proposed", "fix_id": store.create_fix(issue_id, "b", "inbox", "d", {}),
                                     "reason": ""}
    worker.tick(None, propose=propose, apply_fix=lambda fid, by: applied.append(fid))
    assert applied == []


def test_admin_routes_require_super_admin():
    app.dependency_overrides[get_current_user] = lambda: {"id": 2, "role": "analyser", "org_id": 1, "email": "a@x"}
    try:
        assert TestClient(app).get("/api/intel/agent/admin/issues").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_reject_records_reason():
    iid = _only_open()
    fid = store.create_fix(iid, "autofix/none", "inbox", "d", {})
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "super_admin", "org_id": None, "email": "s@x"}
    try:
        r = TestClient(app).post(f"/api/intel/agent/admin/fixes/{fid}/reject", json={"reason": "wrong approach"})
        assert r.status_code == 200 and store.get_fix(fid)["status"] == "rejected"
        assert "wrong approach" in store.get_issue(iid)["note"]
    finally:
        app.dependency_overrides.clear()
```

Run: `$PY -m pytest agent/tests/test_agent_fix_routes.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'worker'`.

- [ ] **Step 2: Write `worker.py`**

```python
"""Background fix worker: one open issue at a time becomes a proposed fix; design-only fixes then apply themselves."""
from __future__ import annotations

import logging
import threading
import time

from ....core import store
from . import apply as apply_mod
from . import fixer

logger = logging.getLogger(__name__)
POLL_SECONDS = 60


def tick(llm, propose=fixer.propose, apply_fix=apply_mod.apply_fix) -> dict | None:
    open_issues = sorted(store.list_issues("open"), key=lambda i: i["id"])
    if not open_issues:
        return None
    issue = open_issues[0]
    out = propose(issue["id"], llm)
    result = {"issue_id": issue["id"], **out}
    if out.get("status") == "proposed" and (store.get_fix(out["fix_id"]) or {}).get("tier") == "auto":
        result["apply"] = apply_fix(out["fix_id"], None)
    return result


def _loop() -> None:
    from ..autopilot import _llm
    while True:
        try:
            if not any(f["status"] in ("applying", "verifying") for f in store.list_fixes()):
                tick(_llm())
        except Exception:       # the worker keeps running; the failure is in the log
            logger.exception("fix worker tick failed")
        time.sleep(POLL_SECONDS)


def start() -> None:
    threading.Thread(target=_loop, daemon=True, name="fix-worker").start()
```

- [ ] **Step 3: Admin routes** (in `router.py`, above `@router.get("/agent/{project_id}")`)

```python
from ...core import config
from . import memory
from .repair import apply as repair_apply, worktree
from .schemas import RejectBody


def _super_admin(user=Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Only a super admin can manage fixes")
    return user


@router.get("/agent/admin/issues")
def admin_issues(status: str | None = None, _a=Depends(_super_admin)):
    return store.list_issues(status)


@router.get("/agent/admin/fixes")
def admin_fixes(status: str | None = None, _a=Depends(_super_admin)):
    return store.list_fixes(status)


@router.post("/agent/admin/fixes/{fix_id}/apply")
def admin_apply(fix_id: Annotated[int, Path(ge=1)], admin=Depends(_super_admin)):
    return repair_apply.apply_fix(fix_id, admin["email"])


@router.post("/agent/admin/fixes/{fix_id}/reject")
def admin_reject(fix_id: Annotated[int, Path(ge=1)], body: RejectBody, admin=Depends(_super_admin)):
    fix = store.get_fix(fix_id)
    if not fix or fix["status"] != "proposed":
        raise HTTPException(409, "Only a proposed fix can be rejected")
    store.update_fix(fix_id, status="rejected", note=f"rejected by {admin['email']}: {body.reason}")
    store.set_issue_status(fix["issue_id"], "rejected", body.reason)
    memory.remember(0, "fix", f"fix_{fix_id}", {"outcome": "rejected", "why": body.reason})
    path = config.DATA_DIR / "autofix" / fix["branch"].replace("/", "-")
    if path.exists():
        worktree.remove(worktree.Worktree(path=path, branch=fix["branch"], base=""))
    return {"ok": True}


@router.post("/agent/admin/issues/{issue_id}/retry")
def admin_retry(issue_id: Annotated[int, Path(ge=1)], _a=Depends(_super_admin)):
    store.set_issue_status(issue_id, "open", "retry requested")
    return {"ok": True}
```

In `main.py` lifespan, after the `verify_pending_async()` call:

```python
    if os.environ.get("HUNTER_AUTOFIX", "1") == "1" and os.environ.get("HUNTER_SUPERVISED") == "1":
        from .domains.agent.repair import worker
        worker.start()
```

Add `import os` to `main.py` if it is not already there.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_agent_fix_routes.py agent/tests/test_agent_autopilot.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add agent/app/domains/agent/repair/worker.py agent/app/domains/agent/router.py agent/app/main.py
git commit -m "feat(agent): background fix worker and super-admin fix routes"
```

- [ ] **Step 6: Fixer acceptance on the Task 14 findings** (spec acceptance; Ruling R5)

Precondition: the backend runs under the supervisor (`.\start.ps1`) and Azure is configured in `.env`.

1. Wait for one worker tick per open issue, about 60 s each.
2. Monitor with: `$PY -c "from agent.app.core import store; [print(f['id'], f['issue_id'], f['tier'], f['status'], f['note'][:80]) for f in store.list_fixes()]"`

Expected:
- Design findings (`stage_pills_wrap`, `faded_on_load`) get `auto` fixes that end `applied`, or `rolled_back` with a reason.
- Logic findings (`stat_mismatch`, `empty_activity`, `failed_request`) get `inbox` fixes, or are `discarded` with a reason.

Record each outcome in the ledger as `Task 19: fixer on issue <id> <kind>: <tier> <status> <note>`. Every fix that ends `applied` turns the matching Task 21 step into a ledgered skip. Nothing to commit in this step.

---

## Phase 4: UI

### Task 20: Backend side of UI issues 4, 6 and 7, plus archived projects

**Files:**
- Modify: `agent/app/domains/execution/router.py:142-149` (issue 4)
- Modify: `web/src/services/intel-api.ts:930`: `getExecutionStatus` returns `| null`.
- Modify: `web/src/pages/ResearchExecution.tsx:331-346`: null-safe.
- Modify: `agent/app/domains/projects/schemas.py:58-68` and, if needed, `projects/repository.py`: add `archived_at` (supports issue 1).
- Modify: `agent/app/domains/deliverable/engine.py`:
  - `_rq_label` at the display sites (issue 6);
  - re-based `STAGE_WEIGHTS` and `typical_seconds` in progress (issue 7).
- Modify: `agent/app/domains/deliverable/repository.py`: add `recent_run_durations`.
- Test: `agent/tests/test_ui_backend_fixes.py`

**Interfaces:**
- Produces:
  - `GET /api/intel/execution/{pid}` returns `200` with a `null` body when there is no execution.
  - `engine._rq_label(q: RQ, limit: int = 90) -> str`.
  - The progress state gains `typical_seconds: float | None`, the median of the last 5 completed runs.
  - `store.recent_run_durations(limit: int = 5) -> list[float]`.
  - `ProjectResponse.archived_at: float | None`.

- [ ] **Step 1: Write the failing tests**

```python
"""Backend side of the 2026-10-07 UI issues."""
from __future__ import annotations
import os, tempfile, time
os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
from fastapi.testclient import TestClient
from agent.app.core import store
from agent.app.core.auth import get_current_user, require_project_access
from agent.app.domains.deliverable import engine
from agent.app.domains.deliverable.engine_types import RQ
from agent.app.main import app

ADMIN = {"id": 1, "role": "super_admin", "org_id": None}


def setup_module(_):
    store.init_intelligence_db()


def test_execution_status_without_run_is_null_not_404():
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[require_project_access] = lambda: ADMIN
    try:
        pid = store.get_or_create_project({"commissioning_brand": {"name": f"Exec {time.time()}"}})
        r = TestClient(app).get(f"/api/intel/execution/{pid}")
        assert r.status_code == 200 and r.json() is None
    finally:
        app.dependency_overrides.clear()


def test_rq_label_shows_question():
    q = RQ(id="RQ4", question="Which experts are cited, and are they affiliated with a brand?", query="")
    assert engine._rq_label(q) == 'RQ4 "Which experts are cited, and are they affiliated with a brand?"'
    assert engine._rq_label(q, 30).endswith('…"') and len(engine._rq_label(q, 30)) < 45
    assert engine._rq_label(RQ(id="RQ1", question="", query="")) == "RQ1"


def test_weights_follow_measured_shape():
    w = engine.STAGE_WEIGHTS
    assert sum(w.values()) == 100 and w["compose"] > w["classify"] and w["assets"] > w["ingest"]


def test_progress_carries_typical_duration(monkeypatch):
    sent = []
    monkeypatch.setattr(engine, "broadcast", sent.append)
    monkeypatch.setattr(engine.store, "recent_run_durations", lambda limit=5: [300.0, 360.0, 420.0])
    pid = store.get_or_create_project({"commissioning_brand": {"name": f"Typ {time.time()}"}})
    run = engine._Run(store.create_deliverable_run(pid), pid)
    run.progress(10, "x")
    assert sent[-1]["typical_seconds"] == 360.0


def test_project_response_has_archived_at():
    from agent.app.domains.projects.schemas import ProjectResponse
    assert "archived_at" in ProjectResponse.model_fields
```

Run: `$PY -m pytest agent/tests/test_ui_backend_fixes.py -q -p no:cacheprovider`
Expected: FAIL, for example `assert 404 == 200` and `AttributeError: _rq_label`.

- [ ] **Step 2: Execution route**

Keep the existing parameters. Change only the response model and the body:

```python
@router.get("/execution/{project_id}", response_model=ExecutionStatusResponse | None)
def get_execution_status(project_id: Annotated[int, Path(ge=1)], _u=Depends(require_project_access)):
    return executor_service.get_execution_status(project_id)
```

In `intel-api.ts:930`, change the return type to `<existing type> | null`.

In `ResearchExecution.tsx`:
- at lines 331-333, set the run only when data is present: `if (data) setRun(data as RunStatus)`;
- at line 346, guard the poll result the same way.

- [ ] **Step 3: RQ labels** (`engine.py`, next to `_STAGE_LABELS`)

```python
def _rq_label(q: RQ, limit: int = 90) -> str:
    """The question itself next to its id: analyst-authored text, never article content."""
    text = " ".join((q.question or "").split())
    if not text:
        return q.id
    return f'{q.id} "{text[:limit - 1]}…"' if len(text) > limit else f'{q.id} "{text}"'
```

Change display strings only; dict keys stay `q.id`. Update these sites:
- line 304: `"; ".join(_rq_label(q, 60) for q in rqs)`
- line 319: `f"{_rq_label(q)}: {len(rows_by_rq[q.id])} articles"`
- line 326: `f"{_rq_label(q)}: " + ", ".join(...)`
- line 327: `f"{_rq_label(q, 40)}: {len(plans[q.id]['modules'])}"`
- line 347: `f"{_rq_label(q)}: {len(drawn)} of ..."`
- line 355: `f"Drafting cited insights for {_rq_label(q, 60)}"`
- line 359: `f"{_rq_label(q)}: {len(insights_by_rq[q.id])} insights drafted"`
- the `_extract_all` labels at lines 176-179: `f"Classifying {kind} in {_rq_label(q, 50)}: ..."`, and the matching log line.

- [ ] **Step 4: Weights and typical duration**

```python
STAGE_WEIGHTS = {"gate": 0, "ingest": 0, "routing": 1, "plan": 4, "classify": 2, "compute": 1, "insights": 10,
                 "template": 1, "render": 17, "qc": 2, "index": 1, "design": 1, "assets": 22, "compose": 32, "export": 6}


def _typical_seconds() -> float | None:
    durations = sorted(store.recent_run_durations(5))
    return durations[len(durations) // 2] if durations else None
```

- In `_Run.__init__`, set `self.typical = _typical_seconds()`.
- In `_Run.progress`, add `"typical_seconds": self.typical` to `state`.

In `deliverable/repository.py`:

```python
def recent_run_durations(limit: int = 5) -> list[float]:
    conn = _conn()
    rows = conn.execute("SELECT finished_at - created_at AS d FROM intel_deliverable_runs WHERE status = 'completed' "
                        "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [r["d"] for r in rows if r["d"] and r["d"] > 0]
```

- [ ] **Step 5: `archived_at`**

1. Add `archived_at: float | None = None` to `ProjectResponse`.
2. Run `grep -n "archived_at\|def get_project" agent/app/domains/projects/repository.py`.
3. If `get_project` selects explicit columns without `archived_at`, add it to the select.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest agent/tests/test_ui_backend_fixes.py agent/tests/test_deliverable_progress.py agent/tests/test_deliverable_engine.py agent/tests/test_execution_gate.py agent/tests/test_agent_issues.py -q -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add agent/app/domains/execution/router.py agent/app/domains/projects/schemas.py agent/app/domains/projects/repository.py agent/app/domains/deliverable/engine.py agent/app/domains/deliverable/repository.py web/src/services/intel-api.ts web/src/pages/ResearchExecution.tsx
git commit -m "fix: no 404 without an execution run, full research questions in run text, progress weights from measured stage times"
```

### Task 21: Frontend fixes for UI issues 1, 2, 3, 5, 6, 7, 8 and 9

**Files:**
- Modify:
  - `web/src/pages/ProjectsPage.tsx`
  - `web/src/App.tsx`
  - `web/src/pages/Dashboard.tsx`
  - `web/src/services/intel-api.ts`
  - `web/src/pages/NewProject.tsx`
  - `web/src/pages/DeliverablesPage.tsx`
  - `web/src/components/deliverable/RunProgress.tsx`
  - `web/src/components/deliverable/RunTimeline.tsx`
  - `web/src/pages/DataSources.tsx`

**Interfaces:**
- Consumes:
  - Task 20 fields.
  - Task 7 `GET /agent/{pid}/events`.
  - Task 14 QA CLI as the red/green check (R3).
- Produces:
  - `intelApi.agentEvents(projectId, limit?)`.
  - Type `AgentEvent`.
  - The new fields on `DeliverableRun`, `DeliverableSection` and `DeliverableProgress`.

**Verification loop for each issue below** (`QA` means `$PY -m agent.app.domains.agent.qa_browser --user 1 --project 262 --pages <page>`):
1. Rebuild with `cd web && npm run build`.
2. Restart the backend.
3. Run QA. It must print the item's finding kind. That is the RED step.
   - If the kind is already absent because Task 19 applied a fix, ledger a skip and move to the next item.
4. Make the change.
5. Run `cd web && npx tsc --noEmit`. Expected: no errors.
6. Rebuild, restart, and run QA again. The finding kind must be gone. That is the GREEN step.

- [ ] **Step 1: Card attribute, so the issue 1 check can run**

In `ProjectsPage.tsx`, add `data-project-id={p.id}` on the outermost element of each project card. That element is the one whose click calls `select(p, ...)`.

Run QA with `--pages projects`. Expected: `url_project_mismatch`.

If issue 1 does not reproduce, ledger it and still apply Step 2: the stale `navigate` closure is a real defect, because `navigate` pushes the previous project's URL.

- [ ] **Step 2: Issue 1, the URL follows the active project**

In `App.tsx`, import `useRef`. Add `const pushNext = useRef(false);` near line 117. Replace `navigate` (lines 169-173):

```tsx
  const navigate = (p: string) => {
    if (!isPage(p)) { console.warn(`Unknown page "${p}"`); return; }
    pushNext.current = true;
    setPageState(p);
  };
```

In the URL sync effect (lines 163-167), replace the history call:

```tsx
    if (window.location.pathname !== url) {
      if (pushNext.current) window.history.pushState(null, "", url);
      else window.history.replaceState(null, "", url);
    }
    pushNext.current = false;
```

In `hydrateProjectFromUrl` (lines 129-138), right after the project is fetched:

```tsx
      if (p.archived_at) { window.history.replaceState(null, "", buildUrl(null, "projects")); setPageState("projects"); return; }
```

Add `archived_at?: number | null` to the `getProject` result type in `intel-api.ts`.

Verify: QA `--pages projects` reports no `url_project_mismatch`.

- [ ] **Step 3: Issues 2 and 4 (frontend), Dashboard counts from the deliverable engine**

In `intel-api.ts`:
- `DeliverableRun` gains `studio_pptx_path: string | null; html_path: string | null; pdf_path: string | null;`.
- `DeliverableSection` gains `slides?: unknown[]` and `lines?: { ts: number; message: string }[]` (unless `lines` already exists).
- `DeliverableProgress` gains `typical_seconds?: number | null`.

In `Dashboard.tsx` `load`:
1. Delete the `getExecutionStatus` block (lines 138-141).
2. Declare `let runActivity: { action: string; detail: string; timestamp: string }[] = [];` at the top.
3. After the legacy summaries, add:

```tsx
      try {
        const d = await intelApi.deliverableLatest(activeProjectId);
        if (d.run) {
          const n = d.sections.filter((x) => x.module === "insights").reduce((a, x) => a + (x.insights?.length ?? 0), 0);
          if (n) s.insightsCount = n;
          const slides = d.sections.find((x) => x.id === "studio")?.slides?.length ?? 0;
          if (slides) s.slidesComposed = slides;
          if (d.run.status === "completed") {
            s.pptxReady = !!(d.run.pptx_path || d.run.studio_pptx_path);
            s.wordReady = !!d.run.docx_path;
            s.executionCompleted = true;
          }
          const lines = d.sections.find((x) => x.id === "log")?.lines ?? [];
          runActivity = lines.slice(-10).reverse().map((l) => ({
            action: l.message, detail: `Deliverable run #${d.run!.id}`,
            timestamp: new Date(l.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          }));
        }
      } catch { /* no deliverable yet: keep the pipeline counts */ }
```

Verify: QA `--pages dashboard` reports no `stat_mismatch` and no `failed_request` for `/execution/`.

- [ ] **Step 4: Issue 3, Recent Activity from agent events and the run log**

In `intel-api.ts`:

```ts
export type AgentEvent = { id: number; actor: string; action: string; detail: Record<string, unknown> | null; at: number; run_id: number | null };
  agentEvents: (projectId: number, limit = 10) => get<AgentEvent[]>(`/agent/${projectId}/events?limit=${limit}`),
```

In `Dashboard.tsx`, add `const [activity, setActivity] = useState<{ action: string; detail: string; timestamp: string }[]>([]);`. At the end of `load`:

```tsx
      const events = await intelApi.agentEvents(activeProjectId, 10).catch(() => []);
      const fromEvents = events.map((e) => ({ action: e.action.replace(/_/g, " "), detail: e.actor,
        timestamp: new Date(e.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }));
      setActivity([...fromEvents, ...runActivity].slice(0, 10));
```

In the Recent Activity panel (lines 368-391), render `const items = activity.length ? activity : demo.activityLog;`. Use `items` in place of `demo.activityLog` at lines 370 and 379.

Verify: QA `--pages dashboard` reports no `empty_activity`.

- [ ] **Step 5: Issue 5, category/editorial research type** (Ruling R6)

1. In `NewProject.tsx`, add `<option>Category / Editorial Analysis</option>` after `<option>Competitor Analysis</option>` (lines 290-293).
2. File the user-report issue through the copilot. In the Hunter drawer, after Task 22, send: "The dashboard says Competitor Analysis but this is a category brief". Or use the CLI equivalent: `$PY -c "from agent.app.domains.agent.repair import issues; print(issues.file_issue('user','user_report','Category brief labelled Competitor Analysis',{'page':'dashboard'},262))"`. Record the issue id.
3. Correct project 262's data through the existing edit-project flow: Project 262 → Edit project → Research Type = "Category / Editorial Analysis" → Save.
4. If the edit form does not expose the field, find the project updater with `grep -n "def update_project" agent/app/domains/projects/repository.py` and run a one-off that changes only 262:

```bash
$PY -c "from agent.app.core import store; p=store.get_project(262); s=dict(p['spec']); s['research_type']='Category / Editorial Analysis'; s.setdefault('methodology',{})['primary']='Category / Editorial Analysis'; store.update_project_spec(262, s); print(store.get_project(262)['spec']['research_type'])"
```

Use the updater name grep printed in place of `update_project_spec`. Expected output: `Category / Editorial Analysis`. Then mark the issue `fixed` with `store.set_issue_status(<id>, "fixed", "form option added; 262 corrected")`.

- [ ] **Step 6: Issue 6, full questions on the Deliverables page**

In `DeliverablesPage.tsx`, near the other derived values:

```tsx
  const question = (rq: string) => summary?.answers?.find((a) => a.rq_id === rq)?.question ?? "";
```

Line 244 becomes:
```tsx
<h2 className="text-base font-semibold text-slate-900">{rq}{question(rq) ? `: ${question(rq)}` : ""}</h2>
```

At line 230, add a subtitle under `{a.rq_id}`:
```tsx
<p className="text-xs text-slate-500">{a.question}</p>
```

Verify: start a run with Generate, then run QA `--pages deliverables` while it runs. Expected: no `internal_code`.

- [ ] **Step 7: Issue 7, ETA blended with the typical run time**

In `RunProgress.tsx`:

```tsx
const MIN_PCT_FOR_ESTIMATE = 10;
...
  const linear = progress.pct >= MIN_PCT_FOR_ESTIMATE && progress.pct < 100
    ? (elapsed * (100 - progress.pct)) / progress.pct : null;
  const typical = progress.typical_seconds ? Math.max(0, progress.typical_seconds - elapsed) : null;
  const remaining = linear === null ? typical : typical === null ? linear : Math.max(linear, typical);
```

Verify:
1. `npx tsc --noEmit` passes.
2. After the next completed run, `$PY -c "from agent.app.core import store; print([i['id'] for i in store.list_issues('open') if i['kind']=='progress_calibration'])"` prints no new calibration issue for that run. Issue 7 is detected by the Task 13 engine check, not by the browser.

- [ ] **Step 8: Issue 8, stage pills on one row**

In `RunTimeline.tsx`:

```tsx
    <ol className="flex flex-nowrap gap-1 overflow-x-auto" aria-label="Deliverable stages">
...
      <li key={s} className={`shrink-0 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-medium ${cls}`}
          title={details[s] ? `${LABELS[s]} · ${details[s]}` : LABELS[s]}>
        {LABELS[s]}
      </li>
```

Verify: QA `--pages deliverables` reports no `stage_pills_wrap`.

- [ ] **Step 9: Issue 9, Data Sources stops fading in on every load**

In `DataSources.tsx:843`, change `className="h-full flex flex-col overflow-hidden animate-fade-in"` to `className="h-full flex flex-col overflow-hidden"`.

Verify: QA `--pages data-sources` reports no `faded_on_load`.

- [ ] **Step 10: Full QA pass and commit**

Run: `$PY -m agent.app.domains.agent.qa_browser --user 1 --project 262`
Expected: none of these kinds remain:
- `url_project_mismatch`
- `stat_mismatch`
- `empty_activity`
- `failed_request` on `/execution/`
- `internal_code`
- `stage_pills_wrap`
- `faded_on_load`

If anything else remains, ledger it with a ruling.

```bash
git add web/src/App.tsx web/src/pages/ProjectsPage.tsx web/src/pages/Dashboard.tsx web/src/services/intel-api.ts web/src/pages/NewProject.tsx web/src/pages/DeliverablesPage.tsx web/src/components/deliverable/RunProgress.tsx web/src/components/deliverable/RunTimeline.tsx web/src/pages/DataSources.tsx
git commit -m "fix(web): URL follows the active project, dashboard counts and activity from real runs, full questions, honest ETA, one-row stages, no faded Data Sources"
```

### Task 22: Agent drawer, autopilot status and the Fixes tab

**Files:**
- Create:
  - `web/src/components/agent/AgentDrawer.tsx`
  - `web/src/pages/FixesTab.tsx`
- Modify:
  - `web/src/App.tsx`: mount the drawer on project pages.
  - `web/src/pages/SettingsPage.tsx`: add a `"fixes"` tab for super_admin.
  - `web/src/services/intel-api.ts`: agent API functions.

**Interfaces:**
- Consumes:
  - Routes from Tasks 7, 8 and 19.
  - `agent_event` WebSocket messages (Task 3), via `agentSocket.onMessage`, which returns an unsubscribe function.
- Produces these `intelApi` functions:
  - `agentState`, `agentStart`, `agentStop`
  - `copilotSend`
  - `adminIssues`, `adminFixes`
  - `adminApplyFix`, `adminRejectFix`, `adminRetryIssue`

- [ ] **Step 1: API types and functions** (`intel-api.ts`)

```ts
export type AgentStep = { key: string; label: string; state: "done" | "ready" | "waiting" | "failed" | "todo"; detail: string };
export type AgentState = { autopilot: { status: string; note: string; updated_at: number } | null;
  status: { project_id: number; name: string; steps: AgentStep[]; next: string | null } };
export type CopilotReply = { reply: string; actions: { tool: string; ok: boolean; error?: string }[];
  pending: { id: string; tool: string; args: Record<string, unknown>; summary: string } | null };
export type AgentIssue = { id: number; project_id: number | null; source: string; kind: string; title: string;
  detail: Record<string, unknown>; status: string; note: string; seen: number; created_at: number };
export type AgentFix = { id: number; issue_id: number; branch: string; tier: "auto" | "inbox" | "never"; diff: string;
  tests: Record<string, string>; status: string; note: string; commit_sha: string | null; created_at: number };

  agentState: (projectId: number) => get<AgentState>(`/agent/${projectId}`),
  agentStart: (projectId: number, inputFolder?: string) =>
    post<AgentState["autopilot"]>(`/agent/${projectId}/autopilot/start`, { input_folder: inputFolder || null }),
  agentStop: (projectId: number) => post<{ ok: boolean }>(`/agent/${projectId}/autopilot/stop`, {}),
  copilotSend: (projectId: number, message: string, confirm?: string) =>
    post<CopilotReply>(`/agent/${projectId}/copilot`, { message, confirm: confirm ?? null }),
  adminIssues: (status?: string) => get<AgentIssue[]>(`/agent/admin/issues${status ? `?status=${status}` : ""}`),
  adminFixes: (status?: string) => get<AgentFix[]>(`/agent/admin/fixes${status ? `?status=${status}` : ""}`),
  adminApplyFix: (id: number) => post<{ status: string; reason: string }>(`/agent/admin/fixes/${id}/apply`, {}),
  adminRejectFix: (id: number, reason: string) => post<{ ok: boolean }>(`/agent/admin/fixes/${id}/reject`, { reason }),
  adminRetryIssue: (id: number) => post<{ ok: boolean }>(`/agent/admin/issues/${id}/retry`, {}),
```

- [ ] **Step 2: `AgentDrawer.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { intelApi, type AgentState, type CopilotReply } from "../../services/intel-api";
import { agentSocket } from "../../services/ws";

type Turn = { who: "you" | "hunter"; text: string; pending?: CopilotReply["pending"] };
const STATE_CLS: Record<string, string> = {
  done: "bg-emerald-50 text-emerald-700 border-emerald-200", waiting: "bg-sky-50 text-sky-700 border-sky-200",
  ready: "bg-amber-50 text-amber-700 border-amber-200", failed: "bg-rose-50 text-rose-700 border-rose-200",
  todo: "bg-slate-50 text-slate-500 border-slate-200",
};

/** Hunter's autopilot status and the copilot chat for the active project, in a drawer on the right. */
export function AgentDrawer({ projectId }: { projectId: number }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<AgentState | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    intelApi.agentState(projectId).then(setState).catch(() => setState(null));
  }, [projectId]);

  useEffect(() => { refresh(); setTurns([]); }, [refresh]);
  useEffect(() => agentSocket.onMessage((m) => {
    if (m.type === "agent_event" && m.project_id === projectId) refresh();
  }), [projectId, refresh]);

  const send = async (message: string, confirm?: string) => {
    setBusy(true); setError(null);
    if (message) setTurns((t) => [...t, { who: "you", text: message }]);
    try {
      const r = await intelApi.copilotSend(projectId, message, confirm);
      setTurns((t) => [...t, { who: "hunter", text: r.reply, pending: r.pending }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The copilot could not answer.");
    } finally { setBusy(false); setDraft(""); }
  };

  const start = async () => {
    setError(null);
    try { await intelApi.agentStart(projectId, folder || undefined); refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not start the autopilot."); }
  };

  const ap = state?.autopilot;
  return (
    <>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="fixed bottom-5 right-5 z-40 rounded-full bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white shadow-lg">
        Hunter{ap?.status === "running" ? " · driving" : ""}
      </button>
      {open && (
        <aside className="fixed right-0 top-0 z-40 flex h-full w-[380px] flex-col border-l border-slate-200 bg-white shadow-xl"
          aria-label="Hunter agent">
          <header className="border-b border-slate-200 p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">Hunter</h2>
              <button onClick={() => setOpen(false)} className="text-sm text-slate-600">Close</button>
            </div>
            <p className="mt-1 text-xs text-slate-600">
              {ap ? `Autopilot: ${ap.status} — ${ap.note}` : "Autopilot is off for this project."}
            </p>
            <ol className="mt-2 flex flex-wrap gap-1">
              {state?.status.steps.map((s) => (
                <li key={s.key} title={s.detail} className={`rounded border px-1.5 py-0.5 text-[11px] ${STATE_CLS[s.state]}`}>{s.label}</li>
              ))}
            </ol>
            <div className="mt-3 flex gap-2">
              {ap?.status === "running" ? (
                <button onClick={() => intelApi.agentStop(projectId).then(refresh)} className="rounded border px-2 py-1 text-xs">Stop</button>
              ) : (
                <>
                  <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Input folder (optional)"
                    aria-label="Input folder" className="min-w-0 flex-1 rounded border px-2 py-1 text-xs" />
                  <button onClick={start} className="rounded bg-[#5B2C9D] px-2 py-1 text-xs text-white">Drive to deck</button>
                </>
              )}
            </div>
          </header>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {turns.map((t, i) => (
              <div key={i} className={t.who === "you" ? "text-right" : ""}>
                <p className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${t.who === "you" ? "bg-[#5B2C9D] text-white" : "bg-slate-100 text-slate-800"}`}>{t.text}</p>
                {t.pending && (
                  <div className="mt-1">
                    <button disabled={busy} onClick={() => send("", t.pending!.id)}
                      className="rounded bg-emerald-700 px-2 py-1 text-xs text-white">Confirm {t.pending.tool.replace(/_/g, " ")}</button>
                  </div>
                )}
              </div>
            ))}
            {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
          </div>
          <form className="flex gap-2 border-t border-slate-200 p-3"
            onSubmit={(e) => { e.preventDefault(); if (draft.trim()) send(draft.trim()); }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder='e.g. "why is the experts question partial?"'
              className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" aria-label="Message Hunter" />
            <button disabled={busy || !draft.trim()} className="rounded bg-[#5B2C9D] px-3 py-1.5 text-sm text-white disabled:opacity-50">Send</button>
          </form>
        </aside>
      )}
    </>
  );
}
```

- [ ] **Step 3: `FixesTab.tsx`**

```tsx
import { useEffect, useState } from "react";
import { intelApi, type AgentFix, type AgentIssue } from "../services/intel-api";

/** Issues Hunter found and the fixes it proposed: approve or reject inbox fixes; see what applied or rolled back. */
export function FixesTab() {
  const [issues, setIssues] = useState<AgentIssue[]>([]);
  const [fixes, setFixes] = useState<AgentFix[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => Promise.all([intelApi.adminIssues(), intelApi.adminFixes()])
    .then(([i, f]) => { setIssues(i); setFixes(f); }).catch(() => setMessage("Could not load fixes."));
  useEffect(() => { load(); }, []);

  const apply = async (id: number) => {
    const r = await intelApi.adminApplyFix(id).catch((e) => ({ status: "refused", reason: String(e) }));
    setMessage(r.status === "verifying" ? "Applied — the app restarts and verifies the fix." : `Not applied: ${r.reason}`);
    load();
  };
  const reject = async (id: number) => {
    const reason = window.prompt("Why reject this fix?");
    if (reason) { await intelApi.adminRejectFix(id, reason); load(); }
  };

  return (
    <div className="space-y-6">
      {message && <p role="status" className="rounded bg-slate-50 p-2 text-sm text-slate-700">{message}</p>}
      <section>
        <h3 className="text-sm font-semibold text-slate-900">Fixes</h3>
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200">
          {fixes.map((f) => {
            const issue = issues.find((i) => i.id === f.issue_id);
            return (
              <li key={f.id} className="p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <button onClick={() => setOpen(open === f.id ? null : f.id)} className="text-left font-medium text-slate-800">
                    #{f.id} {issue?.title ?? `issue ${f.issue_id}`}
                  </button>
                  <span className="shrink-0 text-xs text-slate-600">{f.tier} · {f.status}</span>
                </div>
                {f.note && <p className="mt-1 text-xs text-slate-600">{f.note}</p>}
                {open === f.id && (
                  <div className="mt-2 space-y-2">
                    {Object.entries(f.tests).map(([k, v]) => (
                      <pre key={k} className="max-h-32 overflow-auto rounded bg-slate-50 p-2 text-[11px]">{k}: {v}</pre>))}
                    <pre className="max-h-80 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">{f.diff}</pre>
                  </div>
                )}
                {f.status === "proposed" && f.tier !== "never" && (
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => apply(f.id)} className="rounded bg-[#5B2C9D] px-2 py-1 text-xs text-white">Apply</button>
                    <button onClick={() => reject(f.id)} className="rounded border px-2 py-1 text-xs">Reject</button>
                  </div>
                )}
              </li>
            );
          })}
          {!fixes.length && <li className="p-3 text-sm text-slate-600">No fixes yet.</li>}
        </ul>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-slate-900">Issues</h3>
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200">
          {issues.map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-3 p-3 text-sm">
              <span className="text-slate-800">#{i.id} [{i.source}] {i.title}{i.seen > 1 ? ` ×${i.seen}` : ""}</span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-slate-600">{i.status}
                {["discarded", "rejected", "needs_llm"].includes(i.status) &&
                  <button onClick={() => intelApi.adminRetryIssue(i.id).then(load)} className="rounded border px-1.5 py-0.5">Retry</button>}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Mount the drawer and the tab**

In `App.tsx`, inside `AppShell` after the page content, use the same membership check `BROWSING_PAGES` already uses elsewhere in the file (`.has` or `.includes`):

```tsx
{activeProject && !BROWSING_PAGES.includes(page) && <AgentDrawer projectId={activeProject.id} />}
```

In `SettingsPage.tsx`:
- add `"fixes"` to `SettingsTab`;
- inside the `user.role === "super_admin"` spread, add `{ id: "fixes", label: "Fixes" }`;
- render `{tab === "fixes" && <FixesTab />}`.

- [ ] **Step 5: Type-check, build and smoke**

1. Run: `cd web && npx tsc --noEmit && npm run build`. Expected: no type errors, and the build writes `agent/static/`.
2. Restart with `.\start.ps1`.
3. Run QA with `--pages dashboard,deliverables`. Expected: no new findings compared with Task 21 Step 10. The drawer must add no `low_contrast` or `overflow_x`.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/agent/AgentDrawer.tsx web/src/pages/FixesTab.tsx web/src/App.tsx web/src/pages/SettingsPage.tsx web/src/services/intel-api.ts
git commit -m "feat(web): Hunter drawer with autopilot status and copilot chat; Fixes tab for super admins"
```

### Task 23: Acceptance

**Files:**
- Create: `agent/tests/acceptance_hunter_agent.py`. This is a script; pytest does not collect it because its name does not start with `test_`.

**Interfaces:**
- Consumes everything above.

- [ ] **Step 1: Write the acceptance script**

```python
"""Hunter agent acceptance (spec section 6), against the live backend running under the supervisor:
  python agent/tests/acceptance_hunter_agent.py --user 1"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from agent.app.core import store
from agent.app.domains.agent import autopilot

PROJECTS = {263: str(ROOT / "Band-Aid"), 264: str(ROOT / "Planet-Fitness")}
TIMEOUT = 3 * 3600
POLL = 30


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""))
    return ok


def main() -> int:
    a = argparse.ArgumentParser(); a.add_argument("--user", type=int, required=True); args = a.parse_args()
    results = []
    for pid, folder in PROJECTS.items():
        autopilot.start(pid, args.user, folder)
    deadline = time.time() + TIMEOUT
    while time.time() < deadline and any((store.get_autopilot(p) or {}).get("status") == "running" for p in PROJECTS):
        time.sleep(POLL)
    for pid in PROJECTS:
        ap = store.get_autopilot(pid) or {}
        run = store.get_latest_deliverable_run(pid) or {}
        results.append(check(f"{pid} autopilot done", ap.get("status") == "done", ap.get("note", "")))
        results.append(check(f"{pid} deck delivered", run.get("status") == "completed" and bool(run.get("studio_pptx_path")),
                             str(run.get("error") or "")))
        spec_path = Path(run.get("deck_dir") or ".") / "spec.json"
        if spec_path.exists():
            slides = json.loads(spec_path.read_text("utf-8"))["slides"]
            questions = sum(1 for s in slides if s["type"] == "divider")
            walls = [s for s in slides if s["type"] == "verbatim_wall"]
            results.append(check(f"{pid} verbatim slide per question", len(walls) == questions, f"{len(walls)}/{questions}"))
            results.append(check(f"{pid} wall images present", all(c.get("image") for w in walls for c in w["cards"])))
            thumbs = sum(1 for s in slides for c in s["cards"] if c.get("thumb"))
            results.append(check(f"{pid} insight cards have thumbnails", thumbs > 0, str(thumbs)))
            whys = [s["image"].get("why", "") for s in slides if s.get("image", {}).get("path")]
            off = [w for w in whys if w.startswith("text: does not") or w.startswith("vision: off")]
            results.append(check(f"{pid} every photo matches brand/product/slide", not off and bool(whys),
                                 f"{len(whys)} photos, {len(off)} off-topic"))
        else:
            results.append(check(f"{pid} deck spec found", False, str(spec_path)))
        manual = [e for e in store.list_agent_events(pid, limit=500) if e["actor"] not in ("autopilot", "copilot")]
        results.append(check(f"{pid} no manual steps", not manual))
    issues = store.list_issues()
    kinds = {i["kind"] for i in issues if i["source"] == "qa_browser"}
    results.append(check("QA found the walkthrough issues",
                         {"failed_request", "faded_on_load", "stage_pills_wrap", "stat_mismatch"} <= kinds,
                         ", ".join(sorted(kinds))))
    fixes = store.list_fixes()
    results.append(check("fixer produced auto fixes for design issues", any(f["tier"] == "auto" for f in fixes)))
    results.append(check("fixer produced inbox proposals for logic issues", any(f["tier"] == "inbox" for f in fixes)))
    print(f"{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the full unit suite**

Run: `$PY -m pytest agent/tests/ -q -p no:cacheprovider --ignore=agent/tests/test_e2e_live_workflow.py > "$TEMP/hunter_suite.txt" 2>&1; tail -3 "$TEMP/hunter_suite.txt"`

Expected: everything passes except the known order-dependent `test_word_renderer::test_render_full_report`, which is deferred from Deck Studio and passes when run alone. Any other failure blocks acceptance.

- [ ] **Step 3: Run acceptance against the live backend**

1. Restart with `.\start.ps1`, which now launches through the supervisor.
2. Run: `$PY agent/tests/acceptance_hunter_agent.py --user 1`
   - Expected: every line is `PASS`, ending with `N/N checks passed`.
   - This can take up to about 3 hours. Classifying about 66k Band-Aid rows on a cold cache is the long pole.
3. Open both decks (Deliverables → Studio deck) and look at the verbatim slides and card thumbnails. Record what you see in the ledger.

- [ ] **Step 4: Fixes found by acceptance**

Nothing to commit here, because the tests are git-ignored. If acceptance exposes a defect, fix it test-first in the task that owns that code, with that task's own commit.

---

## Self-review notes

Spec coverage:

| Spec item | Tasks |
|---|---|
| §3.1 memory | 2, 3 |
| §3.2 tools | 6, 8, 12, 13 |
| §3.3 autopilot | 7 |
| §3.4 copilot | 8, 22 |
| §3.5 screenshots | 9, 10 |
| §3.6.1 in-run repair | 11 |
| §3.6.2 detection | 13, 14 |
| §3.6.3 fix proposal | 16, 17 |
| §3.6.4 tiered apply | 15, 18, 19 |
| §3.6.5 outcomes in memory | 18, 19 |
| §4 pages | 21, 22 |
| §5 safety | 13, 15, 16, 17, 18 |
| §6 acceptance | 14 Step 5, 19 Step 6, 23 |
| CSV bug | 1 |
| UI issues | 20, 21 |
| Photos irrelevant to brand/products/slide (user, 2026-10-07) | 12A, 23 |

Judgement calls are Rulings R1–R8 above. The executor copies them into the ledger at setup.

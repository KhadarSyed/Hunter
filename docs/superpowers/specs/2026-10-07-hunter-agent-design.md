# Hunter Agent — autopilot, copilot, project memory, article screenshots and self-repair

Date: 2026-10-07 · Status: draft for review · Builds on Deck Studio (phase 1)

## 1. Why

The pipeline is powerful but needs a person at every step, forgets what happened in earlier runs, shows
articles only as favicons and text, and when something breaks (a bug, an ugly slide, a faded page) a developer
has to notice and fix it. The user wants Hunter to drive projects itself, remember context, put the real
articles and posts on the slides, and find and fix its own code and design problems — safely.

## 2. Decisions taken with the user

| Topic | Decision |
|---|---|
| Control | Both: an **autopilot** that drives a project brief → deck, decides next steps, repairs and resumes after restarts; and an in-app **copilot** chat ("redo slide 7 with a calmer photo", "why is RQ4 partial?") |
| Memory | One per-project memory shared by autopilot and copilot: decisions, user preferences, past runs, fixes |
| Screenshots | Per research question a "Supporting verbatims" slide (grid of 6–9 article/post screenshots) **and** a small thumbnail of the cited article on each insight card; links in PPTX notes |
| Self-repair | All three levels: auto-repair content/design inside a run; detect + propose code fixes; fix code — **tiered**: design/template/CSS/prompt fixes apply automatically behind a health check with auto-rollback; Python/TypeScript logic fixes wait in an in-app **Fixes inbox** for one-click approve (apply, restart, auto-rollback on failed health check) |
| Model | All Azure OpenAI (tool calling), the app's existing provider |
| Browser QA | The agent walks the UI with Playwright (like the manual walkthrough on 2026-10-07) and files issues automatically |

## 3. Components (`agent/app/domains/agent/`)

### 3.1 Memory (`memory.py`, tables `agent_memory`, `agent_events`)
- `agent_memory(project_id, kind, key, value_json, updated_at)` — kinds: `preference` (palette, tone, slide
  order the user asked for), `decision` (approvals the agent made and why), `fact` (brief facts it inferred),
  `fix` (problems seen and how they were fixed).
- `agent_events(project_id, run_id, actor, action, detail_json, at)` — every autopilot/copilot action, for
  the Recent Activity panel and for resuming.
- Context building: for each agent turn, the last N events, all preferences and decisions, and a rolling
  summary (re-summarised by the LLM when the event log for a project passes a token budget) — kept under a
  fixed prompt budget so long projects never overflow the model.

### 3.2 Tools (`tools.py`)
Typed wrappers over the pipeline's own service functions (the same ones the routers call): get project
status, generate/approve scope, generate/approve strategy, upload/approve datasets, run deliverable, read run
log and QC, regenerate a slide with instructions, change design tokens, set a preference. Each tool records an
`agent_events` row. Destructive tools (delete project/dataset) are not exposed.

### 3.3 Autopilot (`autopilot.py`)
- A loop per project: read status + memory → choose the next tool (Azure OpenAI tool calling) → execute →
  record → repeat until the deck is delivered or a step needs a human (an approval the project is configured to
  keep manual, or a failure it cannot repair after N attempts).
- Resumable: state is the database (pipeline stages + agent_events), so a server restart continues the loop.
- Runs one project at a time per worker; progress streams on the existing WebSocket and Live log.

### 3.4 Copilot (`copilot.py`, page panel)
- A chat drawer on every project page; same tools and memory; answers questions from run data and can act
  ("regenerate slide 7", "make the palette calmer", "why is RQ4 partial?").
- Every action shows what it will do before destructive or costly steps (rerunning classification).

### 3.5 Article/post screenshots (`deckstudio/verbatims.py`)
- For each research question, the most-cited and highest-reach articles (and posts) are captured with
  Playwright at 1280×800: cookie banners dismissed, scrolled to the headline, cropped to headline + lead
  image; social posts via the platform's public embed page when the URL is X/Instagram/TikTok/YouTube.
- Paywalled/blocked pages (or failures) fall back to a generated "article card" (outlet favicon, headline,
  date, first sentence) so the grid is never empty.
- New slide type `verbatim_wall` (3×3 grid, outlet + date under each); insight cards get a 48 px thumbnail of
  their first citation; PPTX notes list the URLs.
- Screenshots are cached by URL; their source URLs go in the run log.

### 3.6 Self-repair (`repair/`)
1. **In-run repair (automatic).** QC flags (overflow, contrast, overlap, missing photo, failed creative slide)
   trigger targeted fixes: re-render the slide from its template with adjusted tokens, pick another photo,
   shorten text, split a table — up to 2 attempts per slide; outcomes recorded in memory.
2. **Issue detection.** Sources: engine exceptions (stage failures with tracebacks), QC flags that survive
   in-run repair, console errors and failed requests from the **browser QA agent**, and user reports from the
   copilot ("this page looks faded").
   - Browser QA agent (`qa_browser.py`): Playwright walks the main flows of a project (landing → projects →
     dashboard → each stage page → deliverables), captures screenshots, console errors, failed network calls,
     and visual checks (contrast, overflow, overlapping elements) and files an issue per finding.
3. **Fix proposal (all code/design issues).** The fixer agent (Azure OpenAI with file-read/search/edit tools
   restricted to the repo) works in a separate **git worktree** on a branch `autofix/<issue-id>`: writes a test
   that reproduces the issue, makes the change, runs the related tests, the full suite and (for UI issues) the
   QA browser check on the changed page. A fix without a failing-then-passing test is discarded.
4. **Tiered apply.**
   - **Auto-apply** when the diff only touches design assets: `deckstudio/templates/*`, CSS/Tailwind classes in
     `web/src/**` with no logic change, chart styling constants, LLM prompt strings. Applied by merging the
     branch, rebuilding the frontend, restarting, then a health check (API health, QA browser smoke on the
     affected page). Failure → automatic revert and restart.
   - **Fixes inbox** for anything else (Python/TypeScript logic, schemas, dependencies): an in-app page shows
     the issue, the failing case, the diff, the test results and screenshots; **Apply** merges, restarts and
     health-checks with the same automatic rollback; **Reject** records why in memory.
   - Never auto-applied: secrets/config, auth, migrations, dependency changes, deletions of data.
5. Every fix (applied, rolled back or rejected) is recorded in memory so the same issue is not retried blindly.

## 4. Pages
- Project pages: copilot drawer; Recent Activity fed by `agent_events`; autopilot status ("driving: step 4 of
  7 — waiting on dataset enrichment").
- New **Fixes** page (admin): open issues, proposed fixes, applied/rolled-back history.
- Dashboard counts from the deliverable engine (insights, slides, downloads) — fixes UI issue #2.

## 5. Safety
- The fixer can only read/write inside the repo worktree; no network except the Azure endpoint; no access to
  `.env` contents; secrets redacted from any prompt.
- Auto-apply limited to the design allowlist above; every apply is reversible (git revert + restart).
- Rate limits: at most one fix in flight, at most N auto-applies per hour; repeated failures disable auto-apply
  and alert an admin.

## 6. Testing and acceptance
- Unit tests for memory context budget, tool wrappers, autopilot step selection (fake LLM), screenshot
  fallback card, verbatim slide layout, tier classification of diffs, rollback on failed health check.
- Acceptance: the autopilot takes Band-Aid and Planet Fitness from created project to delivered deck without
  manual steps; each deck has a verbatim slide per question with real screenshots (or fallback cards) and
  thumbnails on insight cards; the browser QA agent finds the 9 UI issues logged on 2026-10-07 on the
  pre-fix build, and the fixer produces passing fixes for the design ones automatically and inbox proposals for
  the logic ones.

## 7. Known limits
- Azure OpenAI as the code fixer is weaker on large multi-file changes than a dedicated coding agent; the
  test gate and the Fixes inbox are what keep that safe.
- Some news sites block automated screenshots; the fallback card keeps the deck complete.

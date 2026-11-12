# 2026-11-12-48 Handover doc rewritten; status doc labelled as history

**Request:** "continue" (review the long reference docs against the code).

**Found:** `docs/handover/HANDOVER.md` (2026-09-08, 366 lines) described the pre-restructure `agent/` layout, two
SQLite files, `intelligence_store.py`, and pages/renderers deleted since; it also carried a former developer's name,
email and Windows paths. `docs/CURRENT_STATUS.md` (718 lines) is a sprint log that marks deleted stages (slide
intelligence, composer, renderers, publishing, evidence library, insights, storylines, orchestrator) "Complete" with
"SQLite tables", yet CLAUDE.md called it "authoritative" and told sessions to consult it.

**Changed:**
- `HANDOVER.md` rewritten (short): what it is, stack, run locally, deploy, how to change the code (repositories,
  Alembic revisions, checks), known limitations; every fact checked in the code/`.env.example`/`deploy/` this session;
  no personal data. Points to CLAUDE.md and Instructions/ as the maintained references.
- `CURRENT_STATUS.md`: title + banner say it is history (what was deleted 2026-11-05, Alembic since 2026-11-12); body
  kept as history.
- CLAUDE.md: no longer calls CURRENT_STATUS authoritative; "before assuming a stage is unbuilt" now points at the
  `domains/<stage>/` folder and `Instructions/log/`; docs list updated.

**Verified:** grep: the stages named in the banner have no code left (remaining matches are words in comments and the
legacy table names). Docs only: no tests/restart needed.

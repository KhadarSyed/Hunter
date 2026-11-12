# 2026-11-12 #19 — plan and brief moved to SQLAlchemy (pipeline domains start)

## Request
"Not done -- Handle these also": move the pipeline domains too, one verified domain at a time, smallest first.
Remaining after this: projects, spec, strategy, research, qc, deliverable, deckstudio, agent (both star-imported by
core/store.py, missed in earlier counts), dataset.

## Changed
- `domains/plan/models.py` (intel_research_plans, 11 columns) + `repository.py` (4 functions, `__all__`).
- `domains/brief/models.py` (intel_background_briefs 14 columns, intel_brief_section_edits 7) + `repository.py`
  (8 functions, `__all__`). Column lists read from the live schema.
- save_research_plan / save_background_brief: MAX(version)+1 and the insert now run in one transaction.

## Verified
- Parity (scratchpad/plan_brief_parity.py, old from git HEAD, writes alternated): version numbering across old/new
  writers, latest per project, approve/reject return values incl. missing ids, section edit on existing / unknown
  section / unknown brief + edit log, approve/reject/docx fields, version lists: 25 comparisons, 0 differences.
- pytest research, spec, strategy, agents, projects: 140 passed. ruff clean.

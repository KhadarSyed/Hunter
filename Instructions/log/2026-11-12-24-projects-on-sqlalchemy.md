# 2026-11-12 #24 — projects moved to SQLAlchemy; deleting a project now removes its deck sections

## Changed
- `domains/projects/models.py` (new): intel_projects (12 columns), intel_jobs (11, text id).
- `domains/projects/repository.py`: SQLAlchemy Core, the same 14 public functions + DESCRIPTION_MAX_CHARS, `__all__`.
  delete_project keeps its schema-driven traversal (declared FKs + every project_id table + _UNDECLARED_LINKS,
  children first, chunks of 500, one transaction, files removed only inside data/ after the commit); dynamic tables
  use SQLAlchemy `table()`/`column()`, table and column lists come from information_schema for current_schema().
  It no longer needs core.db.table_names/table_columns (still used by core/db.py itself).
- BUG FIXED: intel_deliverable_sections (a deck's content, linked to its run only by run_id, no declared FK) was
  left behind when a project was deleted. Added to _UNDECLARED_LINKS.
- Local test `tests/projects/test_delete_files.py`: its fake now stands in for `sa.begin` instead of `_conn`.

## Verified
- Parity (scratchpad/projects_parity.py, old from git HEAD): create/get/list filters/card fields/owner/update
  (partial)/get_or_create (existing, new + owner)/name taken (case, trim, exclude, null org), jobs create/update/
  get/list/stale cancel, and delete_project on twin projects (research → news approvals, briefs, runs → sections,
  plans, jobs, project memory, a file under data/ removed, a path outside data/ kept, an unrelated project kept):
  32 comparisons; the only difference is the intended one — the new code also deletes the twin's deck section.
- pytest projects: 19 passed; projects + security + research + strategy + spec + agent + usage + auth: 237 passed
  before the local test fix (the 1 failure was that test's mock of the removed `_conn`).

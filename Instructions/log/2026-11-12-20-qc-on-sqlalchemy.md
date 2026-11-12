# 2026-11-12 #20 — qc moved to SQLAlchemy; raw SQL outside the repository removed

## Changed
- `domains/qc/models.py` (new): qc_reports (12 columns), qc_runs (11), qc_findings (13), qc_exports (6), from the
  live schema.
- `domains/qc/repository.py`: SQLAlchemy Core, the same 12 functions + `create_qc_export` / `get_qc_export`,
  `__all__`. The update allowlists (`_REPORT_FIELDS`, `_RUN_FIELDS`) are kept: unknown keys are ignored.
- `domains/qc/export.py` `_save_export_record` and `domains/qc/router.py` export download ran raw SQL on qc_exports
  through `store._conn()` (against the "SQL only in repositories" rule); both call the repository now.

## Verified
- Parity (scratchpad/qc_parity.py, old from git HEAD): reports incl. allowlist + JSON round-trip + non-JSON text,
  latest per project, runs + score_breakdown, findings batch (incl. NULL row_number ordering), filters, analyst
  action, export row vs the old raw SELECT: 19 comparisons, 0 differences.
- Imports of qc router/export OK; store exposes the new functions; tests/security (QC access checks): 25 passed.
  No dedicated QC test folder exists.

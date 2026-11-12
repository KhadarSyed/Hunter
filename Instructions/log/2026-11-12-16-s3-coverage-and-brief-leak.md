# 2026-11-12 #16 — Where S3 is (and is not) used; brief upload leak fixed

## Request
"please go head and check if S3 bucket is used where it require" (+ continue SQLAlchemy with usage and auth).

## S3 coverage (code read, `core/object_store.py` callers)
- Uses S3, Postgres fallback when unset: finished decks + deck assets (`deliverable/deck_store.py`), reference PPT
  decks (`deliverable/templates_index.py`), Data set uploads (`dataset/service.py` → `datasets/...`, deleted with
  the file), asset library bytes (`assets/service.py`), email wordmark (`core/email_layout.py`).
- Search Strategy uploads: copy kept in Postgres `intel_dataset_files` (restored to disk on demand). OK.
- Rebuildable caches on local disk only, fine: favicons, brand_logos, email_icons, verbatims, ppt-templates.
- Spec/brief .docx: regenerated on every download. OK.
- GAPS (matter only on a hosted server whose disk resets; local runs keep data/):
  1. Avatars: `auth/router.py` writes `data/uploads/avatars/*` only → broken profile images after a restart.
  2. QC: the uploaded export is kept as a disk path (`qc_reports.file_path`) and re-read by field mapping and the
     run; QC exports are disk-only → a restart breaks an in-progress QC and old export downloads.
  Fix when hosting returns: store the bytes via object_store (S3) with a Postgres fallback, as dataset uploads do.
- Locally: AWS_* are not set in .env, so everything uses the Postgres fallback.

## Fixed
- `brief/router.py` parse-file: the uploaded brief was written to `data/uploads/brief_*` and never removed (19
  client files, 380 KB, on this machine). Now deleted in `finally` after text extraction. Existing 19 NOT deleted
  (user's call).

## Verified
- pytest spec/projects brief/upload/parse selection: 3 passed. Running backend not restarted yet (no --reload).

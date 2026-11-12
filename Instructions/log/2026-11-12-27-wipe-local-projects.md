# 2026-11-12-27 Wipe local projects for a fresh start

**Request:** "Brand new delete all project and its realted data so we can start freshly no need of the back up also".

**Scope:** local only (`.env` DATABASE_URL = 127.0.0.1:5433/hunter). Render/production and S3 untouched.

**Database:** no rows to delete. `intel_projects` held 0 projects (checked in every schema; only `public` has it),
all 40 tables with a `project_id` column were empty, and no `intel_jobs` were running/pending. A scratchpad script
that calls `projects.repository.delete_project` per project was prepared but had nothing to do.

**Files deleted** (untracked contents only; tracked `.gitkeep` files kept):
`data/deliverables` (3292 files, 1.8 GB), `data/verbatims` (2377, 212 MB), `data/backups` (21, 472 MB, incl. the
old SQL dump), `data/uploads` (36), `data/exports` (3), `data/rendered` (19), `data/specifications` (1),
`data/qa` (project 262 screenshots), `data/recreate_inputs` (projects 265+).

**Kept on purpose:** shipped templates (`hunter_template*.pptx`, `data/briefs`), shared non-project caches
(`brand_logos`, `favicons`, `email_icons`, `flags`), `logs`, source inputs `data/test_inputs` and
`data/Foxwoods_Project_Datasets.zip`. Org-level data (users, orgs, providers, plans, memory, asset library) kept.

**Verified:** per-folder file counts after deletion (only `.gitkeep` left); `git status --short data` shows no
tracked file removed.

**Not done / follow-ups:** S3 objects of old projects (decks, `datasets/project-{id}/`) not deleted: the bucket
may be shared with production, whose project ids could overlap.

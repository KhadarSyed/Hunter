# 2026-11-09 #20 — Org dashboard: tabs, logo, status ring, created dates, user status

User: "/org-dashboard — Make project and User display in tabs default project list — missing is Status Circle or pie
and project logo — truncate project name display 10 to 15 characters hover display full with name" and "Created Date
missing for both project, user - show user status active or inactive".

`frontend/src/components/admin/OrgDetailView.tsx` (shared by Org Admin `/org-dashboard` and the Super Admin org view):
- Projects / Users as tabs (house `components/deliverable/Tabs`), Projects default; tab labels carry counts.
- Project row: `BrandLogo` (project logo, as on the project list) + name cut at 15 chars with "…" (brand likewise);
  hover shows the full name · brand. Status column = house `ProjectProgress` (donut % + current stage).
- Created column on projects and users (`created_at` was already returned). User Status pill: Active / Inactive
  (inactive = `archived_at` set).
- Backend: `billing/service.org_detail` now also returns each project's `progress_pct` (from `gates.summary`).
  Until the server restarts the ring shows 0% (restart deferred: comparison run in progress, #19).
- Removed the now-unused `STAGE_LABELS` from `components/admin/adminUi.tsx`.

## Follow-up: pipeline in a popup
User: "show the list in pop up window, same in dashboard pipeline status missing for project".
- `components/PipelineDrillDown.tsx` → new `PipelineModal` (house `admin/adminUi` Modal, portalled to `<body>` because a
  card's hover transform traps `fixed`; stops click bubbling so the card does not navigate; Esc closes).
- Project cards (`ProjectsPage.tsx`) and the landing list (`LandingPage.tsx`): "Pipeline" now opens the popup instead
  of expanding the card.
- Org dashboard: the Status ring is a button that opens the same popup (Org Admin only — a Super Admin cannot open
  projects, the gates route returns 403, so there it stays display-only).
- Checked in the browser (shots/pipeline-card.png, shots/pipeline-dashboard.png): opens, stays on the page, closes.

## Follow-up: pipeline status not matching
User: "the pipeline status is not matching with actual one, dashboard shows 0 progress and drill down also not matching".
- Dashboard 0%: the server had not been restarted after `org_detail` started returning `progress_pct`. Restarted.
- Real bug (`projects/gates._fraction`): a stage counted progress only while its job ran. Once the research job
  completed, the stage stays "running" until the analyst brief is written and approved, and it fell back to 0% (overall
  dropped 23% → 16.67%). Now a finished job counts `JOB_DONE_FRACTION = 0.9` until the stage is done, so progress
  never goes backwards. Local test `tests/projects/test_gates.py::test_finished_job_keeps_its_progress_until_the_stage_is_done`.
- Verified: dashboard ring = popup = gates route (33%, 2 of 6 stages done, Search Strategy next).
- Compare run (#19): the restart would have killed the autorun mid-brief and autorun always redoes research, so
  project 8's brief and strategy were finished through the same API calls autorun makes; the driver resumes after.

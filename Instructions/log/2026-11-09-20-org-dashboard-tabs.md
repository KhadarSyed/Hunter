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

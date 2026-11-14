# 2026-11-14-15 Org-wide projects, owner tag, owner-only delete; Super Admin works in member orgs

## Request
"Super Admin - if he is part of the org he should also able to create project with in the org he was mapped.
Note- Project of every user visible to everyone with in the org tagging the owner First and Last Name, only owner can
delete the project rest any one can update it. Is the available currently? Khadar unable to create project in Testing org."

Answer: not available before this change. `core/auth.can_access_project` returned False for every Super Admin, an
Analyser saw only their own projects, and anyone with access could delete.

## What changed
- `domains/auth/repository.get_session_user`: new `org_member` on the session user. It is True when the user has an
  org and either is not a Super Admin or has a `user_organizations` row for the (active) org.
- `core/auth.can_access_project`: any member of the project's org (any role) may open or edit it. A Super Admin may do
  so only when `org_member` is set. New `require_project_org(user)`: the org a new project goes into, else 403.
- `domains/projects/router.py`:
  - `list_projects_route`: every non-Super Admin gets all of their org's projects (the Analyser owner filter is gone).
  - `create_project_route`: uses `require_project_org`.
  - `delete_project_route`: 403 unless the caller owns the project.
- `domains/research/router.start_background_research` uses `require_project_org` when it creates a project.
- `domains/projects/repository.list_projects` joins `users` and returns `owner_name` (`users.display_name`).
  `ProjectListItem` gains `owner_user_id` and `owner_name`.
- Frontend:
  - `ProjectsPage.tsx`:
    - The owner's name shows on every card.
    - Delete appears only on your own projects.
    - "Delete selected" deletes only the selected projects you own.
    - The Admin-only grouping by owner and its `listUsers` call are removed.
  - `App.tsx` hydrates a deep-linked project for Super Admins too.
  - `ProjectSummary.owner_name`.
- Unchanged on purpose: Usage & cost scoping (an Analyser still sees only their own projects' cost) and the `/admin`
  dashboard.

## Verified
- `ruff check backend`: clean.
- `pytest -q tests --ignore=tests/e2e_3org`: 757 passed.
- `tests/security/test_access_and_hardening.py` was updated to the new rules: any org member reaches every org
  project; a Super Admin only in member orgs; `require_project_org`; only the owner deletes (403 for others).
- Frontend: `tsc --noEmit` clean, lint 0 errors (32 warnings), `npm test` 15 passed, build done.
- Backend restarted (0 running/queued jobs) with `AZURE_OPENAI_*` blanked; health 200.
- Khadar's live session: org 4 (Testing Org), `org_member` True, `require_project_org` returns 4.
  `list_projects` (with the join) returns Testing Org's 1 project, owner name "khadar.syed".

## Not verified
- No project was created (standing rule). No browser click-through of the new card tag or Delete visibility.

## Follow-ups
- Owner names show `users.display_name`. Khadar's is "khadar.syed" (from the email at seeding); set it to his full name
  to get "First Last" on the cards.

# Auth, RBAC & Multi-Tenancy — Design Spec

**Status:** Draft, pending user review
**Author:** Claude Code (with khadar.syed)
**Date:** 2026-09-30

## 1. Goal

Add organization- and role-based login to the Hunter Intelligence Platform, which
today has **no authentication at all** (no users table, no session/JWT handling,
no login screen — confirmed by grep across `agent/app/core/db.py`, `agent/app/main.py`,
and `web/package.json`). This is phase 1 of a four-phase plan the user approved:

1. **Phase 1 (this spec):** core auth, roles, org/user management, data scoping.
2. Phase 2: per-org Tavily/SerpAPI key management + expiry notifications.
3. Phase 3: org branding (Pexels background + manual upload override).
4. Phase 4: visual design pass (frontend-design / ui-ux-pro-max / reactbits).

Phases 2–4 depend on orgs/users existing and are out of scope for this spec and
its implementation plan.

## 2. Roles

Exactly three roles — no others:

| Role | Scope | Can do |
|---|---|---|
| **Super Admin** | Global (not tied to one org) | Create/archive/reactivate Orgs; create/archive/reactivate any user including other Super Admins; view everything across every org; reactivate anything archived (only role that can reactivate). |
| **Admin** | One org (each org has exactly one Admin) | Create/archive Analysers in their own org; reassign an archived Analyser's projects to another Analyser; see and open every project in their org, grouped by owning Analyser. Cannot reactivate anything — only Super Admin can. |
| **Analyser** | One org | Create/own research projects; see and open only their own projects; update their own profile. |

An Admin may also create and own a project themselves, exactly like an Analyser
— project ownership is not restricted to the Analyser role, it's just that an
Admin additionally sees every project in their org regardless of who owns it.

Every user (all three roles) can update their own profile: display name and avatar
image. Email and role are read-only to the user themself.

Only a Super Admin can create another Super Admin — no one else can.

## 3. Data model

### New tables

```sql
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    background_image_url TEXT,          -- populated in phase 3; column added now
    created_at REAL NOT NULL,
    archived_at REAL                     -- NULL = active
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER REFERENCES organizations(id),  -- NULL only for Super Admins
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    role TEXT NOT NULL CHECK (role IN ('super_admin', 'admin', 'analyser')),
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    archived_at REAL                     -- NULL = active
);

CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
```

### Modified table

```sql
ALTER TABLE intel_projects ADD COLUMN org_id INTEGER REFERENCES organizations(id);
ALTER TABLE intel_projects ADD COLUMN owner_user_id INTEGER REFERENCES users(id);
ALTER TABLE intel_projects ADD COLUMN archived_at REAL;  -- NULL = active
```

No other table changes. Every other Intelligence Platform table (research items,
specs, briefs, jobs, evidence — everything `delete_project`'s existing cascade walk
already discovers via `project_id`) inherits its org/owner implicitly through the
project it belongs to. Access is gated at the project boundary, not re-derived
per child table.

### Migration bootstrap

The same migration that creates these tables:
1. Inserts one `organizations` row named "Default Organization".
2. Backfills every existing `intel_projects.org_id` to that org's id (so the
   current McAfee test project, and any other pre-existing project, keeps working).
3. Seeds the first Super Admin: `khadar.syed@infovision.com`, a fixed temp
   password documented in the PR/setup notes, `must_change_password = 1`,
   `org_id = NULL`, `role = 'super_admin'`.

## 4. Session mechanism

Server-side session cookie (not JWT) — chosen specifically because archiving a
user must end their access on their very next request, and a stateless JWT would
keep working until it expires unless a blocklist is added (which reintroduces the
same DB check anyway).

- `POST /api/auth/login` — email + password. On success: hash-verify with
  `bcrypt` (new dependency — nothing in `requirements.txt` currently provides
  password hashing or JWT), reject if the user is archived (same generic error as
  wrong password — never reveal archived status), create a `sessions` row, set an
  httpOnly, `SameSite=Lax` cookie holding the session token.
- `GET /api/auth/me` — returns the current user (id, email, display_name, role,
  org_id, avatar_url, must_change_password) from the session cookie, or 401.
- `POST /api/auth/logout` — deletes the session row, clears the cookie.
- `POST /api/auth/change-password` — required first action when
  `must_change_password` is true; also usable any time after.
- A FastAPI dependency (`core/auth.py::get_current_user`) resolves the session
  cookie into a user on every authenticated request, re-checking the user isn't
  archived on each call (this is what makes archiving instant).
- A second dependency, `require_project_access(project_id)`, wraps
  `get_current_user` and additionally checks: Super Admin always passes; Admin
  passes if `project.org_id == user.org_id`; Analyser passes only if
  additionally `project.owner_user_id == user.id`. Every project-scoped domain
  router endpoint depends on this instead of duplicating the check.

## 5. Archive & reactivate model

Nothing is ever hard-deleted through the UI — "delete" always means "archive":

- **Archiving an Org** cascades to archive all its users and all its projects.
- **Archiving an Analyser** does *not* touch their projects — those stay active
  and visible to the Admin, who can reassign each one's `owner_user_id` to a
  different active Analyser in the same org, whenever they choose (not forced
  at archive time).
- **Archiving a project** just sets `archived_at`; it drops out of every
  role's normal project list.
- **Reactivating** anything (org, user, or project) is a **Super-Admin-only**
  action, exposed in a dedicated "Archived" view under the Super Admin's Manage
  Organization tab — even an Admin's own archived Analyser needs a Super Admin
  to bring back.
- Archiving a session-holding user immediately invalidates their session on
  their next request (see §4).

## 6. Backend API surface

New domain folder `agent/app/domains/auth/` (matches this repo's existing
Django-style feature-folder convention — see `router.py`/`schemas.py`/
`repository.py`/`service.py` in every other `domains/<stage>/`):

- `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`,
  `POST /api/auth/change-password`
- `POST /api/auth/users` (create user — Admin creates Analysers in their own
  org; Super Admin creates users of any role in any org, or another Super
  Admin) — takes a temp password set by the creator, forces
  `must_change_password = 1`.
- `GET /api/auth/users` (list — Admin sees their org, Super Admin sees all or
  filtered by `org_id` query param)
- `POST /api/auth/users/{id}/archive`, `POST /api/auth/users/{id}/reactivate`
  (reactivate is Super-Admin-only, enforced server-side not just hidden in UI)
- `POST /api/auth/users/{id}/reassign-projects` (Admin: move an archived
  Analyser's projects to another active Analyser in the same org)
- `PATCH /api/auth/profile` (self-service: display_name, avatar upload)
- `POST /api/auth/organizations` (Super Admin only — org name + admin name/
  email/temp password in one call)
- `GET /api/auth/organizations` (Super Admin only — list, each row includes
  its Admin's name/email)
- `POST /api/auth/organizations/{id}/archive`,
  `POST /api/auth/organizations/{id}/reactivate` (Super Admin only)
- `GET /api/auth/archived` (Super Admin only — orgs/users/projects currently
  archived, for the reactivate view)

Existing domain routers (`projects`, `research`, etc.) gain
`require_project_access` on every endpoint that takes a `project_id`, and the
project-list endpoint filters by the current user's org/ownership instead of
returning everything.

## 7. Frontend

- **`AuthContext`** wraps the app: current user (id, email, display_name, role,
  org_id, avatar_url), `login()`, `logout()`, `refreshMe()`.
- **`App.tsx`** (currently a bare `useState<Page>` switch with zero auth
  concept) calls `GET /api/auth/me` on load. 401 → render `LoginPage`
  (email + password form) instead of the app shell. `must_change_password:
  true` → render a forced "set new password" screen before anything else.
- **New `SettingsPage`** (a full page in the existing sidebar nav — distinct
  from the unrelated `SettingsPanel.tsx` modal, which stays untouched since it
  configures the separate Brief-to-Deck product):
  - **Profile** (all roles): display name, read-only email/role, avatar upload.
  - **Manage Users** (Admin, and Super Admin drilled into a specific org):
    create/archive Analysers, reassign an archived Analyser's projects.
  - **Manage Organization** (Super Admin only): create Org (name + Admin
    name/email/temp password in one form), Org List (each row shows the
    org's Admin name/email inline), click through to that org's user list,
    plus the Archived view with Reactivate actions.
- **Projects/Dashboard list:** Super Admin sees everything; Admin sees their
  org's projects grouped by owning Analyser; Analyser sees only their own.
  Archived projects are absent from all three except the Super Admin's
  Archived view.

## 8. Error handling

- Login failure (wrong password, unknown email, *or* archived user) always
  returns the same generic "Invalid email or password" — never reveals which
  case, and never reveals that an email belongs to an archived account.
- Password policy: minimum 8 characters, enforced on temp-password creation and
  on the forced first-login change.
- Duplicate email on user/org-admin creation → clear 400 surfaced in the form.
- Basic lockout: a DB-tracked failed-login counter per email with a short
  cooldown after repeated failures — lightweight, not a full rate-limiting
  service, since this app isn't internet-facing yet.

## 9. Testing plan

TDD per this repo's convention (`agent/tests/`, gitignored, RED→GREEN):

- Password hashing round-trip; session create/validate/expire.
- `require_project_access` for all three roles × all three project-relationship
  cases (own org, other org, own project vs. teammate's project).
- Org/user archive cascades (archiving an org archives its users and projects;
  archiving a user does not touch their projects).
- Reactivate is rejected for non-Super-Admin callers, even on their own org's
  archived user.
- Login/me/logout/change-password endpoint behavior, including the generic
  error message for all three failure cases.
- Migration backfill: existing pre-migration projects land in "Default
  Organization" with a valid `org_id`.
- Frontend verified live via Playwright once built (matching how every other
  feature in this codebase has been verified this session).

## 10. Explicitly out of scope for this spec

- Phase 2 (Tavily/SerpAPI key management, expiry notifications, bell icon).
- Phase 3 (Pexels org background, manual upload override).
- Phase 4 (visual design pass).
- Email/SMTP invite flow (confirmed no email infra exists; temp-password model
  chosen instead).
- Rate limiting beyond basic per-email lockout.

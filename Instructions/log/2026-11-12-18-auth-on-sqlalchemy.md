# 2026-11-12 #18 — auth moved to SQLAlchemy; "my organizations" 500 fixed

## Request
"yes as you recommend please go head" — continue with auth after usage.

## Changed
- `domains/auth/models.py` (new): organizations (14 columns), users (12), sessions (5), user_organizations (4,
  unique user_id+org_id), password_resets (10) — column lists read from the live schema — plus intel_projects
  (id, project_name, org_id, owner_user_id, archived_at) for archive/reassign.
- `domains/auth/repository.py`: SQLAlchemy Core, the same 44 functions (names/arguments/results; checked by AST),
  `__all__` listing exactly them (core/store.py star-imports the module). Multi-step writes keep one transaction
  each (delete user/org, archive org, create org + admin, complete reset).
- BUG FIXED: `list_user_organizations` UNIONed a boolean `(u.org_id = o.id)` with an integer `0`; Postgres refuses
  ("UNION types boolean and integer cannot be matched"), so GET /api/auth/me/organizations (profile menu "orgs
  you're mapped to") failed on every call. Both sides are booleans now (schema and frontend expect bool).

## Verified
- Parity in a throwaway schema (`scratchpad/auth_parity.py`, old module from git HEAD), writes alternated between
  old and new: users/emails (case+space), sessions incl. expiry, active-org switching (member, non-member, super
  admin, archived org), 5-failure lockout + clear, password update/reset flags, profile/avatar, make_super_admin,
  orgs create/for-member/bare/find/name-taken/platform flag, archive/reactivate org and user, reassign, list_archived,
  memberships, password resets (otp, admin link, attempts, verify, by token, recent count, complete_reset signs out),
  deletes: 236 comparisons, 0 differences. Old list_user_organizations raises DatatypeMismatch; new returns
  [primary, memberships] ordered.
- pytest auth, security, billing, projects, providers, usage, memory, exclusions, guardrails, assets, agent,
  test_mailer: 185 passed.
- Local backend restarted on the new code (no jobs existed).

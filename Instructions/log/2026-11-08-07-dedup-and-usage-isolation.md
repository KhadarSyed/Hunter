# 2026-11-08 #07 — Duplicate checks + per-org usage/project isolation

**Request:** Did you check deduplication of org and user? Can each org admin reach only their own usage page and
projects (not another org's)?

**Duplicates (all rejected, nothing created):** org name exact / case+spaces / upper-case of a test org → 409; new org
reusing an existing client admin's email (also different case + trailing space) → 400 "Email already in use"; admin
re-adding own user (any case) or itself → 409; project name case variant in same org → 409.

**Bug found + fixed:** an Org Admin who typed the email of a user from ANOTHER client org got 200 and the user was
linked into their org (cross-tenant leak) without any seat check (Acme was full 5/5). Proven, then undone.
Fix (`auth/router.create_user_route`): Admin → 409 "already has an account in another organization. Ask the platform
administrator to share it"; only a Super Admin can share a user into another org, and that now calls
`billing.require_seat`. `billing/repository.org_user_count` now counts shared members too (Super Admins never count).

**Usage / project isolation (Acme 9 vs Globex 10, projects 2 vs 3), all OK:** admin `/usage/calls` only own org's
projects; `?org_id=<other>` ignored; `?project_id=<other>` → 0 rows; summary for other project 0 tokens vs 13,805 for
own; `/usage/projects/<other>/total` 403, own 200; open other org's project 403; project list own only; prices PUT
refused. Analyst 2 can't see/open analyst 1's project or its usage; analyst 1 sees own; analyst → billing org
dashboard 403. Scope lives in `usage/router._scope_where` (mirrors `core.auth.can_access_project`).

Tests: providers + billing + auth 41 passed. Server restarted.

# 2026-11-08 #05 — Admin dashboards, subscriptions, token allowances, org guardrails

**Request:** Super Admin lands on a dashboard tracking all orgs, users, projects, usage and licence (review-only, no
project access) and creates orgs + users there. Org Admin dashboard: projects, owner, last updated. Licence =
subscription plans (users + projects; tokens excluded because orgs buy their own models); Org Admin upgrades/renews in
Settings (before expiry → queued until the current one ends; after expiry → now); test payment gateway for now;
emails to Admin + procurement manager incl. renewal. Org form: name, logo, procurement name/email/phone, address,
country, PIN; that email becomes the org Admin. Org Admin sets per-user token allowance; email when used up.
Org Admin adds/edits/deletes guardrails; InfoVision's pasted guardrail stored unchanged and followed in every stage,
especially research and deck — but only where it matters, to avoid wasting tokens (user chose: writing + tagging).

**Built:**
- Backend: migration 50 (org profile cols, `subscription_plans` seeded Starter/Growth/Enterprise, `org_subscriptions`
  with Enterprise backfill, `user_token_limits`), migration 51 (`org_guardrails`). `domains/billing/` (repository,
  service, router `/api/intel/billing/*`), `domains/guardrails/` (+ `seed_infovision.md`, router `/api/intel/guardrails`).
  `core/llm_provider.py`: `TokenLimitReached`, `_guard()` adds guardrails for `GUARDED_STAGES`, token check before
  every uncached call. `core/auth.can_access_project`: Super Admin → False. `auth/router.py`: org create takes profile
  + plan, user create checks seats (402). `projects/router.py`: project create checks plan (402). `main.py`: seed +
  sweeper.
- Frontend: `pages/AdminDashboard.tsx` (tiles, org table with flags, review-only drill-down, New organization, New
  user via ManageUsersTab, Plans editor), `pages/OrgDashboard.tsx`, `pages/SubscriptionTab.tsx` (test checkout modal),
  `pages/GuardrailsTab.tsx`, `components/admin/{adminUi,OrgDetailView,NewOrgForm}.tsx`; `App.tsx homeFor()`.

**Verified:** tsc clean, build OK; `tests/billing/test_subscriptions.py` 8 passed (queued renewal, after-expiry,
idempotent pay/cancel, limits, sweep reminders once, token cap emails once, month-end). Live: plans + backfill present,
InfoVision guardrail byte-identical to the paste, SA overview/org detail 200, SA open project 403, Admin own org 200,
Admin overview 403, Admin create org 403, Admin open project 200. Server restarted (0 active jobs).

**Not done / risks:** no live paid checkout or email send (would email real InfoVision admins); UI not screenshotted
(browser session token creation was blocked). Guardrails are instructions to the model — output is not post-checked
for the prohibited words. Khadar (Super Admin) can no longer open projects; testing projects needs an Admin/Analyser
account. Design doc `docs/plans/2026-11-08-admin-dashboards-subscriptions-design.md` kept local.

# 2026-11-13-03 Remove the payment system; Super Admin applies every plan

## Request
"remove payment system, usually Super admin can apply plans and top ups, remove payments system from app".

## What changed
- `backend/domains/billing/service.py`: deleted `PaymentGateway`, `TestGateway`, `gateway`, `PAYMENTS_OFF`,
  `payments_live`, `start_checkout`, `complete_checkout`, `_pay_lock` (and the `uuid` / `Protocol` imports).
  `grant(org_id, plan_id, user_id, notify=False)` is the only way a plan is applied (new, renewal, upgrade, top-up);
  with `notify=True` it emails the org's admins "activated" (nothing running) or "renewed" (queued / applied while
  running). Email and limit messages no longer mention payment or "Settings → Subscription"; they say to ask the
  platform team.
- `billing/router.py`: removed `POST /billing/checkout`, `GET /billing/checkout/{id}`, `POST /billing/checkout/{id}/pay`
  and `_own_checkout`. `POST /billing/orgs/{org_id}/grant` (Super Admin) now takes `GrantRequest` and sends the email.
  Org creation (`auth/router.py`) still calls `grant` without notify (the welcome email covers it).
- `billing/schemas.py`: `CheckoutRequest` -> `GrantRequest`; `PayRequest` removed.
- `billing/models.py`, `repository.py`: comments only. No schema change: `payment_ref` stays (grant writes
  "granted"); old `pending_payment` / `cancelled` rows are already excluded by `_PAID_STATUSES`. Local DB had none.
- Frontend: `SubscriptionTab.tsx` (Org Admin) is read-only (plan tiles, queued renewal, plans on offer, history) with
  "contact the platform team"; checkout modal and buy buttons removed. `AdminDashboard.tsx`: new `ApplyPlan` in the
  org detail modal (plan select + Apply plan -> `intelApi.grantPlan`). `intel-api.ts`: `startCheckout` / `getCheckout`
  / `payCheckout` replaced by `grantPlan`.
- Plan price / currency stay on plans (shown as list price; billed outside the app).

## Verified
- `python -m ruff check backend`: All checks passed.
- `python -m vulture backend --min-confidence 80 --exclude backend/static`: one hit, `deckstudio/creative.py:96`
  (pre-existing, file not touched).
- `HUNTER_PG_SCHEMA_PER_DB=1 python -m pytest -q tests/billing`: 11 passed (checkout tests rewritten as grant tests:
  queued renewal emails "renewed", grant after expiry starts now and emails "activated", no email without notify,
  unknown plan refused).
- `cd frontend && npx tsc --noEmit` clean; `npm run lint` 0 errors (32 warnings); `npm test` 14 passed.

## Not verified
- Not clicked through in the browser yet, and the backend was NOT restarted (the A/B project build is running on it;
  a restart kills the job). The running backend still serves the old checkout routes until the restart.
- `npm run build` (backend/static) not run yet: done with the restart.
- `tests/e2e_3org/run.py` steps "acme checkout" and "globex cancels a checkout" are now stale (local only).

## Follow-ups
- After the A/B run: restart, build the frontend, click through Apply plan as Super Admin and the read-only tab as
  Org Admin; then the Super Admin platform-model switch per org (approved in conversation, not built yet).

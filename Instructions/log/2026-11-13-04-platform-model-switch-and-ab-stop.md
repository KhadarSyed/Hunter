# 2026-11-13-04 Super Admin maps the platform model per org; A/B run stopped

## Request
1. (earlier, approved to build after A/B) "whatever model was configured for the org, only those models ... unless
   Super Admin maps or configures LLM to that organization."
2. "delete project and stop A/B run plan for now, once Gpt got approval we can run it ... continue with other request
   ... then move all code to repo main".

## What changed
- A/B batching run stopped (build script task killed, backend restarted mid-brief), project 3 "Casino Gaming —
  Batching A/B" deleted with `store.delete_project`. Test Organization has 0 projects. The A/B is to be re-run once
  GPT spending is approved (the harness `tests/e2e_3org/infovision_compare.py casino_ab` is ready; it now signs in as
  an org Admin via `COMPARE_EMAIL`, default `<seed local>+testorg@<seed domain>`, and sets the session cookie without
  a domain so `requests` sends it).
- `backend/domains/providers/router.py`: new `PUT /llm-providers/platform-access` `{org_id, enabled}`, Super Admin only
  (403 otherwise), sets `organizations.platform_llm` and invalidates the org's provider cache. Registered BEFORE
  `PUT /llm-providers/{provider_id}` (the first version was after it and every call answered 422).
- `providers/schemas.py`: `PlatformAccess`.
- `core/auth.py` `seed_super_admin_if_missing`: InfoVision gets `platform_llm` only when the org is first created;
  it is no longer forced back on at every startup, so a Super Admin's choice sticks.
- Frontend: `ProvidersTab.tsx` shows "Allow the platform model" (checkbox) to the Super Admin only;
  `intel-api.ts` `setPlatformAccess`. `AdminDashboard.tsx` org modal title "Organization" (it now has Apply plan).
- Docs: `Instructions/README.md` LLM chain line, `docs/handover/HANDOVER.md` LLM row, `providers/service.py` docstring.
- Local only: `tests/providers/test_platform_access.py` (new), `tests/e2e_3org/run.py` checkout steps rewritten to the
  Super Admin Apply plan flow (`plan_card` helper removed).
- Local DB: Test Organization got a Starter plan (Super Admin grant) and an Admin user (`+testorg` address) for the
  A/B run; its `platform_llm` is 0. InfoVision keeps 1.

## Verified
- `pytest -q tests/providers tests/billing tests/auth` (HUNTER_PG_SCHEMA_PER_DB=1): 54 passed before the route-order
  test; `tests/providers` 30 passed after it.
- `ruff check backend` clean; `npx tsc --noEmit` clean; `npm run lint` 0 errors; `npm test` 14 passed; `npm run build` ok.
- Browser (Playwright, backend restarted with this code): Super Admin ticks the box for Test Organization -> DB 1,
  unticks -> DB 0; the org Admin's LLM Providers tab has no such box; InfoVision still 1 after restart.
  Screenshot `shots/billing/superadmin-platform-toggle.png`.
- Billing (log 03) in the browser too: Super Admin "Apply plan" queued Starter for Test Organization, the Admin's
  Subscription tab is read-only with no Renew/Buy/Pay buttons; `POST /billing/checkout` -> 405; Admin grant -> 403.

## Not verified
- `tests/e2e_3org/run.py` not run (creates three orgs and sends emails).
- The backend here runs with `AZURE_OPENAI_*` blanked (finance: no GPT spend), so a platform-mapped org gets no chat
  model locally; with GPT configured it gets Azure as before (path unchanged).

## Follow-ups
- Re-run the A/B batching comparison when GPT spend is approved.
- Optional: retry a map-step batch once when Nemotron returns an empty reply (3 of ~46 batches in this run), and
  consider an output cap for reasoning models on the reduce call (one call streamed > 30 min).

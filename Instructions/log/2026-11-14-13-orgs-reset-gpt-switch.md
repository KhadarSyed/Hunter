# 2026-11-14-13 Orgs/users reset; InfoVision on GPT-4.1 (GPT-5 saved, switched off); per-model on/off switch

## Request
- "delete all org and users - except Harish Super Admin, Create Infovision accout which is default account - Super
  admin map gpt-4 and gpt 5 both models only 4 should be active on Infovision - Same thing should be on Prod by default
  infovision will be the Org. For testing In local create Testing Org - assign LLM model Nvidia current 3 models - add
  khadar.syed@infovision.com".
- Answers:
  - Super Admins: Harish (`harish.thulasiram@infovision.com`) and Khadar (`khadar.syed@infovision.com`).
  - Khadar in the Testing Org: "Admin". One role per user, so Khadar stays a Super Admin (a superset of Admin) and is
    a member of the Testing Org.
  - GPT-5: "Add an on/off switch". Prod: "Auto from Render settings".

## What changed (code)
- Migration `0007_provider_enabled`: `org_llm_providers.enabled` BIGINT NOT NULL DEFAULT 1; the column is in
  `providers/models.py`.
- `providers/service._rows` (failover order) leaves out models that are switched off, so they are never called, not
  even as a fallback. `repository.newest_for_org` (the next default after a delete) picks only enabled models.
- `PUT /api/intel/llm-providers/{id}/enabled` `{enabled}` (`schemas.ProviderEnabled`). An org admin or Super Admin
  may use it, an analyser gets 403. Switching off the default gives 400 (make another the default first).
  `POST …/{id}/default` on a model that is off gives 400. `ProviderRecord.enabled`.
- `providers/service.seed_platform_models(org_id, env)`, called from `core/auth.seed_super_admin_if_missing` after the
  InfoVision org exists (wrapped, never blocks startup):
  - It runs only when the org has no models and `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` are set.
  - It adds `AZURE_OPENAI_MODEL` (on, default) and `AZURE_OPENAI_GPT5_MODEL` (default "gpt-5", saved but off),
    both `azure_openai` with the key encrypted. It makes no AI call.
  - So a new production database gets InfoVision with its GPT models from Render's existing env; nothing on Render
    was changed. New env var `AZURE_OPENAI_GPT5_MODEL` is in `.env.example`.
- Frontend `ProvidersTab.tsx`: an "Off" badge (grey card), a "Switch off / Switch on" button on non-default models,
  and no "Make default" while a model is off. `intelApi.setLlmProviderEnabled`, `LlmProvider.enabled`.

## What changed (local data; scratchpad `reset_orgs.py`)
- The backup was taken first: `pg_dump --data-only` of organizations, users, user_organizations, org_llm_providers,
  org_llm_state, org_subscriptions, llm_usage and sessions (scratchpad `backup_orgs_users.sql`).
- Created:
  - "Testing Org" (id 4): `platform_llm` off, plan 1 (the plan Test Organization had, granted via
    `billing.grant`), its 3 NVIDIA model rows copied (keys still encrypted, same default). Khadar is a member.
  - Harish (user 8): super_admin, member of InfoVision, a random password nobody saw, `must_change_password`. He
    signs in first through "Forgot password?". No email was sent to him (test emails go to Khadar only).
  - InfoVision's models from `.env`: Azure `gpt-4.1` on + default, `gpt-5` off.
- Deleted:
  - Orgs 1 "Default Organization" and 3 "Test Organization".
  - User 3 `khadar.syed+testorg@…` with 15 sessions.
  - Their rows: 3 model rows, 3 subscriptions, 69 usage rows; org_llm_state had 0.
- Final:
  - Orgs: InfoVision (2), Testing Org (4). Users: khadar (2) and Harish (8), both super_admin.
  - No rows in any `org_id` table point at a missing org.

## Verified
- `tests/providers/test_enabled.py` (local, Postgres), 4 tests:
  - The seed adds gpt-4.1 on/default and gpt-5 off; failover lists only gpt-4.1; the key decrypts; a second run
    adds nothing.
  - No key means no models.
  - Switching the default off gives 400; making an off model the default gives 400; switching on works; switching
    the old default off after moving the default works; the failover list follows.
  - An analyser gets 403.
- ruff clean; `pytest -q tests` (minus e2e_3org): 755 passed. Frontend tsc clean, lint 0 errors, `npm test` 15
  passed, build done.
- The backend restarted (no projects or jobs) and applied 0006 → 0007; health 200.
- Playwright with a 10-minute temp session for user 2 (deleted afterwards):
  - API: InfoVision has gpt-4.1 DEFAULT on and gpt-5 OFF; Testing Org has nemotron DEFAULT on, minimax on and step
    on. The org list is InfoVision and Testing Org.
  - Settings → LLM Providers for InfoVision shows the Default card, the Off badge and "Switch on"
    (`.playwright-mcp/providers_infovision.png`).

## Not verified / open
- The GPT models were not tested (no AI call: the GPT comparison and GPT spend stay paused).
  - InfoVision's gpt-4.1 has its own key, so the blanked `AZURE_OPENAI_*` launch no longer stops spend for work run
    in InfoVision. Test in the Testing Org.
  - A `gpt-5` deployment is not known to exist on the Azure resource.
- Production: not deployed by me (pushing main auto-deploys). The seed acts only on a database where InfoVision has no
  models, and only if Render has the Azure endpoint and key.
  - Harish is not a Super Admin there unless he is the `SEED_SUPER_ADMIN_EMAIL` or is added after.
- Found, not changed: the app's own "Delete org" (`auth/repository.delete_organization`) removes only the org and
  memberships. Its models, subscriptions and usage rows stay behind (done by hand in this reset).

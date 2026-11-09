# 2026-11-09 #24 — gpt-4.1 / gpt-5 prices, editable by admins on Settings → LLM Providers

User: "please update the usage and cost price like below … GPT-4.1 Global $2.00 / $0.50 / $8.00, GPT-5 Global
$1.25 / $0.13 / $10.00 … give admin to update these option while integrating the llm models now update these things
on Infovision". User also commented out `AZURE_OPENAI_REASONING_EFFORT` in `.env`.

**Found:** no gpt-4.1 row in `llm_prices` (Azure retail sync finds no GPT 4.1 meter in southindia), so every gpt-4.1
call was costed $0. `PUT /usage/prices` existed (super admin only) but no screen called it.

**Done:**
- Local DB: `llm_prices` manual rows effective 2026-11-09: azure_openai gpt-4.1 global 2.00/0.50/8.00 and gpt-5 global
  1.25/0.13/10.00. Response names (`gpt-4.1-2025-04-14`, `gpt-5-2025-08-07`) resolve to them by prefix.
- `usage/prices.py` DEFAULTS seeds gpt-4.1 2.00/0.50/8.00 (dated 2025-04-14) on any DB without a gpt-4.1 row
  (i.e. production on next start). The gpt-5 cached 0.13 is not seeded: set it on prod from the UI.
- `usage/router.py` `_may_price`: super admin any price; an org admin may price a model only its org runs — the
  platform model (`AZURE_OPENAI_MODEL`) for a `platform_llm` org (InfoVision), or a model of its own providers — and
  only when no other org has a provider row on the same provider type + model (price rows are shared). New
  `providers/repository.orgs_using_model`.
- UI `components/usage/ModelPrice.tsx` on `pages/ProvidersTab.tsx`: "Price / 1M tokens" line (input / cached / output,
  since date) under the platform-model card and each provider card, with Edit → 3 inputs → Save (new row from today,
  UTC). Unset price shows "not set (calls are costed at $0)".
- Cost is computed when a call is recorded; earlier rows keep their stored cost.

**Checked:** price lookup and cost (1M in + 1M out on gpt-4.1 = $10.00); permission rule against real orgs
(InfoVision admin yes for gpt-4.1, not for gpt-5 while it is not the platform model; Acme admin no; analyst no);
local tests `backend/tests/test_price_permission.py` 5 passed; `tests/usage`; `tsc` + `npm run build` clean.

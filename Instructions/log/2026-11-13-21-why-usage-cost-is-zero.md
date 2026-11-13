# 2026-11-13-21 Why Usage shows tokens but $0 cost (read-only check)

## Request
"token input and out are calculated but not cost why" (with the Usage page link, last 30 days).

## Findings (code + local DB, nothing changed)
- Cost = tokens x the price row `usage/repository.price_for(provider, model, deployment_type, day)` finds, computed
  once in `usage/service.record()` and stored in `llm_usage.cost_usd`. No row -> `cost_usd()` returns 0.0 silently.
- Org models are recorded as provider `openai_compatible` with the org's model name. `llm_prices` has rows only for
  `azure_openai` GPT models and the seeded `nvidia / nvidia/` $0 row (provider `nvidia`, used by the platform
  embeddings), so no row matches the Test Organization's models:
  `nvidia/nemotron-3-ultra-550b-a55b` 238 calls (251,860 in / 373,844 out), `minimaxai/minimax-m3.1-flash` 176,
  `stepfun-ai/step-5-preview` 18 -> all $0.
- The app already lets a price be set: Settings -> LLM Providers -> "Set price" per model (`ModelPrice.tsx`,
  `PUT /api/usage/prices`; Super Admin any model, org Admin only its own models); it applies from today.
- Gaps: the Usage page does not mark unpriced models (shows $0), and past calls are never re-costed.
- Also seen: `llm_usage` rows from tests (`azure_openai` models `dep`, `d`, `fake-<hex>`), written into the dev DB
  before the memory-test schema fix; not cleaned yet.

## Not changed / open (asked the user)
- Prices for the NVIDIA models are the user's call (NVIDIA's hosted catalog may be free for this account).
- Offered: mark unpriced models on the Usage page; re-cost past calls when a price is saved; delete the test rows.

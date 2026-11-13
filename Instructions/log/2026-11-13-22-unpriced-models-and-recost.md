# 2026-11-13-22 Usage: unpriced models flagged, first price costs earlier calls, test rows removed

## Request
"continue" after log 21 (Usage showed tokens but $0 cost because no price row matched the org models). Did the three
offered fixes.

## What changed
- `usage/router.usage_summary`: each `by_model` row has `priced` (`repo.price_for` finds a row now); `kpis` has
  `unpriced_models`.
- `usage/router.usage_put_price`: a model's FIRST price is back-dated to its first recorded call
  (`repo.first_use_day`) and every stored call from that day is re-costed (`repo.recost`, cache hits stay free); a
  later price applies from its day as before (calls already recorded that day are re-costed). Response adds
  `effective_from`, `recosted_calls`.
- `usage/repository`: `first_use_day`, `recost` (UTC day start via `calendar.timegm`; shortcut: a price with no
  deployment type re-costs every type of the model).
- Frontend: SummaryTable shows "no price set" (amber, tooltip points to Settings -> LLM Providers -> Set price)
  instead of $0; the Total cost tile says "N models have no price set (not counted)"; the price editor says the
  first price also costs earlier calls; `setUsagePrice` return type.
- Dev DB: deleted 77 leaked test rows from `llm_usage` (azure_openai `dep`, `d`, `fake-<hex>`, no org/project,
  0 tokens). Running tests/core, tests/memory and tests/usage added none (the leak was fixed in log 18).

## Verified
- New test `tests/usage/test_usage_router.py::test_unpriced_model_is_flagged_and_its_first_price_costs_earlier_calls`;
  full `pytest -q tests` (minus e2e_3org): 723 passed; ruff and vulture clean; frontend tsc clean, lint 0 errors,
  `npm test` 15 passed, build done.
- Live (Test Org admin session, last 30 days): unpriced_models 3 (Nemotron 3 Ultra, MiniMax M3.1 Flash, Step 5
  Preview); the NVIDIA embedding model priced at the seeded $0.

## Not verified / open
- No price was entered for the NVIDIA chat models: the amount is the user's decision.
- The Usage page and price editor not clicked through in a browser.

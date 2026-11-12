# 2026-11-12 #06 — Where LLM calls can become Python (review only, nothing changed)

## Request
"also see most how LLM call can be reduced and handled by python code where i can - make sure quality is not
compromized". Standing rule: speed/cost changes need before/after proof of no quality loss.

## Already in place (verified in code)
- 7-day identical-prompt memory under every GPT call (`HybridLLMClient.chat`, `domains/memory`).
- Syndicated article copies inherit the original's tags (`tagging_job` → `repo.inherit_article_tags`).
- Per-RQ tagging only sees articles the free Boolean match already matched (`repo.rq_rows_needing`).
- Per-URL extraction cache (`deliverable/extract.py`); per-category entity verdict memory (`entity_relevance.py`).
- Guardrails deck check is Python first (`guardrails/check.py`); count readings are number-checked with a Python
  fallback and one call per chart (`deckstudio/count_reading.py`, repair path only).
- Vision photo checks are budgeted per slide and per run, after Python size/corruption checks (`assets._accept`).
- Per-slide creative restyle is off (`deckstudio/pipeline.CREATIVE_RESTYLE = False`).

## Candidates (not done; each needs a before/after comparison on a real project)
1. Batched insights (`deliverable/insights_batch.py`, opt-in `HUNTER_BATCH_INSIGHTS=1`): 3 calls per question instead
   of 3-8 per chart section. Same _screen/judge checks. Biggest saving; compare decks with it off vs on.
2. Research map step (`research/multi_source.py`): items deduped by URL only; same-story syndication (normalised
   title) could be summarised once and keep an "also covered by" list. One-off per project: small saving.
3. Dead `core/llm_synthesis.py` (audit 10): no runtime calls; deletion is code cleanup only.
- Not candidates: vision checks (quality gate for on-brief photos), per-RQ intent judging (keyword hits alone cannot
  judge intent), `deliverable/classify.py` (only the CLI uses it).

## Needed to rank by real cost
`llm_usage` tokens by stage/sub_stage (Usage page, or a read-only query on production) — not run.

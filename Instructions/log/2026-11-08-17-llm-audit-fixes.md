# 2026-11-08 #17 — LLM-savings audit fixes ("fix all")

**Fixed**
1. Prompt cache per org: `memory.llm_key(..., org=)`; `HybridLLMClient.chat` passes the routed org (else the usage
   scope's org). One org never gets another's cached answer.
2. Bad answers: a `format_json` reply that does not parse (`llm_provider._parses`) is never cached. Deck runs run in
   `memory.fresh()` (`deliverable/engine.run_engine`): Regenerate never replays cached answers (new ones still saved).
3. Tagging: `_parallel` re-raises `NoChatProviderError` (incl. `TokenLimitReached`); a failed phase ends the job
   `failed` with "Tagging stopped — <phase>: <reason>", no "data set tagged" email.
4. Match before content: content phase also fetches unmatched rows with < 400 chars of summary+content
   (`dataset/repository.articles_needing`), and a second free match ("match full text") runs after it.
5. Classification cache: reused only under 30 days old and from the same model (`get_cached_classification(...,
   model)`); `extract` now records the real model name (was always "azure-openai").
6. Vision unavailable: `vision.matches` returns `UNAVAILABLE` when no model / call fails; `assets._accept` then uses
   the text gate. Budget spent still rejects (UNVERIFIED).
7. Fallbacks visible: `deliverable/runlog.py` (`bind`, `note`, `take`) bound to the run's log in `_run_engine`;
   "Fallback: …" lines for theme consolidation, entity relevance, cover subtitle, product makers, insight fact cards,
   default plan, count reading, image scenes (image_brief now logs). Guardrail AI review raises `ReviewFailed` →
   route returns `error`, panel shows it (never "0 findings").
9. Strategy: log says "Rule-based (deterministic)" vs "LLM"; Search Strategy page shows "Rule-based (AI unavailable)".
12. Logo vision checks capped per run: `visuals.MAX_LOGO_CHECKS = 40` via `runlog.take`.
14. `HybridLLMClient.model` property → specs record the real model instead of "unknown".

**Not changed (with reason)**
- 8 batched section summaries: speed-up needs before/after quality proof on a real deck (standing rule); no working
  model with enough credits to build one locally. Left behind `HUNTER_BATCH_INSIGHTS`.
- 10 Azure retries: already recorded per retry in `llm_usage` (azure_openai_client.py:100,109,119); 429s are not
  billed; the 8 rate-limit retries exist so parallel tagging does not come back blank — cutting them loses quality.
- 11 keyword widening: narrowing the match could drop relevant articles; it only costs a few tokens.
- 13 date in research prompt: the date is part of the instruction (recency); caching across days would be wrong.

**Tests:** `tests/core/test_audit_fixes.py` 13 + guardrails 5 updated → 18 passed. Broader suites run in background.

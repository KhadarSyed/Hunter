# 2026-11-08 #16 — Audit: where Python replaces / reduces LLM calls, and the quality cost (report only, no code changed)

**Request:** /ponytail-audit — check where Python code is used to lower LLM calls; report with how much quality is lost.

**Verified in code (beyond the mapping agent):** memory prompt cache key = sha256([model, format_json, messages]),
stored scope "global" with no org (memory/service.py:77-93); taggers catch only (AzureOpenAIError, ValueError)
(article_tagging.py:125, rq_tagging.py:96) and the tagging job ends "completed" after a failed phase
(tagging_job.py:290-296); image_brief.scenes swallows errors silently (image_brief.py:74-75); strategy logs
"LLM strategy generation succeeded" after a deterministic fallback (strategy/router.py:644, marker unused :266);
no memory.fresh() in deliverable/ or deckstudio/.

**Findings delivered to the user (numbered 1–14):** cross-org prompt cache, cached bad answers + Regenerate reuse,
tagging silent pending, Boolean match before content fetch, global classification cache without model/TTL, vision
reject on no LLM, silent fallbacks list, per-chart summary calls (batched mode off), strategy log, Azure retries,
keyword-match widening, logo vision without budget, research map prompt carries the date, guardrail AI review "[]" on
failure. Quality-cost table per Python shortcut included.

**Load assumed:** a few orgs, a handful of analysts each, decks of 4–6 questions, data sets of 1–10k articles.

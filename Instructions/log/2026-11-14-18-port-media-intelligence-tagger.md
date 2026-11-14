# 2026-11-14-18 Port media-intelligence-agent's tagging (rich format 2), behind HUNTER_TAG_FORMAT=2

## Request
"can we integrate the tagging agent D:\media-intelligence-agent\ … using the LLM of the org level model … (Lets port
then)". Also: events and campaigns need "what it is about", and campaigns their name and keywords.

## Decision
- Port, don't import. media-intelligence-agent calls Azure GPT directly through LangGraph/LangChain (`llm/client.py`),
  which would bypass the org's providers and failover, usage, token limits, guardrails, memory and the GPT spend
  freeze. Only the format, the prompt rules and the quality control were ported; calls go through `llm.chat`.

## What changed
- New package `backend/agents/enrichment/`:
  - Copied with only the import paths rewritten: `model.py` (was schemas/enrichment.py), `sentiment.py`,
    `relevancy.py`, `brand_aspects.py`, `classification.py` (theme-merge models dropped), `entities.py`,
    `evidence.py`, `brand_relevancy.py`, `entity_taxonomy.py`, `quality_control.py`.
  - `entities.EntityResult` gains `description` (events and campaigns: what it is about) and `keywords` (campaigns).
  - `tagger.py` (new):
    - prompt from their rules plus the JSON shape, the entity groups and Hunter's `author_type`;
    - articles in token-sized batches (`batching.pack`, `OUT_PER_ARTICLE` = 1800) through `llm.chat`;
    - every answer goes through Pydantic and `validate_enrichment_quality`, and an article that fails gets one
      self-correction call (the better answer is kept, a still-failing one is stored with quality.status "failed");
    - stored tags = the old flat fields (`legacy()`), so every reader keeps working, + `format: 2` + `enrichment` +
      `quality`.
- `dataset/tagging_job._tagger()`: `HUNTER_TAG_FORMAT=2` picks the new tagger. Unset keeps the old one (default).
  The new variable is in `.env.example`.

## Verified
- Their 6 test files ported to `tests/enrichment/` (local): 45 passed.
- New `tests/enrichment/test_tagger.py`, 5 tests with a fake model:
  - a clean answer takes one call and keeps the legacy fields;
  - an invented quote triggers one self-correction;
  - a still-failing answer is flagged;
  - the prompt holds the monitored brands and the entity groups;
  - events and campaigns keep their description and keywords.
- `tests/enrichment` 50 passed; `tests/dataset` passed with it (161 together before the description change); ruff clean.
- Pilot, `tests/enrichment/ab_project41.py 10` (local, writes nothing), Testing Org NVIDIA, project 41:
  - 10/10 answered; quality control 9 passed, 1 review_required, 0 failed;
  - overall sentiment agrees with the stored old tags 10/10;
  - themes are more specific but split more ("Restaurant Opening" / "Celebrity Restaurant" / "Celebrity Restaurant
    Opening" where the old tags used one label); the themes phase consolidates labels;
  - about 62 s per article with ONE article per call.

## Incident (mine)
- A second uvicorn I started at 12:02 UTC could not bind port 8002. Its startup lifespan had already resumed
  project 41's running tagging job, and its shutdown failed the job ("cannot schedule new futures after interpreter
  shutdown").
- Nothing is lost (rows are per article). Re-tag continues from what is untagged (418 RQ rows done).
- Follow-up: resume jobs only after the server is serving, or check that the port is free first.

## Not verified / next
- The 60-article side-by-side with batched calls (speed and theme spread); the flag stays off until then.
- The per-RQ record and table changes (Steps 1-5 of the plan) are not built yet. The sample artifact was updated
  for sign-off.

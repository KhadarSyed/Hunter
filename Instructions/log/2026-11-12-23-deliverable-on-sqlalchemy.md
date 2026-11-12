# 2026-11-12 #23 — deliverable (deck engine storage) moved to SQLAlchemy

## Changed
- `domains/deliverable/models.py` (new): intel_deliverable_runs (15 columns), intel_deliverable_sections (7),
  intel_article_classifications (5, key norm_url+field), intel_reference_decks (5), intel_deliverable_plans (6),
  intel_latest24h_refreshes (12; counts_json/fetched/kept server defaults), intel_deliverable_files (8, bytea).
- `domains/deliverable/repository.py`: SQLAlchemy Core, the same 26 functions + CLASSIFICATION_MAX_AGE_S, `__all__`.
  Kept: the run-field allowlist, streaming deck saves (one part in memory, one transaction, failed save keeps the
  previous run) and streaming part reads (a generator on one connection). replace_deliverable_section's delete +
  insert now share one transaction. Deck-file inserts never return their bytes.

## Verified
- Parity (scratchpad/deliverable_parity.py, old from git HEAD, writes alternated): run create/update/allowlist/
  latest/active/durations, startup cleanup (repair-with-deck -> completed, others failed), sections replace by key +
  order, classification cache (model filter, 30-day age), reference decks, plans upsert, refresh finish + pruning of
  older non-running refreshes per project + interrupted, deck files save/replace other runs/names/S3 keys/parts and a
  save that fails midway rolls back: 38 comparisons, 0 differences.
- pytest deliverable, deckstudio, projects: 160 passed; 11 failed = the known pre-existing set (latest24h 6,
  time_grain 4, live_slides 1).

# 2026-11-12 #22 — research moved to SQLAlchemy

## Changed
- `domains/research/models.py` (new): intel_background_research (11 columns), intel_news_approvals (6),
  brand_logos (6), pexels_images (7), youtube_videos (7), intel_research_items (19, unique project+url),
  intel_research_item_vectors (5, vector bytea) — from the live schema.
- `domains/research/repository.py`: SQLAlchemy Core, same 21 functions + VECTOR_LOOKUP_CHUNK, `__all__`.
  upsert_research_item keeps the source_api accumulation and `access = COALESCE(new, old)`; its read-merge-write
  now runs in one transaction and returns the id via RETURNING. save_item_vectors no longer gets the vector bytes
  back (pg.py appended RETURNING * to every insert). No raw SQL on these tables elsewhere (grep).

## Verified
- Parity (scratchpad/research_parity.py, old from git HEAD, writes alternated): research versions + JSON fields +
  review, news approvals insert/update, the three lookup caches (upsert), cross-source item merge (source_api
  accumulation, known access kept, other project separate), url list, date-window/topic filters, classifications,
  vectors incl. 3-chunk lookup, other model, replacement, empty save: 28 comparisons, 0 differences.
- pytest research, security, spec: 130 passed. ruff clean.

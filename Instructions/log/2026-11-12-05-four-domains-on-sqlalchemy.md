# 2026-11-12 #05 — guardrails, exclusions, assets, memory moved to SQLAlchemy

## Request
"carry on" / "ignore billing lets proceed with others": next domains off core/pg.py, smallest first.

## Changed
- New `models.py` (SQLAlchemy Core tables matching core/db.py) and rewritten `repository.py` in
  `domains/guardrails`, `domains/exclusions`, `domains/assets` (intel_assets only; `library.py` uses pgvector and
  stays on pg.py), `domains/memory`. Same function names, arguments and results.
- Removed dead `assets.repository.delete_asset` (no callers; audit finding 12).
- `exclusions` and `memory` repositories declare `__all__`: `core/store.py` star-imports them, and without it
  `select`/`update`/`delete`/`sa` would leak into `store` (providers/repository has functions named update/delete).
- `put_asset` upsert has no RETURNING (row holds file bytes).

## Verified
- Parity in a throwaway schema, old (git HEAD) vs new, writes mixed across both: guardrails (list/active-only/get/
  org_id_by_name incl. trim+case/delete), exclusions (single + bulk + empty, org/global scopes, get/delete),
  assets (2.5 KB bytes round-trip, upsert), memory (upsert, TTL expiry hidden, hit counting, stats, purge):
  0 differences; `store` exports all functions and none of the helper names. Schema dropped after.
- pytest memory/exclusions/guardrails/assets: 29 passed (after creating the schema in the fresh local DB with
  `store.init_intelligence_db()`, as a backend start does). Broader run (billing, auth, security, providers, usage,
  projects, dataset): only the pre-existing `tests/dataset/test_match_first.py` failure.
- The 3 tests/memory failures seen first were the empty local DB: the same 3 fail on the old code (stash check).

## Not verified
- No running backend / browser pass of Guardrails, Exclusions, deck assets or memory recall.

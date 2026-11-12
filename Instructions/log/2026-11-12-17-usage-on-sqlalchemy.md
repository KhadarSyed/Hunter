# 2026-11-12 #17 — usage moved to SQLAlchemy (repository + router scope)

## Request
"yes as you recommend please go head" — continue the SQLAlchemy move with usage, then auth.

## Changed
- `domains/usage/models.py` (new): llm_usage (all 22 columns), llm_prices, llm_settings, intel_projects and users
  column subsets.
- `domains/usage/repository.py`: SQLAlchemy Core; `summary(cond, grain)` and `calls(cond, limit, offset)` take a
  SQLAlchemy condition instead of a (where-string, params) pair. Every other function unchanged in name and result.
  The trend bucket format is a fixed literal (from `_BUCKET`, never user input) so GROUP BY matches SELECT.
- `domains/usage/router.py`: `_scope_where` / `_filters` build SQLAlchemy conditions. The scope subquery uses an
  alias of intel_projects (`scope_projects`): by_project/calls also join intel_projects, and SQLAlchemy would
  otherwise auto-correlate the subquery to the joined table and change the scope's meaning.

## Verified
- Parity in a throwaway schema (2 orgs, 5 users, 3 projects, 400 random usage rows incl. project-less rows,
  cache hits, 3 sub-stages, 400 days of timestamps): old (git HEAD router+repository) vs new for 7 role scopes
  (super admin all/one org, 2 org admins, 2 analysts, no org) x 5 filter sets x 4 grains, calls with 2 page
  windows, project_total, stage_cost_since, price_for (exact/prefix/deployment fallback/before any price),
  list_prices, has_price_row, earlier_price, settings, insert_usage defaults: 225 comparisons, 0 differences.
- pytest usage, guardrails, providers, billing, security, dataset: 217 passed; 1 failed = the pre-existing
  test_match_first (fails on the old code too).

## Not verified
- No browser pass of the Usage page.

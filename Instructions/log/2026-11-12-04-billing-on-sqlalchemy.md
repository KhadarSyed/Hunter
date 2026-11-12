# 2026-11-12 #04 — Billing moved to SQLAlchemy (first domain off core/pg.py) + missing packages

## Request
"ok continue" after the package map: start the agreed SQLAlchemy move with billing. Earlier in the same turn the
user asked where else standard packages should replace hand-written code (backend, API, DB, frontend); the answer
and agreed order are in the README backlog.

## Changed
- `backend/core/sa.py` (new): one SQLAlchemy engine per process on the psycopg 3 driver; `pool_size=5`,
  `max_overflow=10` (caps open connections: audit finding 6 for moved domains), `pool_pre_ping`, `pool_recycle`.
  `sa.begin()` commits/rolls back and always returns the connection. Honours the test schema.
- `backend/core/db.py`: `schema_for_tests()` extracted (shared by `_conn` and `sa.begin`); behaviour unchanged.
- `backend/domains/billing/models.py` (new): Core `Table`s for `subscription_plans`, `org_subscriptions`,
  `user_token_limits` (as migration 50), plus read-only column subsets of organizations, users,
  user_organizations, sessions, intel_projects, llm_usage (move to their owners when those domains migrate).
- `backend/domains/billing/repository.py`: rewritten with SQLAlchemy Core; same 24 functions, same dict results.
  Difference: `update_subscription` with an unknown column now raises `CompileError` before reaching the DB.
- `backend/requirements.txt`: `SQLAlchemy>=2.0,<3`.
- `CLAUDE.md` + `Instructions/README.md`: how moved domains access the DB; backlog updated.
- Not added: Alembic (an empty setup is config doing nothing; it lands with the first schema change in a moved domain).

## Verified
- Parity script in a throwaway schema (full schema via `init_intelligence_db`, seeded orgs/users/projects/usage/
  subscriptions/limits): 36 read calls old (git HEAD) vs new: 0 differences. Writes through the new code read back
  identically through the old code (plans, subscriptions incl. default `reminders`, token-limit upsert to NULL,
  notified period, org profile). Schema dropped afterwards.
- `pytest tests/billing tests/auth tests/security tests/providers tests/usage tests/projects`: 149 passed.

## Notes
- The local Docker Postgres volume `hunteragent_hunter-pgdata` was created fresh at 12:54 today by
  `docker compose up` (no earlier volume existed on this machine), so the local `hunter` database is empty; earlier
  local data (README "Current state") is not in Docker on this machine.
- Test-schema quirk: `CREATE EXTENSION vector` installs into the first test schema; if that schema is dropped while
  another still runs, the other fails with "type vector does not exist". Pre-existing, test-only.

## Not verified
- No running backend / browser pass of Settings → Subscription, Org and Platform dashboards on the new repository.

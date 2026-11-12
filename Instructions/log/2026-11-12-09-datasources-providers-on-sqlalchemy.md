# 2026-11-12 #09 — datasources and providers moved to SQLAlchemy

## Request
"ignore it now let proceed rest" (local Rancher setup set aside): continue the SQLAlchemy move.

## Changed
- `domains/datasources/models.py` (new, org_data_sources) + `repository.py` on SQLAlchemy Core. Keys still sealed
  with `core/secret_box` (Fernet); legacy plain rows still readable and converted by `encrypt_legacy_keys()`.
- `domains/providers/models.py` (new: org_llm_providers, org_llm_state, intel_projects id/org_id subset) +
  `repository.py`. The module's own `update`/`delete` keep their names; SQLAlchemy's are imported as
  `sql_update`/`sql_delete`. `create` writes the column defaults (is_default 0, status untested, last_error '')
  explicitly — same values as before.

## Verified
- Parity in a throwaway schema, old (git HEAD) vs new, writes alternated: upsert with/without settings, status
  flips, settings update, decrypt, legacy plain key + encrypt_legacy_keys (1 then 0, key unchanged), delete;
  providers create/get/list/default/newest/orgs_using_model, record_test (300-char cap), update with and without a
  new key, clear default, outage save/upsert/clear, delete, project_org: 0 differences. Schema dropped after.
- pytest providers, usage, research, security, billing, auth, memory, exclusions, guardrails, assets, projects:
  277 passed.

## Not verified
- No running backend / browser pass of Settings > LLM Providers and Data Sources.

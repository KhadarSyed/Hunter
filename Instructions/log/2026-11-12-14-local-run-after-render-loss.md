# 2026-11-12 #14 — Running locally only (Render database cannot be kept)

## Request
"I don't have budget to upgrade render and no plan too" / "check and fix on local only".

## Facts (checked)
- Render free Postgres: no backups on the free plan; expired DBs are inaccessible unless upgraded; deleted after a
  14-day grace (https://render.com/docs/postgresql-backups, https://render.com/docs/free). Ours expired
  2026-11-11 18:12 UTC → deletion ≈2026-11-25. Its IP allowlist is empty and it is suspended: no pg_dump possible.
- Local `.env` had no SEED_SUPER_ADMIN_EMAIL; with an empty local DB the new seed (log #03) would create no Super
  Admin, so nobody could sign in. Caused by today's seed change.

## Changed (local only, not in git)
- `.env`: appended `SEED_SUPER_ADMIN_EMAIL=khadar.syed@infovision.com` (backup copied to %TEMP% first).
- Backend started: `Python312\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8002`.
- `Instructions/README.md`: "Current state" note on production being down and local being the environment.

## Verified (HTTP against 127.0.0.1:8002)
- Startup: schema created, "Seeded Super Admin: khadar.syed@infovision.com", "Application startup complete", no
  warnings or errors afterwards.
- /api/health 200 {"ok":true}; / 200 (built SPA); /7/data-set deep link 200; /api/auth/me without session 401;
  login with the temporary password 200 with must_change_password=true; /api/intel/projects before changing it 403.
  The temporary password was read inside the script and never printed.

## Not verified
- No browser pass through the pipeline pages; no LLM call (Azure key present but not exercised).

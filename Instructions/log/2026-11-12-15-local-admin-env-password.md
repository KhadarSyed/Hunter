# 2026-11-12 #15 — Local Super Admin recreated with SEED_SUPER_ADMIN_PASSWORD

## Request
"SEED_SUPER_ADMIN_PASSWORD= configured in env".

## Why something had to change
The seed runs only while no Super Admin exists; the local account had already been created at first start with a
random temporary password, so the new env value alone had no effect.

## Changed (local DB only)
- Local DB held 1 user, 0 projects, 0 running jobs. Deleted that user's sessions, memberships and row, then ran
  the real `core.auth.seed_super_admin_if_missing()` with `.env` loaded: account recreated as super_admin with the
  env password, must_change_password = true (the seed always sets it).

## Verified
- POST /api/auth/login with the .env password → 200, must_change_password true. Password never printed.

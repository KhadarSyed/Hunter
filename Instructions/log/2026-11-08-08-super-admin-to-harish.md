# 2026-11-08 #08 — Super Admin moved to Harish; Khadar becomes InfoVision Admin

**Request:** Let Khadar manually check the org-admin settings: make khadar.syed an Admin of one org, and map
Harish.Thulasiram@infovision.com as the Super/Global admin.

**Done:**
- `core/auth.py`: `SEED_SUPER_ADMIN_EMAIL = "harish.thulasiram@infovision.com"` (name "Harish Thulasiram"). The
  startup seed re-promoted Khadar on every restart/deploy; now it keeps Harish as Super Admin.
- Local DB (127.0.0.1/hunter): Harish (user 16) → super_admin, org_id NULL, still a member of InfoVision;
  must_change_password stays on (he signs in with his emailed temp password or "Forgot password").
  Khadar (user 1) → admin of InfoVision (org 5); InfoVision admins: Khadar, Sweta Shah.
- Verified after a restart: roles unchanged by the seed.

**Production:** the next deploy makes Harish a Super Admin there too (created if missing; temp password comes from
`SEED_SUPER_ADMIN_PASSWORD` or is logged). Khadar's prod account is NOT demoted automatically.

**Note:** Khadar as InfoVision Admin can open project 1 "Casino Gaming" again and sees `/org-dashboard`,
Settings → Subscription / Guardrails / LLM Providers / Users.

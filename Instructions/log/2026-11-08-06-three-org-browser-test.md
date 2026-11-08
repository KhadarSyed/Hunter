# 2026-11-08 #06 — Vendor + 3 client orgs, simultaneous browser test

**Request:** Act as vendor (Super Admin) and clients: create test orgs with subscriptions (user/project limits), org
admin user management, data sources, LLMs, subscription purchase/renewal, every email (welcome, subscription, LLM
outage/expiry, project). Browser, simultaneous logins. Mock projects only (no full pipeline). Test emails to
`khadar.syed+<tag>@infovision.com`. Models: user-supplied keys (never written to files; entered in the UI only).

**Harness:** `tests/e2e_3org/run.py` (local, gitignored) — Python Playwright, one browser context per actor
(vendor, 3 admins, 3 analysts = 7 live sessions). Env: SA_EMAIL, SA_PW, ORG_PW, KEY_BAZAAR, KEY_FREEMODEL,
KEY_CODECRAFT, KEY_RADOX, BACKEND_LOG. Screens in `shots/e2e-3org/` (local). Mail checked via backend log
`Mail sent: '<subject>'` ($TEMP\hunter-backend.log).

**Model probe (2026-11-08):** FreeModel → 503 peak capacity; CodeCraft + RadoxAI → 402 billing failed; Puter →
403 (browser-session token only); BazaarLink `https://bazaarlink.ai/api/v1` → only `qwen3.7-flash` answers
(other models 402: not enough credits).

**Test orgs created (left in place):** 9 Acme Retail (Test 11081934) Starter, 5/5 users, BazaarLink default +
FreeModel; renewals queued Starter 2027-28, Growth 2028-29. 10 Globex Media Growth, FreeModel default (down) →
BazaarLink acting, guardrail "House style". 11 Initech Finance Starter, CodeCraft + RadoxAI (both 402 → paused);
reminder → expired → renewed (fresh 12 months). Mock projects 2, 3, 4 (one per org, owner = analyst 1). All test
accounts' password = the ORG_PW used in the run.

**Results:** all scenarios behave as designed. Emails sent: 11 welcome, outage "switched" (Globex), "paused"
(Initech), token allowance (user + admin), Starter renewed (Acme), Growth renewed (Acme), subscription active
(Initech), "ends in N days" reminder, "subscription expired", Matching label + Data set tagged samples. Seat limit
("Your Starter plan allows 5 users."), expired org blocks new users, cancelled checkout leaves plan + sends nothing,
vendor 403 on client project, admin isolation (other org id → own org, overview/create-org 403), 7 sessions live.
Stage email after a *successful* Brief & Scope: none — by design (`notify._stage_key`: only failed jobs email).

**Bugs found and fixed (commit 413605b):**
- HTTP 402 (no credits / billing) was not a failover/config error → never failed over or alerted. Now `config`
  (`providers/service.classify`), test added in `tests/providers/test_failover.py`.
- LLM Providers page hid a live outage (still said "uses <down model>", all "Not tested"). Now `GET /llm-providers`
  returns `outage` (`outage.snapshot`) and `ProvidersTab` shows an amber/red banner: failing since, acting model,
  last error, failed calls.
- Reminder said "ends in 5 days" with 6 days left (floor) → `math.ceil`.
- Harness-only issues (not app): mail-log regex, Windows console encoding, plan-card selector.

**Not covered:** "recovered" email (FreeModel never came back during the run); real payment gateway; full pipeline.

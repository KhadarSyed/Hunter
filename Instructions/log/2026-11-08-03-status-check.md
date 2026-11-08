# 2026-11-08 · 03 · Status check: anything pending?

- Git: nothing uncommitted or unpushed in tracked files; latest `717909c`.
- Done and tested (tsc clean; local pytest: 217 across providers/auth/emails/agent/projects/dataset/usage, 94 dataset):
  failover + outage emails, one email design, email link fix, Matching label / Data set / Brief & Scope bars,
  tag schema pop-up, Instructions folder.
- Open items (need the user, or outside the code):
  1. Signed-in pages not viewed in a browser (test browser has no session): Matching label, Data set, Brief & Scope
     bars, tag schema pop-up, Settings `?tab=providers`.
  2. Production links rely on Render's `RENDER_EXTERNAL_URL`; confirm with the first real email after the deploy
     (or set `APP_URL` on Render yourself if a custom domain is used — not changed by us per the rules).
  3. `PROVIDER_SECRET_KEY` is not set on Render: org provider keys cannot be saved/decrypted there until it is.
  4. Testing Org is on NVIDIA while VyceAI is in maintenance; the real "recovered" email arrives when VyceAI answers.
  5. Known limits unchanged: slow first failover (~3 min); research/strategy may finish rule-based in a long outage.
  6. Pre-existing failing tests: `tests/deliverable/test_latest24h.py`, `test_time_grain.py`.

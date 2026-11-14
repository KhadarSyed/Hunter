# 2026-11-14-14 Sign-in photo copies stored in S3

## Request
- "Sign in photo copy copy it in to S3 bucke naming login page background; rest no need push in git hub".

## What changed
- No code change. Two uploads to the S3 bucket (prefix `HunterAgent/`), via `core/object_store.put_file`:
  - `branding/login-page-background-power-bi-ai.avif` (35,048 bytes, image/avif), from `power-bi-ai.avif`;
  - `branding/login-page-background-consumer-intelligence.jpg` (138,404 bytes, image/jpeg), from
    `Consumer-Intelligence-Platforms-1536x868.jpg`.
- The live sign-in photo `branding/login-background.avif` (`auth/router.LOGIN_BACKGROUND_KEY`) is unchanged; it is
  byte-identical to `power-bi-ai.avif`.
- The other untracked files (the test data zip, `shots/`, `data/Alphametricx.png`, the two old `docs/plans` files) stay
  local and are not pushed, as asked.

## Verified
- Each upload read back from S3 is byte-identical to its source (sha256).
- `branding/` now lists `login-background.avif` plus the two new keys.

## Not verified / open
- The local photo files are still in the repo root (untracked); they were not deleted.

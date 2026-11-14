# 2026-11-14-06 Split-screen login (logo, feature slider, keep me signed in), new login image, questions in one row; deck logo sample

## Request
- "http://127.0.0.1:8002/39/matching-label better to display all RQ in one row".
- A mockup of the sign-in page: "top left corner Alphametricx logo, bottom slider with Intell architecture".
- Mid-turn: "login image quality compromissed replace it with D:\HunterAgent\power-bi-ai.avif".
- Mid-turn: "Alphametricx logo in presentation also should be dispaled with drop down shaddow diplay 3D effect instead
  of card - for review give me sample once approve implement it".

## What changed
- `LoginPage.tsx`, rewritten as a split screen:
  - Left (from `lg` up): the S3 photo, the AlphaMetricx mark on a white tile with "AlphaMetricx / ENTERPRISE
    PLATFORM" top left, and a feature slider at the bottom. It has 7 slides about what the product really does; the
    first tag is "Intelligent architecture".
  - Slider behavior: auto-advances every 6 s, pauses on hover, never moves under prefers-reduced-motion, and its dots
    are buttons with labels.
  - Right: "Sign in to your account", Work Email Address, Password with a show/hide eye button, "Forgot password?",
    "Keep me signed in for 30 days" (checked by default, as in the mockup), Sign In. The forgot-password steps keep the
    same look.
  - On a phone only the form shows, with the mark above it.
  - Not copied from the mockup:
    - The Google/Microsoft SSO buttons: there is no SSO backend, and buttons that do nothing would mislead.
    - The blue color: the brand violet `#5B2C9D` is kept.
- "Keep me signed in": `LoginRequest.remember` (default false); `auth/service.REMEMBER_TTL_SECONDS` = 30 days;
  `repository.create_session(user_id, ttl_seconds=SESSION_TTL_SECONDS)`. The login route uses 30 days when remember
  is set, else the usual 7. `intelApi.login(email, password, remember)` and `auth-context.login` pass it on.
- Login image:
  - `power-bi-ai.avif` (1920x1080, 35 KB) uploaded to `HunterAgent/branding/login-background.avif`, read back
    identical. The old `login-background.jpg` was deleted from S3.
  - `auth/router.LOGIN_BACKGROUND_KEY` now names the AVIF.
- `MatchingLabel.tsx`: the cards sit in one row (`grid-flow-col auto-cols-[minmax(20rem,1fr)]`). They share the width,
  each at least 20rem, and the row scrolls sideways when they do not fit.
- Deck logo (sample only, nothing implemented):
  - `logo_3d_sample.png` (scratchpad) compares today's white card with the proposal. The proposal has no card and a
    layered drop shadow: a 1 px light edge, a 2 px contact shadow and a 10-16 px soft shadow. The wordmark turns white
    on dark (cover, divider) slides.
  - Made by injecting CSS into run 5's deck in the browser; no file changed. Waiting for the user's approval.

## Verified
- Test `tests/auth/test_recovery.py::test_keep_me_signed_in_asks_for_a_30_day_session[True/False]`: 30 vs 7 days,
  and the cookie Max-Age matches.
- Full `pytest -q tests` (minus e2e_3org): 740 passed. ruff clean.
- Frontend: tsc clean, lint 0 errors (32 warnings as before), `npm test` 15 passed, build done.
- Playwright, login page:
  - At 1600 px it is split screen: the logo top left, the slider at the bottom. Dot 4 shows "Every article read
    against your questions", and the eye button toggles the password field to text.
  - At 390 px the photo panel is hidden.
  - The new image loads at 1920x1080 through the route.
- Playwright, `/39/matching-label`: RQ1-RQ4 share one top (one row), 320 px each.

## Not verified / open
- Signing in with "Keep me signed in" was not done in a browser; a real password is needed. The route is covered by
  the test.
- The deck logo change waits for approval. On dark slides the white wordmark also turns the purple swoosh white.
- `power-bi-ai.avif` and the old JPEG stay untracked in the repo root.

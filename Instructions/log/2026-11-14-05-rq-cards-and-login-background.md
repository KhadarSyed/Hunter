# 2026-11-14-05 Matching label cards (15-line query, 3-line question, edit pop-up); login page background photo

## Request
"RQ card or panel display 15 lines remaining scrollable and label of each should be truncated display only 3 lines up
on hover display complete RQ text ... Up on clicking edit the entire RQ should open in pop up window and go back to
normal once user update it. D:\HunterAgent\Consumer-Intelligence-Platforms-1536x868.jpg upload on S3 in Project level
folder - make this as Login page background image, Move login card to right side"

## What changed
- `frontend/src/pages/SearchStrategy.tsx` `BooleanDisplay`: an optional `maxLines`. The query body shows that many
  lines, and the rest scrolls inside the panel (focusable, labelled "<RQ> Query, scrollable"). Search Strategy's own
  callers do not pass it, so they are unchanged.
- `frontend/src/pages/MatchingLabel.tsx`:
  - `ClampedQuestion`: the question shows at most 3 lines. A longer one shows its full text on hover or keyboard focus
    (a tooltip under it), measured with a ResizeObserver.
  - The card's query uses `maxLines={15}`.
  - `EditModal`: "Edit RQn" opens the whole question and query in a pop-up (the shared `components/admin/adminUi`
    Modal).
    - Save closes it once the change is saved; a failed save keeps it open with the error.
    - Cancel, ×, or Escape closes it unless a save is running.
  - The inline edit textareas were removed. Cards are keyed by `question_id`.
- Login background:
  - The photo is uploaded to S3 at `HunterAgent/branding/login-background.jpg`, the project's folder in the bucket
    (138,404 bytes, read back identical). It is not committed to git.
  - `backend/domains/auth/router.py` `GET /api/auth/login-background` (public, like the sign-in itself) answers 307 to
    a 1-hour signed S3 link. Without S3 it answers 404, and the page keeps a plain background.
  - `LoginPage.tsx`: the photo is the full-page background, with a soft shade on the right. The card is on the right
    from the `md` width up, centered on a phone, and slightly translucent with a blur.

## Verified
- The route answered 307 to the signed S3 link; following it gave 200, image/jpeg, 138,404 bytes.
- Playwright, login page:
  - At 1600 px the card sits on the right over the photo.
  - At 390 px it is centered.
- Playwright, `/39/matching-label` (signed in with the test session; the browser read the token from a local file, so
  it never appeared in a tool call):
  - Long questions clamp to 3 lines, and hovering RQ1 shows its full 184 characters.
  - RQ3 and RQ4's long queries show 15 lines and scroll; RQ1 and RQ2's one-line queries stay short.
  - Edit RQ1 opened the pop-up with the full question and query. Save closed it after saving; Escape closed it.
  - After shortening the query box to 12 rows (at most 45% of the screen height), Save sits inside the window.
- Frontend: tsc clean, lint 0 errors (32 warnings as before), `npm test` 15 passed, build done. ruff clean.

- Follow-up ("continue"), checked in the same browser on Settings → LLM Providers as the Test Org admin:
  - The Nemotron 3 Ultra card shows the "No images" badge it learned on its first image refusal (log 2026-11-14-01),
    and the prices $2.00 / $0.50 / $8.00 since 2026-11-12.
  - Its edit form's "Reads images" choice reads "No" (options: Not known / Yes / No). It was canceled; nothing was
    saved.

## Not verified / open
- Clicked through Playwright's Chromium only.
- The original JPEG stays in the repo root, untracked; delete it if it is no longer needed.

# 2026-11-14-07 Full-screen login photo with a glass card; the deck's AlphaMetricx logo in 3D (approved); the Pinterest pin left open

## Request
- "image in the login page make it full screen background for login have transparant card".
- "use this <iframe src="https://assets.pinterest.com/ext/embed.html?id=978477456577495582" ...> in the login card
  background".
- Mid-turn: "Alphametricx logo looks good approve" (the sample from log 2026-11-14-06).

## What changed
- `frontend/src/pages/LoginPage.tsx`:
  - The S3 photo now covers the whole page, under a left-to-right dark shade.
  - The logo and slider sit on it with no panel of their own.
  - The sign-in card is frosted glass (`bg-white/10`, `backdrop-blur-xl`, a white/25 border) with white text and
    violet-200 links. The input boxes stay near-solid white so typing is easy to read.
  - On a phone, the card and the white-tiled mark show over the photo.
- `backend/domains/deckstudio/templates/deck.html.j2` `.house`:
  - The white card behind the AlphaMetricx wordmark is gone. The wordmark (28 px) floats with layered drop shadows: a
    1 px light edge, a 2 px contact shadow and a 10-16 px soft shadow.
  - On full-bleed photo slides (`data-treatment` "full" or "A": cover, dividers, closing, executive summary and photo
    slides) it turns white with a stronger shadow. Pure CSS: no renderer change.
- Runs 5 (project 38) and 7 (project 39) re-rendered (`deck_store._render_html`), so both test decks show it.
- The Pinterest embed was not used.
  - The embed is Pinterest's pin widget: a red "Save" button, a "facebook Marketing / Published by Digital Marketing"
    footer and scrollbars. The image belongs to the pin's publisher and shows Facebook, Instagram, Pinterest and
    YouTube logos.
  - As an iframe on the sign-in page it would load Pinterest for every visitor before they sign in.
  - Asked the user how to proceed.

## Verified
- Playwright, login at 1600 px: the photo is full screen, with the logo and slider on the left and the glass card on
  the right.
- Playwright, run 5's re-rendered deck:
  - The badge has no background (rgba 0) on every slide, and the wordmark is 28 px.
  - It is white on "cover" (full) and "executive-summary" (A), and dark on the light "rq1-sentiment_split-3" (S).
- `pytest -q tests` (minus e2e_3org): 740 passed. Frontend tsc clean, lint 0 errors, build done.
- Backend restarted, so new decks get the template.

## Follow-up: "AlphaMetricx logo in decks increase the size matched 1st brand logo"
- `deck.html.j2`: a small script on the cover sets the AlphaMetricx wordmark to the client logo's drawn height (the
  `.brand-logo` image's object-fit size, measured in the page, so any logo shape works). It places the wordmark top
  right (110 px from the edge) and centers it on the brand chip's line.
- A cover with a product photo in that corner keeps the small corner mark. Other slides keep 28 px.
- Runs 5 and 7 re-rendered. Browser check on run 5's cover (screen px at the deck's scale): Foxwoods drawn 47 px tall,
  and the wordmark 47 px. Both are centered at y≈92; other slides are still 28 px.
- Deck, amcharts and deliverable tests: 219 passed. Backend restarted.

## Not verified / open
- The exported PDF/PPTX of a new deck with the larger cover wordmark was not opened. The export takes its screenshots
  after this script runs.
- Decks restyled by the creative pass keep `.house` from this template; a restyled slide's own background was not
  checked.
- The Pinterest pin waits on the user's answer.

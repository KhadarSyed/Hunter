# 2026-11-14-20 Recreate Foxwoods (project 42); glass look for every signed-in page

## Request
- "restart creating the project, I want to see the latest changes reflecting or not" (project 41 was deleted from the UI
  at 20:33:44).
- Mid-run: "update FE let it be glassy look and all pages background place it with same background image of the login
  slightly masked with white color layer transparant, should match with login styling".

## Done
- Chrome (Khadar): New Project "Foxwoods Resort Casino", United States, Social Listening, Past 7 days, brief text from
  `Dataset/Casino Gaming/Casino Gaming.docx` (2,341 chars incl. tables). Project 42. Brief & Scope completed (20/20),
  clarifying questions skipped, approved; Background Research started (NVIDIA org models, GPT keys blank).
- Frontend glass shell:
  - `App.tsx`: the shell div gets `app-glass` (was `bg-white`); `<main>` drops `bg-slate-50/50`.
  - `index.css`: `.app-glass` = the login photo (`/api/auth/login-background`, fixed, cover) under a white gradient
    veil (84%→74%); inside it `bg-white` surfaces become rgba(255,255,255,.62) + blur(16px); table rows tint only (no
    per-row blur); fixed/absolute/sticky/dialog surfaces stay 90% white; `bg-slate-50` 55%; sidebars 55%.
  - Blur is skipped on any surface that contains a `.fixed` element (`:not(:has(.fixed))`), because a backdrop-filter
    makes a fixed modal position against that card instead of the viewport.
  - Login page untouched (it renders outside the shell).

## Verified
- `npm run build` ok; `npm run lint` 0 errors (32 warnings, unchanged).
- Screenshot of /42/background-research in Chrome: photo visible through the veil, frosted card, translucent sidebar.

## Not verified
- Every page visually (Data set table, drawers, modals); contrast of light-grey text on the glass in all places.
- Firefox (`:has()` is supported in current Firefox; older browsers just lose the blur).

## Follow-ups
- Finish project 42: Search Strategy, keep RQ1/RQ3/RQ8 approved on Matching label, then Map the Excel files
  (Khadar attaches them; the extension cannot pick local files).

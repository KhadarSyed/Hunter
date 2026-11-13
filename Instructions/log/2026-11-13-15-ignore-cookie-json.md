# 2026-11-13-15 cookie.json ignored by git

## Request
"coontinue" (after log 14 flagged the untracked `cookie.json` at the repo root).

## What changed
- `.gitignore`: added `cookie.json` (local browser session cookies, may hold a session token). The file itself was not
  opened, moved or deleted.

## Verified
- `git check-ignore -v cookie.json` -> `.gitignore:92:cookie.json`; it no longer shows in `git status`.

## Not verified / still open (all need approval)
- A/B batching comparison and a full NVIDIA brief/deck run (no GPT spend, no new projects).
- `tests/e2e_3org/run.py` (creates three orgs, sends emails).
- Other untracked files left as they are (user's own): `data/Alphametricx.png`, `data/Foxwoods_Project_Datasets.zip`,
  two `docs/plans/*.md` design notes, `shots/`.

# 2026-11-13-20 Deck run 3 with the fixes: before/after on the synthetic project

## Request
Same as log 19 ("recreate the synthetic 10 articles project until deck creation ... test and fix"): rebuild the deck
on the synthetic project 38 (Test Organization, NVIDIA models) after the two fixes of commit b60828f went live.

## Result (same data, same models; run 2 = before, run 3 = after)
| | Run 2 | Run 3 |
|---|---|---|
| Status / checks | completed, 17/17 after repair | completed, 17/17 after repair |
| Slides | 33 | 33 |
| Rule-based fallback insight cards | 4 (2 before repair, 2 in repair) | 0 |
| Reply cut off at the output cap | 1 | 0 |
| Text-only model marked "outage" in photo checks | 7, with "switched"/"recovered" emails | 0 (skipped 12 times, no email) |
| Chart categories without an insight before repair | 3 charts | 1 chart (1 of 2) |
| Run time | 121 min | 96 min |
- Run 3 had 1 genuine outage mark: MiniMax M3.1 Flash returned HTTP 503 "content safety screening is temporarily
  unavailable" (a provider fault), with one "switched" email to the Test Organization admin.
- Deck scan (python-pptx, all slide text, tables, links): blocked domain, blocked keyword, both Irrelevant articles and
  the analyst-rejected solar article are on no slide of either deck.

## Not verified
- Insight quality judged by a person (both decks are at /38/deliverables for the user to compare).
- Whether the low-reasoning retry fired in run 3 (no cut-off happened, so it was not needed).

## Open
- Synthetic project 38 is kept for the user's review; afterwards run `cleanup.py` (project, vectors, analyst
  corrections, exclusion rules 2, session, S3 copy, test cache rows).

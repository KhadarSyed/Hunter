# 2026-11-14-04 Deck resume after the render checkpoint, verified live (project 39, run 7)

## Request
"continue", with a screenshot of project 39's Matching label: RQ1 and RQ2 read "Foxwoods", and RQ3 keeps its long
AI-written query.

## Notes on the screenshot
- RQ1 and RQ2 read "Foxwoods" because of my test edit (log 2026-11-14-02). The AI-written queries matched none of the
  10 synthetic articles, so I widened them through the Data set query panel. It is not a product bug.
- RQ3 and RQ4 match no synthetic article. For this run they were set back to draft through the API
  (`POST /strategy/38/research-question/{RQ3,RQ4}/status {"status":"draft"}`), which keeps the deck to two questions.

## What was done
- Deck run 7 on project 39 (2 questions, NVIDIA, Azure blanked).
- The photo stage took under 5 minutes: the photos came from run 6 through the asset cache. So I killed the server in
  the repair stage, which is still after the render checkpoint, and restarted.
- After the restart, the run log reads:
  - "Resumed after a server restart; already finished: insights:RQ1, insights:RQ2, insights:_brand, render, template".
  - "insights kept from before the restart" for both questions.
  - "Classic deck, Word brief and fact check kept from before the restart".
- Gate to qc took 10 s, and all 12 photos were reused in 6 s. Compose, export and repair then ran.
- Completed with 36 slides, 25 of 27 checks. The 2 open checks come from the synthetic data: cited articles that never
  name a brand, and a brief ask for spokesperson tracking.
- Checkpoints were cleared after the deck saved to S3 (60 files).

## Verified
- Every deck checkpoint has now been resumed live:
  - insights per question (runs 5, 6);
  - brand summaries (run 6);
  - template and render (run 7).
- No code changed in this step.

## Not verified / open
- The "Reads images" control in LLM Providers was not clicked in a browser. Doing it through Playwright would mean
  writing the session token into the tool call.
- Projects 38 and 39 are still kept for review. On project 39, RQ3 and RQ4 are now draft and run 7 is its latest deck.

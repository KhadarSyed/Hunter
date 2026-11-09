# 2026-11-09 #19 — InfoVision before/after comparison projects

**Goal:** two real InfoVision projects on full datasets (Casino Gaming, Planet Fitness) to compare deck quality,
tokens and cost with the LLM tuning on ("after", `LLM_LIGHT_TASKS` unset) vs off ("before", `LLM_LIGHT_TASKS=0`).

**Driver (local only, never pushed):** `tests/e2e_3org/infovision_compare.py [casino|fitness]`, env `KPW`.
- Project creation is done **in the browser** (Playwright, as the user asked): login as khadar.syed@infovision.com →
  /new-project → name, client, "Competitor Analysis", brief .docx upload → "Analyze Brief". Screenshots
  `shots/compare/<key>-new-project.png`, `<key>-after-analyze.png`.
- Then via API: wait for the Brief & Scope job the browser started (else start one) → approve spec → agent autorun
  (research, strategy, matching label) → upload all dataset files → match → tag (≤6h) → approve all matched →
  approve data set (starts the deck) → wait for the deck.
- Resumable: re-run finds the project by name and skips finished stages. Logs `shots/compare/<key>.log`, `run.out`.

**Next:** when both decks finish, restart the server with `LLM_LIGHT_TASKS=0` (check no running deck first),
Regenerate each deck, compare insights + `llm_usage` per run; replace the DevOps cost estimate with measured figures.

## Article cap: 1000 per project (user: "tag only 1000 not more than that" / "no each project 1000 i mean")
- Full Casino upload: 10,046 articles, 7,743 matched (5,294 originals, 8 RQs). Tagging was stopped at the content
  phase (287/7240, almost no GPT spend) by restarting the server (no cancel route; the job is marked cancelled on start).
- Driver now has `MAX_ARTICLES = 1000` + `cap()`: after the free match, if more than 1000 originals match, it keeps the
  top 1000 by reach, rewrites the source rows (unchanged) into `shots/compare/<key>-sample/`, deletes the uploaded
  files through the app, uploads the samples and matches again. It refuses to tag if more than 1000 still match.

## Results — "after" (LLM_LIGHT_TASKS on), measured from llm_usage, platform Azure GPT-5
| | Casino (project 8, deck run 1) | Planet Fitness (project 9, deck run 2) |
|---|---|---|
| Articles tagged | 996 (8 RQs) | 1000 (9 RQs) |
| Brief & Scope | $6.49 (144 calls) | $2.06 (49 calls) |
| Research + strategy | $0.27 | $0.28 |
| Tagging | $9.40 (133 calls) | $17.94 (241 calls) |
| Deck engine (insights, classify, compute) | $16.59 — insights alone $12.92 | $17.30 — insights $14.58 |
| Deck studio (repair, assets, render) | $3.97 — repair $3.24 | $5.11 — repair $4.39 |
| **Total** | **$36.72** | **$42.69** |
| Deck checks | 36/39 pass, 129 slides | 34/36 pass, 7 rule-based fallback lines |

- Planet Fitness tagging costs double: every article matched all 9 RQs (RQ keywords too broad).
- Repair step is slow (~75-95 min, 150-170 sequential calls).
- Not yet run: the "before" side (server with LLM_LIGHT_TASKS=0, Regenerate both decks, ~$20-25 each).

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

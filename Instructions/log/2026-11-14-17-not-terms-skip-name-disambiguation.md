# 2026-11-14-17 Data set match: NOT blocks no longer exclude the brand (project 41, 5 RQs matched 0)

## Request
"uploaded data set" (project 41, Foxwoods Resort Casino, Testing Org): Khadar uploaded
`IV_Frenold_CEO_Brand_Competitors_Editorial.xlsx` and `IV_SU_Campaign_Data_"This Is How We Resort".xlsx`.

## What was wrong
- After the upload: 614 articles. 452 matched and 162 Irrelevant, but RQ1 (share of voice), RQ6, RQ7 and RQ8 matched
  0 and RQ2 matched 4.
- The strategy's NOT blocks hold name-disambiguation groups, e.g. `("Foxwoods" NOT (casino OR resort OR CT ...))`.
  `dataset/service.not_terms` read every term in a NOT clause as an exclusion term, so "Foxwoods", "Mohegan" and
  "Resorts World" excluded every brand article. Exactly the RQs whose NOT block had those groups were starved.

## What changed
- `dataset/service.py`:
  - New `_own_level(text)` and `_without_disambiguations(text)`: inside a NOT block, a bracketed group with its own
    NOT at its own level is dropped. A keyword matcher cannot express "this name only in that sense".
  - `not_terms` uses it. Plain NOT clauses are unchanged (`"Tesla" NOT ("Nikola Tesla" OR museum)` still gives both).
- Data: `service.match_rqs(41)` was re-run (free, no model calls) from a script with the new code. Result: 593 of 614
  matched, 21 Irrelevant, 325 syndicated copies. Per RQ: RQ1 588, RQ2 270, RQ3 258, RQ4 455, RQ5 237, RQ6 256,
  RQ7 588, RQ8 589, RQ9 328.
  - The keyword pass is a loose OR of every group by design: the per-RQ tagging model decides "matched". So RQ8's
    589 are candidates, not answers.

## Verified
- New test `tests/dataset/test_query_panel.py::test_not_terms_skip_nested_name_disambiguation`.
  `pytest -q tests/dataset`: 112 passed; ruff clean.
- Dry run before writing: 585 of 614 matched (the saved run adds syndicated copies: 593).
- Tagging (started by Khadar at 11:56 UTC) works on the 593 matched articles.

## Not verified / open
- The backend still runs the OLD process: a restart was skipped because tagging for project 41 is running (rule:
  check runs before a restart). Until the restart, an action that re-matches in that process (a new upload, an
  undone "mark relevant") would use the old NOT terms again. The tagging job re-matches only when articles are
  unmatched (0 now). Restart once tagging is done.

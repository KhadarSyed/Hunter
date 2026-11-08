# 2026-11-08 #15 — Production-style tests: two users across projects + research compliance (part D)

**Request:** test as production: review/tag comment and block status apply to other projects; log in as two users
one after the other; check research follows the guardrails and the block list.

**Two-user browser test** — `tests/e2e_3org/two_users_blocklist.py` (local; env ORG_PW; cleans up everything):
fixture on test org Acme only — analyst 1's mock project and a new mock project created in analyst 2's own session get
earlier stages marked approved (spec, research, brief, strategy with RQ1 `match_query: Acme`) and 6 sample articles
(channel `traditional`; 2 from blockeddeals.test). Browser, separate sessions, sequential:
admin pastes "blockeddeals.test, https://www.blockeddeals.test/x" → "1 added, 1 already in the list" ·
analyst 1 Match → 4 matched / 2 irrelevant, 2 "Blocked" pills · Mark relevant with comment → stored, unblocked ·
analyst 2: 403 on analyst 1's project · own project Match → same 2 Blocked (rule in force) · Settings > Exclusions shows
"kept 1×" with the comment · org AI context carries it. **7/7 passed.** Screens `shots/e2e-blocklist/` (local).
Note: acme-analyst2's password set to the test password (it had never signed in).

**Research compliance (in-process, real code, InfoVision guardrail):** guarded research calls start with the
guardrail; QC untouched; another org never gets InfoVision's text; `scrub_research` and `multi_source.keep` drop a
blocked site and its subdomains. **5/5 passed.**

**Test totals today:** research 99, deckstudio 57 (+1 pre-existing failure `test_live_slides`), image licensing 11,
guardrails check 5, exclusions 9, billing 8, providers 25 — all passing except the pre-existing one.

**Config notes:** `.env` has `FIRECRWAL_API_KEY` (spelling) — research uses the org key saved in Settings > Data Sources,
not .env (no org has one saved now). `PIXABAY_API_KEY` missing → Pixabay skipped. Openverse needs no key.

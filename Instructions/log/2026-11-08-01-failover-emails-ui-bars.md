# 2026-11-08 · 01 · Model failover, one email design, email links, stage action bars

Commits on `main`: `bb72590` (failover + emails + link fix), `cda1219` (Matching label / Data set UI), and `325a452`
(Brief & Scope sticky bar).

## 1. Model failover and outage emails (`bb72590`)

- What: an org's models fail over in order; when all are down the call waits and resumes; admins are emailed.
- Files: `backend/domains/providers/service.py` (`route`, `classify`, `call`, `_down` marks, `AllModelsDown`),
  `backend/domains/providers/outage.py` (state + emails), `backend/domains/providers/repository.py`
  (`get_outage`, `save_outage`, `clear_outage`), `backend/core/db.py` (migration 49 `org_llm_state`),
  `backend/core/llm_provider.py` (`_route`, `_invoke`), `backend/domains/projects/gates.py`
  ("Paused · waiting for a model").
- Tests (local): `tests/providers/test_failover.py`.

## 2. One email design (`bb72590`)

- Layout: `backend/core/email_layout.py`, template `backend/core/templates/email.html.j2`; old
  `deliverable_ready.html.j2` deleted.
- Footer: "Questions? support@alphametricx.com / AlphaMetricx © {current year} · Never share your password or codes."
- Org panel lists admin names and emails (no AI model row).
- New emails: Matching label ready (`notify.notify_matching_label`, sent by `agent/autorun.py`), Data set tagged
  (`notify.notify_dataset_tagged`, sent by `dataset/tagging_job.py`).
- Wordmark in S3: `HunterAgent/assets/house/alphametricx-logo.png`.

## 3. Email buttons did not open the right page (`bb72590`)

- Cause 1: `APP_URL` unset locally and on Render → every link was `http://localhost:5173`.
  Fix: `backend/core/config.py` `app_url` defaults to `RENDER_EXTERNAL_URL` (set by Render) before localhost.
- Cause 2: Settings always opened on My Profile. Fix: `frontend/src/pages/SettingsPage.tsx` reads `?tab=`; outage
  emails link to `settings?tab=providers`.
- Not a bug: "Deliverable ready" for project 1 lands on Data set because Deliverables is locked (stage gate).
- Resent 3 outage review emails ("[Review n/3 · fixed links]") to khadar.syed@infovision.com; script kept in the
  session scratchpad, not the repo.

## 4. Matching label and Data set UI (`cda1219`)

- `frontend/src/pages/MatchingLabel.tsx`: sticky top bar (title + "+ Add research question", form opens at top),
  cards scroll, sticky bottom bar ("← Back to Search Strategy", "N of M approved", "Go to Data set →").
- Tag schema: `frontend/src/components/dataset/TagSchemaView.tsx` — `TagSchemaView` shows readable names
  (`readable()`), kind ("Pick one" / "Pick any that apply" / "Names found in the article"), definition, value
  chips; `TagSchemaModal` is the pop-up (Escape / backdrop / Close). Also used by `components/dataset/RqPanel.tsx`.
- API: `backend/domains/dataset/router.py` `_schema_view` now returns `definition`; type
  `TagSchemaField.definition?` in `frontend/src/types/dataset.ts`.
- `frontend/src/pages/DataSet.tsx`: "← Back to Matching label" at the top.

## 5. Brief & Scope review action bar (this response)

- `frontend/src/pages/BriefScopeReview.tsx`: both action rows (before approval: Back / Save / Approve; after:
  Back / "Proceed to Background Research →") are now a sticky bottom bar (`sticky bottom-0 -mx-8 -mb-8 px-8`,
  matching the page's `p-8` wrapper). "← Back to Projects" is a bordered button.

## 6. Instructions folder (this response)

- Created `Instructions/README.md` (map, rules, current state) and this `log/` note. Every later response adds a
  note here; read the README first instead of scanning the codebase.

## Not verified

- The signed-in pages were not viewed in a browser (no session in the test browser); checked with `tsc` and tests.

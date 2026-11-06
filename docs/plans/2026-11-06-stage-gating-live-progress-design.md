# Stage gating, live progress, live usage, Data set upload card, Alphametricx branding — design

Date: 2026-11-06. Approved in brainstorming the same day.

## 1. Stage flow and gating

- **One gate, two places.** A backend `stage_gate(project_id)` reports, per stage, `done`, `running` or `locked`.
  - `GET /api/intel/projects/{id}/gates` returns it.
  - The routes that start a stage's job return **409 "Finish <stage> first"** when the earlier stage is not done: research, strategy generation, Data set upload and tagging, and the deck run.
- **Frontend.** `App.tsx` checks the gates whenever a project page opens, including from a typed URL such as `/299/background-research`. A locked page redirects to the furthest unlocked stage and shows a toast. The Dashboard stage buttons and its "Next stage" link use the same gates.
- **When each stage counts as done:**

| Stage | Done when |
|---|---|
| Brief & Scope | Job finished and the user approved it. This is the only manual approval. |
| Background Research | The research and brief jobs finished. The server approves it automatically. |
| Search Strategy | The strategy job finished. The server approves it automatically. |
| Matching label | At least one RQ exists. |
| Data set | Tagging finished and at least one article is approved. |
| Deliverables | (Last stage; nothing after it to unlock.) |

- **Background Research.**
  - The "Approve & Continue" button and the idle "Generate Brief" screen are removed.
  - With no brief and nothing running, the page starts research itself.
  - "Request Revision" stays.
- **Search Strategy.** The "Approve Strategy" button is removed.
- **Matching label.** RQ cards sit in a 3-per-row grid (`grid-cols-1 md:grid-cols-2 xl:grid-cols-3`). The per-RQ Approve button stays.

## 2. Live progress, live usage, logos

- **Project progress.**
  - `GET /projects` returns `progress_pct` and `current_stage`, computed from the gates. Each of the 6 stages is an equal share; a running stage adds its job percent within its share.
  - A `useProjectProgress` hook updates the cards live from the `intel_job_update` and `dataset_tagging` socket events. It refetches only when a stage finishes or a project is deleted.
  - Each card on Home and on All projects shows a thin violet bar with "<stage> · N%", and a check at 100%.
- **Home logos.** Recent-project rows use `BrandLogo`.
- **Live usage.**
  - `usage.record()` broadcasts `{"type":"llm_usage", ts, project_id, stage, sub_stage, provider, model, input_tokens, output_tokens, cost_usd}` after each insert. It is scoped by the existing audience rules.
  - **The Usage page:**
    - It gets a Live feed panel with the last 50 calls and a Pause toggle.
    - KPI tiles and today's trend point update as rows arrive.
    - A full refetch runs at most every 10 s.
  - The project Dashboard shows a live "Cost so far" chip.
- **Top projects.** Rows and the #1 card show the project's `BrandLogo`.
- **Deleting a project** also deletes its `llm_usage` rows.
- **Polish.**
  - Number formatting follows one set of rules everywhere.
  - Loading shows skeleton placeholders, and empty tables show empty states.
  - Charts animate on update.
  - No new libraries.

## 3. Data set page, branding, reset and live run

- **Upload card.**
  - Each uploaded file shows as a chip: a file-type icon, the article count and an × button. The tooltip gives the name, rows read and duplicates. The data comes from `GET /articles/{pid}/files`, so the chips survive a reload.
  - `DELETE /articles/{pid}/files/{file_id}` removes that file's articles and their RQ rows in one transaction. It returns 409 while tagging or a deck run is active. The confirm dialog names how many articles, and how many approved, will leave.
- **Review controls.** Approve/Reject (`BulkBar`) and `FilterBar` appear only after tagging has finished at least once and nothing is tagging. Before that, the page shows the hint "Tag the data set to review and approve".
- **Task 9 is folded in.** That is the RQ query panel and drawer on the Data set page, and the tag schema shown on Matching label.
- **Branding.**
  - Every visible "InfoVision" becomes Alphametricx: sidebar, icon rail, home heading, alt texts, footer, page title and favicon.
  - The logo is `/alphametricx.png`.
  - The `infovision-…` localStorage keys stay, so saved drafts survive.
- **Reset and live run (local dev database only, never Render).**
  1. Check that nothing is running.
  2. Delete every project through `DELETE /projects/{id}`.
  3. Delete all `llm_usage` rows. Prices and settings are kept.
  4. Create one project per folder in `D:\HunterAgent\Dataset` (6 in all) through the real API. Brief & Scope is approved as the user; autorun runs the rest.
  5. Upload and tag **1000 articles in total**, about 166 per project, sampled from each folder's files and preferring the `_500set`/`_700set` files.
  6. Screenshot Home, All projects and Usage & cost with live numbers.

## Testing

- **Local only:**
  - gate 409s and the URL redirect
  - the progress-percent maths
  - deleting a file
  - the shape of the usage broadcast
  - deleting a project deletes its usage rows
- **Builds:** `tsc` and `npm run build`.
- **Live:** Playwright on the run above.

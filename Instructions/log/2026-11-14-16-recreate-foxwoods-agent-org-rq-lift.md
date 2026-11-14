# 2026-11-14-16 Recreate Foxwoods in Testing Org; fixes found on the way (Super Admin list, agent org, nested RQs)

## Request
- New Project gave "409: A project named 'Foxwoods Resort Casino' already exists in this organization". Create the
  project with the Casino Gaming brief (`Dataset/Casino Gaming/Casino Gaming.docx`) and upload
  `IV_Frenold_CEO_Brand_Competitors_Editorial.xlsx` + `IV_SU_Campaign_Data_"This Is How We Resort".xlsx`.
  "use chrome browser", "using khadar login", then "delete the project and create again".
- Why the 409: project 40 had been created at 09:55 UTC (before log 15), but Khadar could not open it then (Super
  Admin block). The retry hit the duplicate-name check.

## Done in Chrome (Khadar's session, port 8002)
- Project 40 was deleted by its owner from the Projects page, after Testing Org was picked in the profile menu.
- Project 41 "Foxwoods Resort Casino" was created: client the same, United States, Social Listening, Past 7 days.
  - Chrome refuses local file uploads ("Allow access to file URLs" is off for the browser extension), so the brief
    text was read from the .docx with python-docx (2,341 chars) and put in the Client Brief box.
- Brief & Scope: 20/20 sections; approved. Background Research and Search Strategy completed (NVIDIA models, no GPT).
- Data set: NOT uploaded yet, waiting for Khadar to choose the two files (same Chrome restriction).

## Fixes (code)
1. `projects/router.list_projects_route`: a Super Admin sees projects only when `org_member` (an org they belong to
   is picked). Before, a fresh session with no org listed EVERY org's projects, which then answered 403 on open and
   delete. That was the 403 on the first delete attempt.
2. `agent/api_client.ApiClient(user_id, project_id=None)`: the in-process session is put in the project's org
   (`store.set_session_org`). Autorun, autopilot and copilot pass `project_id`. Before, a Super Admin's autorun got
   "GET /projects/41 -> 403" right after approving Brief & Scope.
3. `agents/meltwater_query_builder._apply_defaults`: sections the model nested inside `query_versions`
   (`research_question_queries`, `exclusion_strategy`, `filter_recommendations`, `quality_assessment`) are moved to
   the top level. Strategy 39 (project 41) came back from the NVIDIA model with all 9 RQs and the exclusions nested
   there. Matching label showed "No research questions yet".
   - Strategy 39 was repaired in place: lifted, then the router's post-processing (`_quoted_phrases`,
     `_brand_wide_queries`, `_only_brief_questions`, `_no_geographic_exclusions`) applied again.
   - Result: RQ1-RQ9 approved, the real exclusions, versions broad/balanced/precise only.

## Verified
- ruff clean.
- Tests (local):
  - New: `tests/security/...::test_super_admin_lists_only_member_org_projects` and
    `tests/strategy/test_query_builder_prompt.py::test_rq_list_nested_in_query_versions_is_lifted_out`.
  - security/auth/projects 74 passed; agent/security 42 passed; strategy/research 125 passed; strategy 15 passed
    after the generalized lift.
- Live:
  - Delete of project 40 worked (owner).
  - Autorun ran Background Research and Search Strategy to done after fix 2.
  - Matching label lists RQ1-RQ9 after the repair.

## Not verified
- A fresh strategy generation with the lift in place (only the unit test and the repaired row).
- The Data set upload, tagging and deck for project 41.

## Follow-ups
- Khadar uploads the two .xlsx files on `/41/data-set` (about 620 rows across 4 sheets, within the 1000-article budget), or
  turns on "Allow access to file URLs" for the browser extension so uploads can be automated.

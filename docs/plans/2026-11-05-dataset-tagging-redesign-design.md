# Data set tagging redesign — design

Date: 2026-11-05 · Status: approved in brainstorming, not yet built

## Goal

One place to upload every dataset for a project, one tagging run that tags each article once and then against each
approved research question (RQ), one review table, and a deck built only from approved article–RQ rows. Replaces the
per-RQ upload flow and the current Review tab. Existing projects are deleted; there is no data migration.

## Flow

1. **Matching label tab** — every RQ with its question, Boolean query and query-tag schema. Each RQ is Draft or
   Approved; only approved RQs are tagged or used in the deck. Edit (re-tags only that RQ), delete, un-approve (hides
   its columns and drops it from the deck; tags are kept), add. Editable before or after upload.
2. **Upload** — one upload area for any number of Excel/CSV files. Rows are normalised with the existing
   Meltwater/Empower loaders, split into Traditional and Social, and deduplicated by normalised link across all files.
   The **Data set** tab (replacing Review) opens with "N articles uploaded (T traditional, S social, D duplicates
   removed)". A file with no recognisable link or title column is rejected with the columns it has; other files load.
3. **Start tagging** (top left of the Data set tab; becomes **Re-tag**, which only tags new or changed rows):
   - Phase 1 — fetch content (Scrapling, falling back to headless Chromium). Status per article: Full text,
     Summary only (subscription required), Blocked by site, Not reachable. Social posts skip this phase. CAPTCHAs and
     bot blocks are not bypassed.
   - Phase 2 — article tags, once per article: sentiment + confidence + summary; primary/secondary/tertiary themes;
     entities; category (industry) and group (product/device); signals; every brand mentioned with aspect sentiment,
     confidence and summary.
   - Phase 3 — RQ tags, RQ1 then RQ2 …, approved RQs only. A free keyword pre-filter applies the RQ's Boolean query;
     GPT then judges intent on title + content (summary when content is unavailable) for every article, keyword hit
     or not. Output per article–RQ: matched, reason, summary, the RQ's query-tag values with quoted evidence, matched
     keywords, match confidence.
   - Phase 4 — syndicated (same text, text fingerprint, no GPT) and similar articles (same intent: NVIDIA embeddings
     group candidates, GPT confirms groups in batches).
4. **Review** in the Data set tab, then **Deck** from approved rows.

## Batching

Every GPT phase packs batches by tokens, not article count: articles are added until the input budget or the
expected output budget is reached, whichever is first. Both budgets come from `.env` (defaults sized for GPT-5:
about 40% of the context window for input, an output cap so replies are never cut off). Each article is trimmed to a
maximum length first. Batches run on the existing 8-worker pool. A cut-off or malformed reply is retried once at half
size, then those articles are marked "Tagging failed" and Re-tag retries only them. Each batch is saved as it
finishes, so a restart resumes from the last saved batch. Progress shows phase, batches and minutes left.

## Data model

- `intel_articles` — one row per project + normalised link: normalised fields, traditional/social, content and
  content status, article-level tags, syndicated/similar groups, social author name, author ID, post ID.
- `intel_article_rq` — one row per article per approved RQ: matched keywords, query-tag values + evidence, summary,
  reason, match confidence, status (pending / approved / irrelevant), reviewer and time.
- Uploads keep only file metadata. Old enrichment tables stay in place, unread.

## Approval

- An article–RQ row is auto-approved when min(sentiment confidence, RQ match confidence) > 75.
- The article's Status is Approved only when every RQ it matched is approved.
- No RQ matched → "No RQ match", starts Irrelevant, can be overridden.
- Analyst decisions (approve, reject, cell edits) are final; Re-tag never overwrites them.

## Data set tab

Two tabs, Traditional and Social media, sharing one table component (from today's enriched table). Rows are paged
server-side (100 per page) with filters applied on the server.

Columns, left to right (checkbox, S.No, Status, Title pinned):

- Checkbox · S.No · Status · Title (links to the article)
- Content — full text cut to 3 lines; hover shows the complete text in a scrollable popover; click opens the side
  panel. Falls back to the export summary, marked "Summary".
- Content status · outlet · date · country with circular flag · syndicated / similar counts (clickable)
- Social: Author (real name from the export; handle when no name), Author ID, Post ID (from the export or parsed
  from the post link), author type
- Overall sentiment (pill + confidence, summary on hover) · one sentiment column per brand mentioned · themes ·
  signals · entities · category · group
- Per approved RQ: query-tag columns from its schema (chips, evidence on hover), matched keywords, summary & reason,
  RQ status
- Matched RQs (chips)

A column picker hides groups.

Filters: All / Approved / Review / Irrelevant; an RQ selector (All RQs, RQ1, …) that scopes rows and Status;
sentiment, theme, brand, content status.

Selection and bulk review:

- The header checkbox selects every row that matches the filters, across pages, and shows a partial state.
- A bulk bar shows "N selected · Approve · Reject · Clear". Reject asks for an optional reason.
- The scope follows the RQ selector ("Approve for RQ2" or "Approve for all matched RQs").
- Each row has hover ✓/✕ buttons for one-click decisions.
- Each decision stores who and when, shown on hover over Status.
- Undo is offered for 10 seconds after a bulk action.
- The selection clears when the tab, filter or scope changes.

## Deck

- One function in `deliverable/rows.py`: `approved_rows(project_id, rq=None)`. Every engine read of rows and the
  coverage panel go through it.
- RQ sections use only that RQ's approved rows. Deck-wide slides (overview, share of voice, sentiment trend, brand
  comparison) use every approved article, each counted once.
- The browser-side threshold filter from 75fbf59 is removed; the fixed 75 rule applies on the server.
- A deck run is blocked while tagging is in progress for that project.

## Testing (local, gitignored)

- Upload: normalise, split traditional and social, dedupe by link across files.
- Batch packer: token budget, trimming, half-size retry.
- Approval: the min > 75 rule, article status across matched RQs, decisions surviving a Re-tag.
- Bulk approve/reject scoped to one RQ and to all RQs.
- `approved_rows`: per-RQ rows, and deck-wide rows counted once.
- One Playwright end-to-end run: upload a 300-row export → tag → approve → deck.

## Open risks

- Batch budgets are estimates until measured on a real 300-article set.
- Some exports may lack a real-name author field; the handle is shown then.
- Every engine read of rows must move to `approved_rows`; the plan lists each call site.

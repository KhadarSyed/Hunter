# 2026-11-08 #10 — Blocked domain list: paste a separated list or upload Excel / CSV / JSON

**Request:** A domain list to block fetching data from; supply it separated, or upload Excel, CSV or JSON.

**Already existed:** Settings → Exclusions (`domains/exclusions/`, table `intel_exclusions`, per org, kinds domain /
keyword). Enforced in Background Research (`research/router.py` scrub, `research/multi_source.py` keep), deck rows
(`deliverable/rows.py`) and latest-24h (`deliverable/latest24h.py`). Domains match subdomains too. Missing: only one
value at a time, cap 500.

**Added:**
- `exclusions/service.py`: `split_values` (commas, semicolons, tabs, spaces, new lines; keywords keep spaces),
  `values_from_file` (.xlsx/.xlsm every cell of every sheet via openpyxl; .csv/.txt every cell; .json list of
  strings, list of objects with domain/website/url/host/…, or {"domains": [...]}; 2 MB max), `prepare` (URL →
  domain via `normalize_domain`, de-dupe against the list and within the batch, skips column headings like
  Domain/Keyword, reports invalid values).
- `POST /api/intel/exclusions/bulk` {kind, text} and `POST /api/intel/exclusions/import` (multipart file + kind) →
  {added, duplicates, invalid[≤20], invalid_count, total}. Cap raised 500 → 5000 per org. `repository.add_exclusions`
  inserts a batch in one transaction.
- `ExclusionsTab.tsx`: the box takes one value or a pasted list ("Add all"), "Upload list" button (.xlsx .csv .txt
  .json), result line (added / already listed / not valid with examples / total), search box over 20 rules,
  scrolling chips.

**Verified:** `tests/exclusions/test_bulk_import.py` 9 passed (local). Live as Acme admin: paste 3 added + 3 invalid;
Excel header skipped + duplicate counted; JSON {"domains"} ok; keyword CSV phrases kept whole (heading skipped after
fix); PDF → 422 "Upload an .xlsx, .csv, .txt or .json file"; Globex can't see Acme's list; research filter drops
news.dealmoon.com, keeps reuters.com. Test rows removed. Screenshot `shots/exclusions-tab.png` (local).

**Next (asked in the same message):** apply the block list to the Data set too — excluded articles marked
Irrelevant with the rule as reason, analyst can mark Relevant with a comment, and that decision kept as learning.

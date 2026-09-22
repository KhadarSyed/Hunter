# Publishing & Quality Gateway

*Stage 15 — Final quality gate before client delivery*

---

## Purpose

The Publishing & Quality Gateway is a pure validation/packaging engine. It **NEVER** generates new content, rewrites insights, or modifies reports. Its sole responsibility is to validate, certify, and publish approved deliverables.

---

## Architecture

```
publishing_gateway.py          # Core service (~960 lines)
├── Quality Validator          # 8 validation functions across 7 dimensions
├── Deliverable Comparator     # PPTX vs Word content extraction + diffing
├── Version Manager            # Semantic versioning (major.minor.revision)
├── Package Builder            # ZIP packaging with manifest/metadata/evidence
├── Approval Workflow          # 6-state workflow (submit→approve→publish)
├── Download Manager           # File retrieval + download tracking
├── Readiness Summary          # Aggregated readiness scoring
└── Audit Trail                # Complete action history
```

---

## Validation Dimensions

| Dimension | Weight | Checks |
|-----------|--------|--------|
| Narrative | 0.15 | Slide titles, narrative text, key message duplication |
| Evidence | 0.20 | Evidence references on content slides |
| Design | 0.10 | Visual/chart recommendations on visual slides |
| Branding | 0.10 | Meaningful presentation title |
| Completeness | 0.15 | Cover slide, executive summary, content slides, recommendations |
| Rendering | 0.20 | PPTX file exists on disk, Word file exists on disk |
| Consistency | 0.10 | Duplicate slide titles |

### Issue Severities

| Severity | Score Penalty | Effect |
|----------|--------------|--------|
| Critical | -0.40 per issue | Forces readiness class to "blocked" |
| Major | -0.20 per issue | Degrades dimension score |
| Minor | -0.05 per issue | Minor degradation |
| Information | 0.00 | Informational only |

### Readiness Classification

| Class | Threshold | Meaning |
|-------|-----------|---------|
| Client Ready | Score >= 0.80, 0 critical | Ready for client delivery |
| Internal Review | Score >= 0.50, 0 critical | Needs internal review |
| Draft | Score < 0.50 | Early stage, significant gaps |
| Blocked | Any critical issues | Cannot proceed until resolved |

---

## Deliverable Comparison

Compares PPTX and Word output content extracted from the same presentation data:

- **Titles** — slide/section titles match
- **Recommendations** — recommendation content identical
- **Evidence References** — same evidence IDs cited
- **Metrics** — metric content blocks match
- **Sources** — source references align
- **Rendering Status** — both deliverables rendered

Match percentage = `1.0 - (differences / total_items)`.

---

## Version Management

Semantic versioning: `v{major}.{minor}.{revision}`

- First version: `v1.0.0`
- Subsequent versions increment minor: `v1.1.0`, `v1.2.0`
- Tracks pipeline version, renderer version, presentation version

---

## Approval Workflow

```
draft → submitted → approved → published → archived
                  ↘ rejected
                  ↘ revision_requested
```

| Action | Transitions To | Prerequisites |
|--------|---------------|---------------|
| Submit for Review | submitted | Auto-creates version if none exists |
| Approve | approved | Version must exist |
| Reject | rejected | Version must exist |
| Request Revision | revision_requested | Version must exist |
| Publish | published | Version must be approved |
| Archive | archived | Version must exist |

---

## Package Builder

Creates a ZIP deliverable package containing:

| File | Description |
|------|-------------|
| `{name}.pptx` | PowerPoint presentation (if rendered) |
| `{name}.docx` | Word report (if rendered) |
| `evidence_index.json` | Evidence ID → slide mapping |
| `metadata.json` | Project/presentation metadata |
| `manifest.json` | Package contents and provenance |

---

## Database Tables (7)

| Table | Purpose |
|-------|---------|
| `intel_pub_validations` | Validation runs with scores, issues, readiness |
| `intel_pub_diff_reports` | PPTX vs Word comparison results |
| `intel_pub_versions` | Semantic version history |
| `intel_pub_packages` | Built deliverable packages |
| `intel_pub_approvals` | Approval workflow actions |
| `intel_pub_downloads` | Download tracking |
| `intel_pub_audit` | Complete audit trail |

10 indexes for query performance.

---

## API Endpoints (24)

### Actions (POST)

| Endpoint | Description |
|----------|-------------|
| `/publishing/validate` | Run quality validation |
| `/publishing/compare` | Compare PPTX vs Word outputs |
| `/publishing/package` | Build deliverable package |
| `/publishing/version` | Create new version |
| `/publishing/submit` | Submit for review |
| `/publishing/approve` | Approve deliverable |
| `/publishing/reject` | Reject deliverable |
| `/publishing/revision` | Request revision |
| `/publishing/publish` | Publish deliverable |
| `/publishing/archive` | Archive deliverable |

### Queries (GET)

| Endpoint | Description |
|----------|-------------|
| `/publishing/readiness/{project_id}/{pres_id}` | Readiness summary |
| `/publishing/versions/{pres_id}` | Version history |
| `/publishing/audit/{project_id}` | Audit trail |
| `/publishing/validation/{validation_id}` | Validation detail |
| `/publishing/validations/{pres_id}` | Validation history |
| `/publishing/diff/{pres_id}` | Latest diff report |
| `/publishing/package/{package_id}` | Package detail |
| `/publishing/packages/{pres_id}` | Package history |
| `/publishing/download/package/{package_id}` | Download package ZIP |
| `/publishing/download/pptx/{pres_id}` | Download PPTX |
| `/publishing/download/word/{pres_id}` | Download Word |
| `/publishing/downloads/{project_id}` | Download history |
| `/publishing/approvals/{pres_id}` | Approval history |
| `/publishing/stats/{project_id}` | Publishing statistics |

---

## Frontend

`PublishingGatewayPage.tsx` — Full publishing dashboard:

- **Header** with STAGE 15 badge
- **Project/Presentation selectors** populated from API
- **Summary cards** (5): Readiness Score, Version, Output Match, Package, Publications
- **Dimension score bars** (7) with color-coded thresholds
- **Action bar** (11 buttons): Run Validation, Compare Outputs, Build Package, New Version, Submit/Approve/Reject/Revision/Publish/Archive, Refresh
- **Download links**: PPTX, Word, Package ZIP
- **6-tab layout**: Validation, Difference Report, Versions, Approval History, Packages, Audit Trail

---

## Tests

84 automated tests across 16 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| ValidationTest | 11 | Missing presentations, project mismatch, complete presentation, critical issues, evidence gaps, readiness classification, dimensions, rejected slides, duplicates, branding |
| ComparisonTest | 3 | Missing presentation, identical outputs, diff report persistence |
| VersionTest | 4 | First version, minor increment, listing, not found |
| ApprovalWorkflowTest | 10 | Submit, approve, reject, revision, publish, archive, error cases, history tracking, full workflow |
| PackageBuilderTest | 2 | No renders error, missing presentation |
| ReadinessSummaryTest | 3 | Empty state, after validation, with version |
| AuditTrailTest | 4 | Validation audit, approval audit, version audit, comparison audit |
| StoreValidationTest | 4 | CRUD operations |
| StoreVersionTest | 2 | Create + list |
| StorePackageTest | 1 | Create + get |
| StoreApprovalTest | 1 | Create + list |
| StoreAuditTest | 1 | Add + list |
| StoreDownloadTest | 1 | Create + list |
| StoreStatsTest | 2 | Empty stats, populated stats |
| StoreDiffReportTest | 1 | Create + get |
| StoreListProjectsTest | 1 | List projects |
| ConstantsTest | 4 | Valid actions, readiness classes, severities, dimensions |
| HelperFunctionTest | 8 | Readiness computation (blocked/client_ready/draft), dimension scoring, classification, list comparison |
| DownloadManagerTest | 4 | Missing package/render paths, record download |
| APIEndpointTest | 17 | All 24 endpoints via TestClient |

---

## Known Limitations

1. **No file-level content comparison** — Compares structured data (titles, evidence refs) not rendered file contents. A pixel-level or text-level diff of actual .pptx/.docx files would require additional tooling.
2. **Single approval track** — One linear approval chain per presentation. Parallel review tracks (e.g., content review + design review) not implemented.
3. **No email/notification integration** — Approval state changes are recorded but do not trigger notifications.
4. **Package requires rendered files on disk** — If rendered files have been moved or deleted, packaging will fail.

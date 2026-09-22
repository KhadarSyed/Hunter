# Hunter Intelligence — Product Specification

## Product Purpose

Hunter Intelligence is a locally-hosted research automation platform that transforms a client brief into a structured, evidence-backed research deck. It combines five agent modules — each with validation gates and human approval — to move from raw brief through background research, Meltwater query building, dataset evaluation, and research planning before execution begins.

The platform serves a single analyst workflow: receive brief, understand scope, research the brand/issue landscape, build and validate Meltwater Boolean queries, upload and evaluate a real dataset sample, then plan the research execution. Every step produces auditable output; no step proceeds without explicit approval.

---

## Approved 10-Stage Workflow

| # | Stage | Owner | Inputs | Outputs | Gate |
|---|-------|-------|--------|---------|------|
| 1 | Understanding | Brief & Scope Agent | Client brief (.txt/.docx/.pptx) | ProjectSpecification | Gate 1 — Scope Approved |
| 2 | Background | Brand Intelligence Agent | Approved spec | Brand & Issue Intelligence | Gate 2 — Research Approved |
| 3 | Search Strategy | Meltwater Query Builder | Spec + Brand Intelligence | Boolean queries (broad/balanced/precise) | Gate 3 — Strategy Approved |
| 4 | Data Collection | Data Source Manager | Approved queries | Validated Meltwater dataset | Gate 4 — Dataset Approved |
| 5 | Planning | Research Planner Agent | Spec + Dataset + Background | Research Plan (objectives) | Gate 5 — Plan Approved |
| 6 | Researching | Research Executor | Research Plan + Dataset | Evidence Collection | Pending |
| 7 | Synthesizing | Insight Agent | Evidence Collection | Insights & Themes | Pending |
| 8 | Storylining | Storyline Agent | Insights & Themes | Narrative Structure | Pending |
| 9 | Designing | Deck Builder | Narrative Structure | Presentation Deck | Pending |
| 10 | Quality Review | QA Agent | Final Deck | Approved Deliverable | Pending |

Stages 1-5 are implemented. Stages 6-10 are planned but not yet built.

---

## Agent / Module Responsibilities

### Brief & Scope Agent (`agents/brief_scope.py`)

Converts a raw client brief into a validated `ProjectSpecification`. Distinguishes four roles: commissioning brand, research subject, research audience, strategic application. Validates entities with alternatives-considered reasoning. Runs the LLM up to 3 attempts with correction prompts on validation failure. 11 validation functions enforce structural completeness, scope compliance, and exclusion conflicts.

### Brand Intelligence Agent (`agents/brand_intelligence.py`)

Produces structured brand background research to ground downstream agents. Covers brand overview (products, aliases, social handles, misspellings), category context, entity disambiguation, search implications (23 terms typed as must_include/precision/exclusion/audience_language/campaign_hashtag), source quality assessment (tier 1/2/3), and research gaps. Optionally augments LLM output with live web research via DuckDuckGo.

### Meltwater Query Builder (`agents/meltwater_query_builder.py`)

Generates three Boolean query versions (broad/balanced/precise) compatible with Meltwater syntax. Produces 10 query modules, 8 research-question-specific queries, exclusion strategy (entity/spam/content-type), filter recommendations, and a 9-dimension quality score. Includes a Boolean syntax validator (balanced parens, quoted strings, operator adjacency).

### Query Evaluator (`agents/query_evaluator.py`)

Rule-based evaluator (no LLM). Accepts CSV/XLSX Meltwater exports. Detects Meltwater column format with 12 logical fields and 5-10 name variants each. Classifies records as relevant/partial/irrelevant with confidence scores. Detects duplicates (URL and headline similarity >= 0.85). Calculates precision, false-positive rate, recall risk, and per-RQ coverage. Recommends query refinements.

### Research Planner (`agents/research_planner.py`)

Decomposes approved research questions into 2-5 research objectives. Each objective specifies platforms with per-platform justification, evidence requirements, analytical methods (from 10 validated types), deliverable mapping, and search concepts. Validates question coverage, duplicate detection (word overlap > 75%), and scope compliance.

### Web Research Adapter (`web_research_adapter.py`)

Live web research via DuckDuckGo with citation tracking, entity validation, date filtering, and source quality classification. Builds 14+ query families from the approved spec. Filters blocked domains, validates entity relevance (specialized rules for brand disambiguation), classifies sources into tiers. Returns structured output with citations and confidence scores.

---

## Project Workspace

A project workspace is a SQLite record (`intel_projects` table) containing the project name and full spec JSON. All downstream artifacts (research, strategies, evaluations, jobs) are linked to a project by foreign key. There is no multi-user or multi-tenant model; the database is local.

The deck-builder pipeline uses a separate workspace model: a watched briefs inbox folder, a PPTX repository folder, and an output folder — all configured via `settings.json`.

---

## Dataset Upload and Normalization

The `query_evaluator.py` module handles dataset ingestion:

- **Supported formats:** Meltwater CSV (primary), Meltwater XLSX (primary), Brandwatch CSV, Cision Excel, Manual CSV
- **Column detection:** 12 logical fields (headline, URL, source, date, author, content, reach, engagement, sentiment, language, country, media_type) matched against 5-10 Meltwater column name variants per field
- **Encoding:** Attempts utf-8, then latin-1, then cp1252
- **Deduplication:** By exact URL match and headline text similarity (SequenceMatcher >= 0.85)
- **Classification:** Each record scored as relevant/partially_relevant/irrelevant/uncertain based on keyword matching against spec terms and strategy terms, with confidence and reason tracking

The frontend Data Sources page provides a simulated upload flow (demo mode) or a real file upload (live mode via `POST /api/intel/evaluation/upload`).

---

## Background Research

Background research produces a `BrandIntelligenceOutput` containing:

- **Brand overview:** official name, parent company, products, social handles, aliases, misspellings, ambiguous terms, exclusions
- **Category context:** definition, terminology, consumer needs, cultural context, seasonal factors, false-positive sources
- **Entity disambiguation:** correct spelling, variations, ambiguous terms with irrelevant meanings
- **Search implications:** typed search terms (must_include, precision, exclusion, audience_language, campaign_hashtag) with rationale
- **News context:** recent articles with tier ratings, summaries, relevance assessment, suggested search terms
- **Source quality:** tiered source records
- **Research gaps:** identified gaps in available intelligence

Live mode executes DuckDuckGo web + news searches, validates entity relevance, classifies source quality, and augments LLM output with cited web findings. Individual news items have per-item approval controls (approve/reject/irrelevant).

Constraint: "If live web research cannot execute, the agent must return LIVE_WEB_RESEARCH_UNAVAILABLE and block approval of the Background Research stage."

---

## Meltwater Search Strategy

The search strategy output (`MeltwaterStrategyOutput`) contains:

- **Strategy summary:** objective, approach (audience-led), strengths, blind spots, false-positive risks, validation steps
- **Core queries:** broad/balanced/precise Boolean strings. Each undergoes syntax validation (balanced parens, unclosed quotes, operator adjacency, length limits)
- **Query modules:** 10 modules (brand terms, audience terms, topic modules, life-stage modules, language, exclusions) each with terms and boolean_fragment
- **Research question queries:** 8 RQ-specific Boolean queries with coverage notes
- **Exclusion logic:** entity exclusions (6), spam exclusions (8), content-type exclusions (5), combined NOT string
- **Filter recommendations:** geography, language, date range, platforms, editorial/owned/retweet/engagement/duplicate handling
- **Quality score:** overall + 9 sub-scores (entity accuracy, scope alignment, estimated recall risk, precision, ambiguity control, audience relevance, topic coverage, FP protection, RQ coverage), warnings, recommended refinements
- **Version history:** every query edit tracked with timestamp and summary

Constraints:
- "Do not claim full Meltwater compatibility unless the syntax has been tested in Meltwater."
- "Do not claim recall as a measured metric from one retrieved sample unless an independent benchmark exists. Label any recall assessment as: Estimated Recall Risk not measured recall."
- Queries display "Demo query — Meltwater validation pending" in demo mode.

---

## Approval Gates

Each gate blocks downstream stages until explicitly approved:

| Gate | Unlocks | Approval Method | Revision |
|------|---------|----------------|----------|
| Gate 1 — Scope | Background Research | `POST /api/intel/research/{id}/approve` or frontend button | Request Changes button |
| Gate 2 — Background | Search Strategy | `POST /api/intel/research/{id}/approve` or frontend button | Request Revision (revokes approval) |
| Gate 3 — Strategy | Query Evaluation + Data Sources | `POST /api/intel/strategy/{id}/approve` or frontend button | Request Revision (revokes approval) |
| Gate 4 — Dataset | Research Plan | Frontend approval button in Data Sources | — |

Frontend shared state (`DemoStateProvider`) tracks all four gates and computes `nextAction` and `researchPlanLocked` from the approval state.

---

## Evidence Traceability

- Every search term in brand intelligence includes a `rationale` field explaining why it was included
- Every exclusion includes a `reason` field
- Every news item includes `tier`, `relevance_notes`, and `suggested_search_terms`
- Every query module traces back to spec research questions
- Every research objective links to question IDs, platforms with justifications, and required evidence
- Source quality is classified into three tiers with named exemplar domains
- Constraint: "No uncited current factual claims are permitted."
- Constraint: "Do not represent Tier 3 sources as authoritative confirmation."

---

## Frontend Principles

- **Framework:** React 18 + Vite 5 + TypeScript, Tailwind CSS v4.3.3 via `@tailwindcss/vite` plugin
- **Routing:** State-driven navigation via `useState<Page>` in App.tsx. No router library.
- **State:** Local `useState` per component + `DemoStateProvider` (React Context) for cross-page demo state. No external state management library.
- **Modes:** Demo mode uses centralized demo data and local state (no backend dependency). Live mode calls the FastAPI backend at `localhost:8000` via `intel-api.ts`.
- **Styling:** Light mode only. White background, blue-600 primary accent, Inter typeface, rounded-xl cards, subtle shadows. Inline SVG icons.
- **Build output:** Production builds to `agent/static/` for serving by the FastAPI backend.
- **Dev proxy:** Vite dev server at port 5173 proxies `/api` and `/ws` to `localhost:8000`.

---

## Key Data Contracts

Defined in `web/src/data/contracts.ts`:

### BrandIntelligenceOutput
```
brand_overview: BrandIntelligenceRecord
category_context: CategoryContext
entity_disambiguation: EntityDisambiguation
search_implications: SearchImplication[]
news_context: NewsContextRecord[]
sources: SourceRecord[]
research_confidence: Record<string, string>
research_gaps: string[]
metadata: { sources_reviewed, sources_retained, sources_rejected, date_range }
```

### MeltwaterStrategyOutput
```
strategy_summary: { objective, approach, strengths[], blind_spots[], false_positive_risks[], validation_steps[] }
core_query: { broad: MeltwaterQueryRecord, balanced: MeltwaterQueryRecord, precise: MeltwaterQueryRecord }
query_modules: QueryModule[]
research_question_queries: ResearchQuestionQuery[]
exclusion_logic: { entity_exclusions[], spam_exclusions[], content_type_exclusions[], combined_not_string }
filter_recommendations: FilterRecommendations
quality_score: QueryQualityScore
term_rationale: { term, rationale }[]
versions: QueryVersion[]
```

### ProjectSpecification (backend schema)
```
executive_interpretation, commissioning_brand, research_subject, research_audience,
strategic_application, business_objective, research_objective, deliverable_objective,
validated_entities[], research_questions[], included_scope, excluded_scope[],
missing_information[], assumptions[], recommended_methodology, risks[],
success_criteria[], confidence_assessment, self_validation
```

### ResearchPlan (backend schema)
```
research_objectives[]: { id, objective, why, question_ids[], priority,
  platforms[{name, justification}], evidence[], methods[], deliverable,
  search_concepts[], confidence, complexity, status }
```

### SQLite Schema (intelligence_store)
```
intel_projects(id, project_name, spec_json, created_at, updated_at)
intel_jobs(id, project_id, job_type, status, progress_pct, result_json, error, ...)
intel_background_research(id, project_id, version, status, research_json, approval_status, ...)
intel_search_strategies(id, project_id, version, strategy_json, approval_status, ...)
intel_query_versions(id, strategy_id, version_label, query_type, query_text, is_active, ...)
intel_sample_evaluations(id, project_id, strategy_id, file_name, evaluation_json, ...)
intel_news_approvals(id, research_id, item_index, status, notes, ...)
```

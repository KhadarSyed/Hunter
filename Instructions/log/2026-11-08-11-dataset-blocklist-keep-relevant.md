# 2026-11-08 #11 — Exclusion list in every stage; Data set "Blocked" → Irrelevant, analyst "Mark relevant" + org learning

**Request:** Guardrails are per org, for every project of that org (confirmed: `org_guardrails.org_id`, applied to all
of the org's projects, never across orgs). The block list must apply wherever data is fetched or used: web search,
uploaded data set, deliverables. In the Data set, blocked articles become Irrelevant with the rule as reason; an
analyst can mark one Relevant with a comment; the org's projects/agents learn from it; memory kept.
Learning choice (asked): **remember + advise** — the rule stays in force; the org remembers overrides.

**Enforcement map now:** web research (`research/router.py` scrub, `multi_source.py` keep) · latest-24h · Data set
(new, in the free Boolean match, before tagging — saves tokens) · deck rows (`deliverable/rows._without_excluded`,
now honours analyst-kept articles by norm_url).

**Built:**
- Migration 52: `intel_articles.excluded_reason, keep_by, keep_at, keep_comment`.
- `dataset/service.match_rqs`: `blocked_reasons()` (org rules; kept articles skipped) removed from every question's
  matches → Irrelevant pool, never tagged; returns `blocked`. `repository.save_blocked` runs before the match is saved:
  frees undecided rows the block moved (rule removed / article kept), sets reasons, moves undecided+unapproved rows to
  irrelevant with reason `BLOCK_PREFIX (…)`. Analyst-decided rows never touched.
- `POST /api/intel/articles/{pid}/{aid:int}/keep {comment ≥3}` → `service.keep_relevant`: stores override, org memory
  (`exclusions.remember_override`, memory_items scope org / type `exclusion_override`, key `domain:x` / `keyword:x`,
  count + last 5 comments), re-runs the match, clears data set approval. `:int` keeps /decisions/undo routing intact.
- Learning surfaced: `GET /exclusions` adds `kept_relevant`, `last_comment` (Settings shows "kept N×" with the
  comment); `guardrails.text_for` appends `exclusions.override_context` ("ANALYST DECISIONS ON BLOCKED CONTENT…") so
  the org's AI agents in the guarded stages get it; cache invalidated on each override.
- UI: Data set table "Blocked" pill (reason on hover) + "Mark relevant" (dialog, required comment; available in the
  Irrelevant pool, not while tagging runs); "Kept · <name>" pill (comment on hover); Irrelevant pool note updated;
  toast Undo only when there is an undo token.

**Verified (live, Acme mock project 2, all cleaned up):** 2 of 3 blocked (domain + subdomain), reason stored, pending RQ
row → irrelevant with reason; keep → override stored, unblocked on re-match, other still blocked; org memory count 1 +
comment; agent context includes it; Settings list shows kept 1× + comment; deck filter drops blocked, keeps analyst-kept.
Tests 42 passed (exclusions/billing/providers) + dataset suite earlier (136 incl. dataset).

**Known limit:** adding a rule does not re-run the match of projects already at the Data set stage; it applies on the
next Match (and the deck filter blocks it meanwhile).

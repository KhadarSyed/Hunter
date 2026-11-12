# 2026-11-12 #26 — spec moved to SQLAlchemy

## Changed
- `domains/spec/models.py` (new): intel_research_specifications (19), intel_spec_section_approvals (13),
  intel_spec_clarifications (10), intel_spec_audit (9); approval_status / is_locked server defaults kept.
- `domains/spec/repository.py`: SQLAlchemy Core, the same 20 public functions (AST-checked) + FORM_FIELDS,
  SPEC_SECTION_ORDER (read via store by spec/service + renderer), MANDATORY_SECTIONS; `__all__`. The readiness engine
  is unchanged; each multi-statement change (save + section rows, section edit + approval + audit, clarification +
  audit + readiness) is one transaction.

## Verified
- Parity (scratchpad/spec_parity.py, old from git HEAD; the same sequence run through each module on its own spec,
  compared without ids/timestamps): versions, full spec shape incl. section approvals, edits to existing and new
  sections, industry, approve/lock/unlock, blocking and optional clarifications, readiness blocked and approval
  refused, resolve (and missing), remove stale, approval allowed, reject/docx/update, audit actions and values,
  version list: 17 comparisons, 0 differences.
- pytest spec, projects, security, research, agents: 149 passed. ruff clean.

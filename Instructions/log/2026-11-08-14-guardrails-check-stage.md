# 2026-11-08 #14 — Deliverables "Guardrails check" stage (part C)

**Request:** a stage in Deliverables that checks the deck against the org's guardrails. User asked whether it is Python
or an LLM call → answer: both; Python first (exact, free), optional AI review for meaning-level rules.

**Built:**
- `guardrails/check.py`: `prohibited_terms(org)` parses each active guardrail — quoted terms after a "Prohibited
  vocabulary" heading + comma lists under "Examples of variations", until "This list is…" or the next numbered
  section (InfoVision → 86 terms incl. "%", "in this space", "share of voice"). `_pattern`: symbols literal; single
  words ≥5 letters match their word family (stem + \w*); shorter/multi-word match with s/es plural. `deck_slides(pptx)`
  reads titles, text boxes and table cells per slide (python-pptx). `scan`: prohibited words (longest term wins on
  overlaps), repeated title openings (first 3 words, titles ≥4 words), sentences ≥60 chars repeated across slides.
  `ai_review(org, slides, llm)`: one call, guardrail text as system prompt, JSON {issues:[slide, rule, excerpt,
  suggestion]}; [] on failure. `check_deck` → {slides, terms_checked, issues, passed}.
- Routes: `GET /api/intel/deliverable/{pid}/runs/{rid}/guardrails` (Python check, free) and `POST …/guardrails/ai`
  (usage scope deck_engine / sub_stage guardrails_review).
- UI: `components/deliverable/GuardrailsCheck.tsx` above the downloads of a completed run (red = prohibited words,
  amber = repetitions / AI findings, green = clean), findings table (slide, rule, found, suggestion), "Run AI review".

**Verified:** `tests/guardrails/test_check.py` 5 passed (real guardrail text, word family, symbols, repetition, real
.pptx, AI JSON + failure). No completed deck on disk locally for a live run.

**Not done:** automatic rewriting of flagged sentences inside the PPTX ("Fix wording"); the suggestions are shown for
the analyst to apply with the existing slide Fix.

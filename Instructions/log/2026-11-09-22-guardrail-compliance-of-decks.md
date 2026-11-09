# 2026-11-09 #22 — Were InfoVision's guardrails followed in the two decks?

User: "hope guadrials are followed and make sure presentation generated with guadrials answer this"

**Checked (Python, no GPT):** org 5 InfoVision, 1 active guardrail "Instructions/Guardrail Prompt" (11,003 chars, 86
prohibited terms incl. "%"). Every GPT stage both projects used (brief_scope, background_research, search_strategy,
dataset_tagging, deck_engine, deck_studio) is in `GUARDED_STAGES`, so every GPT call carried the guardrail.

**Result: decks do NOT fully comply.** `guardrails/check.check_deck`: Casino 255 issues, Planet Fitness 309.
- GPT-written prose almost complies: Casino 0 real slips; Planet Fitness 2 ("repeatable", "free summer entry").
- Almost all hits are text written by Python, not GPT:
  - "%" in chart values, KPI tiles, rule-based fact cards and the executive summary answers (141 / 168).
  - "X named in N articles" (entities chart labels), `Theme "…"` labels, "syndicated copies", "3 approved files"
    (methodology slide), "Share Of Voice" in the deck title (from the brief's own title).
  - Article headlines quoted in the source list ("Single", "Sets", "engine") — quotations, cannot be reworded.
- The insight word screen (`insights._guardrail_words`) runs only on the first draft; the repair step redrafts
  insights without it (likely source of the 2 GPT slips).

**Proposed fix (awaiting approval):** a per-org replacement map for its prohibited terms (made once by GPT, cached,
editable), applied by Python to all Python-written slide text at render (labels, fact cards, summaries, titles),
never to quoted headlines/URLs; same screen after the repair step; "%" → "percent" in prose, chart number labels
decision for the user.

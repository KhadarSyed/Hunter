# 2026-11-13-05 Map-step retry, output cap for OpenAI-compatible models, small clean-ups

## Request
"yes continue and do the fixes where it required" (follow-ups from the NVIDIA-only A/B run, log 04).

## What changed
- `backend/domains/research/multi_source.py` `_map_batch`: a reply with no JSON object (`ValueError` from
  `extract_json_object`) is asked once more; a second miss skips the batch (warning). Provider errors (incl.
  `ReplyCutOff`, a `RuntimeError`) are not retried here, as before. Safe because `HybridLLMClient.chat` never caches a
  broken JSON reply and sends a repeat prompt on the same client to the model (`core/llm_provider.py` 163, 178).
  Seen in the A/B run: Nemotron gave 6-7-token empty replies on 3 of ~46 batches.
- `backend/core/org_chat_clients.py` `OpenAICompatClient._stream`: sends `max_tokens = MAX_OUTPUT_TOKENS` (16384), the
  cap the Azure (`max_completion_tokens`) and Anthropic clients already send. A capped reply ends with
  `finish_reason == "length"` -> `ReplyCutOff`, never cached (unchanged). Seen in the A/B run: one uncapped reduce call
  on Nemotron streamed for 30+ minutes.
- `backend/domains/deckstudio/creative.py`: `handle_decl(self, _decl)` (vulture false positive; HTMLParser passes the
  argument positionally). vulture is now clean.
- Local `.env` (not in git): line 71 `CURL=...` (a pasted command, read by no code: grep for `CURL` in backend finds
  nothing) commented out, so python-dotenv stops warning "could not parse statement starting at line 69" on every load.
  Backup kept in the session scratchpad.

## Verified
- `pytest -q tests/research tests/providers` (HUNTER_PG_SCHEMA_PER_DB=1): 138 passed, incl. new
  `tests/research/test_map_batch_retry.py` (empty reply retried, two misses skip, provider error not retried) and a
  `max_tokens` assertion in `tests/providers/test_providers.py`. `tests/deckstudio`: 58 passed.
- `ruff check backend` clean; `vulture backend --min-confidence 80 --exclude backend/static` clean.
- Live: one tiny chat call per Test Organization model with the cap: nemotron-3-ultra-550b-a55b, minimax-m3.1-flash,
  step-5-preview all answered "ok" (1-2.4 s), so none rejects max_tokens=16384.
- `dotenv_values('.env')` parses 79 keys with no warning; restarted backend log has 0 "could not parse" lines.

## Not verified
- A full brief on NVIDIA with the retry + cap (the A/B run is paused until GPT spend is approved).
- Whether 16384 is enough for Nemotron's reasoning + the reduce JSON on a large project; if not, the reduce raises
  `ReplyCutOff` and compose_brief falls back to the rule-based brief (same behaviour as on Azure).

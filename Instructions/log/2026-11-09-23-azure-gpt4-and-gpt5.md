# 2026-11-09 #23 — Platform Azure chat works on both gpt-5 and gpt-4.x

User: "in env i have update the configuration LLM model rom 5 to 4 please make sure agent is compatible with both"

**Problem:** `.env` now has `AZURE_OPENAI_MODEL=gpt-4.1`, but `core/azure_openai_client.py` sent the GPT-5-only
`reasoning_effort` (from `AZURE_OPENAI_REASONING_EFFORT`, still set, and from `llm_effort.light()`) and `verbosity`.
gpt-4.x rejects both with HTTP 400, so every platform GPT call would fail.

**Fix (`core/azure_openai_client.py`):**
- `reasoning_params` = False when the deployment name starts with `gpt-4` / `gpt-35` / `gpt-3.5`; `_payload` then
  sends only messages + `max_completion_tokens` (accepted by gpt-4.1 on `2025-01-01-preview`).
- `_post_chat`: if a deployment with an unrevealing name returns 400 naming `reasoning_effort`/`verbosity`/
  "unrecognized request argument", it retries once without them and stops sending them for that client.
- `chat` (plain + stream) and `chat_tools` go through `_post_chat`. gpt-5 behaviour unchanged.
- Org providers (`core/org_chat_clients.py`) never sent these params; untouched.

**Checked:** live gpt-4.1 calls — plain, light()+JSON mode, streaming, and the forced 400 fallback — all OK.
Local tests `backend/tests/test_azure_payload.py` 5 passed (2 new: gpt-4 payload, 400 fallback).

**Not changed:** tagging batch budgets (`dataset/batching.py`: 100k in / 12k out) fit gpt-4.1 (1M / 32k); on gpt-4o
(128k context) lower `HUNTER_TAG_INPUT_TOKENS`. Usage prices for gpt-4.1 come from the daily Azure price sync
(only gpt-5 has a seeded default row).

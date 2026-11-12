# 2026-11-12-34 Which NVIDIA chat models fit (GLM 5.3 Flash does not answer)

**Request:** "check for other models which can fit for us".

**Method (scratchpad `model_probe.py`, `model_probe2.py`; key = existing NVIDIA key, never printed; no DB writes):**
NVIDIA's `/v1/models` lists ~55 chat models. 16 current general-purpose ones probed in parallel with an app-shaped
task (news snippet -> JSON brand/competitors/sentiment/theme), parsed with the app's own
`core.llm_provider.extract_json_object` and checked for the right answer, 60 s limit. Finalists then ran a
tagging-shaped task (6 headlines vs a research question: matched + sentiment, JSON array; answers fixed beforehand)
3 times each, 90 s limit.

**Round 1:** correct: nemotron-3-ultra-550b-a55b 6.4 s, step-5-preview 8.7 s, minimax-m3.1-flash 12.3 s.
Empty answer (reasoning only): nemotron-3.5-lightning-30b-a3b. Timeout >60 s: z-ai/glm-5.3-flash,
deepseek-v4.1-flash, mistral-large-4-1t-a52b, gpt-oss-20b. HTTP 404 although listed: gemma-4-31b-it, gemma-3-12b-it,
kimi-k2.6, nemotron-3-super-120b-a12b, llama-3.1-nemotron-ultra-253b-v1, nemotron-nano-3-30b-a3b,
mistral-large-2-instruct, jamba-1.5-large-instruct.

**Round 2 (scores of 6, three runs):** nemotron-3-ultra-550b-a55b [6,6,6], 13.6-33.8 s (median 14.2);
minimax-m3.1-flash [6,6,6], 22.5-31.2 s (median 22.6); step-5-preview [6, timeout, 6].

**Recommendation:** nemotron-3-ultra-550b-a55b as the org default, minimax-m3.1-flash as the second provider
(the providers domain fails over in order: saved default, then newest). Not changed yet: awaiting the user's go.

**Not verified:** NVIDIA free-endpoint rate limits / terms for production use; quality on long prompts (brief scope,
deck writing) beyond these two tasks; results are a point-in-time snapshot of NVIDIA's hosted catalogue.

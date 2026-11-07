# Organisation LLM providers — design

Date: 2026-11-07

## Goal

An organisation admin connects the organisation's own chat model in **Settings → LLM Providers**, tests the
connection, and every chat call of that organisation's projects then goes to it. Organisations without one keep
the platform model (Azure OpenAI GPT-5). InfoVision stays on the platform model.

## Decisions

| Topic | Decision |
|---|---|
| Routing | Every chat call (`HybridLLMClient.chat` / `chat_tools`) of the org goes to its default provider. |
| Failure | The call fails with `OrgProviderError: Org provider '<name>' failed: <reason>`. No fallback to the platform. |
| Types | OpenAI-compatible (any base URL: OpenAI, VyceAI, OpenRouter…), Azure OpenAI, Anthropic, Google Gemini. |
| Keys | Fernet-encrypted at rest (`PROVIDER_SECRET_KEY`), never returned; the UI shows the last 4 characters. |
| Replace | An org can save several providers; one is the default. Saving a new one as default replaces the old. |
| Embeddings | Stay on the platform (NVIDIA). |
| File text | An org on its own provider reads brief files with Python only (PDF, Word, PowerPoint, Excel, CSV, JSON, TXT), never the platform's NVIDIA parser. |
| Active org | The profile menu switches the session's organisation (`sessions.active_org_id`); projects, new projects and providers follow it. |

## Pieces

- Migration 46: `org_llm_providers`, `sessions.active_org_id`.
- `core/secret_box.py` (encryption), `core/org_chat_clients.py` (adapters; reuse the Azure client's retry and usage
  helpers), `domains/providers/` (repository, service with a 30 s cache, router), `HybridLLMClient._backend()`.
- Routes under `/api/intel/llm-providers`: list, create, update (blank key keeps it), delete, set default,
  use platform, test saved, test draft. Admin: own org; Super Admin: any org.
- `POST /api/auth/me/active-org`.
- Usage rows carry the provider type and the model the org entered, so a price row (Usage → prices) applies.

## Removed in the same change

Settings → Fixes and the code-fix agent behind it (fixer, worker, worktrees, apply, supervisor). Issue recording
(`agent/repair/issues.py`) stays.

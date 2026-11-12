# 2026-11-12-35 Test Organization: three NVIDIA models connected; Providers tab text corrected

**Request:** "let integrate all three working in the Testing Organization".

**Done (local DB, scratchpad `add_org_models.py`, same steps as the add-provider route: Fernet-encrypted key,
`repo.set_default`, `service.invalidate`):** Test Organization (id 3) providers, in failover order
(`service.route`): 1 `nvidia/nemotron-3-ultra-550b-a55b` (default, id 4), 2 `minimaxai/minimax-m3.1-flash` (id 3),
3 `stepfun-ai/step-5-preview` (id 2), 4 `z-ai/glm-5.3-flash` (id 1, kept, last; its test fails). Order is "default,
then newest first", so Step was created before MiniMax.

**Verified:**
- App Test connection (POST `/api/intel/llm-providers/{id}/test`): Nemotron ok 2.2 s, MiniMax ok 1.5 s,
  Step ok 39.6 s; results stored and shown as "Connected" on the Providers tab (browser screenshot, 0 console errors).
- Real path: `get_llm_client().chat([...])` in `usage.scope(org_id=3)`: text reply "OK" 3.3 s, `format_json` reply
  `{"status": "ok"}` 2.8 s; `llm_usage` rows: org 3, model nemotron-3-ultra, error 0, not cached.
- Failover is covered by `tests/providers/test_failover.py` (25 passed); not forced live, because a forced failure
  would mark a real provider down in the DB.
- (My first real-path call passed a bare string instead of a message list and got HTTP 400: caller error, not app.)

**Fixed:** `frontend/src/pages/ProvidersTab.tsx` said "if it fails, the call fails with its reason (no fallback)",
contradicting `providers/service.call` (down default -> next model in the listed order; all down -> wait and resume,
admins emailed; never the platform model). Text and doc comment corrected; tsc/lint (0 errors)/build ok.

**Open:** GLM 5.3 Flash stays as the 4th model; while NVIDIA does not serve it, it only adds a timeout at the end of
a full outage chain. Remove it in Settings -> LLM Providers if not wanted (not removed: not asked).

**Follow-up (user: "yes please"):** GLM 5.3 Flash removed from Test Organization through the app's
DELETE `/api/intel/llm-providers/1` (200). Order now: Nemotron 3 Ultra (default), MiniMax M3.1 Flash, Step 5 Preview.

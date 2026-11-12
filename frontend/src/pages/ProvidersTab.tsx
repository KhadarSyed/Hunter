import { useCallback, useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { useAuth } from "../context/auth-context";
import {
  intelApi, type AuthOrganizationRow, type LlmOutage, type LlmProvider, type LlmProvidersResponse, type ProviderFields,
  type ProviderTestResult, type ProviderType,
} from "../services/intel-api";
import { PROVIDER_ICONS } from "../components/usage/ProviderLogo";
import { ModelPrice } from "../components/usage/ModelPrice";
import type { UsagePrices } from "../types/usage";
import { formatRelativeOrDate } from "../utils/time";

type Preset = { id: string; label: string; type: ProviderType; baseUrl: string; model: string; apiVersion: string; icon: string };

const PRESETS: Preset[] = [
  { id: "openai", label: "OpenAI", type: "openai_compatible", baseUrl: "https://api.openai.com/v1", model: "gpt-4.1", apiVersion: "", icon: "simple-icons:openai" },
  { id: "azure", label: "Azure OpenAI", type: "azure_openai", baseUrl: "", model: "", apiVersion: "2025-01-01-preview", icon: "logos:microsoft-azure" },
  { id: "anthropic", label: "Anthropic Claude", type: "anthropic", baseUrl: "", model: "claude-sonnet-4-5", apiVersion: "", icon: "simple-icons:anthropic" },
  { id: "gemini", label: "Google Gemini", type: "gemini", baseUrl: "", model: "gemini-2.5-pro", apiVersion: "", icon: "logos:google-gemini" },
  { id: "custom", label: "Custom (OpenAI-compatible)", type: "openai_compatible", baseUrl: "", model: "", apiVersion: "", icon: "lucide:plug" },
];
const TYPE_LABEL: Record<ProviderType, string> = {
  openai_compatible: "OpenAI-compatible", azure_openai: "Azure OpenAI", anthropic: "Anthropic", gemini: "Google Gemini",
};

type Draft = ProviderFields & { api_key: string };
const emptyDraft = (p: Preset): Draft => ({
  name: p.id === "custom" ? "" : p.label, provider_type: p.type, base_url: p.baseUrl, model: p.model,
  api_version: p.apiVersion, api_key: "",
});
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

function StatusBadge({ p }: { p: LlmProvider }) {
  if (p.status === "ok")
    return <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">Connected{p.last_latency_ms != null ? ` · ${(p.last_latency_ms / 1000).toFixed(1)}s` : ""}</span>;
  if (p.status === "failed")
    return <span className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700">Failed</span>;
  return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">Not tested</span>;
}

function TestLine({ r }: { r: ProviderTestResult | null }) {
  if (!r) return null;
  return r.ok
    ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">Connected in {(r.latency_ms / 1000).toFixed(1)}s. The model replied “{r.reply || "(empty)"}”.</p>
    : <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 break-words">Connection failed: {r.error}</p>;
}

/** The provider form, for a new provider or an edit (a blank key keeps the saved one). Test runs one tiny real call. */
function ProviderForm({ orgId, editing, onDone, onCancel }:
  { orgId: number; editing: LlmProvider | null; onDone: () => void; onCancel: () => void }) {
  const [presetId, setPresetId] = useState(editing ? "" : "openai");
  const [draft, setDraft] = useState<Draft>(editing
    ? { name: editing.name, provider_type: editing.provider_type, base_url: editing.base_url, model: editing.model,
        api_version: editing.api_version, api_key: "" }
    : emptyDraft(PRESETS[0]));
  const [busy, setBusy] = useState<"" | "test" | "save">("");
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [error, setError] = useState("");
  const set = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setResult(null); };
  const fields: ProviderFields = { name: draft.name, provider_type: draft.provider_type, base_url: draft.base_url,
    model: draft.model, api_version: draft.api_version };
  const isAzure = draft.provider_type === "azure_openai";
  const urlOptional = draft.provider_type === "anthropic" || draft.provider_type === "gemini";
  const canSubmit = draft.name.trim() && draft.model.trim() && (urlOptional || draft.base_url.trim())
    && (editing || draft.api_key.trim());

  const test = async () => {
    setBusy("test"); setError("");
    try {
      setResult(await intelApi.testLlmProviderDraft({ ...fields, org_id: orgId, provider_id: editing?.id, api_key: draft.api_key }));
    } catch (e) { setError(errText(e, "Test failed")); } finally { setBusy(""); }
  };
  const save = async () => {
    setBusy("save"); setError("");
    try {
      if (editing) {
        await intelApi.updateLlmProvider(editing.id, { ...fields, api_key: draft.api_key });
      } else {
        await intelApi.createLlmProvider({ ...fields, org_id: orgId, api_key: draft.api_key });
      }
      onDone();
    } catch (e) { setError(errText(e, "Could not save the provider")); } finally { setBusy(""); }
  };

  const input = "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-[#5B2C9D] focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/15";
  return (
    <div className="space-y-4 rounded-xl border border-[#5B2C9D]/30 bg-[#5B2C9D]/[0.03] p-4">
      <div className="text-sm font-semibold text-slate-900">{editing ? `Edit ${editing.name}` : "Add a provider"}</div>
      {!editing && (
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Provider">
          {PRESETS.map((p) => (
            <button key={p.id} type="button" role="radio" aria-checked={presetId === p.id}
                    onClick={() => { setPresetId(p.id); setDraft(emptyDraft(p)); setResult(null); }}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                      presetId === p.id ? "border-[#5B2C9D] bg-white text-[#5B2C9D] shadow-sm" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}>
              <Icon icon={p.icon} width={14} aria-hidden /> {p.label}
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs font-medium text-slate-600">Display name
          <input className={input} value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. VyceAI gpt-6-luna" />
        </label>
        <label className="space-y-1 text-xs font-medium text-slate-600">{isAzure ? "Deployment name" : "Model name"}
          <input className={input} value={draft.model} onChange={(e) => set({ model: e.target.value })}
                 placeholder={isAzure ? "e.g. gpt-5" : "e.g. gpt-4.1"} />
        </label>
        <label className="space-y-1 text-xs font-medium text-slate-600 sm:col-span-2">
          {isAzure ? "Endpoint" : "Base URL"}{urlOptional && <span className="font-normal text-slate-400"> (optional: the provider's default)</span>}
          <input className={input} value={draft.base_url} onChange={(e) => set({ base_url: e.target.value })}
                 placeholder={isAzure ? "https://your-resource.openai.azure.com" : urlOptional ? "Leave blank for the official API" : "https://api.example.com/v1"} />
        </label>
        {isAzure && (
          <label className="space-y-1 text-xs font-medium text-slate-600">API version
            <input className={input} value={draft.api_version} onChange={(e) => set({ api_version: e.target.value })} />
          </label>
        )}
        <label className={`space-y-1 text-xs font-medium text-slate-600 ${isAzure ? "" : "sm:col-span-2"}`}>API key
          <input className={input} type="password" autoComplete="off" value={draft.api_key}
                 onChange={(e) => set({ api_key: e.target.value })}
                 placeholder={editing ? `Saved key ${editing.key_hint}: leave blank to keep it` : "Paste the key"} />
        </label>
      </div>
      {!editing && <p className="text-xs text-slate-500">Saved, it becomes this organization's model straight away: the newest provider always comes first.</p>}
      <TestLine r={result} />
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={test} disabled={!canSubmit || busy !== ""}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40">
          <Icon icon={busy === "test" ? "lucide:loader-2" : "lucide:plug-zap"} width={14} className={busy === "test" ? "animate-spin" : ""} aria-hidden />
          {busy === "test" ? "Testing…" : "Test connection"}
        </button>
        <button type="button" onClick={save} disabled={!canSubmit || busy !== ""}
                className="rounded-lg bg-[#5B2C9D] px-3 py-2 text-sm font-semibold text-white hover:bg-[#4a2380] disabled:opacity-40">
          {busy === "save" ? "Saving…" : editing ? "Save changes" : "Save provider"}
        </button>
        <button type="button" onClick={onCancel} className="px-2 py-2 text-sm text-slate-500 hover:text-slate-700">Cancel</button>
      </div>
    </div>
  );
}

/** The live outage (org_llm_state): which model is failing, what work runs on now, or that AI steps are paused. */
function OutageBanner({ outage, providers }: { outage: LlmOutage; providers: LlmProvider[] }) {
  const acting = providers.find((p) => p.id === outage.acting_provider_id);
  const since = new Date(outage.down_since * 1000).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const paused = Boolean(outage.paused);
  return (
    <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${paused ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      <div className="font-semibold">
        {paused ? `Every model is failing (since ${since}). AI steps are paused and retried every 5 minutes.`
          : acting ? `Your default model is failing (since ${since}). Work is running on ${acting.name} for now.`
          : `A model is failing (since ${since}).`}
      </div>
      {outage.last_error && <div className="mt-0.5 text-xs break-words opacity-90">Last error: {outage.last_error}</div>}
      <div className="mt-0.5 text-xs opacity-80">{outage.failed_calls} failed call{outage.failed_calls === 1 ? "" : "s"}. This clears by itself when the default model answers again.</div>
    </div>
  );
}

/** Settings → LLM Providers: an organization's own chat model (OpenAI, Azure OpenAI, Claude, Gemini or any
 * OpenAI-compatible server). The default provider carries every chat call of the org's projects; when it is down the
 * next one in the listed order takes over (providers/service.call), never the platform model; with none, the org uses
 * the platform model. Embeddings stay on the platform. */
export function ProvidersTab() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [orgs, setOrgs] = useState<AuthOrganizationRow[]>([]);
  const [orgId, setOrgId] = useState<number | undefined>(user?.org_id ?? undefined);
  const [data, setData] = useState<LlmProvidersResponse | null>(null);
  const [form, setForm] = useState<"closed" | "new" | LlmProvider>("closed");
  const [busy, setBusy] = useState<number | null>(null);
  const [tests, setTests] = useState<Record<number, ProviderTestResult>>({});
  const [error, setError] = useState("");
  const [prices, setPrices] = useState<UsagePrices | null>(null);
  const loadPrices = useCallback(() => { intelApi.usagePrices().then(setPrices).catch(() => setPrices(null)); }, []);
  useEffect(loadPrices, [loadPrices]);

  useEffect(() => {
    if (!isSuper) return;
    intelApi.listOrganizations().then((all) => {
      const live = all.filter((o) => !(o as { archived_at?: number | null }).archived_at);
      setOrgs(live);
      setOrgId((cur) => cur ?? live[0]?.id);
    }).catch(() => setOrgs([]));
  }, [isSuper]);

  const load = useCallback(() => {
    if (isSuper && !orgId) return;
    intelApi.listLlmProviders(orgId).then((d) => { setData(d); setError(""); })
      .catch((e) => setError(errText(e, "Could not load providers")));
  }, [isSuper, orgId]);
  useEffect(load, [load]);

  const act = async (id: number, fn: () => Promise<unknown>) => {
    setBusy(id); setError("");
    try { await fn(); load(); } catch (e) { setError(errText(e, "Action failed")); } finally { setBusy(null); }
  };
  const testSaved = (p: LlmProvider) => act(p.id, async () => {
    const r = await intelApi.testLlmProvider(p.id);
    setTests((t) => ({ ...t, [p.id]: r }));
  });
  const remove = (p: LlmProvider) => {
    if (!window.confirm(`Remove ${p.name}?${p.is_default ? " This organization goes back to the platform model." : ""}`)) return;
    act(p.id, () => intelApi.deleteLlmProvider(p.id));
  };

  const current = data?.providers.find((p) => p.is_default);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-xl text-sm text-slate-500">
          Connect this organization's own chat models. The default answers every chat call of the organization's
          projects; when it is down, the next model in this list takes over, in the order shown. When all are down,
          calls wait and resume as soon as one is back, and admins are emailed. Keys are encrypted and never shown
          again. Embeddings stay on the platform.
        </p>
        {isSuper && (
          <label className="text-xs font-medium text-slate-600">Organization
            <select value={orgId ?? ""} onChange={(e) => { setOrgId(Number(e.target.value)); setForm("closed"); setTests({}); }}
                    className="mt-1 block rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm">
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </label>
        )}
      </div>
      {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {!data ? <p className="text-sm text-slate-400">Loading…</p> : (
        <>
          <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${
            !current && !data.platform_llm ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50/60"}`}>
            <Icon icon={current ? PROVIDER_ICONS[current.provider_type] ?? "lucide:cpu" : data.platform_llm ? "logos:microsoft-azure" : "lucide:triangle-alert"}
                  width={22} aria-hidden className={!current && !data.platform_llm ? "text-amber-600" : ""} />
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-semibold text-slate-900">
                {current ? `${data.org_name} uses ${current.name} (${current.model})`
                  : data.platform_llm ? `${data.org_name} uses the platform model (${data.platform_model})`
                  : `${data.org_name} has no model yet`}
              </div>
              <div className="text-xs text-slate-600">
                {current ? `${TYPE_LABEL[current.provider_type]} · own key ${current.key_hint}`
                  : data.platform_llm ? "Azure OpenAI · billed to the platform"
                  : "Add a provider below. Until then every AI step of this organization's projects stops with this message."}
              </div>
              {!current && data.platform_llm && prices && data.platform_model !== "not configured" && (
                <ModelPrice provider="azure_openai" model={data.platform_model} prices={prices} canEdit onSaved={loadPrices} />
              )}
            </div>
            {current && data.platform_llm && (
              <button type="button" onClick={() => act(current.id, () => intelApi.usePlatformLlm(data.org_id))}
                      className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
                Use platform model
              </button>
            )}
          </div>

          {data.outage && <OutageBanner outage={data.outage} providers={data.providers} />}

          {data.providers.map((p) => (
            <div key={p.id} className={`rounded-xl border p-4 ${p.is_default ? "border-[#5B2C9D]/40" : "border-slate-200"}`}>
              <div className="flex flex-wrap items-center gap-3">
                <Icon icon={PROVIDER_ICONS[p.provider_type] ?? "lucide:cpu"} width={26} aria-hidden className="shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">{p.name}</span>
                    {p.is_default && <span className="rounded bg-[#5B2C9D]/10 px-1.5 py-0.5 text-[11px] font-semibold text-[#5B2C9D]">Default</span>}
                    <StatusBadge p={p} />
                  </div>
                  <div className="mt-0.5 truncate text-xs text-slate-500">
                    {TYPE_LABEL[p.provider_type]} · <span className="font-mono">{p.model}</span>
                    {p.base_url && <> · {p.base_url}</>} · key <span className="font-mono">{p.key_hint}</span>
                    {p.last_tested_at && <> · tested {formatRelativeOrDate(p.last_tested_at)}</>}
                  </div>
                  {p.status === "failed" && p.last_error && !tests[p.id] && <p className="mt-1 text-xs text-red-600 break-words">{p.last_error}</p>}
                  {prices && <ModelPrice provider={p.provider_type} model={p.model} prices={prices} canEdit onSaved={loadPrices} />}
                </div>
                <div className="flex shrink-0 flex-wrap gap-1.5">
                  <button type="button" onClick={() => testSaved(p)} disabled={busy === p.id}
                          className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                    {busy === p.id ? "Working…" : "Test connection"}
                  </button>
                  {!p.is_default && (
                    <button type="button" onClick={() => act(p.id, () => intelApi.setDefaultLlmProvider(p.id))} disabled={busy === p.id}
                            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                      Make default
                    </button>
                  )}
                  <button type="button" onClick={() => setForm(p)}
                          className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Edit</button>
                  <button type="button" onClick={() => remove(p)} disabled={busy === p.id}
                          className="rounded-lg px-2 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40">Remove</button>
                </div>
              </div>
              {tests[p.id] && <div className="mt-3"><TestLine r={tests[p.id]} /></div>}
              {typeof form === "object" && form.id === p.id && (
                <div className="mt-3">
                  <ProviderForm key={p.id} orgId={data.org_id} editing={p} onCancel={() => setForm("closed")}
                                onDone={() => { setForm("closed"); load(); }} />
                </div>
              )}
            </div>
          ))}

          {form === "new" ? (
            <ProviderForm orgId={data.org_id} editing={null} onCancel={() => setForm("closed")}
                          onDone={() => { setForm("closed"); load(); }} />
          ) : (
            <button type="button" onClick={() => setForm("new")}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:border-[#5B2C9D] hover:text-[#5B2C9D]">
              <Icon icon="lucide:plus" width={15} aria-hidden /> Add a provider
            </button>
          )}
        </>
      )}
    </div>
  );
}

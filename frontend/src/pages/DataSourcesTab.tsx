import { useEffect, useState } from "react";
import { intelApi, type DataSourceRecord } from "../services/intel-api";
import { BrandLogo } from "../components/BrandLogo";
import { formatRelativeOrDate } from "../utils/time";

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  expired: "bg-red-50 text-red-700",
  unverified: "bg-amber-50 text-amber-700",
  quota: "bg-amber-50 text-amber-700",
  not_configured: "bg-slate-100 text-slate-500",
};

const STATUS_LABEL: Record<string, string> = {
  ok: "OK",
  expired: "Invalid key",
  unverified: "Not verified yet",
  quota: "Out of credits",
  not_configured: "Not configured",
};

const DESCRIPTION: Record<string, string> = {
  tavily: "Web and news search for Background Research.",
  serpapi: "Google News and web results for Background Research.",
  firecrawl: "Optional extra web search for Background Research, run alongside the others. With full pages on, the "
    + "articles themselves are read for the summaries. Used only with your own key.",
};

type FirecrawlSettings = { enabled: boolean; max_results: number; full_content: boolean };

/** Admin tab (gated by SettingsPage) for this org's Tavily / SerpAPI / Firecrawl keys. Keys are stored encrypted and
 * shown masked (last 4 characters). Research uses an org's Tavily/SerpAPI key instead of the shared one, and Firecrawl
 * only when the org saved a key and switched it on — see domains/datasources/ and research/extra_sources.py. */
export function DataSourcesTab() {
  const [sources, setSources] = useState<DataSourceRecord[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = () => intelApi.listDataSources().then(setSources).catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  useEffect(() => { load(); }, []);

  const run = async (source: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(source); setError(""); setNotice("");
    try { await fn(); await load(); if (done) setNotice(done); }
    catch (e) { setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "Failed"); }
    finally { setBusy(null); }
  };

  const save = (s: DataSourceRecord) => {
    const apiKey = drafts[s.source]?.trim();
    if (!apiKey) return;
    run(s.source, async () => {
      await intelApi.setDataSourceKey(s.source, apiKey);
      setDrafts((d) => ({ ...d, [s.source]: "" }));
    }, `${s.display_name} key saved.`);
  };

  const test = (s: DataSourceRecord) => run(s.source, async () => {
    const r = await intelApi.validateDataSource(s.source);
    setNotice(r.status === "ok" ? `${s.display_name}: connection works.` : `${s.display_name}: ${r.error ?? STATUS_LABEL[r.status]}`);
  });

  const remove = (s: DataSourceRecord) => {
    if (!window.confirm(`Remove your ${s.display_name} key?${s.source === "firecrawl" ? " Research stops using Firecrawl." : " Research goes back to the shared key."}`)) return;
    run(s.source, () => intelApi.removeDataSource(s.source), `${s.display_name} key removed.`);
  };

  const setOption = (s: DataSourceRecord, patch: Partial<FirecrawlSettings>) => {
    const next = { enabled: true, max_results: 5, full_content: true, ...(s.settings ?? {}), ...patch };
    run(s.source, () => intelApi.setDataSourceSettings(s.source, next));
  };

  if (!sources) return <p className="text-sm text-slate-400">Loading…</p>;

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">
        Your organization's own search keys for Background Research. Keys are stored encrypted and only their last
        4 characters are shown. Each key is checked when it is entered, used by a research run, or tested here.
      </p>
      {error && <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {notice && <div role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</div>}
      {sources.map((s) => (
        <div key={s.source} className="rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <BrandLogo brandName={s.display_name} size={28} rounded="lg" className="shrink-0 bg-white ring-1 ring-slate-200" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">{s.display_name}</span>
                <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${STATUS_STYLE[s.status] ?? STATUS_STYLE.not_configured}`}>
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
              </div>
              <div className="text-xs text-slate-500 mt-0.5">{DESCRIPTION[s.source]}</div>
              {s.configured ? (
                <div className="text-xs text-slate-500 mt-0.5">
                  Key: <span className="font-mono">{s.masked_key}</span>
                  {s.status === "expired" && s.expired_at && <span className="text-red-600"> — rejected {formatRelativeOrDate(s.expired_at)}</span>}
                  {s.last_error && s.status !== "ok" && <span className="block text-amber-700">{s.last_error}</span>}
                </div>
              ) : (
                <div className="text-xs text-slate-400 mt-0.5">
                  {s.source === "firecrawl" ? "Not configured — research runs without Firecrawl." : "Not configured — using the shared default key, if any."}
                </div>
              )}
            </div>
            {s.configured && (
              <div className="flex shrink-0 gap-1.5">
                <button onClick={() => test(s)} disabled={busy === s.source}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                  {busy === s.source ? "Working…" : "Test connection"}
                </button>
                <button onClick={() => remove(s)} disabled={busy === s.source}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40">Remove key</button>
              </div>
            )}
          </div>

          {s.source === "firecrawl" && s.configured && s.settings && (
            <div className="mt-3 flex flex-wrap items-center gap-5 rounded-lg bg-slate-50 px-3 py-2.5 text-sm text-slate-700">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={s.settings.enabled} disabled={busy === s.source}
                  onChange={(e) => setOption(s, { enabled: e.target.checked })} />
                Use in research
              </label>
              <label className="flex items-center gap-2">
                Results per search
                <select value={s.settings.max_results} disabled={busy === s.source}
                  onChange={(e) => setOption(s, { max_results: Number(e.target.value) })}
                  className="rounded border border-slate-200 bg-white px-2 py-1 text-sm">
                  {[3, 5, 10, 15, 20].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-2" title="Reads each result page (main content only) so summaries use the article, not a snippet. Uses more Firecrawl credits.">
                <input type="checkbox" checked={s.settings.full_content} disabled={busy === s.source}
                  onChange={(e) => setOption(s, { full_content: e.target.checked })} />
                Fetch full page content
              </label>
            </div>
          )}

          <div className="mt-3 flex items-center gap-2">
            <input type="password" autoComplete="off" value={drafts[s.source] ?? ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [s.source]: e.target.value }))}
              placeholder={s.configured ? `Replace ${s.display_name} API key` : `${s.display_name} API key`}
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm" />
            <button onClick={() => save(s)} disabled={busy === s.source || !drafts[s.source]?.trim()}
              className="rounded-lg bg-[#5B2C9D] px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Save</button>
          </div>
        </div>
      ))}
    </div>
  );
}

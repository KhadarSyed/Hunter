import { useEffect, useState } from "react";
import { intelApi, type DataSourceRecord } from "../services/intel-api";
import { BrandLogo } from "../components/BrandLogo";
import { formatRelativeOrDate } from "../utils/time";

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  expired: "bg-red-50 text-red-700",
  not_configured: "bg-slate-100 text-slate-500",
};

const STATUS_LABEL: Record<string, string> = {
  ok: "OK",
  expired: "Expired",
  not_configured: "Not configured",
};

/** Admin/Super Admin tab (gated by SettingsPage) for entering and validating this org's
 * Tavily/SerpAPI keys. The research pipeline uses these keys when configured (falling back
 * to the server's global keys otherwise) and reactively flips status to "expired" the first
 * time a real call gets an auth error — see domains/datasources/ and NotificationBell.tsx. */
export function DataSourcesTab() {
  const [sources, setSources] = useState<DataSourceRecord[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = () => intelApi.listDataSources().then(setSources).catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  useEffect(() => { load(); }, []);

  const handleSave = async (source: string) => {
    const apiKey = drafts[source]?.trim();
    if (!apiKey) return;
    setBusy(source);
    setError("");
    try {
      await intelApi.setDataSourceKey(source, apiKey);
      setDrafts((d) => ({ ...d, [source]: "" }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save key");
    } finally {
      setBusy(null);
    }
  };

  const handleValidate = async (source: string) => {
    setBusy(source);
    setError("");
    try {
      await intelApi.validateDataSource(source);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setBusy(null);
    }
  };

  if (!sources) return <p className="text-sm text-slate-400">Loading…</p>;

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">
        Enter your organization's own Tavily and SerpAPI keys so Background Research uses
        them instead of the shared default. Each key is validated with a live call whenever
        it's entered, used by a research run, or checked with "Validate now".
      </p>
      {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {sources.map((s) => (
        <div key={s.source} className="rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-3">
            <BrandLogo brandName={s.display_name} size={28} rounded="lg" className="shrink-0 bg-white ring-1 ring-slate-200" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">{s.display_name}</span>
                <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${STATUS_STYLE[s.status]}`}>
                  {STATUS_LABEL[s.status]}
                </span>
              </div>
              {s.configured ? (
                <div className="text-xs text-slate-500 mt-0.5">
                  Key: <span className="font-mono">{s.masked_key}</span>
                  {s.status === "expired" && s.expired_at && (
                    <span className="text-red-600"> — expired {formatRelativeOrDate(s.expired_at)}</span>
                  )}
                </div>
              ) : (
                <div className="text-xs text-slate-400 mt-0.5">Not configured — using the shared default key, if any.</div>
              )}
            </div>
            {s.configured && (
              <button
                onClick={() => handleValidate(s.source)}
                disabled={busy === s.source}
                className="shrink-0 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                {busy === s.source ? "Validating…" : "Validate now"}
              </button>
            )}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <input
              type="password"
              value={drafts[s.source] ?? ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [s.source]: e.target.value }))}
              placeholder={`${s.display_name} API key`}
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
            <button
              onClick={() => handleSave(s.source)}
              disabled={busy === s.source || !drafts[s.source]?.trim()}
              className="rounded-lg bg-[#5B2C9D] px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
            >
              Save
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

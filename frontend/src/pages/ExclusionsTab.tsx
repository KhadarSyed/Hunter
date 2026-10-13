import { useEffect, useState } from "react";
import { intelApi, type ExclusionKind, type ExclusionRecord } from "../services/intel-api";

const KIND_LABEL: Record<ExclusionKind, string> = { domain: "Website / domain", keyword: "Keyword" };
const PLACEHOLDER: Record<ExclusionKind, string> = { domain: "e.g. dealmoon.com", keyword: "e.g. giveaway" };

/** Admin / Analyser / Super Admin tab (gated by SettingsPage): this organization's excluded websites and keywords.
 * Articles from an excluded site (and its subdomains), or naming an excluded keyword as a whole word, are dropped
 * from web research and datasets, so they never reach a chart, insight, verbatim, deck or report — see
 * backend/domains/exclusions/. */
export function ExclusionsTab() {
  const [rows, setRows] = useState<ExclusionRecord[] | null>(null);
  const [kind, setKind] = useState<ExclusionKind>("domain");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    intelApi.listExclusions().then(setRows).catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  useEffect(() => { load(); }, []);

  const add = async () => {
    const v = value.trim();
    if (!v) return;
    setBusy(true);
    setError("");
    try {
      await intelApi.addExclusion(kind, v);
      setValue("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "Could not add");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    setError("");
    try {
      await intelApi.deleteExclusion(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove");
    }
  };

  const groups: ExclusionKind[] = ["domain", "keyword"];
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-900">Exclusions</h2>
      <p className="mt-1 text-sm text-slate-500">
        Articles and posts from these websites, or that mention these keywords, are left out of web research and
        uploaded datasets — and so out of every chart, insight, presentation and report. Applies to your whole
        organization from the next run.
      </p>

      <div className="mt-5 flex flex-wrap items-end gap-2">
        <label className="text-xs font-medium text-slate-600">
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as ExclusionKind)}
            className="mt-1 block rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800">
            {groups.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
        </label>
        <label className="flex-1 min-w-[220px] text-xs font-medium text-slate-600">
          {KIND_LABEL[kind]}
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={PLACEHOLDER[kind]}
            onKeyDown={(e) => { if (e.key === "Enter") add(); }} maxLength={200}
            className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800" />
        </label>
        <button onClick={add} disabled={busy || !value.trim()}
          className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Adding…" : "Add"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {rows === null ? (
        <p className="mt-6 text-sm text-slate-400">Loading…</p>
      ) : (
        <div className="mt-6 grid gap-6 sm:grid-cols-2">
          {groups.map((k) => {
            const list = rows.filter((r) => r.kind === k);
            return (
              <div key={k}>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {KIND_LABEL[k]}s · {list.length}
                </div>
                {list.length === 0 ? (
                  <p className="mt-2 text-sm text-slate-400">None excluded</p>
                ) : (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {list.map((r) => (
                      <li key={r.id} className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 py-1 pl-3 pr-1.5 text-sm text-slate-700">
                        {r.value}
                        <button onClick={() => remove(r.id)} aria-label={`Remove ${r.value}`}
                          className="flex h-5 w-5 items-center justify-center rounded-full text-slate-400 hover:bg-slate-200 hover:text-slate-700">
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

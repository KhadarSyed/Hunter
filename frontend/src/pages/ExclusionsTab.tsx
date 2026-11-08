import { useEffect, useRef, useState } from "react";
import { intelApi, type ExclusionImportResult, type ExclusionKind, type ExclusionRecord } from "../services/intel-api";

const KIND_LABEL: Record<ExclusionKind, string> = { domain: "Website / domain", keyword: "Keyword" };
const PLACEHOLDER: Record<ExclusionKind, string> = {
  domain: "dealmoon.com, slickdeals.net, …",
  keyword: "giveaway, sponsored, promo code, …",
};
const SEPARATED = /[,;\n\t]/;
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : fallback);

/** Admin / Analyser / Super Admin tab (gated by SettingsPage): this organization's excluded websites and keywords.
 * Articles from an excluded site (and its subdomains), or naming an excluded keyword as a whole word, are dropped
 * from web research and datasets, so they never reach a chart, insight, verbatim, deck or report — see
 * backend/domains/exclusions/. A whole block list can be pasted (comma / new-line separated) or uploaded as an
 * .xlsx, .csv, .txt or .json file. */
export function ExclusionsTab() {
  const [rows, setRows] = useState<ExclusionRecord[] | null>(null);
  const [kind, setKind] = useState<ExclusionKind>("domain");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<(ExclusionImportResult & { source: string }) | null>(null);
  const [filter, setFilter] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () =>
    intelApi.listExclusions().then(setRows).catch((e) => setError(errText(e, "Failed to load")));
  useEffect(() => { load(); }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setReport(null);
    try { await fn(); await load(); } catch (e) { setError(errText(e, "Could not add")); } finally { setBusy(false); }
  };

  const add = () => {
    const v = value.trim();
    if (!v) return;
    run(async () => {
      if (SEPARATED.test(v)) setReport({ ...(await intelApi.bulkExclusions(kind, v)), source: "pasted list" });
      else await intelApi.addExclusion(kind, v);
      setValue("");
    });
  };

  const upload = (file: File | undefined) => {
    if (!file) return;
    run(async () => setReport({ ...(await intelApi.importExclusions(kind, file)), source: file.name }));
    if (fileRef.current) fileRef.current.value = "";
  };

  const remove = async (id: number) => {
    setError("");
    try { await intelApi.deleteExclusion(id); await load(); } catch (e) { setError(errText(e, "Could not remove")); }
  };

  const groups: ExclusionKind[] = ["domain", "keyword"];
  const q = filter.trim().toLowerCase();
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
        <label className="flex-1 min-w-[260px] text-xs font-medium text-slate-600">
          {KIND_LABEL[kind]}
          <textarea value={value} onChange={(e) => setValue(e.target.value)} placeholder={PLACEHOLDER[kind]} rows={value.includes("\n") ? 4 : 1}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !value.includes("\n")) { e.preventDefault(); add(); } }}
            className="mt-1 block w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800" />
        </label>
        <button onClick={add} disabled={busy || !value.trim()}
          className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Adding…" : SEPARATED.test(value) ? "Add all" : "Add"}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy}
          className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
          Upload list
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv,.txt,.json" className="sr-only"
               onChange={(e) => upload(e.target.files?.[0])} aria-label="Upload an exclusion list" />
      </div>
      <p className="mt-1.5 text-xs text-slate-400">
        Paste many separated by commas, semicolons or new lines, or upload an Excel (.xlsx), CSV, text or JSON file —
        every cell is read, full URLs become domains (https://www.site.com/page → site.com) and duplicates are skipped.
      </p>
      {error && <p className="mt-2 text-sm text-red-600" role="alert">{error}</p>}
      {report && (
        <div role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          From {report.source}: <b>{report.added}</b> added, {report.duplicates} already in the list
          {report.invalid_count > 0 && <>, {report.invalid_count} not valid ({report.invalid.slice(0, 5).join(", ")}{report.invalid_count > 5 ? "…" : ""})</>}.
          {" "}{report.total} {kind === "domain" ? "websites" : "keywords"} excluded now.
        </div>
      )}

      {rows === null ? (
        <p className="mt-6 text-sm text-slate-400">Loading…</p>
      ) : (
        <>
          {rows.length > 20 && (
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search exclusions"
                   aria-label="Search exclusions" className="mt-6 w-full max-w-xs rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
          )}
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            {groups.map((k) => {
              const all = rows.filter((r) => r.kind === k);
              const list = q ? all.filter((r) => r.value.toLowerCase().includes(q)) : all;
              return (
                <div key={k}>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {KIND_LABEL[k]}s · {all.length}{q && ` (${list.length} shown)`}
                  </div>
                  {list.length === 0 ? (
                    <p className="mt-2 text-sm text-slate-400">{q ? "No match" : "None excluded"}</p>
                  ) : (
                    <ul className="mt-2 flex max-h-80 flex-wrap gap-2 overflow-y-auto">
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
        </>
      )}
    </div>
  );
}

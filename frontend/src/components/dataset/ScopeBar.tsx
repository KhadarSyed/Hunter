import { useEffect, useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { DataSetScope } from "../../types/dataset";
import { DateRangePicker } from "./DateRangePicker";

/** The scope filter applied after upload and before matching / tagging: the outlet's country and a date range
 * (default: the uploaded data's own range). Applying re-matches for free; articles outside go to Out of scope. */
export function ScopeBar({ projectId, refreshKey, disabled, onChanged }: {
  projectId: number; refreshKey: number; disabled?: boolean; onChanged: (outOfScope: number) => void;
}) {
  const [scope, setScope] = useState<DataSetScope | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let stale = false;
    intelApi.dataSetScope(projectId).then((s) => { if (!stale) setScope(s); }).catch(() => { /* the bar stays hidden */ });
    return () => { stale = true; };
  }, [projectId, refreshKey]);

  if (!scope || !scope.data_from) return null;
  const apply = async (country: string, from: string, to: string) => {
    setSaving(true);
    setError("");
    try {
      const r = await intelApi.setDataSetScope(projectId, country, from, to);
      setScope(r.scope);
      onChanged(r.out_of_scope);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not apply the scope filter"); }
    finally { setSaving(false); }
  };
  const countries = [...new Set([scope.country, ...scope.countries].filter(Boolean))];

  return (
    <div role="group" aria-label="Scope filter" className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Scope filter</span>
      <label className="flex items-center gap-2 text-xs font-semibold text-slate-500">Country
        <select value={scope.country} disabled={disabled || saving} onChange={(e) => void apply(e.target.value, scope.from, scope.to)}
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-normal text-slate-700">
          <option value="">All countries</option>
          {countries.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <span className="flex items-center gap-2 text-xs font-semibold text-slate-500">Date range
        <DateRangePicker from={scope.from} to={scope.to} min={scope.data_from} max={scope.data_to}
          onApply={(from, to) => void apply(scope.country, from, to)} />
      </span>
      <span className="text-xs text-slate-500">
        {saving ? "Applying…" : "Default: the uploaded data's own dates. Articles with no country or date are kept; the rest go to Out of scope and are not tagged."}
      </span>
      {error && <span role="alert" className="text-xs text-red-600">{error}</span>}
    </div>
  );
}

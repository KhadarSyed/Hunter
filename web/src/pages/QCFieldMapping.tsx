import { useState, useEffect } from "react";
import { useActiveProjectId } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

const QC_FIELDS = [
  { key: "headline", label: "Headline", required: true },
  { key: "url", label: "URL / Link", required: true },
  { key: "date", label: "Publication Date", required: true },
  { key: "source", label: "Source / Publisher", required: true },
  { key: "summary", label: "Summary / Snippet", required: false },
  { key: "sentiment", label: "Sentiment", required: false },
  { key: "reach", label: "Reach / Impressions", required: false },
  { key: "author", label: "Author", required: false },
  { key: "media_type", label: "Media Type", required: false },
  { key: "engagement", label: "Engagement", required: false },
  { key: "geography", label: "Geography", required: false },
  { key: "language", label: "Language", required: false },
];

interface Report {
  id: number;
  file_name: string;
  row_count: number;
  column_count: number;
  columns_json: string[] | null;
  field_mapping: Record<string, string> | null;
  parse_status: string;
}

export function QCFieldMapping({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState<Record<string, string>[]>([]);

  useEffect(() => {
    if (!projectId) { setLoading(false); return; }
    intelApi.qcGetReport(projectId)
      .then((r) => {
        const rep = r as unknown as Report;
        setReport(rep);
        if (rep.field_mapping) {
          setMapping(rep.field_mapping);
        }
        return intelApi.qcGetPreview(rep.id);
      })
      .then((p) => setPreview(p.preview || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  const handleMapField = (reportColumn: string, qcField: string) => {
    setMapping((prev) => {
      const next = { ...prev };
      for (const [col, field] of Object.entries(next)) {
        if (field === qcField) delete next[col];
      }
      if (qcField) {
        next[reportColumn] = qcField;
      } else {
        delete next[reportColumn];
      }
      return next;
    });
    setSaved(false);
  };

  const handleSave = async () => {
    if (!report) return;
    setSaving(true);
    try {
      await intelApi.qcSaveFieldMapping(report.id, mapping);
      setSaved(true);
      onNavigate("qc-results");
    } catch { /* ignore */ }
    setSaving(false);
  };

  const reverseMapping = Object.fromEntries(
    Object.entries(mapping).map(([col, field]) => [field, col])
  );

  if (!projectId) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700">
          No project selected.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 max-w-4xl mx-auto animate-fade-in">
        <div className="text-sm text-slate-400 py-8 text-center">Loading report...</div>
      </div>
    );
  }

  if (!report || report.parse_status !== "done") {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in space-y-4">
        <h1 className="text-xl font-semibold text-slate-900">Field Mapping</h1>
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700">
          No parsed report available.{" "}
          <button onClick={() => onNavigate("qc-upload")} className="underline font-medium">
            Upload a report
          </button>{" "}
          first.
        </div>
      </div>
    );
  }

  const columns = report.columns_json || [];

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Field Mapping</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {report.file_name} -- {report.row_count} rows, {report.column_count} columns
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && <span className="text-xs text-emerald-600 font-medium">Saved</span>}
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-50"
            style={{ backgroundColor: "#0F7B6C" }}
          >
            {saving ? "Saving..." : "Save Mapping"}
          </button>
        </div>
      </div>

      {/* Mapping Table */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center px-5 py-3 bg-slate-50 border-b border-slate-200 text-xs font-medium text-slate-400 uppercase tracking-wider">
          <span>Report Column</span>
          <span className="px-4">Maps To</span>
          <span>QC Field</span>
        </div>
        <div className="divide-y divide-slate-100">
          {columns.map((col) => (
            <div key={col} className="grid grid-cols-[1fr_auto_1fr] items-center px-5 py-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-900 font-medium">{col}</span>
                {preview[0] && preview[0][col] && (
                  <span className="text-[11px] text-slate-400 truncate max-w-[180px]" title={preview[0][col]}>
                    e.g. {preview[0][col]}
                  </span>
                )}
              </div>
              <svg className="mx-4 text-slate-300" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
              <select
                value={mapping[col] || ""}
                onChange={(e) => handleMapField(col, e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400 transition-all"
              >
                <option value="">-- Not mapped --</option>
                {QC_FIELDS.map((f) => (
                  <option key={f.key} value={f.key} disabled={reverseMapping[f.key] !== undefined && reverseMapping[f.key] !== col}>
                    {f.label}{f.required ? " *" : ""}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* Coverage summary */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-3">
          Field Coverage
        </h3>
        <div className="flex flex-wrap gap-2">
          {QC_FIELDS.map((f) => {
            const mapped = !!reverseMapping[f.key];
            return (
              <span
                key={f.key}
                className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                  mapped
                    ? "bg-emerald-50 text-emerald-700"
                    : f.required
                      ? "bg-red-50 text-red-600"
                      : "bg-slate-100 text-slate-400"
                }`}
              >
                {mapped ? "✓" : f.required ? "!" : "-"} {f.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* Preview table */}
      {preview.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-3">
            Data Preview (first {Math.min(preview.length, 5)} rows)
          </h3>
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  {columns.slice(0, 8).map((col) => (
                    <th key={col} className="px-3 py-2 text-left font-medium text-slate-500 whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {preview.slice(0, 5).map((row, i) => (
                  <tr key={i}>
                    {columns.slice(0, 8).map((col) => (
                      <td key={col} className="px-3 py-2 text-slate-700 whitespace-nowrap max-w-[200px] truncate">
                        {row[col] || "-"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { useActiveProjectId } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

interface QCRun {
  id: number;
  status: string;
  total_findings: number;
  score: number | null;
}

export function QCExport({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId();
  const [latestRun, setLatestRun] = useState<QCRun | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<{ export_id: number; file_name: string } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) { setLoading(false); return; }
    (async () => {
      try {
        const report = await intelApi.qcGetReport(projectId) as { id: number };
        const runs = await intelApi.qcGetRuns(report.id) as unknown as QCRun[];
        const completed = runs.find((r) => r.status === "completed");
        if (completed) setLatestRun(completed);
      } catch { /* no report or runs */ }
      setLoading(false);
    })();
  }, [projectId]);

  const handleExport = async () => {
    if (!latestRun) return;
    setExporting(true);
    setError("");
    try {
      const result = await intelApi.qcExport(latestRun.id);
      setExportResult(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
    setExporting(false);
  };

  const handleDownload = () => {
    if (!exportResult) return;
    const url = intelApi.qcExportDownloadUrl(exportResult.export_id);
    window.open(url, "_blank");
  };

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
    return <div className="p-8 text-sm text-slate-400 text-center">Loading...</div>;
  }

  return (
    <div className="px-8 py-6 max-w-3xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Export QC Report</h1>
        <p className="text-sm text-slate-500 mt-0.5">Generate an annotated Excel file with QC findings</p>
      </div>

      {!latestRun && (
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <p className="text-sm text-slate-500">
            No completed QC run found.{" "}
            <button onClick={() => onNavigate("qc-results")} className="text-emerald-600 underline font-medium">
              Run quality checks first
            </button>
          </p>
        </div>
      )}

      {latestRun && !exportResult && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: "#0F7B6C15" }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-slate-900">Ready to export</p>
              <p className="text-xs text-slate-500">
                {latestRun.total_findings} findings &middot; Score: {latestRun.score ?? "N/A"}/100
              </p>
            </div>
          </div>

          <p className="text-xs text-slate-500">
            The export includes the original monitoring data with QC annotations: per-row score, severity,
            issues found, and details. A summary sheet is also included.
          </p>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-600">{error}</div>
          )}

          <button
            onClick={handleExport}
            disabled={exporting}
            className="w-full px-4 py-2.5 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-50"
            style={{ backgroundColor: "#0F7B6C" }}
          >
            {exporting ? "Generating..." : "Generate Excel Export"}
          </button>
        </div>
      )}

      {exportResult && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-emerald-50 flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-slate-900">Export ready</p>
              <p className="text-xs text-slate-500">{exportResult.file_name}</p>
            </div>
          </div>

          <button
            onClick={handleDownload}
            className="w-full px-4 py-2.5 text-sm font-medium text-white rounded-lg transition-colors"
            style={{ backgroundColor: "#0F7B6C" }}
          >
            Download Excel File
          </button>

          <button
            onClick={() => setExportResult(null)}
            className="w-full px-4 py-2 text-sm font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            Generate Another
          </button>
        </div>
      )}
    </div>
  );
}

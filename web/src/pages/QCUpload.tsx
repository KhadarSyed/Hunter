import { useState, useEffect, useCallback } from "react";
import { useActiveProjectId } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

interface QCReport {
  id: number;
  file_name: string;
  row_count: number;
  column_count: number;
  columns_json: string[] | null;
  field_mapping: Record<string, string> | null;
  parse_status: string;
  parse_error: string | null;
}

export function QCUpload({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId();
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState("");
  const [report, setReport] = useState<QCReport | null>(null);
  const [loadingReport, setLoadingReport] = useState(true);

  useEffect(() => {
    if (!projectId) { setLoadingReport(false); return; }
    intelApi.qcGetReport(projectId)
      .then((r) => setReport(r as unknown as QCReport))
      .catch(() => {})
      .finally(() => setLoadingReport(false));
  }, [projectId]);

  useEffect(() => {
    if (!report || report.parse_status !== "parsing") return;
    const interval = setInterval(async () => {
      try {
        const updated = await intelApi.qcGetReportDetail(report.id) as unknown as QCReport;
        setReport(updated);
        if (updated.parse_status !== "parsing") clearInterval(interval);
      } catch { /* ignore */ }
    }, 1500);
    return () => clearInterval(interval);
  }, [report]);

  const handleFile = useCallback(
    async (file: File) => {
      if (!projectId) {
        setError("No project selected.");
        return;
      }
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!ext || !["csv", "xlsx", "xls", "docx", "pptx"].includes(ext)) {
        setError("Supported formats: CSV, Excel (.xlsx, .xls), Word (.docx), PowerPoint (.pptx)");
        return;
      }
      setError("");
      setFileName(file.name);
      setUploading(true);

      try {
        const formData = new FormData();
        formData.append("project_id", String(projectId));
        formData.append("file", file);

        const res = await fetch("/api/intel/qc/upload", {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          const text = await res.text().catch(() => res.statusText);
          throw new Error(text);
        }

        const result = await res.json();
        if (result.parse_status === "done") {
          const detail = await intelApi.qcGetReportDetail(result.report_id) as unknown as QCReport;
          setReport(detail);
        } else if (result.parse_status === "error") {
          setReport({
            id: result.report_id,
            file_name: result.file_name,
            row_count: 0,
            column_count: 0,
            columns_json: null,
            field_mapping: null,
            parse_status: "error",
            parse_error: result.parse_error || "Parse failed",
          });
        } else {
          setReport({
            id: result.report_id,
            file_name: result.file_name,
            row_count: 0,
            column_count: 0,
            columns_json: null,
            field_mapping: null,
            parse_status: "parsing",
            parse_error: null,
          });
        }
        setUploading(false);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Upload failed");
        setUploading(false);
      }
    },
    [projectId]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  if (!projectId) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700">
          No project selected. <button onClick={() => onNavigate("new-project")} className="underline font-medium">Create a QC project</button> first.
        </div>
      </div>
    );
  }

  if (loadingReport) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <div className="text-sm text-slate-400 py-8 text-center">Loading...</div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Upload Monitoring Report</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Upload your media monitoring export for quality checking
        </p>
      </div>

      {/* Existing report info */}
      {report && report.parse_status === "done" && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: "#0F7B6C1A" }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <path d="M14 2v6h6" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-900">{report.file_name}</p>
                <p className="text-xs text-slate-400">
                  {report.row_count} rows, {report.column_count} columns
                  {report.field_mapping && ` -- ${Object.keys(report.field_mapping).length} fields mapped`}
                </p>
              </div>
            </div>
            <button
              onClick={async () => {
                if (report) {
                  try { await intelApi.qcStartRun(report.id); } catch { /* ignore */ }
                }
                onNavigate("qc-results");
              }}
              className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors"
              style={{ backgroundColor: "#0F7B6C" }}
            >
              Run QC
            </button>
          </div>
        </div>
      )}

      {report && report.parse_status === "parsing" && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 flex items-center gap-3">
          <svg className="animate-spin h-4 w-4 shrink-0" style={{ color: "#0F7B6C" }} viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm font-medium" style={{ color: "#0F7B6C" }}>Parsing {report.file_name}...</span>
        </div>
      )}

      {report && report.parse_status === "error" && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          Parse failed: {report.parse_error}
        </div>
      )}

      {/* Upload area */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`bg-white border-2 border-dashed rounded-xl p-12 text-center transition-all cursor-pointer ${
          dragOver
            ? "border-[#0F7B6C] bg-[#0F7B6C]/5"
            : "border-slate-200 hover:border-[#0F7B6C]/40 hover:bg-[#0F7B6C]/[0.02]"
        }`}
        onClick={() => document.getElementById("qc-file-input")?.click()}
      >
        <input
          id="qc-file-input"
          type="file"
          accept=".csv,.xlsx,.xls,.docx,.pptx"
          className="hidden"
          onChange={onFileSelect}
        />

        {uploading ? (
          <div className="space-y-3">
            <svg className="animate-spin h-8 w-8 mx-auto" style={{ color: "#0F7B6C" }} viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-sm font-medium text-slate-700">Uploading {fileName}...</p>
          </div>
        ) : (
          <div className="space-y-3">
            <svg className="mx-auto" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <div>
              <p className="text-sm font-medium text-slate-700">
                {report ? "Upload a new report to replace" : "Drop your monitoring report here"}
              </p>
              <p className="text-xs text-slate-400 mt-1">
                CSV, Excel, Word, or PowerPoint -- Meltwater, Cision, or custom exports
              </p>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-3">
          Expected Columns
        </h3>
        <div className="grid grid-cols-3 gap-2 text-xs text-slate-600">
          {[
            "Headline",
            "URL / Link",
            "Publication Date",
            "Source / Publisher",
            "Summary / Snippet",
            "Sentiment",
            "Reach / Impressions",
            "Author",
            "Media Type",
          ].map((col) => (
            <div key={col} className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "#0F7B6C" }} />
              {col}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

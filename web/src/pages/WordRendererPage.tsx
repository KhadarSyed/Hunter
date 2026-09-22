import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";
import type {
  PCPresentation,
  WordRenderResult,
  WordRenderJob,
  WordRenderSummary,
  WordRenderMetric,
  WordRenderHistory,
  WordValidation,
  RenderTheme,
} from "../data/contracts";

interface Props {
  onNavigate: (page: string) => void;
}

const SECTION_NAMES = [
  "cover", "confidentiality", "executive_summary", "methodology",
  "key_findings", "supporting_evidence", "business_impact",
  "recommendations", "conclusion", "appendix",
];

const SECTION_LABELS: Record<string, string> = {
  cover: "Cover Page",
  confidentiality: "Confidentiality Notice",
  executive_summary: "Executive Summary",
  methodology: "Methodology",
  key_findings: "Key Findings",
  supporting_evidence: "Sources & Evidence",
  business_impact: "Business Impact",
  recommendations: "Recommendations",
  conclusion: "Conclusion",
  appendix: "Appendix",
};

export function WordRendererPage({ onNavigate }: Props) {
  const projectId = useActiveProjectId() ?? 1;
  const [presentations, setPresentations] = useState<PCPresentation[]>([]);
  const [selectedPresId, setSelectedPresId] = useState<number | null>(null);
  const [summary, setSummary] = useState<WordRenderSummary | null>(null);
  const [themes, setThemes] = useState<RenderTheme[]>([]);
  const [selectedTheme, setSelectedTheme] = useState("hunter_default");
  const [validation, setValidation] = useState<WordValidation | null>(null);
  const [renderResult, setRenderResult] = useState<WordRenderResult | null>(null);
  const [rendering, setRendering] = useState(false);
  const [metrics, setMetrics] = useState<WordRenderMetric[]>([]);
  const [history, setHistory] = useState<WordRenderHistory[]>([]);
  const [jobs, setJobs] = useState<WordRenderJob[]>([]);
  const [activeTab, setActiveTab] = useState<"sections" | "metrics" | "history" | "jobs">("sections");
  const [error, setError] = useState("");

  const loadPresentations = useCallback(async () => {
    try {
      const list = await intelApi.composerList(projectId);
      setPresentations(list);
      const approved = list.find((p) => p.status === "approved");
      if (approved) setSelectedPresId(approved.id);
      else if (list.length > 0) setSelectedPresId(list[0].id);
    } catch {
      setPresentations([]);
    }
  }, [projectId]);

  const loadSummary = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      setSummary(await intelApi.wordRenderSummary(selectedPresId));
    } catch {
      setSummary(null);
    }
  }, [selectedPresId]);

  const loadThemes = useCallback(async () => {
    try {
      setThemes(await intelApi.wordThemes());
    } catch {
      setThemes([]);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      setHistory(await intelApi.wordHistory(selectedPresId));
    } catch {
      setHistory([]);
    }
  }, [selectedPresId]);

  const loadJobs = useCallback(async () => {
    if (!selectedPresId) return;
    try {
      setJobs(await intelApi.wordJobs(selectedPresId));
    } catch {
      setJobs([]);
    }
  }, [selectedPresId]);

  useEffect(() => { loadPresentations(); }, [loadPresentations]);
  useEffect(() => { loadThemes(); }, [loadThemes]);
  useEffect(() => {
    if (selectedPresId) {
      loadSummary();
      loadHistory();
      loadJobs();
    }
  }, [selectedPresId, loadSummary, loadHistory, loadJobs]);

  const handleValidate = async () => {
    if (!selectedPresId) return;
    setError("");
    try {
      const v = await intelApi.wordValidate(selectedPresId);
      setValidation(v);
    } catch (e: any) {
      setError(e.message || "Validation failed");
    }
  };

  const handleRenderFull = async () => {
    if (!selectedPresId) return;
    setError("");
    setRendering(true);
    setRenderResult(null);
    try {
      const result = await intelApi.wordRender(selectedPresId, selectedTheme);
      setRenderResult(result);
      if (result.job_id) {
        try {
          setMetrics(await intelApi.wordMetrics(result.job_id));
        } catch { /* metrics optional */ }
      }
      loadSummary();
      loadHistory();
      loadJobs();
    } catch (e: any) {
      setError(e.message || "Render failed");
    } finally {
      setRendering(false);
    }
  };

  const handleRenderSection = async (section: string) => {
    if (!selectedPresId) return;
    setError("");
    try {
      const result = await intelApi.wordRenderSection(selectedPresId, section, selectedTheme);
      setRenderResult(result);
      loadSummary();
      loadHistory();
      loadJobs();
    } catch (e: any) {
      setError(e.message || "Section render failed");
    }
  };

  const handleDownload = (jobId: string) => {
    window.open(intelApi.wordDownloadUrl(jobId), "_blank");
  };

  const handleRefresh = () => {
    loadSummary();
    loadHistory();
    loadJobs();
  };

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      completed: "bg-emerald-100 text-emerald-700",
      running: "bg-blue-100 text-blue-700",
      pending: "bg-slate-100 text-slate-600",
      failed: "bg-red-100 text-red-700",
      cancelled: "bg-amber-100 text-amber-700",
    };
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || "bg-slate-100 text-slate-600"}`}>
        {status}
      </span>
    );
  };

  const formatDuration = (ms: number) =>
    ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

  const formatBytes = (b: number) =>
    b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;

  const formatTime = (ts: number) =>
    new Date(ts * 1000).toLocaleString();

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Word Report Renderer</h1>
          <p className="text-slate-500 text-sm mt-1">Generate professionally formatted Word (.docx) reports from approved presentations</p>
        </div>
        <button onClick={handleRefresh}
          className="px-3 py-1.5 text-sm bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-700 transition-colors">
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">{error}</div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">Total Renders</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.total_renders ?? 0}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">Total Jobs</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.total_jobs ?? 0}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">Latest Status</div>
          <div className="mt-1">{summary?.latest_job ? statusBadge(summary.latest_job.status) : <span className="text-slate-400">—</span>}</div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">Word Count</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">
            {summary?.latest_document?.word_count?.toLocaleString() ?? "—"}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">Download</div>
          <div className="mt-1">
            {summary?.has_download && summary.latest_job ? (
              <button onClick={() => handleDownload(summary.latest_job!.id)}
                className="text-sm text-violet-600 hover:text-violet-800 font-medium">
                Download .docx
              </button>
            ) : <span className="text-slate-400 text-sm">Not available</span>}
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-slate-600">Presentation:</label>
            <select
              value={selectedPresId ?? ""}
              onChange={(e) => setSelectedPresId(Number(e.target.value) || null)}
              className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
            >
              <option value="">Select...</option>
              {presentations.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.id} — {p.title || "Untitled"} ({p.status})
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-slate-600">Theme:</label>
            <select
              value={selectedTheme}
              onChange={(e) => setSelectedTheme(e.target.value)}
              className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
            >
              {themes.length === 0 && <option value="hunter_default">Default</option>}
              {themes.map((t) => (
                <option key={t.id} value={t.id}>{t.name || t.id}</option>
              ))}
            </select>
          </div>
          <button onClick={handleValidate} disabled={!selectedPresId}
            className="px-4 py-1.5 text-sm bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-700 disabled:opacity-50 transition-colors">
            Validate
          </button>
          <button onClick={handleRenderFull} disabled={!selectedPresId || rendering}
            className="px-4 py-1.5 text-sm bg-violet-600 hover:bg-violet-700 text-white rounded-lg disabled:opacity-50 transition-colors font-medium">
            {rendering ? "Rendering..." : "Render Word Report"}
          </button>
        </div>

        {/* Validation Result */}
        {validation && (
          <div className={`mt-3 p-3 rounded-lg text-sm ${validation.valid ? "bg-emerald-50 border border-emerald-200" : "bg-red-50 border border-red-200"}`}>
            <div className="font-medium">{validation.valid ? "Validation passed" : "Validation failed"}</div>
            {validation.issues.length > 0 && (
              <ul className="mt-1 list-disc list-inside text-red-700">
                {validation.issues.map((issue, i) => <li key={i}>{issue}</li>)}
              </ul>
            )}
            {validation.warnings.length > 0 && (
              <ul className="mt-1 list-disc list-inside text-amber-700">
                {validation.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
          </div>
        )}

        {/* Render Result */}
        {renderResult && (
          <div className={`mt-3 p-3 rounded-lg text-sm ${renderResult.error ? "bg-red-50 border border-red-200" : "bg-emerald-50 border border-emerald-200"}`}>
            {renderResult.error ? (
              <div className="text-red-700">Render failed: {renderResult.error}</div>
            ) : (
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-emerald-800">Report rendered successfully</span>
                  <span className="text-emerald-600 ml-3">
                    {renderResult.section_count} sections · {renderResult.word_count?.toLocaleString()} words · {formatBytes(renderResult.file_size_bytes || 0)} · {formatDuration(renderResult.render_duration_ms || 0)}
                  </span>
                  {renderResult.warnings && renderResult.warnings.length > 0 && (
                    <span className="text-amber-600 ml-2">({renderResult.warnings.length} warning{renderResult.warnings.length > 1 ? "s" : ""})</span>
                  )}
                </div>
                {renderResult.job_id && (
                  <button onClick={() => handleDownload(renderResult.job_id)}
                    className="px-3 py-1 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700">
                    Download .docx
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-slate-200">
        <div className="border-b border-slate-200 px-4">
          <nav className="flex gap-6">
            {(["sections", "metrics", "history", "jobs"] as const).map((tab) => (
              <button key={tab} onClick={() => setActiveTab(tab)}
                className={`py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab
                    ? "border-violet-600 text-violet-600"
                    : "border-transparent text-slate-500 hover:text-slate-700"
                }`}>
                {tab === "sections" ? "Sections" : tab === "metrics" ? "Metrics" : tab === "history" ? "History" : "Jobs"}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-4">
          {/* Sections Tab */}
          {activeTab === "sections" && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500 mb-3">Render individual sections or the entire report. Each section maps to content from the Presentation Model.</p>
              <div className="grid grid-cols-2 gap-2">
                {SECTION_NAMES.map((sec) => (
                  <div key={sec} className="flex items-center justify-between p-3 rounded-lg border border-slate-200 hover:border-violet-200 transition-colors">
                    <div>
                      <div className="text-sm font-medium text-slate-800">{SECTION_LABELS[sec]}</div>
                      <div className="text-xs text-slate-400">{sec}</div>
                    </div>
                    <button onClick={() => handleRenderSection(sec)} disabled={!selectedPresId}
                      className="px-3 py-1 text-xs bg-slate-100 hover:bg-violet-100 text-slate-600 hover:text-violet-700 rounded-md disabled:opacity-50 transition-colors">
                      Render
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Metrics Tab */}
          {activeTab === "metrics" && (
            <div>
              {metrics.length === 0 ? (
                <p className="text-slate-400 text-sm py-6 text-center">No render metrics yet. Render a report to see per-section timing data.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                      <th className="py-2 pr-4">#</th>
                      <th className="py-2 pr-4">Section</th>
                      <th className="py-2 pr-4">Duration</th>
                      <th className="py-2 pr-4">Elements</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.map((m) => (
                      <tr key={m.id} className="border-b border-slate-100">
                        <td className="py-2 pr-4 text-slate-400">{m.section_number}</td>
                        <td className="py-2 pr-4 font-medium text-slate-800">{SECTION_LABELS[m.section_name] || m.section_name}</td>
                        <td className="py-2 pr-4">{formatDuration(m.duration_ms)}</td>
                        <td className="py-2 pr-4">{m.element_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* History Tab */}
          {activeTab === "history" && (
            <div>
              {history.length === 0 ? (
                <p className="text-slate-400 text-sm py-6 text-center">No render history yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                      <th className="py-2 pr-4">Time</th>
                      <th className="py-2 pr-4">Action</th>
                      <th className="py-2 pr-4">Actor</th>
                      <th className="py-2 pr-4">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.id} className="border-b border-slate-100">
                        <td className="py-2 pr-4 text-slate-500 text-xs">{formatTime(h.created_at)}</td>
                        <td className="py-2 pr-4">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            h.action.includes("completed") ? "bg-emerald-100 text-emerald-700" :
                            h.action.includes("failed") ? "bg-red-100 text-red-700" :
                            "bg-blue-100 text-blue-700"
                          }`}>{h.action}</span>
                        </td>
                        <td className="py-2 pr-4 text-slate-600">{h.actor}</td>
                        <td className="py-2 pr-4 text-slate-500 text-xs max-w-xs truncate">
                          {JSON.stringify(h.details_json).slice(0, 80)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Jobs Tab */}
          {activeTab === "jobs" && (
            <div>
              {jobs.length === 0 ? (
                <p className="text-slate-400 text-sm py-6 text-center">No render jobs yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                      <th className="py-2 pr-4">Job ID</th>
                      <th className="py-2 pr-4">Type</th>
                      <th className="py-2 pr-4">Status</th>
                      <th className="py-2 pr-4">Size</th>
                      <th className="py-2 pr-4">Created</th>
                      <th className="py-2 pr-4">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => (
                      <tr key={j.id} className="border-b border-slate-100">
                        <td className="py-2 pr-4 font-mono text-xs text-slate-500">{j.id.slice(0, 8)}</td>
                        <td className="py-2 pr-4">{j.job_type}</td>
                        <td className="py-2 pr-4">{statusBadge(j.status)}</td>
                        <td className="py-2 pr-4">{j.output_size_bytes ? formatBytes(j.output_size_bytes) : "—"}</td>
                        <td className="py-2 pr-4 text-xs text-slate-500">{formatTime(j.created_at)}</td>
                        <td className="py-2 pr-4">
                          {j.status === "completed" && j.output_path && (
                            <button onClick={() => handleDownload(j.id)}
                              className="text-xs text-violet-600 hover:text-violet-800 font-medium">
                              Download
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("powerpoint-renderer")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to PowerPoint Renderer
        </button>
        <button onClick={() => onNavigate("pipeline-orchestrator")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Pipeline
        </button>
      </div>
    </div>
  );
}

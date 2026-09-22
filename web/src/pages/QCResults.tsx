import { useState, useEffect, useRef } from "react";
import { useActiveProjectId } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

const SEV = {
  critical: { bg: "#FEF2F2", border: "#FECACA", text: "#991B1B", dot: "#DC2626", label: "Critical" },
  high:     { bg: "#FFF7ED", border: "#FED7AA", text: "#9A3412", dot: "#EA580C", label: "High" },
  medium:   { bg: "#FFFBEB", border: "#FDE68A", text: "#92400E", dot: "#D97706", label: "Medium" },
  low:      { bg: "#F0FDF4", border: "#BBF7D0", text: "#166534", dot: "#16A34A", label: "Low" },
  info:     { bg: "#EFF6FF", border: "#BFDBFE", text: "#1E40AF", dot: "#2563EB", label: "Info" },
};

const GRADE_COLORS: Record<string, string> = {
  A: "#16A34A", B: "#65A30D", C: "#D97706", D: "#DC2626", F: "#991B1B",
};

interface Finding {
  id: number;
  check_type: string;
  row_number: number | null;
  column_name: string | null;
  severity: string;
  message: string;
  expected: string | null;
  actual: string | null;
  source_url: string | null;
  analyst_action: string | null;
}

interface QCRun {
  id: number;
  status: string;
  total_rows: number;
  total_checks: number;
  total_findings: number;
  score: number | null;
  score_breakdown: Record<string, unknown> | null;
}

interface ArticleRow {
  Headline?: string;
  headline?: string;
  URL?: string;
  url?: string;
  Source?: string;
  source?: string;
  Date?: string;
  date?: string;
  Author?: string;
  author?: string;
}

interface ArticleGroup {
  rowNum: number;
  headline: string;
  source: string;
  date: string;
  url: string;
  findings: Finding[];
  worstSeverity: string;
}

const SEV_ORDER = ["critical", "high", "medium", "low", "info"];

function worstSev(findings: Finding[]): string {
  for (const s of SEV_ORDER) {
    if (findings.some((f) => f.severity === s)) return s;
  }
  return "info";
}

export function QCResults({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId();
  const [run, setRun] = useState<QCRun | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [articles, setArticles] = useState<ArticleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterSeverity, setFilterSeverity] = useState<string>("");
  const [selectedArticle, setSelectedArticle] = useState<ArticleGroup | null>(null);
  const [running, setRunning] = useState(false);
  const [reportId, setReportId] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [running]);

  useEffect(() => {
    if (!projectId) { setLoading(false); return; }
    (async () => {
      try {
        const report = await intelApi.qcGetReport(projectId) as { id: number; parse_status: string };
        setReportId(report.id);

        const previewRes = await fetch(`/api/intel/qc/all-rows/${report.id}`);
        if (previewRes.ok) {
          const allRows = await previewRes.json();
          setArticles(allRows.rows || []);
        }

        const runs = await intelApi.qcGetRuns(report.id) as unknown as QCRun[];
        if (runs.length > 0) {
          const latest = runs[0] as QCRun;
          setRun(latest);
          if (latest.status === "completed") {
            const f = await intelApi.qcGetResults(latest.id) as unknown as Finding[];
            setFindings(f);
          } else if (latest.status === "running" || latest.status === "pending") {
            setRunning(true);
            const poll = setInterval(async () => {
              try {
                const updated = await intelApi.qcGetRuns(report.id) as unknown as QCRun[];
                if (updated.length > 0 && updated[0].status === "completed") {
                  clearInterval(poll);
                  setRun(updated[0]);
                  setRunning(false);
                  const f = await intelApi.qcGetResults(updated[0].id) as unknown as Finding[];
                  setFindings(f);
                }
              } catch { /* ignore */ }
            }, 2000);
          }
        }
      } catch { /* no report yet */ }
      setLoading(false);
    })();
  }, [projectId]);

  const handleRunQC = async () => {
    if (!reportId) return;
    setRunning(true);
    try {
      await intelApi.qcStartRun(reportId);
      const poll = setInterval(async () => {
        try {
          const runs = await intelApi.qcGetRuns(reportId!) as unknown as QCRun[];
          if (runs.length > 0) {
            const latest = runs[0];
            setRun(latest);
            if (latest.status === "completed") {
              clearInterval(poll);
              setRunning(false);
              const f = await intelApi.qcGetResults(latest.id) as unknown as Finding[];
              setFindings(f);
            }
          }
        } catch { /* ignore */ }
      }, 2000);
    } catch {
      setRunning(false);
    }
  };

  // Group findings by article
  const articleGroups: ArticleGroup[] = [];
  const reportLevel: Finding[] = [];
  const findingsByRow = new Map<number, Finding[]>();

  for (const f of findings) {
    if (filterSeverity && f.severity !== filterSeverity) continue;
    if (!f.row_number || f.row_number === 0) {
      reportLevel.push(f);
    } else {
      const arr = findingsByRow.get(f.row_number) || [];
      arr.push(f);
      findingsByRow.set(f.row_number, arr);
    }
  }

  for (const [rowNum, rowFindings] of findingsByRow) {
    const idx = rowNum - 2;
    const art = articles[idx] || {};
    articleGroups.push({
      rowNum,
      headline: art.Headline || art.headline || `Article #${idx + 1}`,
      source: art.Source || art.source || "",
      date: art.Date || art.date || "",
      url: art.URL || art.url || "",
      findings: rowFindings,
      worstSeverity: worstSev(rowFindings),
    });
  }

  articleGroups.sort((a, b) => SEV_ORDER.indexOf(a.worstSeverity) - SEV_ORDER.indexOf(b.worstSeverity));

  const breakdown = (run?.score_breakdown || {}) as Record<string, unknown>;
  const grade = (breakdown.grade || "-") as string;
  const sevDist = (breakdown.severity_distribution || {}) as Record<string, number>;
  const cleanCount = (breakdown.clean_rows ?? 0) as number;

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
    <div className="px-8 py-6 max-w-5xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">QC Results</h1>
          <p className="text-sm text-slate-500 mt-0.5">Quality check findings by article</p>
        </div>
        <div className="flex items-center gap-3">
          {run && run.status === "completed" && (
            <button
              onClick={() => onNavigate("qc-export")}
              className="px-4 py-2 text-sm font-medium border rounded-lg transition-colors"
              style={{ borderColor: "#0F7B6C40", color: "#0F7B6C" }}
            >
              Export
            </button>
          )}
          {reportId && (
            <button
              onClick={handleRunQC}
              disabled={running}
              className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors disabled:opacity-50"
              style={{ backgroundColor: "#0F7B6C" }}
            >
              {running ? "Running..." : run ? "Re-run QC" : "Run QC"}
            </button>
          )}
        </div>
      </div>

      {running && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 flex items-center gap-3">
          <svg className="animate-spin h-4 w-4 shrink-0" style={{ color: "#0F7B6C" }} viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm font-medium" style={{ color: "#0F7B6C" }}>Running quality checks...</span>
          <span className="text-sm font-mono ml-auto" style={{ color: "#0F7B6C" }}>{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</span>
        </div>
      )}

      {/* Score cards */}
      {run && run.status === "completed" && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm text-center">
            <div className="text-3xl font-bold" style={{ color: GRADE_COLORS[grade] || "#333" }}>{grade}</div>
            <div className="text-xs text-slate-400 mt-1">Grade</div>
            <div className="text-lg font-semibold text-slate-700 mt-0.5">{run.score ?? "-"}/100</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm text-center">
            <div className="text-2xl font-bold text-slate-900">{run.total_findings}</div>
            <div className="text-xs text-slate-400 mt-1">Total Issues</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm text-center">
            <div className="text-2xl font-bold" style={{ color: "#16A34A" }}>{cleanCount}</div>
            <div className="text-xs text-slate-400 mt-1">Clean Articles</div>
            <div className="text-xs text-slate-400">of {run.total_rows}</div>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <div className="text-xs text-slate-400 mb-2">Issues by Severity</div>
            <div className="space-y-1">
              {SEV_ORDER.slice(0, 4).map((sev) =>
                sevDist[sev] ? (
                  <div key={sev} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SEV[sev as keyof typeof SEV]?.dot }} />
                      {SEV[sev as keyof typeof SEV]?.label}
                    </span>
                    <span className="font-medium">{sevDist[sev]}</span>
                  </div>
                ) : null
              )}
            </div>
          </div>
        </div>
      )}

      {/* Filter */}
      {findings.length > 0 && (
        <div className="flex items-center gap-3">
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none"
          >
            <option value="">All severities</option>
            {SEV_ORDER.map((s) => (
              <option key={s} value={s}>{SEV[s as keyof typeof SEV]?.label}</option>
            ))}
          </select>
          <span className="text-xs text-slate-400 ml-auto">
            {articleGroups.length} article{articleGroups.length !== 1 ? "s" : ""} with issues
            {reportLevel.length > 0 && ` + ${reportLevel.length} report-level`}
          </span>
        </div>
      )}

      {/* Report-level findings */}
      {reportLevel.length > 0 && (
        <div className="rounded-xl border-2 p-4 space-y-2" style={{ borderColor: SEV.critical.border, backgroundColor: SEV.critical.bg }}>
          <div className="flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={SEV.critical.dot} strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span className="text-sm font-semibold" style={{ color: SEV.critical.text }}>Report-Level Issues</span>
          </div>
          {reportLevel.map((f) => (
            <div key={f.id} className="text-sm" style={{ color: SEV.critical.text }}>{f.message}</div>
          ))}
        </div>
      )}

      {/* Article cards */}
      {articleGroups.map((group) => {
        const sev = SEV[group.worstSeverity as keyof typeof SEV] || SEV.info;
        return (
          <div
            key={group.rowNum}
            className="bg-white border rounded-xl shadow-sm overflow-hidden cursor-pointer hover:shadow-md transition-shadow"
            style={{ borderColor: sev.border }}
            onClick={() => setSelectedArticle(selectedArticle?.rowNum === group.rowNum ? null : group)}
          >
            <div className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-slate-900 leading-snug">{group.headline}</h3>
                  <div className="flex items-center gap-2 mt-1.5 text-xs text-slate-500">
                    {group.source && <span>{group.source}</span>}
                    {group.source && group.date && <span>·</span>}
                    {group.date && <span>{group.date}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span
                    className="text-xs font-medium px-2.5 py-1 rounded-full"
                    style={{ backgroundColor: sev.bg, color: sev.text, border: `1px solid ${sev.border}` }}
                  >
                    {group.findings.length} issue{group.findings.length !== 1 ? "s" : ""}
                  </span>
                  <svg
                    width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" strokeWidth="2"
                    className={`transition-transform ${selectedArticle?.rowNum === group.rowNum ? "rotate-180" : ""}`}
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
              </div>

              {/* Expanded findings */}
              {selectedArticle?.rowNum === group.rowNum && (
                <div className="mt-4 space-y-2 border-t border-slate-100 pt-3">
                  {group.url && (
                    <div className="text-xs text-slate-400 break-all mb-2">{group.url}</div>
                  )}
                  {group.findings.map((f) => {
                    const fs = SEV[f.severity as keyof typeof SEV] || SEV.info;
                    return (
                      <div
                        key={f.id}
                        className="flex items-start gap-3 rounded-lg px-3 py-2.5"
                        style={{ backgroundColor: fs.bg }}
                      >
                        <span
                          className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                          style={{ backgroundColor: fs.dot }}
                        />
                        <div className="flex-1 min-w-0">
                          <span className="text-xs font-medium" style={{ color: fs.text }}>{fs.label}</span>
                          <p className="text-sm text-slate-700 mt-0.5">{f.message}</p>
                          {f.actual && f.actual !== "(blank)" && (
                            <p className="text-xs text-slate-400 mt-1 break-all">{f.actual}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* Empty states */}
      {run && run.status === "completed" && articleGroups.length === 0 && reportLevel.length === 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-8 text-center">
          <svg className="mx-auto mb-3" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#16A34A" strokeWidth="2" strokeLinecap="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <p className="text-sm font-medium text-emerald-800">All articles passed quality checks</p>
          <p className="text-xs text-emerald-600 mt-1">{run.total_rows} articles checked, no issues found</p>
        </div>
      )}

      {!run && !running && reportId && (
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <p className="text-sm text-slate-500">No QC run yet. Click "Run QC" to start quality checking.</p>
        </div>
      )}

      {!reportId && (
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <p className="text-sm text-slate-500">
            No report uploaded yet.{" "}
            <button onClick={() => onNavigate("qc-upload")} className="text-emerald-600 underline font-medium">Upload a report</button>
          </p>
        </div>
      )}
    </div>
  );
}

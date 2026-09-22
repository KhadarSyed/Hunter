import { useState, useEffect, useRef, useCallback } from "react";
import * as XLSX from "xlsx";
import { intelApi, type StrategyResult, type JobStatus, type EvaluationResult } from "../lib/intel-api";
import { useActiveProjectId, useProject } from "../lib/project-context";
import { useDemoState } from "../lib/demo-state";

type Tab = "overview" | "modules" | "queries" | "exclusions" | "filters" | "score" | "evaluation";
type LiveState = "idle" | "generating" | "completed" | "failed";

/* ── Boolean query syntax highlighter ── */

function tokenizeBooleanQuery(query: string): { text: string; type: "operator" | "quote" | "paren" | "text" | "near" }[] {
  const tokens: { text: string; type: "operator" | "quote" | "paren" | "text" | "near" }[] = [];
  const regex = /("(?:[^"\\]|\\.)*"|\b(?:AND|OR|NOT)\b|\bNEAR\/\d+\b|[()])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(query)) !== null) {
    if (m.index > last) tokens.push({ text: query.slice(last, m.index), type: "text" });
    const val = m[0];
    if (val === "(" || val === ")") tokens.push({ text: val, type: "paren" });
    else if (val.startsWith('"')) tokens.push({ text: val, type: "quote" });
    else if (val.startsWith("NEAR")) tokens.push({ text: val, type: "near" });
    else tokens.push({ text: val, type: "operator" });
    last = regex.lastIndex;
  }
  if (last < query.length) tokens.push({ text: query.slice(last), type: "text" });
  return tokens;
}

const V = "#5B2C9D";

function BooleanDisplay({ query, label, description, onCopy, editable, onEdit }: {
  query: string; label: string; description?: string; onCopy: () => void;
  editable?: boolean; onEdit?: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(query);
  const tokens = tokenizeBooleanQuery(query);

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-slate-700">{label}</span>
          {description && <span className="text-[11px] text-slate-400 hidden sm:inline">— {description}</span>}
        </div>
        <div className="flex items-center gap-2">
          {editable && !editing && (
            <button onClick={() => { setEditing(true); setEditText(query); }} className="text-xs font-medium hover:opacity-80 transition-opacity" style={{ color: V }}>
              Edit
            </button>
          )}
          <button onClick={onCopy} className="text-xs font-medium hover:opacity-80 flex items-center gap-1 transition-opacity" style={{ color: V }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
            Copy
          </button>
        </div>
      </div>
      {editing ? (
        <div className="p-4 space-y-3">
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            className="w-full h-32 text-xs font-mono border border-slate-200 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-violet-200 resize-none"
          />
          <div className="flex items-center gap-2 justify-end">
            <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-xs font-medium text-slate-500 hover:text-slate-700">Cancel</button>
            <button
              onClick={() => { onEdit?.(editText); setEditing(false); }}
              className="px-3 py-1.5 text-xs font-medium text-white rounded-lg" style={{ background: V }}
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="p-4 font-mono text-[13px] leading-relaxed text-slate-700 overflow-x-auto whitespace-pre-wrap" style={{ wordBreak: "break-word" }}>
          {tokens.map((t, i) => {
            if (t.type === "operator") return <span key={i} className="font-bold" style={{ color: t.text === "NOT" ? "#dc2626" : t.text === "AND" ? "#2563eb" : "#059669" }}>{t.text}</span>;
            if (t.type === "near") return <span key={i} className="font-bold text-purple-600">{t.text}</span>;
            if (t.type === "quote") return <span key={i} className="text-amber-700">{t.text}</span>;
            if (t.type === "paren") return <span key={i} className="text-slate-400 font-bold">{t.text}</span>;
            return <span key={i}>{t.text}</span>;
          })}
        </div>
      )}
    </div>
  );
}

function ScoreGauge({ score, max = 10, label }: { score: number; max?: number; label: string }) {
  const pct = Math.round((score / max) * 100);
  const color = pct >= 80 ? "#059669" : pct >= 60 ? "#d97706" : "#dc2626";
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-500 w-32 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs font-bold tabular-nums w-8 text-right" style={{ color }}>{score}/{max}</span>
    </div>
  );
}

function ProgressBar({ pct, message }: { pct: number; message: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-700 font-medium">Generating search strategy...</span>
        <span className="text-slate-400 tabular-nums">{pct}%</span>
      </div>
      <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: V }} />
      </div>
      <p className="text-xs text-slate-500">{message}</p>
    </div>
  );
}

interface Props {
  onNavigate: (page: string) => void;
}

export function SearchStrategy({ onNavigate }: Props) {
  const projectId = useActiveProjectId();
  const { activeProject } = useProject();
  const demo = useDemoState();
  const [tab, setTab] = useState<Tab>("overview");
  const [queryView, setQueryView] = useState<"broad" | "balanced" | "precise">("balanced");
  const [approved, setApproved] = useState(false);
  const [copied, setCopied] = useState(false);

  const [liveState, setLiveState] = useState<LiveState>("idle");
  const [jobProgress, setJobProgress] = useState({ pct: 0, message: "" });
  const [strategy, setStrategy] = useState<StrategyResult | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationIssues, setValidationIssues] = useState<string[]>([]);
  const [uploadingFile, setUploadingFile] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  useEffect(() => {
    if (projectId && !strategy && liveState === "idle") {
      intelApi.getStrategy(projectId)
        .then((s) => {
          setStrategy(s);
          setLiveState("completed");
          const isApproved = s.approval_status === "approved";
          setApproved(isApproved);
          if (isApproved) demo.setStrategyApproved(true);
          const strat = s.strategy as Record<string, unknown>;
          setValidationIssues((strat?._validation_issues as string[]) || []);
        })
        .catch(() => {});
      intelApi.getEvaluation(projectId)
        .then((e) => setEvaluation(e))
        .catch(() => {});
    }
  }, [projectId, strategy, liveState]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const generateStrategy = async () => {
    if (!projectId) {
      setError("No project found — run Background Research first");
      setLiveState("failed");
      return;
    }
    setError(null);
    setLiveState("generating");
    setJobProgress({ pct: 0, message: "Starting..." });
    try {
      const result = await intelApi.generateStrategy(projectId);
      pollRef.current = setInterval(async () => {
        try {
          const status: JobStatus = await intelApi.getJob(result.job_id);
          setJobProgress({ pct: status.progress_pct, message: status.progress_message });
          if (status.status === "completed") {
            stopPolling();
            const s = await intelApi.getStrategy(projectId);
            setStrategy(s);
            setLiveState("completed");
            const strat = s.strategy as Record<string, unknown>;
            setValidationIssues((strat?._validation_issues as string[]) || []);
          } else if (status.status === "failed") {
            stopPolling();
            setError(status.error || "Strategy generation failed");
            setLiveState("failed");
          }
        } catch {
          stopPolling();
          setError("Lost connection to server");
          setLiveState("failed");
        }
      }, 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start strategy generation");
      setLiveState("failed");
    }
  };

  const handleQueryEdit = async (queryType: string, queryText: string) => {
    if (!strategy) return;
    try {
      const result = await intelApi.editQuery(strategy.strategy_id, queryType, queryText);
      setValidationIssues(result.validation_issues);
      const refreshed = await intelApi.getStrategy(projectId!);
      setStrategy(refreshed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save query edit");
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!projectId || !strategy) return;
    setUploadingFile(true);
    setError(null);
    try {
      const result = await intelApi.uploadSample(projectId, strategy.strategy_id, file);
      pollRef.current = setInterval(async () => {
        try {
          const status = await intelApi.getJob(result.job_id);
          if (status.status === "completed") {
            stopPolling();
            const evalResult = await intelApi.getEvaluation(projectId);
            setEvaluation(evalResult);
            setUploadingFile(false);
          } else if (status.status === "failed") {
            stopPolling();
            setError(status.error || "Evaluation failed");
            setUploadingFile(false);
          }
        } catch {
          stopPolling();
          setError("Lost connection");
          setUploadingFile(false);
        }
      }, 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setUploadingFile(false);
    }
  };

  const handleApprove = async () => {
    if (!strategy) return;
    try {
      await intelApi.approveStrategy(strategy.strategy_id);
      setApproved(true);
      demo.setStrategyApproved(true);
      setTimeout(() => onNavigate("data-sources"), 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  /* ── Extract live data with correct keys ── */
  const strat = (strategy?.strategy ?? {}) as Record<string, any>;
  const strategySummary: string = strat.strategy_summary || "";
  const queryModules: any[] = strat.query_modules || [];
  const queryVersions: Record<string, any> = strat.query_versions || {};
  const rqQueries: any[] = strat.research_question_queries || [];
  const exclusionStrategy: any = strat.exclusion_strategy || {};
  const filterRecs: any = strat.filter_recommendations || {};
  const qualityAssessment: any = strat.quality_assessment || {};
  const meta: any = strat._meta || {};

  const currentQuery = queryVersions[queryView] || {};
  const currentQueryText: string = currentQuery.query || "";
  const currentQueryDesc: string = currentQuery.description || "";

  const exclusionCats: any[] = exclusionStrategy.exclusion_categories || [];
  const globalExclusions: string = exclusionStrategy.global_exclusions || "";

  const additionalFilters: any[] = filterRecs.additional_filters || [];
  const platforms: string[] = filterRecs.platforms || [];
  const sourceTypes: string[] = filterRecs.source_types || [];

  const totalExclusions = exclusionCats.reduce((sum: number, c: any) => sum + (c.terms?.length || 0), 0);

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "overview", label: "Strategy" },
    { id: "modules", label: "Modules", count: queryModules.length },
    { id: "queries", label: "RQ Queries", count: rqQueries.length },
    { id: "exclusions", label: "Exclusions", count: totalExclusions },
    { id: "filters", label: "Filters" },
    { id: "score", label: "Quality" },
    ...(strategy ? [{ id: "evaluation" as Tab, label: "Sample Eval" }] : []),
  ];

  const hasData = liveState === "completed" && strategy;

  const exportToExcel = () => {
    if (!hasData) return;
    const wb = XLSX.utils.book_new();
    const brandName = activeProject?.name ?? "Strategy";

    // 1. Strategy Overview
    const overviewRows = [
      ["Search Strategy Export"],
      ["Brand", brandName],
      ["Version", `v${strategy?.version || 1}`],
      ["Status", approved ? "Approved" : "Draft"],
      ["Generated", meta.elapsed_seconds ? `${meta.elapsed_seconds}s` : "—"],
      [],
      ["Strategy Summary"],
      [strategySummary],
      [],
      ["Quality Scores"],
      ["Overall", `${qualityAssessment.overall_score || 0}/10`],
      ["Coverage", `${qualityAssessment.coverage_score || 0}/10`],
      ["Precision", `${qualityAssessment.precision_score || 0}/10`],
    ];
    const wsOverview = XLSX.utils.aoa_to_sheet(overviewRows);
    wsOverview["!cols"] = [{ wch: 20 }, { wch: 80 }];
    XLSX.utils.book_append_sheet(wb, wsOverview, "Overview");

    // 2. Boolean Queries
    const queryRows: (string | number)[][] = [
      ["Query Version", "Boolean Query", "Description", "Noise Level", "Use Case", "Characters"],
    ];
    for (const v of ["broad", "balanced", "precise"] as const) {
      const qv = queryVersions[v];
      if (qv) {
        queryRows.push([
          v.charAt(0).toUpperCase() + v.slice(1),
          qv.query || "",
          qv.description || "",
          qv.estimated_noise_level || "",
          qv.use_case || "",
          (qv.query || "").length,
        ]);
      }
    }
    const wsQueries = XLSX.utils.aoa_to_sheet(queryRows);
    wsQueries["!cols"] = [{ wch: 12 }, { wch: 80 }, { wch: 50 }, { wch: 10 }, { wch: 50 }, { wch: 10 }];
    XLSX.utils.book_append_sheet(wb, wsQueries, "Boolean Queries");

    // 3. Query Modules
    const moduleRows: string[][] = [
      ["Module ID", "Module Name", "Purpose", "Primary Terms", "Synonyms", "Exclusions"],
    ];
    for (const m of queryModules) {
      moduleRows.push([
        m.module_id || "",
        m.name || "",
        m.purpose || "",
        (m.terms?.primary || []).join(", "),
        (m.terms?.synonyms || []).join(", "),
        (m.terms?.exclusions || []).join(", "),
      ]);
    }
    const wsModules = XLSX.utils.aoa_to_sheet(moduleRows);
    wsModules["!cols"] = [{ wch: 10 }, { wch: 30 }, { wch: 50 }, { wch: 50 }, { wch: 50 }, { wch: 50 }];
    XLSX.utils.book_append_sheet(wb, wsModules, "Query Modules");

    // 4. Research Question Queries
    const rqRows: string[][] = [
      ["Question ID", "Research Question", "Boolean Query", "Rationale"],
    ];
    for (const q of rqQueries) {
      rqRows.push([
        q.question_id || "",
        q.question || "",
        q.query || "",
        q.rationale || "",
      ]);
    }
    const wsRQ = XLSX.utils.aoa_to_sheet(rqRows);
    wsRQ["!cols"] = [{ wch: 12 }, { wch: 50 }, { wch: 80 }, { wch: 50 }];
    XLSX.utils.book_append_sheet(wb, wsRQ, "RQ Queries");

    // 5. Exclusions
    const exclRows: string[][] = [
      ["Category", "Terms", "Reason"],
    ];
    if (globalExclusions) {
      exclRows.push(["Global NOT String", globalExclusions, exclusionStrategy.rationale || ""]);
    }
    for (const cat of exclusionCats) {
      exclRows.push([
        cat.category || "",
        (cat.terms || []).join(", "),
        cat.reason || "",
      ]);
    }
    const wsExcl = XLSX.utils.aoa_to_sheet(exclRows);
    wsExcl["!cols"] = [{ wch: 25 }, { wch: 80 }, { wch: 50 }];
    XLSX.utils.book_append_sheet(wb, wsExcl, "Exclusions");

    // 6. Filters
    const filterRows: string[][] = [
      ["Filter", "Value", "Reason"],
      ["Date Range", filterRecs.date_range || "", ""],
      ["Geography", (filterRecs.geography || []).join(", "), ""],
      ["Language", (filterRecs.language || []).join(", "), ""],
      ["Source Types", sourceTypes.join(", "), ""],
      ["Platforms", platforms.join(", "), ""],
    ];
    for (const f of additionalFilters) {
      filterRows.push([f.filter || "", f.value || "", f.reason || ""]);
    }
    const wsFilters = XLSX.utils.aoa_to_sheet(filterRows);
    wsFilters["!cols"] = [{ wch: 30 }, { wch: 60 }, { wch: 60 }];
    XLSX.utils.book_append_sheet(wb, wsFilters, "Filters");

    // 7. Quality Assessment
    const qualRows: string[][] = [
      ["Quality Assessment"],
      ["Overall Score", `${qualityAssessment.overall_score || 0}/10`],
      ["Coverage Score", `${qualityAssessment.coverage_score || 0}/10`],
      ["Precision Score", `${qualityAssessment.precision_score || 0}/10`],
      [],
      ["Potential Gaps"],
      ...(qualityAssessment.potential_gaps || []).map((g: string) => [g]),
      [],
      ["Noise Risks"],
      ...(qualityAssessment.potential_noise || []).map((n: string) => [n]),
      [],
      ["Recommendations"],
      ...(qualityAssessment.recommendations || []).map((r: string) => [r]),
    ];
    const wsQual = XLSX.utils.aoa_to_sheet(qualRows);
    wsQual["!cols"] = [{ wch: 100 }];
    XLSX.utils.book_append_sheet(wb, wsQual, "Quality Assessment");

    XLSX.writeFile(wb, `${brandName}_Search_Strategy.xlsx`);
  };

  return (
    <div className="h-full flex flex-col animate-fade-in">
      {/* ── Header ── */}
      <div className="shrink-0 px-8 pt-6 pb-4 border-b border-slate-100">
        <div className="flex items-center justify-between mb-1">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Search Strategy</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Meltwater Boolean queries for <span className="font-medium text-slate-700">{activeProject?.name ?? "Research Project"}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            {copied && <span className="text-xs text-emerald-600 font-medium animate-fade-in">Copied!</span>}
            {hasData && (
              <button
                onClick={exportToExcel}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border rounded-lg transition-colors hover:bg-slate-50"
                style={{ color: V, borderColor: "#ddd6fe" }}
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                Export Excel
              </button>
            )}
            {hasData && (
              <span className="text-xs font-medium px-2.5 py-1 rounded-full border"
                style={approved
                  ? { color: "#059669", background: "#ecfdf5", borderColor: "#a7f3d0" }
                  : { color: V, background: "#f5f3ff", borderColor: "#ddd6fe" }
                }>
                v{strategy?.version || 1} {approved ? "Approved" : "Draft"}
              </span>
            )}
            {hasData && meta.elapsed_seconds && (
              <span className="text-[11px] text-slate-400">Generated in {meta.elapsed_seconds}s</span>
            )}
          </div>
        </div>
      </div>

      {/* ── Idle: generate prompt ── */}
      {liveState === "idle" && !strategy && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center max-w-md space-y-5">
            <div className="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center" style={{ background: "#f5f3ff" }}>
              <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
              </svg>
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-800 mb-1">Generate Search Strategy</h3>
              <p className="text-sm text-slate-500 leading-relaxed">
                {projectId
                  ? "Build Meltwater Boolean queries from your approved background research. The AI will create query modules, three precision levels, and per-question queries."
                  : "Approve Background Research first, then return here to generate."
                }
              </p>
            </div>
            <button
              onClick={generateStrategy}
              disabled={!projectId}
              className="px-6 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: projectId ? V : "#94a3b8" }}
            >
              Generate Strategy
            </button>
          </div>
        </div>
      )}

      {/* ── Generating ── */}
      {liveState === "generating" && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-lg">
            <ProgressBar pct={jobProgress.pct} message={jobProgress.message} />
          </div>
        </div>
      )}

      {/* ── Failed ── */}
      {liveState === "failed" && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm max-w-lg w-full">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-red-500 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-red-700">Strategy Generation Failed</h3>
                <p className="text-xs text-red-600 mt-1">{error}</p>
              </div>
              <button onClick={() => { setLiveState("idle"); setError(null); }}
                className="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors">
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Strategy content ── */}
      {hasData && (
        <div className="flex-1 flex flex-col min-h-0">
          {/* Validation banner */}
          {validationIssues.length > 0 && (
            <div className="mx-8 mt-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <div className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-1">Boolean Validation Issues</div>
              {validationIssues.map((issue, i) => (
                <div key={i} className="text-xs text-amber-600">{issue}</div>
              ))}
            </div>
          )}

          {/* Tab bar */}
          <div className="shrink-0 px-8 pt-4 pb-0">
            <div className="flex items-center gap-1 border-b border-slate-200">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-2.5 text-xs font-medium border-b-2 transition-all -mb-px ${
                    tab === t.id
                      ? "border-current text-[#5B2C9D]"
                      : "border-transparent text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {t.label}
                  {t.count !== undefined && (
                    <span className={`ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full ${
                      tab === t.id ? "bg-violet-100 text-violet-700" : "bg-slate-100 text-slate-500"
                    }`}>{t.count}</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-8 py-6">

            {/* ── Overview ── */}
            {tab === "overview" && (
              <div className="space-y-6 max-w-4xl animate-fade-in">
                {/* Summary */}
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Strategy Summary</h3>
                  <p className="text-sm text-slate-700 leading-relaxed font-reading">{strategySummary}</p>
                </div>

                {/* Stats row */}
                <div className="grid grid-cols-5 gap-3">
                  {[
                    { label: "Overall", value: qualityAssessment.overall_score, color: qualityAssessment.overall_score >= 8 ? "#059669" : qualityAssessment.overall_score >= 6 ? "#d97706" : "#dc2626" },
                    { label: "Coverage", value: qualityAssessment.coverage_score, color: "#2563eb" },
                    { label: "Precision", value: qualityAssessment.precision_score, color: "#7c3aed" },
                    { label: "Modules", value: queryModules.length, color: "#0f172a", plain: true },
                    { label: "RQ Queries", value: rqQueries.length, color: "#0f172a", plain: true },
                  ].map((s, i) => (
                    <div key={i} className="bg-white border border-slate-200 rounded-xl p-4 text-center shadow-sm">
                      <div className="text-2xl font-bold tabular-nums" style={{ color: s.color }}>
                        {s.value ?? 0}{!s.plain && <span className="text-sm font-normal text-slate-300">/10</span>}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-1">{s.label}</div>
                    </div>
                  ))}
                </div>

                {/* Boolean queries */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Boolean Queries</h3>
                    <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
                      {(["broad", "balanced", "precise"] as const).map((v) => (
                        <button
                          key={v}
                          onClick={() => setQueryView(v)}
                          className={`px-3 py-1.5 text-xs rounded-md transition-all capitalize ${
                            queryView === v
                              ? "bg-white text-slate-800 font-semibold shadow-sm"
                              : "text-slate-500 hover:text-slate-700"
                          }`}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </div>
                  <BooleanDisplay
                    query={currentQueryText}
                    label={`${queryView.charAt(0).toUpperCase() + queryView.slice(1)} Query`}
                    description={currentQueryDesc.slice(0, 100)}
                    onCopy={() => handleCopy(currentQueryText)}
                    editable
                    onEdit={(text) => handleQueryEdit(queryView, text)}
                  />
                  <div className="flex items-center gap-4 mt-2 text-[11px] text-slate-400">
                    <span>Noise: <span className={`font-semibold ${currentQuery.estimated_noise_level === "high" ? "text-red-500" : currentQuery.estimated_noise_level === "medium" ? "text-amber-500" : "text-emerald-500"}`}>{currentQuery.estimated_noise_level || "—"}</span></span>
                    <span>Use case: {currentQuery.use_case || "—"}</span>
                    <span>{currentQueryText.length} chars</span>
                  </div>
                </div>

                {/* Potential gaps and noise */}
                {(qualityAssessment.potential_gaps?.length > 0 || qualityAssessment.potential_noise?.length > 0) && (
                  <div className="grid grid-cols-2 gap-4">
                    {qualityAssessment.potential_gaps?.length > 0 && (
                      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                        <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-3">Potential Gaps</h4>
                        <div className="space-y-2">
                          {qualityAssessment.potential_gaps.slice(0, 4).map((g: string, i: number) => (
                            <div key={i} className="text-xs text-slate-600 leading-relaxed flex items-start gap-2">
                              <svg className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                              <span>{g}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {qualityAssessment.potential_noise?.length > 0 && (
                      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                        <h4 className="text-xs font-semibold text-red-500 uppercase tracking-wide mb-3">Noise Risks</h4>
                        <div className="space-y-2">
                          {qualityAssessment.potential_noise.slice(0, 4).map((n: string, i: number) => (
                            <div key={i} className="text-xs text-slate-600 leading-relaxed flex items-start gap-2">
                              <svg className="w-3 h-3 text-red-400 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
                              <span>{n}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── Modules ── */}
            {tab === "modules" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                {queryModules.map((m: any, i: number) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-50">
                      <div className="flex items-center gap-3">
                        <span className="text-[11px] font-bold px-2 py-0.5 rounded text-white" style={{ background: V }}>{m.module_id}</span>
                        <span className="text-sm font-semibold text-slate-800">{m.name}</span>
                      </div>
                      <span className="text-[11px] text-slate-400">{(m.terms?.primary?.length || 0) + (m.terms?.synonyms?.length || 0)} terms</span>
                    </div>
                    <div className="px-5 py-4">
                      <p className="text-xs text-slate-500 mb-3">{m.purpose}</p>

                      {m.terms?.primary?.length > 0 && (
                        <div className="mb-3">
                          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Primary Terms</div>
                          <div className="flex flex-wrap gap-1.5">
                            {m.terms.primary.map((t: string, j: number) => (
                              <span key={j} className="text-xs font-medium px-2 py-0.5 rounded" style={{ color: V, background: "#f5f3ff" }}>{t}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.terms?.synonyms?.length > 0 && (
                        <div className="mb-3">
                          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Synonyms / Variations</div>
                          <div className="flex flex-wrap gap-1.5">
                            {m.terms.synonyms.map((t: string, j: number) => (
                              <span key={j} className="text-xs text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-100">{t}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.terms?.exclusions?.length > 0 && (
                        <div>
                          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Exclusions</div>
                          <div className="flex flex-wrap gap-1.5">
                            {m.terms.exclusions.map((t: string, j: number) => (
                              <span key={j} className="text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">{t}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── RQ Queries ── */}
            {tab === "queries" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                {rqQueries.map((q: any, i: number) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                    <div className="flex items-center gap-3 px-5 py-3.5 border-b border-slate-50">
                      <span className="text-[11px] font-bold text-white px-2 py-0.5 rounded" style={{ background: V }}>{q.question_id}</span>
                      <span className="text-sm text-slate-700 flex-1">{q.question}</span>
                    </div>
                    <div className="p-4">
                      <BooleanDisplay
                        query={q.query || ""}
                        label={`${q.question_id} Query`}
                        onCopy={() => handleCopy(q.query || "")}
                        editable
                        onEdit={(text) => handleQueryEdit(q.question_id, text)}
                      />
                      {q.rationale && (
                        <p className="text-xs text-slate-500 mt-3 px-1 leading-relaxed">{q.rationale}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── Exclusions ── */}
            {tab === "exclusions" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                {globalExclusions && (
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Global NOT String</h3>
                    <div className="font-mono text-xs text-red-700 bg-red-50 rounded-lg px-4 py-3 overflow-x-auto leading-relaxed">{globalExclusions}</div>
                    <p className="text-xs text-slate-500 mt-2">{exclusionStrategy.rationale}</p>
                  </div>
                )}
                {exclusionCats.map((cat: any, i: number) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-xs font-semibold text-red-600 uppercase tracking-wide capitalize">{cat.category?.replace(/_/g, " ")}</span>
                      <span className="text-[10px] text-slate-400">({cat.terms?.length || 0} terms)</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {(cat.terms || []).map((t: string, j: number) => (
                        <span key={j} className="text-xs font-medium text-red-600 bg-red-50 px-2.5 py-1 rounded border border-red-100">{t}</span>
                      ))}
                    </div>
                    <p className="text-xs text-slate-500">{cat.reason}</p>
                  </div>
                ))}
              </div>
            )}

            {/* ── Filters ── */}
            {tab === "filters" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-4">Meltwater Filter Configuration</h3>
                  <div className="space-y-4">
                    <div className="flex justify-between items-start border-b border-slate-50 pb-3">
                      <span className="text-xs text-slate-500 w-32 shrink-0">Date Range</span>
                      <span className="text-sm text-slate-700 text-right">{filterRecs.date_range || "—"}</span>
                    </div>
                    <div className="flex justify-between items-start border-b border-slate-50 pb-3">
                      <span className="text-xs text-slate-500 w-32 shrink-0">Geography</span>
                      <span className="text-sm text-slate-700">{(filterRecs.geography || []).join(", ") || "—"}</span>
                    </div>
                    <div className="flex justify-between items-start border-b border-slate-50 pb-3">
                      <span className="text-xs text-slate-500 w-32 shrink-0">Language</span>
                      <span className="text-sm text-slate-700">{(filterRecs.language || []).join(", ") || "—"}</span>
                    </div>
                    <div className="flex justify-between items-start border-b border-slate-50 pb-3">
                      <span className="text-xs text-slate-500 w-32 shrink-0">Source Types</span>
                      <div className="flex flex-wrap gap-1.5 justify-end">
                        {sourceTypes.map((t, i) => (
                          <span key={i} className="text-xs font-medium px-2 py-0.5 rounded capitalize" style={{ color: V, background: "#f5f3ff" }}>{t}</span>
                        ))}
                      </div>
                    </div>
                    <div className="flex justify-between items-start pb-1">
                      <span className="text-xs text-slate-500 w-32 shrink-0">Platforms</span>
                      <div className="flex flex-wrap gap-1.5 justify-end">
                        {platforms.map((p, i) => (
                          <span key={i} className="text-xs text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-100">{p}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                {additionalFilters.length > 0 && (
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-4">Additional Filter Recommendations</h3>
                    <div className="space-y-4">
                      {additionalFilters.map((f: any, i: number) => (
                        <div key={i} className={`${i < additionalFilters.length - 1 ? "border-b border-slate-50 pb-4" : ""}`}>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-slate-800">{f.filter}</span>
                          </div>
                          <div className="text-xs text-slate-600 mb-1">{f.value}</div>
                          <div className="text-[11px] text-slate-400">{f.reason}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Quality Score ── */}
            {tab === "score" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                  <div className="flex items-center gap-6 mb-6">
                    <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{
                      background: qualityAssessment.overall_score >= 8 ? "#ecfdf5" : qualityAssessment.overall_score >= 6 ? "#fffbeb" : "#fef2f2"
                    }}>
                      <span className="text-3xl font-bold" style={{
                        color: qualityAssessment.overall_score >= 8 ? "#059669" : qualityAssessment.overall_score >= 6 ? "#d97706" : "#dc2626"
                      }}>{qualityAssessment.overall_score || 0}</span>
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-800">Overall Quality Score</div>
                      <div className="text-xs text-slate-500 mt-0.5">Based on coverage and precision analysis</div>
                    </div>
                  </div>
                  <div className="space-y-3">
                    <ScoreGauge score={qualityAssessment.coverage_score || 0} label="Coverage" />
                    <ScoreGauge score={qualityAssessment.precision_score || 0} label="Precision" />
                  </div>
                </div>

                {qualityAssessment.recommendations?.length > 0 && (
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <h4 className="text-xs font-semibold uppercase tracking-wide mb-3" style={{ color: V }}>Recommendations</h4>
                    <div className="space-y-2.5">
                      {qualityAssessment.recommendations.map((r: string, i: number) => (
                        <div key={i} className="text-xs text-slate-600 leading-relaxed flex items-start gap-2.5">
                          <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0 mt-px" style={{ background: V }}>{i + 1}</span>
                          <span>{r}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {qualityAssessment.potential_gaps?.length > 0 && (
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
                    <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-3">Coverage Gaps</h4>
                    <div className="space-y-2">
                      {qualityAssessment.potential_gaps.map((g: string, i: number) => (
                        <div key={i} className="text-xs text-slate-600 leading-relaxed flex items-start gap-2">
                          <svg className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                          <span>{g}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Sample Evaluation ── */}
            {tab === "evaluation" && (
              <div className="space-y-4 max-w-4xl animate-fade-in">
                {!evaluation ? (
                  <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-8 text-center space-y-4">
                    <div className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center" style={{ background: "#f5f3ff" }}>
                      <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><line x1="10" y1="9" x2="8" y2="9" />
                      </svg>
                    </div>
                    <h3 className="text-sm font-semibold text-slate-700">Upload Meltwater Sample</h3>
                    <p className="text-xs text-slate-500 max-w-md mx-auto">
                      Export a sample dataset from Meltwater (CSV or XLSX) and upload it here to evaluate how well the queries perform.
                    </p>
                    <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
                      onChange={(e) => { const file = e.target.files?.[0]; if (file) handleFileUpload(file); }} />
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploadingFile}
                      className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm hover:shadow-md disabled:opacity-50"
                      style={{ background: V }}
                    >
                      {uploadingFile ? "Uploading..." : "Upload Sample"}
                    </button>
                  </div>
                ) : (
                  <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-4">
                      Evaluation — {evaluation.file_name}
                    </h3>
                    {evaluation.evaluation ? (
                      <div className="space-y-4">
                        <div className="grid grid-cols-4 gap-4 text-center">
                          {[
                            { label: "Total Records", value: (evaluation.evaluation as any).total_records, color: "#0f172a" },
                            { label: "Relevant", value: (evaluation.evaluation as any).relevant_count, color: "#059669" },
                            { label: "Partial", value: (evaluation.evaluation as any).partially_relevant_count, color: "#d97706" },
                            { label: "Irrelevant", value: (evaluation.evaluation as any).irrelevant_count, color: "#dc2626" },
                          ].map((s, i) => (
                            <div key={i}>
                              <div className="text-2xl font-bold tabular-nums" style={{ color: s.color }}>{s.value}</div>
                              <div className="text-xs text-slate-400">{s.label}</div>
                            </div>
                          ))}
                        </div>
                        <div className="space-y-2">
                          <ScoreGauge score={Math.round(((evaluation.evaluation as any).precision_estimate || 0) * 10)} label="Precision" />
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-slate-500">Evaluation in progress...</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Bottom bar ── */}
          <div className="shrink-0 px-8 py-4 border-t border-slate-200 bg-white">
            <div className="flex items-center justify-between max-w-4xl">
              <button onClick={() => onNavigate("background-research")}
                className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
                Background Research
              </button>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => handleCopy(currentQueryText)}
                  className="px-4 py-2 text-sm font-medium border rounded-lg transition-colors"
                  style={{ color: V, borderColor: "#ddd6fe" }}
                >
                  Copy {queryView.charAt(0).toUpperCase() + queryView.slice(1)} Query
                </button>
                {hasData && (
                  <button
                    onClick={generateStrategy}
                    className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    Regenerate
                  </button>
                )}
                <button
                  onClick={handleApprove}
                  className={`px-5 py-2 text-sm font-medium text-white rounded-lg transition-all shadow-sm ${approved ? "" : "hover:shadow-md"}`}
                  style={{ background: approved ? "#059669" : V }}
                >
                  {approved ? "Approved" : "Approve Strategy"}
                </button>
                <button onClick={() => onNavigate("data-sources")}
                  className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">
                  Data Sources
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { useDemoState } from "../lib/demo-state";
import { intelApi, type PlanResult, type JobStatus } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";
import type {
  ResearchPlanData,
  PlanObjective,
  ExecutionUnit,
  PlanValidation,
  AnalysisMethodSummary,
} from "../data/contracts";

function Badge({ label, variant }: { label: string; variant: "high" | "medium" | "low" | "clean" | "warnings" | "blocked" | "pending" | "approved" | "rejected" | "draft" | string }) {
  const colors: Record<string, string> = {
    high: "text-blue-700 bg-blue-50 border-blue-200",
    medium: "text-amber-700 bg-amber-50 border-amber-200",
    low: "text-slate-500 bg-slate-100 border-slate-200",
    clean: "text-emerald-700 bg-emerald-50 border-emerald-200",
    warnings: "text-amber-700 bg-amber-50 border-amber-200",
    blocked: "text-red-700 bg-red-50 border-red-200",
    pending: "text-slate-500 bg-slate-100 border-slate-200",
    approved: "text-emerald-700 bg-emerald-50 border-emerald-200",
    rejected: "text-red-700 bg-red-50 border-red-200",
    draft: "text-slate-500 bg-slate-100 border-slate-200",
    completed: "text-emerald-700 bg-emerald-50 border-emerald-200",
    in_progress: "text-blue-700 bg-blue-50 border-blue-200",
    deterministic: "text-amber-700 bg-amber-50 border-amber-200",
    llm: "text-emerald-700 bg-emerald-50 border-emerald-200",
  };
  return (
    <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${colors[variant] || colors.low}`}>
      {label}
    </span>
  );
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">{title}</div>
      {count !== undefined && (
        <span className="text-[10px] text-slate-400 font-medium tabular-nums">{count} items</span>
      )}
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
}

function StatCard({ value, label, accent }: { value: string | number; label: string; accent?: boolean }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm text-center">
      <div className={`text-2xl font-bold tabular-nums ${accent ? "text-emerald-600" : "text-slate-900"}`}>{value}</div>
      <div className="text-xs text-slate-400 mt-0.5">{label}</div>
    </div>
  );
}

function ObjectiveCard({ obj }: { obj: PlanObjective }) {
  const [open, setOpen] = useState(false);

  const evidence = obj.evidence || { mandatory: [], optional: [] };
  const platforms = obj.platforms || [];
  const methods = obj.methods || [];

  return (
    <div className={`bg-white border border-slate-200 rounded-xl shadow-sm transition-all ${open ? "shadow-md" : ""}`}>
      <button onClick={() => setOpen(!open)} className="w-full text-left p-5 flex items-start gap-4">
        <span className="text-xs font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded shrink-0 mt-0.5 tabular-nums">
          {obj.objective_id}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-900 leading-snug">{obj.objective}</div>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <Badge label={obj.priority} variant={obj.priority} />
            <span className="text-[10px] text-slate-400 font-medium">{(obj.business_question_ids || []).join(", ")}</span>
            <Badge label={obj.estimated_complexity + " complexity"} variant={obj.estimated_complexity} />
          </div>
        </div>
        <svg className={`w-4 h-4 text-slate-400 shrink-0 mt-1 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="px-5 pb-5 pt-0 space-y-4 animate-fade-in border-t border-slate-100 mt-0 pt-4 ml-10">
          {obj.reason && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">Rationale</div>
              <p className="text-sm text-slate-600 italic">{obj.reason}</p>
            </div>
          )}

          {platforms.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Platforms</div>
              <div className="space-y-1.5">
                {platforms.map((p, i) => (
                  <div key={i} className="flex gap-3 text-sm">
                    <span className="font-semibold text-blue-600 w-20 shrink-0">{p.name}</span>
                    <span className="text-slate-500">{p.justification}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(evidence.mandatory?.length > 0 || evidence.optional?.length > 0) && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Evidence Requirements</div>
              <ul className="space-y-1">
                {(evidence.mandatory || []).map((e, i) => (
                  <li key={i} className="text-sm text-slate-600 flex items-start gap-2">
                    <span className="text-emerald-500 mt-0.5 text-xs font-bold">REQ</span>
                    {e}
                  </li>
                ))}
                {(evidence.optional || []).map((e, i) => (
                  <li key={i} className="text-sm text-slate-500 flex items-start gap-2">
                    <span className="text-slate-300 mt-1.5">&#8226;</span>
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            {methods.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Methods</div>
                <div className="flex flex-wrap gap-1.5">
                  {methods.map((m, i) => (
                    <span key={i} className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">{m}</span>
                  ))}
                </div>
              </div>
            )}
            {obj.expected_output && (
              <div>
                <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Expected Output</div>
                <p className="text-sm text-slate-600">{obj.expected_output}</p>
              </div>
            )}
          </div>

          {obj.deliverable_mapping && (
            <div className="flex items-center gap-4 pt-2 border-t border-slate-100 text-xs text-slate-500">
              <span>Supports: <span className="text-slate-700 font-medium">{obj.deliverable_mapping.supports}</span></span>
              {obj.deliverable_mapping.recommended_visual && (
                <span>Visual: <span className="text-slate-700 font-medium">{obj.deliverable_mapping.recommended_visual}</span></span>
              )}
            </div>
          )}

          <div className="flex items-center gap-4 pt-2 border-t border-slate-100 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-400">Confidence</span>
              <Badge label={obj.confidence_target} variant={obj.confidence_target} />
            </div>
            {obj.dependencies.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-slate-400">Depends on</span>
                <span className="text-xs text-slate-600">{obj.dependencies.join(", ")}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ExecutionUnitRow({ unit }: { unit: ExecutionUnit }) {
  return (
    <div className="flex items-center gap-4 py-3 px-4 bg-white border border-slate-200 rounded-lg text-sm">
      <span className="font-bold text-blue-600 tabular-nums w-12 shrink-0">{unit.id}</span>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-slate-800 truncate">{unit.title}</div>
        <div className="text-xs text-slate-400 mt-0.5">{unit.recommended_method} &middot; {unit.estimated_runtime}</div>
      </div>
      <Badge label={unit.priority} variant={unit.priority} />
      <Badge label={unit.status} variant={unit.status} />
    </div>
  );
}

function ValidationPanel({ validation }: { validation: PlanValidation }) {
  return (
    <div className={`border rounded-xl p-4 ${
      validation.status === "clean" ? "border-emerald-200 bg-emerald-50/30" :
      validation.status === "warnings" ? "border-amber-200 bg-amber-50/30" :
      "border-red-200 bg-red-50/30"
    }`}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold uppercase tracking-widest text-slate-600">Plan Validation</div>
        <Badge label={validation.status} variant={validation.status} />
      </div>
      <div className="flex gap-6 text-xs text-slate-500 mb-3">
        <span>{validation.total_objectives} objectives</span>
        <span>{validation.total_execution_units} execution units</span>
        <span>RQ coverage: {validation.question_coverage}</span>
      </div>
      {validation.warnings.length > 0 && (
        <div className="space-y-1.5">
          {validation.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-amber-700">
              <svg className="w-3.5 h-3.5 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              {w.message}
            </div>
          ))}
        </div>
      )}
      {validation.warnings.length === 0 && (
        <div className="text-xs text-emerald-600 flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
          All validations passed
        </div>
      )}
    </div>
  );
}

function MethodsSummary({ methods }: { methods: AnalysisMethodSummary[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {methods.map((m, i) => (
        <div key={i} className="bg-white border border-slate-200 rounded-lg p-3">
          <div className="text-sm font-semibold text-slate-800">{m.method}</div>
          <div className="text-xs text-slate-500 mt-1">{m.description}</div>
          <div className="flex items-center gap-2 mt-2 text-[10px] text-slate-400">
            <span>Output: {m.output_type}</span>
            <span>&middot;</span>
            <span>{m.execution_units.length} unit{m.execution_units.length !== 1 ? "s" : ""}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ResearchPlan({ onNavigate }: { onNavigate: (page: string) => void }) {
  const demo = useDemoState();
  const [plan, setPlan] = useState<ResearchPlanData | null>(null);
  const [planRecord, setPlanRecord] = useState<PlanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [activeTab, setActiveTab] = useState<"objectives" | "execution" | "methods" | "deliverables">("objectives");
  const [approving, setApproving] = useState(false);

  const projectId = useActiveProjectId() ?? 1;

  const loadPlan = useCallback(async () => {
    try {
      setError(null);
      const result = await intelApi.getPlan(projectId);
      setPlanRecord(result);
      const data = (typeof result.plan_json === "string" ? JSON.parse(result.plan_json) : result.plan_json) as ResearchPlanData;
      setPlan(data);
    } catch {
      setPlan(null);
      setPlanRecord(null);
    }
  }, []);

  useEffect(() => {
    async function init() {
      setLoading(true);
      // Sync gate flags from backend in parallel
      await Promise.all([
        loadPlan(),
        intelApi.getBrief(projectId)
          .then((b) => { if (b?.approval_status === "approved") demo.setBackgroundApproved(true); })
          .catch(() => {}),
        intelApi.getStrategy(projectId)
          .then((s) => { if (s?.approval_status === "approved") demo.setStrategyApproved(true); })
          .catch(() => {}),
        Promise.all([
          intelApi.getStrategy(projectId),
          intelApi.getAllDatasets(projectId).catch(() => [] as any[]),
        ]).then(([strat, allDs]) => {
          const stratObj = (strat?.strategy ?? {}) as Record<string, any>;
          const rqs: any[] = stratObj.research_question_queries || [];
          if (rqs.length === 0) return;
          const dsMap: Record<string, any> = {};
          for (const ds of allDs) {
            if (ds.research_question_id && (!dsMap[ds.research_question_id] || ds.id > dsMap[ds.research_question_id].id))
              dsMap[ds.research_question_id] = ds;
          }
          const anyApproved = rqs.some((rq: any) => dsMap[rq.question_id]?.approval_status === "approved");
          if (anyApproved) demo.setDatasetApproved(true);
        }).catch(() => {}),
      ]);
      setLoading(false);
    }
    init();
  }, [loadPlan]);

  useEffect(() => {
    if (!jobId) return;
    const interval = setInterval(async () => {
      try {
        const status: JobStatus = await intelApi.getJob(jobId);
        if (status.status === "completed") {
          clearInterval(interval);
          setGenerating(false);
          setJobId(null);
          await loadPlan();
        } else if (status.status === "failed") {
          clearInterval(interval);
          setGenerating(false);
          setJobId(null);
          setError(status.error || "Plan generation failed");
        }
      } catch {
        // keep polling
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [jobId, loadPlan]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await intelApi.generatePlan(projectId);
      if (result.status === "blocked") {
        setError("Prerequisites not met — approve all prior stages first.");
        setGenerating(false);
        return;
      }
      setJobId(result.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start plan generation");
      setGenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!planRecord) return;
    setApproving(true);
    try {
      await intelApi.approvePlan(planRecord.id);
      await loadPlan();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  };

  const handleReject = async () => {
    if (!planRecord) return;
    try {
      await intelApi.rejectPlan(planRecord.id, "Rejected by analyst");
      await loadPlan();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rejection failed");
    }
  };

  if (loading) {
    return (
      <div className="p-8 max-w-4xl mx-auto animate-fade-in">
        <div className="text-center py-12">
          <div className="w-10 h-10 rounded-full mx-auto border-4 border-slate-200 border-t-blue-600 animate-spin" />
          <p className="text-sm text-slate-500 mt-4">Loading...</p>
        </div>
      </div>
    );
  }

  if (demo.researchPlanLocked && !plan) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Research Plan</h1>
            <p className="text-sm text-slate-500 mt-0.5">Analysis Blueprint</p>
          </div>
        </div>
        <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-12 text-center space-y-4">
          <div className="w-14 h-14 mx-auto bg-slate-100 rounded-xl flex items-center justify-center">
            <svg className="w-7 h-7 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
          </div>
          <h3 className="text-base font-semibold text-slate-700">Research Plan Locked</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto">
            Complete and approve all prerequisite stages before generating the research plan.
          </p>
          <div className="flex items-center justify-center gap-3 mt-4">
            {[
              { label: "Brief", done: demo.briefApproved },
              { label: "Background", done: demo.backgroundApproved },
              { label: "Strategy", done: demo.strategyApproved },
              { label: "Dataset", done: demo.datasetApproved },
            ].map((g) => (
              <div key={g.label} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${g.done ? "bg-emerald-50 text-emerald-700" : "bg-slate-50 text-slate-400"}`}>
                {g.done && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>}
                {g.label}
              </div>
            ))}
          </div>
          <button
            onClick={() => onNavigate("data-sources")}
            className="mt-4 px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
          >
            Go to Data Sources
          </button>
        </div>
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Research Plan</h1>
            <p className="text-sm text-slate-500 mt-0.5">Analysis Blueprint</p>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
        )}

        <div className="bg-white border-2 border-dashed border-slate-200 rounded-xl p-12 text-center space-y-4">
          <div className="w-14 h-14 mx-auto bg-blue-50 rounded-xl flex items-center justify-center">
            <svg className="w-7 h-7 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          </div>
          <h3 className="text-base font-semibold text-slate-700">No Research Plan Yet</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto">
            Generate a structured research plan based on the approved brief, background research, search strategy, and dataset.
          </p>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="mt-4 px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {generating ? "Generating Plan..." : "Generate Research Plan"}
          </button>
        </div>
      </div>
    );
  }

  const objectives = plan.research_objectives || [];
  const executionUnits = plan.execution_units || [];
  const analysisMethods = plan.analysis_methods || [];
  const deliverables = plan.expected_deliverables || [];
  const validation = plan.validation;
  const overview = plan.project_overview;
  const meta = plan._meta;
  const approvalStatus = planRecord?.approval_status || "pending";

  const filtered = objectives.filter((obj) => {
    if (filterPriority !== "all" && obj.priority !== filterPriority) return false;
    if (search && !obj.objective.toLowerCase().includes(search.toLowerCase()) && !obj.objective_id.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const uniqueMethods = new Set(objectives.flatMap((o) => o.methods || []));
  const uniquePlatforms = new Set(
    objectives.flatMap((o) => (o.platforms || []).map((p) => (typeof p === "string" ? p : p.name)))
  );

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Research Plan</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {overview ? `${overview.brand} — ${overview.category}` : "Analysis Blueprint"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {meta?.source && <Badge label={meta.source} variant={meta.source} />}
          <Badge label={approvalStatus} variant={approvalStatus} />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
      )}

      {/* Summary */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <p className="text-sm text-slate-600 leading-relaxed">{plan.plan_summary}</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-5 gap-4">
        <StatCard value={objectives.length} label="Objectives" />
        <StatCard value={executionUnits.length} label="Execution Units" />
        <StatCard value={uniquePlatforms.size} label="Platforms" />
        <StatCard value={uniqueMethods.size} label="Methods" />
        <StatCard value={validation?.question_coverage || "—"} label="RQ Coverage" accent />
      </div>

      {/* Validation */}
      {validation && <ValidationPanel validation={validation} />}

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-0.5 text-xs">
        {(["objectives", "execution", "methods", "deliverables"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-md capitalize transition-all ${
              activeTab === tab
                ? "bg-blue-50 text-blue-700 font-semibold shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab === "execution" ? "Execution Units" : tab}
          </button>
        ))}
      </div>

      {/* Objectives tab */}
      {activeTab === "objectives" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <path d="M21 21l-4.35-4.35" />
              </svg>
              <input
                type="text"
                placeholder="Search objectives..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
              />
            </div>
            <div className="flex items-center bg-white border border-slate-200 rounded-lg p-0.5 text-xs">
              {["all", "high", "medium", "low"].map((p) => (
                <button
                  key={p}
                  onClick={() => setFilterPriority(p)}
                  className={`px-3 py-1.5 rounded-md capitalize transition-all ${
                    filterPriority === p
                      ? "bg-blue-50 text-blue-700 font-semibold shadow-sm"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <SectionHeader title="Research Objectives" count={filtered.length} />

          <div className="space-y-3">
            {filtered.map((obj) => (
              <ObjectiveCard key={obj.objective_id} obj={obj} />
            ))}
            {filtered.length === 0 && (
              <div className="text-center py-12 text-sm text-slate-400">No objectives match your filters</div>
            )}
          </div>
        </div>
      )}

      {/* Execution Units tab */}
      {activeTab === "execution" && (
        <div className="space-y-3">
          <SectionHeader title="Execution Units" count={executionUnits.length} />
          {executionUnits.map((u) => (
            <ExecutionUnitRow key={u.id} unit={u} />
          ))}
          {executionUnits.length === 0 && (
            <div className="text-center py-12 text-sm text-slate-400">No execution units in this plan</div>
          )}
        </div>
      )}

      {/* Methods tab */}
      {activeTab === "methods" && (
        <div className="space-y-3">
          <SectionHeader title="Analysis Methods" count={analysisMethods.length} />
          <MethodsSummary methods={analysisMethods} />
        </div>
      )}

      {/* Deliverables tab */}
      {activeTab === "deliverables" && (
        <div className="space-y-3">
          <SectionHeader title="Expected Deliverables" count={deliverables.length} />
          {deliverables.map((d, i) => (
            <div key={i} className="bg-white border border-slate-200 rounded-lg p-4">
              <div className="text-sm font-semibold text-slate-800">{d.deliverable}</div>
              <div className="flex items-center gap-3 mt-2 text-xs text-slate-400">
                <span>Format: {d.format}</span>
                <span>&middot;</span>
                <span>{d.execution_units.length} unit{d.execution_units.length !== 1 ? "s" : ""}: {d.execution_units.join(", ")}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Action bar */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
        >
          {generating ? "Regenerating..." : "Regenerate Plan"}
        </button>

        {approvalStatus === "pending" && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleReject}
              className="px-4 py-2 text-sm font-medium text-red-600 bg-white border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
            >
              Reject
            </button>
            <button
              onClick={handleApprove}
              disabled={approving}
              className="px-5 py-2 text-sm font-medium bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors shadow-sm disabled:opacity-50"
            >
              {approving ? "Approving..." : "Approve Plan"}
            </button>
          </div>
        )}

        {approvalStatus === "approved" && (
          <div className="flex items-center gap-2 text-sm text-emerald-600 font-medium">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
            Plan Approved
          </div>
        )}

        {approvalStatus === "rejected" && (
          <div className="text-sm text-red-600 font-medium">
            Plan Rejected — regenerate with revisions
          </div>
        )}
      </div>

      {/* Meta footer */}
      {meta && (
        <div className="text-[10px] text-slate-400 text-right">
          Source: {meta.source} &middot; v{meta.version} &middot; {meta.attempts} attempt{meta.attempts !== 1 ? "s" : ""}
          {meta.elapsed_seconds > 0 && ` &middot; ${Math.round(meta.elapsed_seconds)}s`}
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-4">
        <button onClick={() => onNavigate("data-sources")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Data Sources
        </button>
        <button onClick={() => onNavigate("research-execution")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Research Execution
        </button>
      </div>
    </div>
  );
}

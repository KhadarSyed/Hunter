import { useState, useEffect, useCallback } from "react";
import { useDemoState } from "../lib/demo-state";
import { useProject, useActiveProjectId } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

interface StageInfo {
  id: string;
  label: string;
  page: string;
  status: "completed" | "active" | "pending";
  detail?: string;
}

interface ProjectStats {
  insightsCount: number;
  avgConfidence: number;
  storylineNodes: number;
  slidesComposed: number;
  pptxReady: boolean;
  wordReady: boolean;
  researchType: string;
}

const QUICK_ACTIONS = [
  { page: "brief-scope-review", label: "Brief & Scope", desc: "Review and approve the project brief", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { page: "background-research", label: "Background Research", desc: "AI-synthesized competitive intelligence", icon: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" },
  { page: "search-strategy", label: "Search Strategy", desc: "Build and refine Meltwater queries", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" },
  { page: "data-sources", label: "Data Sources", desc: "Upload datasets per research question", icon: "M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" },
  { page: "analysis", label: "Analysis", desc: "AI-generated insights and storyline", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" },
  { page: "deliverables", label: "Deliverables", desc: "Generate and download PPTX & Word", icon: "M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
];

function ProgressRing({ progress, size = 96, strokeWidth = 7 }: { progress: number; size?: number; strokeWidth?: number }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (progress / 100) * circumference;
  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(91,44,157,0.08)" strokeWidth={strokeWidth} />
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="url(#progressGrad)" strokeWidth={strokeWidth}
        strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
        style={{ transition: "stroke-dashoffset 0.8s ease" }} />
      <defs>
        <linearGradient id="progressGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#5B2C9D" />
          <stop offset="100%" stopColor="#7C4DFF" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? "border-[#5B2C9D]/20 bg-[#5B2C9D]/[0.03]" : "border-slate-200 bg-white"} shadow-sm`}>
      <div className="text-[10px] text-slate-400 uppercase tracking-wider font-medium mb-1.5">{label}</div>
      <div className="text-2xl font-bold text-slate-900 tabular-nums leading-none">{value}</div>
      {sub && <div className="text-[11px] text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

export function Dashboard({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject } = useProject();
  const activeProjectId = useActiveProjectId();
  const demo = useDemoState();
  const [stats, setStats] = useState<ProjectStats>({
    insightsCount: 0, avgConfidence: 0, storylineNodes: 0,
    slidesComposed: 0, pptxReady: false, wordReady: false, researchType: "Research Project",
  });
  const [stages, setStages] = useState<StageInfo[]>([]);

  const computeStages = useCallback((s: ProjectStats): StageInfo[] => {
    const result: StageInfo[] = [
      { id: "brief", label: "Brief & Scope", page: "brief-scope-review", status: "pending" },
      { id: "background", label: "Background", page: "background-research", status: "pending" },
      { id: "strategy", label: "Strategy", page: "search-strategy", status: "pending" },
      { id: "data", label: "Data Sources", page: "data-sources", status: "pending" },
      { id: "execution", label: "Execution", page: "research-execution", status: "pending" },
      { id: "analysis", label: "Analysis", page: "analysis", status: "pending", detail: s.insightsCount > 0 ? `${s.insightsCount} insights` : undefined },
      { id: "deliverables", label: "Deliverables", page: "deliverables", status: "pending", detail: s.pptxReady || s.wordReady ? "Downloads ready" : undefined },
    ];

    if (demo.briefApproved) result[0].status = "completed";
    if (demo.backgroundApproved) result[1].status = "completed";
    if (demo.strategyApproved) result[2].status = "completed";
    if (demo.datasetApproved) result[3].status = "completed";
    if (demo.datasetApproved) result[4].status = "completed";
    if (s.insightsCount > 0) result[5].status = "completed";
    if (s.pptxReady || s.wordReady) result[6].status = "completed";

    let foundPending = false;
    for (const stage of result) {
      if (stage.status === "pending" && !foundPending) {
        stage.status = "active";
        foundPending = true;
      }
    }

    return result;
  }, [demo.briefApproved, demo.backgroundApproved, demo.strategyApproved, demo.datasetApproved]);

  useEffect(() => {
    if (!activeProjectId) return;

    const load = async () => {
      const s: ProjectStats = {
        insightsCount: 0, avgConfidence: 0, storylineNodes: 0,
        slidesComposed: 0, pptxReady: false, wordReady: false, researchType: "Research Project",
      };

      try {
        const project = await intelApi.getProject(activeProjectId);
        const spec = project.spec as any;
        if (spec) {
          s.researchType = spec.research_type || spec.methodology?.primary || "Research";
        }
      } catch {}

      try {
        const summary = await intelApi.getInsightsSummary(activeProjectId);
        s.insightsCount = summary.total_insights || 0;
        s.avgConfidence = summary.avg_confidence || 0;
      } catch {}

      try {
        const slSummary = await intelApi.getStorylineSummary(activeProjectId);
        s.storylineNodes = slSummary.total_nodes || 0;
      } catch {}

      try {
        const compSummary = await intelApi.composerSummary(activeProjectId);
        const latest = compSummary as any;
        s.slidesComposed = latest.total_slides || latest.slide_count || 0;
        if (latest.latest_presentation_id) {
          try {
            const renderSummary = await intelApi.rendererSummary(latest.latest_presentation_id);
            s.pptxReady = !!(renderSummary as any)?.latest_job_id;
          } catch {}
          try {
            const wordSummary = await intelApi.wordRenderSummary(latest.latest_presentation_id);
            s.wordReady = !!(wordSummary as any)?.latest_job_id;
          } catch {}
        }
      } catch {}

      setStats(s);
      setStages(computeStages(s));
    };

    load();
  }, [activeProjectId, computeStages]);

  const completedCount = stages.filter((s) => s.status === "completed").length;
  const progress = stages.length > 0 ? Math.round((completedCount / stages.length) * 100) : 0;
  const projectName = activeProject?.name ?? "No Active Project";

  const nextStage = stages.find((s) => s.status === "active");
  const nextAction = nextStage
    ? `Continue to ${nextStage.label}`
    : completedCount === stages.length && stages.length > 0
      ? "All stages complete"
      : demo.nextAction;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-8 py-6 space-y-6 animate-fade-in">

        <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 opacity-[0.04]" style={{
            background: "radial-gradient(ellipse at 30% 50%, #5B2C9D 0%, transparent 60%), radial-gradient(ellipse at 90% 30%, #7C4DFF 0%, transparent 50%)"
          }} />
          <div className="relative flex items-center justify-between px-7 py-5">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-xl flex items-center justify-center"
                style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}>
                <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-900">Start a new research project</div>
                <div className="text-xs text-slate-500 mt-0.5">Upload a client brief to begin the intelligence pipeline.</div>
              </div>
            </div>
            <button
              onClick={() => onNavigate("new-project")}
              className="px-6 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm transition-all hover:shadow-md"
              style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
            >
              + New Project
            </button>
          </div>
        </div>

        <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="absolute inset-0 opacity-[0.03]" style={{
            background: "radial-gradient(ellipse at 20% 50%, #5B2C9D 0%, transparent 70%), radial-gradient(ellipse at 80% 20%, #7C4DFF 0%, transparent 60%)"
          }} />
          <div className="relative px-8 py-7 flex items-center gap-8">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-1">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-sm"
                  style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}>
                  {projectName.charAt(0)}
                </div>
                <div>
                  <h1 className="text-xl font-bold text-slate-900">{projectName}</h1>
                  <p className="text-xs text-slate-500">{stats.researchType}</p>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-5">
                <div>
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-medium mb-1">Next Action</div>
                  <button onClick={() => nextStage && onNavigate(nextStage.page)} className="text-sm font-semibold text-[#5B2C9D] hover:underline text-left">
                    {nextAction}
                  </button>
                </div>
                <div className="w-px h-8 bg-slate-200" />
                <div>
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-medium mb-1">Status</div>
                  <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-0.5 rounded-full border ${
                    completedCount === stages.length && stages.length > 0
                      ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                      : "text-blue-700 bg-blue-50 border-blue-200"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      completedCount === stages.length && stages.length > 0 ? "bg-emerald-500" : "bg-blue-500 animate-pulse"
                    }`} />
                    {completedCount === stages.length && stages.length > 0 ? "Complete" : "In Progress"}
                  </span>
                </div>
                <div className="w-px h-8 bg-slate-200" />
                <div>
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider font-medium mb-1">Pipeline</div>
                  <div className="text-sm font-semibold text-slate-800 tabular-nums">{completedCount}/{stages.length} stages</div>
                </div>
              </div>
            </div>

            <div className="shrink-0">
              <div className="relative">
                <ProgressRing progress={progress} />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-slate-900 tabular-nums">{progress}%</div>
                    <div className="text-[9px] text-slate-400 uppercase tracking-wider">Complete</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm px-6 py-5">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-5">Pipeline Progress</h2>
          <div className="flex items-start gap-0">
            {stages.map((stage, i) => {
              const isCompleted = stage.status === "completed";
              const isActive = stage.status === "active";
              return (
                <div key={stage.id} className="flex-1 flex flex-col items-center relative">
                  <button
                    onClick={() => onNavigate(stage.page)}
                    className="relative z-10 flex flex-col items-center group cursor-pointer"
                  >
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                      isCompleted
                        ? "bg-gradient-to-br from-[#5B2C9D] to-[#7C4DFF] shadow-md shadow-[#5B2C9D]/20"
                        : isActive
                          ? "bg-white border-2 border-[#5B2C9D] shadow-md shadow-[#5B2C9D]/10"
                          : "bg-slate-100 border-2 border-slate-200"
                    }`}>
                      {isCompleted ? (
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      ) : isActive ? (
                        <span className="w-2.5 h-2.5 rounded-full bg-[#5B2C9D] animate-pulse" />
                      ) : (
                        <span className="w-2 h-2 rounded-full bg-slate-300" />
                      )}
                    </div>
                    <div className={`mt-2 text-center text-[11px] font-medium transition-colors ${
                      isCompleted ? "text-[#5B2C9D]" : isActive ? "text-slate-800" : "text-slate-400"
                    } group-hover:text-[#5B2C9D]`}>
                      {stage.label}
                    </div>
                    {stage.detail && (
                      <div className="text-[9px] text-slate-400 mt-0.5">{stage.detail}</div>
                    )}
                  </button>
                  {i < stages.length - 1 && (
                    <div className={`absolute top-4 left-[calc(50%+16px)] right-[calc(-50%+16px)] h-0.5 ${
                      isCompleted ? "bg-gradient-to-r from-[#5B2C9D] to-[#7C4DFF]" : "bg-slate-200"
                    }`} />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard label="Insights" value={stats.insightsCount} sub={stats.avgConfidence > 0 ? `${Math.round(stats.avgConfidence * 100)}% avg confidence` : undefined} accent={stats.insightsCount > 0} />
          <StatCard label="Storyline" value={stats.storylineNodes} sub={stats.storylineNodes > 0 ? "narrative nodes" : undefined} />
          <StatCard label="Slides" value={stats.slidesComposed} sub={stats.slidesComposed > 0 ? "composed" : undefined} />
          <StatCard
            label="Downloads"
            value={[stats.pptxReady && "PPTX", stats.wordReady && "Word"].filter(Boolean).join(" + ") || "None"}
            sub={stats.pptxReady || stats.wordReady ? "Ready to download" : "Not generated"}
            accent={stats.pptxReady || stats.wordReady}
          />
        </div>

        <div className="grid grid-cols-3 gap-5">
          <div className="col-span-2">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Quick Actions</h2>
            <div className="grid grid-cols-3 gap-3">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action.page}
                  onClick={() => onNavigate(action.page)}
                  className="group bg-white border border-slate-200 rounded-xl p-4 text-left hover:border-[#5B2C9D]/30 hover:shadow-md transition-all"
                >
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3 transition-colors bg-[#5B2C9D]/5 group-hover:bg-[#5B2C9D]/10">
                    <svg className="w-4.5 h-4.5 text-[#5B2C9D]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d={action.icon} />
                    </svg>
                  </div>
                  <div className="text-sm font-semibold text-slate-800 mb-0.5 group-hover:text-[#5B2C9D] transition-colors">{action.label}</div>
                  <div className="text-[11px] text-slate-400 leading-snug">{action.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Recent Activity</h2>
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden" style={{ maxHeight: 320 }}>
              {demo.activityLog.length === 0 ? (
                <div className="px-5 py-10 text-center">
                  <svg className="w-8 h-8 mx-auto text-slate-200 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <p className="text-xs text-slate-400">Activity will appear here as you work through the pipeline.</p>
                </div>
              ) : (
                <div className="divide-y divide-slate-100 overflow-y-auto" style={{ maxHeight: 320 }}>
                  {demo.activityLog.slice(0, 10).map((item, i) => (
                    <div key={i} className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50/50 transition-colors">
                      <div className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#5B2C9D] shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-slate-800 truncate">{item.action}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5 truncate">{item.detail}</div>
                      </div>
                      <div className="text-[10px] text-slate-400 shrink-0 tabular-nums mt-0.5">{item.timestamp}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
